import os
import time
import uuid
import json
import asyncio
import aiohttp
import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from database.multi_db import db

logger = logging.getLogger(__name__)

# ==========================================
# 🚦 ENGINE STATE & CONCURRENCY CONTROLS
# ==========================================
# Strictly limit Hugging Face to 2 concurrent media tasks to prevent RAM/CPU Crashes
MAX_CONCURRENT_JOBS = 2
media_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

# Tracks how many people are currently waiting in line
current_queue_size = 0  

# RAM State Tracker to remember button layouts without using the Database
# Format: { "chat_id_msg_id": {"ss_url": str, "spl_url": str, "ss_proc": bool, "spl_proc": bool} }
MEDIA_STATE = {}


# ==========================================
# ⚙️ PHASE 3: FFMPEG & CLOUD UPLOAD ENGINE
# ==========================================

async def get_file_by_unique_id(unique_id: str):
    """Searches all database collections for the full file data using the short ID."""
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
            with open(img_path, 'rb') as f:
                form = aiohttp.FormData()
                form.add_field('file', f, filename=os.path.basename(img_path), content_type='image/jpeg')
                async with session.post('https://telegra.ph/upload', data=form) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        if isinstance(res_json, list) and 'src' in res_json[0]:
                            uploaded_urls.append(f"https://telegra.ph{res_json[0]['src']}")
        
        if not uploaded_urls:
            return None
            
        # 2. Construct the Telegraph Page HTML
        html_content = ""
        for url in uploaded_urls:
            html_content += f'<img src="{url}"/><br>'
            
        html_content += f'<br><br><b>Credits:</b> @llathu63035<br><b>Developer:</b> @TG_LATHEESH'

        # 3. Create a temporary Telegraph account and publish the page
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
            
            # 🚀 THE MAGIC SWAP: Bypassing the Indian ISP Block!
            clean_url = page_data['url'].replace("telegra.ph", "graph.org")
            return clean_url

async def generate_watermarked_screenshots(client: Client, status_msg, file_id: str, num_images: int, file_name: str) -> str:
    """Downloads the file, extracts frames via FFmpeg, uploads them, and cleans up."""
    temp_dir = "/tmp/autofilter_media"
    os.makedirs(temp_dir, exist_ok=True)
    
    unique_run_id = str(uuid.uuid4())[:8]
    video_path = os.path.join(temp_dir, f"vid_{unique_run_id}.mkv")
    
    try:
        # 1. Download the target file safely
        await status_msg.edit_text("⚙️ **Processing Media...**\n`[1/4]` Downloading stream to secure server buffer...")
        await client.download_media(message=file_id, file_name=video_path)
        
        # 2. Get video duration using ffprobe
        await status_msg.edit_text("⚙️ **Processing Media...**\n`[2/4]` Analyzing video matrix...")
        probe_cmd = f'ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "{video_path}"'
        proc = await asyncio.create_subprocess_shell(probe_cmd, stdout=asyncio.subprocess.PIPE)
        stdout, _ = await proc.communicate()
        try:
            duration = float(stdout.decode().strip())
        except Exception:
            duration = 120.0 # Fallback if metadata is missing
            
        # 3. Extract and watermark the frames
        await status_msg.edit_text(f"⚙️ **Processing Media...**\n`[3/4]` Rendering {num_images} watermarked frames...")
        image_paths = []
        interval = duration / (num_images + 1)
        
        for i in range(1, num_images + 1):
            timestamp = int(interval * i)
            img_path = os.path.join(temp_dir, f"frame_{unique_run_id}_{i}.jpg")
            
            # The elite FFmpeg rendering command with timestamps and your specific watermark
            ff_cmd = (
                f'ffmpeg -y -ss {timestamp} -i "{video_path}" -vframes 1 -q:v 2 '
                f'-vf "drawtext=text=\'@llathu63035\':x=20:y=h-th-20:fontsize=36:fontcolor=white@0.9:box=1:boxcolor=black@0.6, '
                f'drawtext=text=\'%{{pts\\:hms}}\':x=w-tw-20:y=h-th-20:fontsize=36:fontcolor=white@0.9:box=1:boxcolor=black@0.6" '
                f'"{img_path}"'
            )
            process = await asyncio.create_subprocess_shell(ff_cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await process.communicate()
            
            if os.path.exists(img_path):
                image_paths.append(img_path)
                
        # 4. Upload to Telegraph
        await status_msg.edit_text("⚙️ **Processing Media...**\n`[4/4]` Uploading gallery to cloud servers...")
        gallery_link = await upload_to_telegraph(image_paths, f"Screenshots: {file_name[:50]}")
        return gallery_link
        
    finally:
        # 🧹 5. CRITICAL PURGE: Delete all files instantly to protect Hugging Face storage
        if os.path.exists(video_path):
            os.remove(video_path)
        for img in [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if unique_run_id in f]:
            if os.path.exists(img):
                os.remove(img)


# ==========================================
# 🛠️ UI COMPONENT GENERATORS
# ==========================================

def get_initial_media_markup(file_unique_id: str) -> list:
    """Returns the base buttons to append to your delivered file message."""
    return [
        [
            InlineKeyboardButton("🖼️ Screenshots", callback_data=f"med_ss_flow:{file_unique_id}"),
            InlineKeyboardButton("🎬 Sample Video", callback_data=f"med_spl_flow:{file_unique_id}")
        ]
    ]

def get_dynamic_media_markup(chat_id: int, message_id: int, file_unique_id: str) -> InlineKeyboardMarkup:
    """Intelligently rebuilds the buttons based on what is currently processing or completed."""
    state_key = f"{chat_id}_{message_id}"
    state = MEDIA_STATE.get(state_key, {"ss_url": None, "spl_url": None, "ss_proc": False, "spl_proc": False})
    
    # 1. Evaluate Screenshot Button State
    if state["ss_url"]:
        btn_ss = InlineKeyboardButton("🔗 Watch Screenshots", url=state["ss_url"])
    elif state["ss_proc"]:
        btn_ss = InlineKeyboardButton("⏳ Processing SS...", callback_data="ignore_spam")
    else:
        btn_ss = InlineKeyboardButton("🖼️ Screenshots", callback_data=f"med_ss_flow:{file_unique_id}")
        
    # 2. Evaluate Sample Video Button State
    if state["spl_url"]:
        btn_spl = InlineKeyboardButton("🔗 Watch Sample", url=state["spl_url"])
    elif state["spl_proc"]:
        btn_spl = InlineKeyboardButton("⏳ Processing Sample...", callback_data="ignore_spam")
    else:
        btn_spl = InlineKeyboardButton("🎬 Sample Video", callback_data=f"med_spl_flow:{file_unique_id}")
        
    return InlineKeyboardMarkup([[btn_ss, btn_spl]])

def get_screenshot_selection_markup(file_unique_id: str) -> InlineKeyboardMarkup:
    """Generates selection buttons 1 to 10 for screenshots."""
    buttons = [
        [InlineKeyboardButton(str(i), callback_data=f"med_ss_req:{i}:{file_unique_id}") for i in range(1, 6)],
        [InlineKeyboardButton(str(i), callback_data=f"med_ss_req:{i}:{file_unique_id}") for i in range(6, 11)],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"med_revert:{file_unique_id}")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_sample_selection_markup(file_unique_id: str) -> InlineKeyboardMarkup:
    """Generates options for sample video duration."""
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
    
    # Intelligently reverts back to whatever state the buttons were in before clicking
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
    
    # 1. Initialize state and mark as processing
    if state_key not in MEDIA_STATE:
        MEDIA_STATE[state_key] = {"ss_url": None, "spl_url": None, "ss_proc": False, "spl_proc": False}
    MEDIA_STATE[state_key]["ss_proc"] = True
    
    # 2. Update the original message buttons instantly
    await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
    
    # 3. Add to queue and send private status update
    current_queue_size += 1
    queue_position = current_queue_size
    status_msg = await callback.message.reply_text(
        f"⏳ **Request Queued!**\n**Task:** `{num_images} Screenshots`\n**Queue Position:** `#{queue_position}`\n_Please wait..._"
    )
    await callback.answer("Added to queue!", show_alert=False)
    
    # 4. 🛑 THE BOTTLENECK (Wait in line here)
    async with media_semaphore:
        current_queue_size -= 1
        
        # ----------------------------------------------------
        # THE PHASE 3 INTEGRATION
        # ----------------------------------------------------
        file_data = await get_file_by_unique_id(file_unique_id)
        if not file_data:
            await status_msg.edit_text("❌ **Error:** Could not locate the raw file in the database.")
            MEDIA_STATE[state_key]["ss_proc"] = False
            await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
            return
            
        actual_file_id = file_data.get("file_id")
        movie_title = file_data.get("title", "Unknown Movie")
        
        try:
            # Boot up the heavy FFmpeg engine!
            gallery_url = await generate_watermarked_screenshots(client, status_msg, actual_file_id, num_images, movie_title)
            
            if gallery_url:
                MEDIA_STATE[state_key]["ss_url"] = gallery_url
            else:
                await status_msg.edit_text("⚠️ **Upload Failed:** Could not push images to Telegraph.")
                MEDIA_STATE[state_key]["ss_proc"] = False
                
        except Exception as e:
            logger.error(f"FFmpeg Generation Error: {e}")
            await status_msg.edit_text("❌ **Engine Error:** The media processor encountered a fatal error.")
            MEDIA_STATE[state_key]["ss_proc"] = False
        # ----------------------------------------------------
        
        # 5. Execution Finished: Update State & Buttons
        MEDIA_STATE[state_key]["ss_proc"] = False
        await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
        
        # Clean up the status message
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
        
        # ----------------------------------------------------
        # TODO: PHASE 3 - Sample Video FFmpeg Extraction
        # ----------------------------------------------------
        await asyncio.sleep(3) # Temporary mock delay for Sample Video
        mock_url = "https://graph.org/AutoFilter-Sample-Mock-07-12"
        # ----------------------------------------------------
        
        MEDIA_STATE[state_key]["spl_proc"] = False
        MEDIA_STATE[state_key]["spl_url"] = mock_url
        await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
        
        await asyncio.sleep(2)
        try:
            await status_msg.delete()
        except Exception:
            pass
