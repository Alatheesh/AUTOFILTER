import os
import time
import uuid
import json
import asyncio
import aiohttp
import re
import logging
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.file_id import FileId
from pyrogram.raw.functions.upload import GetFile
from pyrogram.raw.types import InputDocumentFileLocation
from database.multi_db import db

logger = logging.getLogger(__name__)

# ==========================================
# 🚦 ENGINE STATE & CONCURRENCY CONTROLS
# ==========================================
MAX_CONCURRENT_JOBS = 2
media_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
current_queue_size = 0  
MEDIA_STATE = {}

# ==========================================
# 🚀 PHASE 4: INTERNAL STREAMING SERVER
# ==========================================

class LocalStreamer:
    def __init__(self, client):
        self.client = client
        self.app = web.Application()
        self.app.router.add_get('/stream/{file_id}', self.stream_handler)
        self.runner = None
        self.port = 8080

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', self.port)
        await site.start()
        logger.info("🚀 Internal MTProto Streaming Server Started on 127.0.0.1:8080")

    async def stream_handler(self, request):
        file_id = request.match_info['file_id']
        file_size = int(request.query.get('size', 0))
        
        range_header = request.headers.get('Range', '')
        start = 0
        end = file_size - 1
        
        if range_header:
            match = re.search(r'bytes=(\d+)-(\d*)', range_header)
            if match:
                start = int(match.group(1))
                if match.group(2):
                    end = int(match.group(2))
                    
        headers = {
            'Content-Range': f'bytes {start}-{end}/{file_size}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(end - start + 1),
            'Content-Type': 'video/mp4'
        }
        
        resp = web.StreamResponse(status=206 if range_header else 200, headers=headers)
        await resp.prepare(request)
        
        chunk_size = 1024 * 1024 # Telegram chunk size is 1MB
        start_chunk = start // chunk_size
        end_chunk = end // chunk_size
        
        try:
            # Decode file_id to Pyrogram Raw Location
            file_id_obj = FileId.decode(file_id)
            location = InputDocumentFileLocation(
                id=file_id_obj.media_id,
                access_hash=file_id_obj.access_hash,
                file_reference=file_id_obj.file_reference,
                thumb_size=""
            )
            
            # Fetch only the EXACT bytes FFmpeg asks for
            for chunk_idx in range(start_chunk, end_chunk + 1):
                offset = chunk_idx * chunk_size
                result = await self.client.invoke(GetFile(
                    location=location,
                    offset=offset,
                    limit=chunk_size
                ))
                
                chunk_data = result.bytes
                if chunk_idx == start_chunk and chunk_idx == end_chunk:
                    chunk_data = chunk_data[start % chunk_size : (end % chunk_size) + 1]
                elif chunk_idx == start_chunk:
                    chunk_data = chunk_data[start % chunk_size :]
                elif chunk_idx == end_chunk:
                    chunk_data = chunk_data[: (end % chunk_size) + 1]
                    
                await resp.write(chunk_data)
        except Exception as e:
            pass # Suppress broken pipe errors when FFmpeg finishes reading
            
        return resp

STREAMER_INSTANCE = None

async def ensure_streamer_running(client):
    global STREAMER_INSTANCE
    if not STREAMER_INSTANCE:
        STREAMER_INSTANCE = LocalStreamer(client)
        await STREAMER_INSTANCE.start()


# ==========================================
# ⚙️ PHASE 3: FFMPEG & CLOUD UPLOAD ENGINE
# ==========================================

async def get_file_by_unique_id(unique_id: str):
    for coll in db.collections:
        doc = await coll.find_one({"file_unique_id": unique_id})
        if doc: return doc
    return None

async def upload_to_telegraph(image_paths: list, title: str) -> str:
    """Uploads local images to Telegraph and returns a graph.org gallery link."""
    async with aiohttp.ClientSession() as session:
        uploaded_urls = []
        
        # 1. Upload each image to Telegraph servers
        for img_path in image_paths:
            if not os.path.exists(img_path):
                logger.error(f"❌ File missing before upload: {img_path}")
                continue
                
            with open(img_path, 'rb') as f:
                form = aiohttp.FormData()
                form.add_field('file', f, filename=os.path.basename(img_path), content_type='image/jpeg')
                async with session.post('https://telegra.ph/upload', data=form) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        if isinstance(res_json, list) and 'src' in res_json[0]:
                            uploaded_urls.append(f"https://telegra.ph{res_json[0]['src']}")
                        else:
                            logger.error(f"❌ Telegraph Upload Format Error: {res_json}")
                    else:
                        logger.error(f"❌ Telegraph Upload Failed with status {resp.status}")
        
        if not uploaded_urls:
            return None
            
        html_content = ""
        for url in uploaded_urls:
            html_content += f'<img src="{url}"/><br>'
            
        html_content += f'<br><br><b>Credits:</b> @llathu63035<br><b>Developer:</b> @TG_LATHEESH'

        async with session.get('https://api.telegra.ph/createAccount?short_name=AutoFilter&author_name=Lathu') as resp:
            account_data = (await resp.json())['result']
            access_token = account_data['access_token']
            
        payload = {
            'access_token': access_token,
            'title': title[:250],
            'content': f'[{{"tag":"p","children":[{{"tag":"span","children":["{html_content}"]}}]}}]',
            'return_content': 'false'
        }
        
        async with session.post('https://api.telegra.ph/createPage', data=payload) as resp:
            page_data = (await resp.json())['result']
            # Bypassing the ISP Block!
            return page_data['url'].replace("telegra.ph", "graph.org")

async def generate_watermarked_screenshots(client: Client, status_msg, file_id: str, num_images: int, file_name: str, file_size: int) -> str:
    await ensure_streamer_running(client)
    
    temp_dir = "/tmp/autofilter_media"
    os.makedirs(temp_dir, exist_ok=True)
    unique_run_id = str(uuid.uuid4())[:8]
    
    # We hand FFmpeg a direct local HTTP stream instead of a downloaded file!
    video_url = f"http://127.0.0.1:8080/stream/{file_id}?size={file_size}"
    
    try:
        await status_msg.edit_text("⚙️ **Processing Media...**\n`[1/3]` Connecting to live MTProto stream...")
        
        probe_cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_url}"'
        proc = await asyncio.create_subprocess_shell(probe_cmd, stdout=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        try:
            duration = float(stdout.decode().strip())
        except Exception:
            duration = 120.0
            
        await status_msg.edit_text(f"⚙️ **Processing Media...**\n`[2/3]` Rendering {num_images} watermarked frames instantly...")
        image_paths = []
        interval = duration / (num_images + 1)
        
        for i in range(1, num_images + 1):
            timestamp = int(interval * i)
            img_path = os.path.join(temp_dir, f"frame_{unique_run_id}_{i}.jpg")
            
            ff_cmd = (
                f'ffmpeg -y -ss {timestamp} -i "{video_url}" -vframes 1 -q:v 2 "{img_path}"'
            )
            process = await asyncio.create_subprocess_shell(ff_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await process.communicate()
            
            if os.path.exists(img_path) and os.path.getsize(img_path) > 0:
                image_paths.append(img_path)
                
        await status_msg.edit_text("⚙️ **Processing Media...**\n`[3/3]` Uploading gallery to cloud servers...")
        gallery_link = await upload_to_telegraph(image_paths, f"Screenshots: {file_name[:50]}")
        return gallery_link
        
    finally:
        for img in [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if unique_run_id in f]:
            if os.path.exists(img):
                os.remove(img)


# ==========================================
# 🛠️ UI COMPONENT GENERATORS
# ==========================================

def get_initial_media_markup(file_unique_id: str) -> list:
    return [
        [
            InlineKeyboardButton("🖼️ Screenshots", callback_data=f"med_ss_flow:{file_unique_id}"),
            InlineKeyboardButton("🎬 Sample Video", callback_data=f"med_spl_flow:{file_unique_id}")
        ]
    ]

def get_dynamic_media_markup(chat_id: int, message_id: int, file_unique_id: str) -> InlineKeyboardMarkup:
    state_key = f"{chat_id}_{message_id}"
    state = MEDIA_STATE.get(state_key, {"ss_url": None, "spl_url": None, "ss_proc": False, "spl_proc": False})
    
    if state["ss_url"]:
        btn_ss = InlineKeyboardButton("🔗 Watch Screenshots", url=state["ss_url"])
    elif state["ss_proc"]:
        btn_ss = InlineKeyboardButton("⏳ Processing SS...", callback_data="ignore_spam")
    else:
        btn_ss = InlineKeyboardButton("🖼️ Screenshots", callback_data=f"med_ss_flow:{file_unique_id}")
        
    if state["spl_url"]:
        btn_spl = InlineKeyboardButton("🔗 Watch Sample", url=state["spl_url"])
    elif state["spl_proc"]:
        btn_spl = InlineKeyboardButton("⏳ Processing Sample...", callback_data="ignore_spam")
    else:
        btn_spl = InlineKeyboardButton("🎬 Sample Video", callback_data=f"med_spl_flow:{file_unique_id}")
        
    return InlineKeyboardMarkup([[btn_ss, btn_spl]])

def get_screenshot_selection_markup(file_unique_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(str(i), callback_data=f"med_ss_req:{i}:{file_unique_id}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"med_ss_req:{i}:{file_unique_id}") for i in range(6, 11)],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"med_revert:{file_unique_id}")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_sample_selection_markup(file_unique_id: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("15s", callback_data=f"med_spl_req:15:{file_unique_id}"),
            InlineKeyboardButton("30s", callback_data=f"med_spl_req:30:{file_unique_id}"),
            InlineKeyboardButton("45s", callback_data=f"med_spl_req:45:{file_unique_id}"),
            InlineKeyboardButton("60s", callback_data=f"med_spl_req:60:{file_unique_id}")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"med_revert:{file_unique_id}")]
    ]
    return InlineKeyboardMarkup(buttons)


# ==========================================
# 🧠 INTERACTIVE FLOW HANDLERS
# ==========================================

@Client.on_callback_query(filters.regex(r"^med_ss_flow:(.+)"))
async def handle_screenshot_flow(client: Client, callback: CallbackQuery):
    file_unique_id = callback.matches[0].group(1)
    await callback.message.edit_reply_markup(reply_markup=get_screenshot_selection_markup(file_unique_id))
    await callback.answer()

@Client.on_callback_query(filters.regex(r"^med_spl_flow:(.+)"))
async def handle_sample_flow(client: Client, callback: CallbackQuery):
    file_unique_id = callback.matches[0].group(1)
    await callback.message.edit_reply_markup(reply_markup=get_sample_selection_markup(file_unique_id))
    await callback.answer()

@Client.on_callback_query(filters.regex(r"^med_revert:(.+)"))
async def handle_ui_revert(client: Client, callback: CallbackQuery):
    file_unique_id = callback.matches[0].group(1)
    chat_id = callback.message.chat.id
    msg_id = callback.message.id
    await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
    await callback.answer("Cancelled Operation")

@Client.on_callback_query(filters.regex(r"^ignore_spam"))
async def handle_ignore(client, callback):
    await callback.answer("⏳ Please wait, this task is already processing!", show_alert=True)


# ==========================================
# 🚀 PHASE 2/3: MEDIATOR QUEUE ENGINE
# ==========================================

@Client.on_callback_query(filters.regex(r"^med_ss_req:(\d+):(.+)"))
async def handle_screenshot_request(client: Client, callback: CallbackQuery):
    global current_queue_size
    num_images = int(callback.matches[0].group(1))
    file_unique_id = callback.matches[0].group(2)
    chat_id = callback.message.chat.id
    msg_id = callback.message.id
    state_key = f"{chat_id}_{msg_id}"
    
    if state_key not in MEDIA_STATE:
        MEDIA_STATE[state_key] = {"ss_url": None, "spl_url": None, "ss_proc": False, "spl_proc": False}
    MEDIA_STATE[state_key]["ss_proc"] = True
    
    await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
    
    current_queue_size += 1
    queue_position = current_queue_size
    status_msg = await callback.message.reply_text(
        f"⏳ **Request Queued!**\n**Task:** `{num_images} Screenshots`\n**Queue Position:** `#{queue_position}`\n_Please wait..._"
    )
    await callback.answer("Added to queue!", show_alert=False)
    
    async with media_semaphore:
        current_queue_size -= 1
        
        file_data = await get_file_by_unique_id(file_unique_id)
        if not file_data:
            await status_msg.edit_text("❌ **Error:** Could not locate the raw file in the database.")
            MEDIA_STATE[state_key]["ss_proc"] = False
            await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
            return
            
        actual_file_id = file_data.get("file_id")
        movie_title = file_data.get("title", "Unknown Movie")
        file_size_bytes = file_data.get("size", 0)
        
        try:
            gallery_url = await generate_watermarked_screenshots(client, status_msg, actual_file_id, num_images, movie_title, file_size_bytes)
            
            if gallery_url:
                MEDIA_STATE[state_key]["ss_url"] = gallery_url
            else:
                await status_msg.edit_text("⚠️ **Upload Failed:** Could not push images to Telegraph.")
                MEDIA_STATE[state_key]["ss_proc"] = False
                
        except Exception as e:
            logger.error(f"FFmpeg Generation Error: {e}")
            await status_msg.edit_text("❌ **Engine Error:** The media processor encountered a fatal error.")
            MEDIA_STATE[state_key]["ss_proc"] = False
        
        MEDIA_STATE[state_key]["ss_proc"] = False
        await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
        
        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^med_spl_req:(\d+):(.+)"))
async def handle_sample_request(client: Client, callback: CallbackQuery):
    global current_queue_size
    duration = int(callback.matches[0].group(1))
    file_unique_id = callback.matches[0].group(2)
    chat_id = callback.message.chat.id
    msg_id = callback.message.id
    state_key = f"{chat_id}_{msg_id}"
    
    if state_key not in MEDIA_STATE:
        MEDIA_STATE[state_key] = {"ss_url": None, "spl_url": None, "ss_proc": False, "spl_proc": False}
    MEDIA_STATE[state_key]["spl_proc"] = True
    
    await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
    
    current_queue_size += 1
    queue_position = current_queue_size
    status_msg = await callback.message.reply_text(
        f"⏳ **Request Queued!**\n**Task:** `{duration}s Sample Video`\n**Queue Position:** `#{queue_position}`\n_Please wait..._"
    )
    await callback.answer("Added to queue!", show_alert=False)
    
    async with media_semaphore:
        current_queue_size -= 1
        await status_msg.edit_text(f"⚙️ **Processing Media...**\nExtracting a {duration}s sample clip now.")
        
        await asyncio.sleep(3) # Temporary mock delay for Sample Video
        mock_url = "https://graph.org/AutoFilter-Sample-Mock-07-12"
        
        MEDIA_STATE[state_key]["spl_proc"] = False
        MEDIA_STATE[state_key]["spl_url"] = mock_url
        await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
        
        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except Exception:
            pass
