import time
import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import Config

logger = logging.getLogger(__name__)

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

def get_screenshot_selection_markup(file_unique_id: str) -> InlineKeyboardMarkup:
    """Generates selection buttons 1 to 10 for screenshots + Cancel option."""
    buttons = []
    # Row 1: 1-5
    row1 = [InlineKeyboardButton(str(i), callback_data=f"med_ss_req:{i}:{file_unique_id}") for i in range(1, 6)]
    # Row 2: 6-10
    row2 = [InlineKeyboardButton(str(i), callback_data=f"med_ss_req:{i}:{file_unique_id}") for i in range(6, 11)]
    
    buttons.append(row1)
    buttons.append(row2)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"med_revert:{file_unique_id}")])
    return InlineKeyboardMarkup(buttons)

def get_sample_selection_markup(file_unique_id: str) -> InlineKeyboardMarkup:
    """Generates options for sample video duration + Cancel option."""
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
    """Triggers when user clicks '🖼️ Screenshots'."""
    file_unique_id = callback.matches[0].group(1)
    await callback.message.edit_reply_markup(
        reply_markup=get_screenshot_selection_markup(file_unique_id)
    )
    await callback.answer()

@Client.on_callback_query(filters.regex(r"^med_spl_flow:(.+)"))
async def handle_sample_flow(client: Client, callback: CallbackQuery):
    """Triggers when user clicks '🎬 Sample Video'."""
    file_unique_id = callback.matches[0].group(1)
    await callback.message.edit_reply_markup(
        reply_markup=get_sample_selection_markup(file_unique_id)
    )
    await callback.answer()

@Client.on_callback_query(filters.regex(r"^med_revert:(.+)"))
async def handle_ui_revert(client: Client, callback: CallbackQuery):
    """Reverts the button interface back to the original layout if Cancel is pressed."""
    file_unique_id = callback.matches[0].group(1)
    
    # ⚠️ Developer Note: In your actual search plugin, fetch the existing buttons 
    # (like download/shortener links) and append this base list to them.
    original_buttons = get_initial_media_markup(file_unique_id)
    
    await callback.message.edit_reply_markup(
        reply_markup=InlineKeyboardMarkup(original_buttons)
    )
    await callback.answer("Cancelled Operation")

# ==========================================
# 🚀 QUEUE HOOK PLACEHOLDERS (For Phase 2)
# ==========================================

@Client.on_callback_query(filters.regex(r"^med_ss_req:(\d+):(.+)"))
async def handle_screenshot_request(client: Client, callback: CallbackQuery):
    """Triggers when a numeric screenshot count is confirmed."""
    num_images = int(callback.matches[0].group(1))
    file_unique_id = callback.matches[0].group(2)
    
    # Instantly strip the utility buttons so the user cannot double-click or reuse them
    await callback.message.edit_reply_markup(reply_markup=None)
    
    await callback.answer(f"⏳ Added request for {num_images} screenshots to the processing queue...", show_alert=True)
    # TODO: Pass this to the Phase 2 Mediator Queue Engine

@Client.on_callback_query(filters.regex(r"^med_spl_req:(\d+):(.+)"))
async def handle_sample_request(client: Client, callback: CallbackQuery):
    """Triggers when a sample clip duration is confirmed."""
    duration = int(callback.matches[0].group(1))
    file_unique_id = callback.matches[0].group(2)
    
    # Instantly strip the utility buttons
    await callback.message.edit_reply_markup(reply_markup=None)
    
    await callback.answer(f"⏳ Added request for {duration}s sample video to the processing queue...", show_alert=True)
    # TODO: Pass this to the Phase 2 Mediator Queue Engine
