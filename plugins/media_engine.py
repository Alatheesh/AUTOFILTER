import os
import time
import uuid
import asyncio
import aiohttp
import re
import logging
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto
from pyrogram.file_id import FileId
from pyrogram.raw.functions.upload import GetFile
from pyrogram.raw.types import InputDocumentFileLocation
from database.multi_db import db

logger = logging.getLogger(__name__)

MAX_CONCURRENT_JOBS = 2
media_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
current_queue_size = 0  
MEDIA_STATE = {}

async def get_file_by_unique_id(unique_id: str):
    """Searches all database collections for the full file data using the short ID."""
    for coll in db.collections:
        doc = await coll.find_one({"file_unique_id": unique_id})
        if doc: return doc
    return None

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
        
        chunk_size = 1024 * 1024 
        start_chunk = start // chunk_size
        end_chunk = end // chunk_size
        
        try:
            file_id_obj = FileId.decode(file_id)
            location = InputDocumentFileLocation(
                id=file_id_obj.media_id,
                access_hash=file_id_obj.access_hash,
                file_reference=file_id_obj.file_reference,
                thumb_size=""
            )
            
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
        except Exception:
            pass 
            
        return resp

STREAMER_INSTANCE = None

async def ensure_streamer_running(client):
    global STREAMER_INSTANCE
    if not STREAMER_INSTANCE:
        STREAMER_INSTANCE = LocalStreamer(client)
        await STREAMER_INSTANCE.start()


# ==========================================
# 🌐 THE KEYLESS FALLBACK UPLOADER
# ==========================================

async def upload_file_waterfall(file_path: str, is_video: bool = False) -> str:
    """Attempts to upload to multiple keyless public APIs. Returns URL on success."""
    file_name = os.path.basename(file_path)
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 1000:
        return None
        
    with open(file_path, 'rb') as f:
        file_data = f.read()

    # 🚀 SSL BYPASS: Hugging Face sometimes blocks strict SSL handshakes. 
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        
        # 🌐 ATTEMPT 1: Uguu.se (Extremely fast, 128MB limit)
        try:
            form = aiohttp.FormData()
            form.add_field('files[]', file_data, filename=file_name)
            async with session.post('https://uguu.se/upload.php', data=form, timeout=120) as resp:
                if resp.status == 200:
                    res_json = await resp.json()
                    if res_json.get('success'):
                        return res_json['files'][0]['url']
        except Exception as e:
            logger.warning(f"Uguu Upload Error: {e}")

        # 🌐 ATTEMPT 2: 0x0.st (Developer favorite)
        try:
            form = aiohttp.FormData()
            form.add_field('file', file_data, filename=file_name)
            async with session.post('https://0x0.st', data=form, timeout=120) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    if text.startswith("http"):
                        return text.strip()
        except Exception as e:
            logger.warning(f"0x0.st Upload Error: {e}")

        # 🌐 ATTEMPT 3: Catbox / Litterbox (The original fallback)
        try:
            form = aiohttp.FormData()
            if is_video:
                form.add_field('reqtype', 'fileupload')
                form.add_field('time', '72h')
                form.add_field('fileToUpload', file_data, filename=file_name)
                url = 'https://litterbox.catbox.moe/resources/internals/api.php'
            else:
                form.add_field('reqtype', 'fileupload')
                form.add_field('fileToUpload', file_data, filename=file_name)
                url = 'https://catbox.moe/user/api.php'
                
            async with session.post(url, data=form, timeout=120) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    if text.startswith("http"):
                        return text.strip()
        except Exception as e:
            logger.warning(f"Catbox Upload Error: {e}")

    return None

# ==========================================
# ⚙️ PHASE 3: FFMPEG MEDIA ENGINES
# ==========================================

async def generate_watermarked_screenshots(client: Client, status_msg, file_id: str, num_images: int, file_name: str, file_size: int, target_chat_id: int, target_msg_id: int) -> str:
    await ensure_streamer_running(client)
    
    temp_dir = "/tmp/autofilter_media"
    os.makedirs(temp_dir, exist_ok=True)
    unique_run_id = str(uuid.uuid4())[:8]
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
        
        # Pointing explicitly to the font we installed in the Dockerfile
        font_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        
        for i in range(1, num_images + 1):
            timestamp = int(interval * i)
            img_path = os.path.join(temp_dir, f"frame_{unique_run_id}_{i}.jpg")
            
            ff_cmd = (
                f'ffmpeg -y -ss {timestamp} -i "{video_url}" -vframes 1 -q:v 2 '
                f'-vf "drawtext=fontfile={font_path}:text=\'@llathu63035\':x=10:y=h-th-10:fontsize=24:fontcolor=white@0.9:shadowcolor=black@0.8:shadowx=2:shadowy=2, '
                f'drawtext=fontfile={font_path}:text=\'%{{pts\\:hms}}\':x=w-tw-10:y=h-th-10:fontsize=24:fontcolor=white@0.9:shadowcolor=black@0.8:shadowx=2:shadowy=2" '
                f'"{img_path}"'
            )
            process = await asyncio.create_subprocess_shell(ff_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await process.communicate()
            
            if os.path.exists(img_path) and os.path.getsize(img_path) > 0:
                image_paths.append(img_path)
                
        # 🌐 ATTEMPT 1 & 2: External Server Uploads
        await status_msg.edit_text("⚙️ **Processing Media...**\n`[3/3]` Uploading frames to external servers...")
        uploaded_urls = []
        for img in image_paths:
            url = await upload_file_waterfall(img, is_video=False)
            if url:
                uploaded_urls.append(url)
                
        if len(uploaded_urls) == len(image_paths) and len(image_paths) > 0:
            msg_text = f"🖼 **{file_name[:80]}**\n\n"
            for idx, url in enumerate(uploaded_urls):
                msg_text += f"📸 [Screenshot {idx+1}]({url})\n"
            msg_text += "\n_Screenshots Generated by @suchitha1bot_"
            
            await client.send_message(chat_id=target_chat_id, text=msg_text, reply_to_message_id=target_msg_id, disable_web_page_preview=False)
            return "SENT"
            
        # 🌐 ATTEMPT 3: Native Fallback (If External APIs fail)
        await status_msg.edit_text("⚠️ **External Servers Failed.**\n`[3/3]` Falling back to Native Secure Album...")
        if image_paths:
            media_group = []
            for idx, img in enumerate(image_paths):
                caption = f"🖼 **{file_name[:80]}**\n_Screenshots Generated by @suchitha1bot_" if idx == 0 else ""
                media_group.append(InputMediaPhoto(media=img, caption=caption))
            
            await client.send_media_group(chat_id=target_chat_id, media=media_group, reply_to_message_id=target_msg_id)
            return "SENT"
            
        return None
            
    finally:
        for img in [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if unique_run_id in f]:
            if os.path.exists(img):
                os.remove(img)


async def generate_sample_video(client: Client, status_msg, file_id: str, sample_duration: int, file_name: str, file_size: int, target_chat_id: int, target_msg_id: int) -> str:
    await ensure_streamer_running(client)
    
    temp_dir = "/tmp/autofilter_media"
    os.makedirs(temp_dir, exist_ok=True)
    unique_run_id = str(uuid.uuid4())[:8]
    video_url = f"http://127.0.0.1:8080/stream/{file_id}?size={file_size}"
    out_video_path = os.path.join(temp_dir, f"sample_{unique_run_id}.mp4")
    
    try:
        await status_msg.edit_text("⚙️ **Processing Media...**\n`[1/3]` Analyzing stream timeline...")
        
        probe_cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_url}"'
        proc = await asyncio.create_subprocess_shell(probe_cmd, stdout=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        try:
            total_duration = float(stdout.decode().strip())
        except Exception:
            total_duration = 120.0
            
        start_time = max(0, int((total_duration / 2) - (sample_duration / 2)))
        font_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        
        await status_msg.edit_text(f"⚙️ **Processing Media...**\n`[2/3]` Rendering {sample_duration}s watermarked video clip...\n_(This takes a moment)_")
        
        ff_cmd = (
            f'ffmpeg -y -ss {start_time} -i "{video_url}" -t {sample_duration} '
            f'-vf "drawtext=fontfile={font_path}:text=\'@llathu63035\':x=10:y=h-th-10:fontsize=16:fontcolor=white@0.9:shadowcolor=black@0.8:shadowx=2:shadowy=2" '
            f'-c:v libx264 -preset veryfast -crf 28 -c:a aac -b:a 128k "{out_video_path}"'
        )
        process = await asyncio.create_subprocess_shell(ff_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await process.communicate()
        
        if os.path.exists(out_video_path) and os.path.getsize(out_video_path) > 10000:
            
            # 🌐 ATTEMPT 1 & 2: External Server Uploads
            await status_msg.edit_text("⚙️ **Processing Media...**\n`[3/3]` Uploading video to external servers...")
            video_url = await upload_file_waterfall(out_video_path, is_video=True)
            
            if video_url:
                msg_text = f"🎬 **Sample Video ({sample_duration}s)**\n📁 {file_name[:80]}\n\n🔗 [Watch/Download Video]({video_url})\n_Generated by @suchitha1bot_"
                await client.send_message(chat_id=target_chat_id, text=msg_text, reply_to_message_id=target_msg_id)
                return "SENT"
                
            # 🌐 ATTEMPT 3: Native Fallback (If External APIs fail)
            await status_msg.edit_text("⚠️ **External Servers Failed.**\n`[3/3]` Falling back to Native Video Upload...")
            caption = f"🎬 **Sample Video ({sample_duration}s)**\n📁 {file_name[:80]}"
            await client.send_video(chat_id=target_chat_id, video=out_video_path, caption=caption, reply_to_message_id=target_msg_id, supports_streaming=True)
            return "SENT"
            
        return None
            
    finally:
        if os.path.exists(out_video_path):
            os.remove(out_video_path)


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
    
    if state["ss_url"] == "SENT":
        btn_ss = InlineKeyboardButton("✅ Screenshots Sent", callback_data="ignore_spam")
    elif state["ss_proc"]:
        btn_ss = InlineKeyboardButton("⏳ Processing SS...", callback_data="ignore_spam")
    else:
        btn_ss = InlineKeyboardButton("🖼️ Screenshots", callback_data=f"med_ss_flow:{file_unique_id}")
        
    if state["spl_url"] == "SENT":
        btn_spl = InlineKeyboardButton("✅ Sample Sent", callback_data="ignore_spam")
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
            await status_msg.edit_text("❌ **Error:** Could not locate the raw file.")
            MEDIA_STATE[state_key]["ss_proc"] = False
            await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
            return
            
        actual_file_id = file_data.get("file_id")
        movie_title = file_data.get("title", "Unknown Movie")
        file_size_bytes = file_data.get("size", 0)
        
        try:
            gallery_result = await generate_watermarked_screenshots(client, status_msg, actual_file_id, num_images, movie_title, file_size_bytes, chat_id, msg_id)
            
            if gallery_result == "SENT":
                MEDIA_STATE[state_key]["ss_url"] = "SENT"
            else:
                await status_msg.edit_text("⚠️ **Upload Failed:** Could not generate or send frames.")
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
        
        file_data = await get_file_by_unique_id(file_unique_id)
        if not file_data:
            await status_msg.edit_text("❌ **Error:** Could not locate the raw file.")
            MEDIA_STATE[state_key]["spl_proc"] = False
            await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
            return
            
        actual_file_id = file_data.get("file_id")
        movie_title = file_data.get("title", "Unknown Movie")
        file_size_bytes = file_data.get("size", 0)
        
        try:
            sample_result = await generate_sample_video(client, status_msg, actual_file_id, duration, movie_title, file_size_bytes, chat_id, msg_id)
            
            if sample_result == "SENT":
                MEDIA_STATE[state_key]["spl_url"] = "SENT" 
            else:
                await status_msg.edit_text("⚠️ **Upload Failed:** Could not extract sample clip.")
                MEDIA_STATE[state_key]["spl_proc"] = False
                
        except Exception as e:
            logger.error(f"Sample Video Error: {e}")
            await status_msg.edit_text("❌ **Engine Error:** Failed to process the sample.")
            MEDIA_STATE[state_key]["spl_proc"] = False
        
        MEDIA_STATE[state_key]["spl_proc"] = False
        await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
        
        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except Exception:
            pass
