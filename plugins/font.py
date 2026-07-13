import math
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ForceReply
from fonts import apply_font

# 🧠 Temporary RAM Cache
pending_font_texts = {}

# 📚 THE FULL FONT MENU LIST
# Tuple format: ("Button Display Name", "font_dictionary_key")
ALL_FONTS = [
    ("𝗔𝗯𝗰 (Sans Bold)", "sans_bold"),
    ("𝖠𝖻𝖼 (Sans Normal)", "sans_normal"),
    ("𝐀𝐛𝐜 (Serif Bold)", "serif_bold"),
    ("𝙰𝚋𝚌 (Monospace)", "monospace"),
    ("𝘈𝘉𝘊 (Sans Italic)", "sans_italic"),
    ("𝘼𝘽𝘾 (Sans Bold Italic)", "sans_bold_italic"),
    ("𝐴𝐵𝐶 (Serif Italic)", "serif_italic"),
    ("𝑨𝑩𝑪 (Serif Bold Italic)", "serif_bold_italic"),
    ("𝒜𝒷𝒸 (Script)", "script_normal"),
    ("𝓐𝓑𝓒 (Script Bold)", "script_bold"),
    ("𝔄𝔟𝔠 (Fraktur)", "fraktur_normal"),
    ("𝕬𝕭𝕮 (Fraktur Bold)", "fraktur_bold"),
    ("𝔸𝔹ℂ (Double Struck)", "double_struck"),
    ("Ⓐⓑⓒ (Circled)", "circled"),
    ("🅐🅑🅒 (Neg Circled)", "negative_circled"),
    ("🄰🄱🄲 (Squared)", "squared"),
    ("🅰🅱🅲 (Neg Squared)", "negative_squared"),
    ("⒜⒝⒞ (Parentheses)", "parenthesized"),
    ("ᴀʙᴄ (Small Caps)", "small_caps"),
    ("ᴬᴮᶜ (Superscript)", "superscript"),
    ("ₐBCD (Subscript)", "subscript"),
    ("ＡＢＣ (Fullwidth)", "fullwidth_symbols"),
    ("∀𐐒Ɔ (Inverted)", "inverted"),
    ("AᙠƆ (Reversed)", "reversed"),
    ("ДБС (Faux Cyrillic)", "faux_cyrillic"),
    ("Λß८ (Faux Ethio)", "faux_ethiopian"),
    ("48C (Leet Speak)", "leet_speak"),
    ("₳฿₵ (Currency)", "currency"),
    ("卂乃匚 (Medieval)", "medieval"),
    ("卂乃匚 (Aesthetic)", "aesthetic"),
    ("ABC (Normal)", "normal")
]

FONTS_PER_PAGE = 10  # Shows 5 rows of 2 buttons per page

def get_font_keyboard(page: int = 0):
    """Generates the paginated Inline Keyboard dynamically."""
    total_pages = math.ceil(len(ALL_FONTS) / FONTS_PER_PAGE)
    
    # Calculate start and end indices for the current page
    start_idx = page * FONTS_PER_PAGE
    end_idx = start_idx + FONTS_PER_PAGE
    current_page_fonts = ALL_FONTS[start_idx:end_idx]
    
    keyboard = []
    row = []
    
    # 1. Build the font buttons (2 per row)
    for display_name, font_key in current_page_fonts:
        row.append(InlineKeyboardButton(display_name, callback_data=f"applyfont_{font_key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row: # Catch any leftover odd button
        keyboard.append(row)
        
    # 2. Build the Pagination buttons (Prev/Next)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"fontpage_{page - 1}"))
    
    # Middle button showing current page
    nav_buttons.append(InlineKeyboardButton(f"📖 {page + 1}/{total_pages}", callback_data="ignore_pagination"))
    
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"fontpage_{page + 1}"))
        
    keyboard.append(nav_buttons)
    
    return InlineKeyboardMarkup(keyboard)


@Client.on_message(filters.command("font") & filters.private)
async def font_command_handler(client, message):
    """Triggers when the user sends /font or /font <text>"""
    
    if len(message.command) > 1:
        raw_text = message.text.split(None, 1)[1]
        pending_font_texts[message.from_user.id] = raw_text

    await message.reply_text(
        "✨ **Select a Font Style:**\n_Choose how you want your text to look!_",
        reply_markup=get_font_keyboard(page=0)
    )


@Client.on_callback_query(filters.regex(r"^fontpage_(\d+)"))
async def pagination_handler(client, callback_query):
    """Handles the Prev and Next page flips."""
    new_page = int(callback_query.matches[0].group(1))
    
    await callback_query.message.edit_reply_markup(
        reply_markup=get_font_keyboard(page=new_page)
    )


@Client.on_callback_query(filters.regex(r"^applyfont_(.*)"))
async def font_selection_handler(client, callback_query):
    """Triggers when the user clicks an actual font button."""
    font_style = callback_query.matches[0].group(1)
    user_id = callback_query.from_user.id
    chat_id = callback_query.message.chat.id
    
    await callback_query.message.delete()
    
    # SCENARIO A: They provided text in the command
    if user_id in pending_font_texts:
        raw_text = pending_font_texts.pop(user_id)
        await send_split_text(client, chat_id, raw_text, font_style)
        
    # SCENARIO B: Ask for text using ForceReply
    else:
        await client.send_message(
            chat_id=chat_id,
            text=f"📝 **Send the text you want to convert to `{font_style}`:**\n\n_(Reply directly to this message)_",
            reply_markup=ForceReply(selective=True)
        )


@Client.on_message(filters.reply & filters.private)
async def process_font_reply(client, message):
    """Triggers when the user replies to the ForceReply prompt."""
    if message.reply_to_message and "Send the text you want to convert to" in message.reply_to_message.text:
        try:
            font_style = message.reply_to_message.text.split("`")[1]
        except IndexError:
            return

        raw_text = message.text
        if not raw_text:
            return
            
        await send_split_text(client, message.chat.id, raw_text, font_style)


async def send_split_text(client, chat_id, text, font_style):
    """Translates text and safely splits it into chunks to avoid Telegram limits."""
    translated_text = apply_font(text, font_style)
    chunk_size = 4000
    
    for i in range(0, len(translated_text), chunk_size):
        chunk = translated_text[i : i + chunk_size]
        await client.send_message(chat_id=chat_id, text=chunk)
