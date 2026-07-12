import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

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
# 🚀 PHASE 2: MEDIATOR QUEUE ENGINE
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
        await status_msg.edit_text(f"⚙️ **Processing Media...**\nGenerating {num_images} screenshots now.")
        
        # ----------------------------------------------------
        # TODO: PHASE 3 - FFmpeg Execution goes here
        # ----------------------------------------------------
        await asyncio.sleep(5) # Mock delay for testing
        mock_url = "https://telegra.ph/AutoFilter-Screenshots-Mock-07-12"
        # ----------------------------------------------------
        
        # 5. Execution Finished: Update State & Buttons
        MEDIA_STATE[state_key]["ss_proc"] = False
        MEDIA_STATE[state_key]["ss_url"] = mock_url
        await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
        
        await status_msg.delete()


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
        # TODO: PHASE 3 - FFmpeg Execution goes here
        # ----------------------------------------------------
        await asyncio.sleep(5) # Mock delay for testing
        mock_url = "https://telegra.ph/AutoFilter-Sample-Mock-07-12"
        # ----------------------------------------------------
        
        MEDIA_STATE[state_key]["spl_proc"] = False
        MEDIA_STATE[state_key]["spl_url"] = mock_url
        await callback.message.edit_reply_markup(reply_markup=get_dynamic_media_markup(chat_id, msg_id, file_unique_id))
        
        await status_msg.delete()
