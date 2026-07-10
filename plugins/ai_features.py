import os
import random
import logging
from pyrogram import Client, filters, StopPropagation
from pyrogram.types import Message
from config import Config
from plugins.search import auto_filter
from huggingface_hub import InferenceClient

logger = logging.getLogger(__name__)

# 🛠️ GLOBAL AI MAINTENANCE TOGGLE
AI_FEATURES_ENABLED = True 

# Helper to get an AI client
def get_ai_client(model_id):
    if not getattr(Config, "HF_TOKENS", None):
        return None
    token = random.choice(Config.HF_TOKENS)
    # We removed the 'base_url' argument. 
    # InferenceClient knows where to connect automatically.
    return InferenceClient(
        model=model_id, 
        token=token
    )
# ==========================================
# 🎙️ 1. AI VOICE SEARCH
# ==========================================
@Client.on_message((filters.voice | filters.audio) & filters.private)
async def ai_voice_search(client: Client, message: Message):
    if not AI_FEATURES_ENABLED: return
    status_msg = await message.reply_text("🎙️ **Listening to your voice...**")

    try:
        file_path = await message.download()
        client_ai = get_ai_client("openai/whisper-tiny")
        if not client_ai: return await status_msg.edit_text("❌ **AI tokens missing.**")

        # Use official library
        result = client_ai.automatic_speech_recognition(file_path)
        os.remove(file_path)

        # Handle text extraction
        spoken_text = str(result).strip()
        clean_text = "".join([c for c in spoken_text if c.isalnum() or c.isspace()])
        
        await status_msg.edit_text(f"🗣️ **You said:** `{clean_text}`\n🔍 *Searching...*")
        message.text = clean_text
        await auto_filter(client, message)
        await status_msg.delete()
    except Exception as e:
        logger.error(f"Voice Search Error: {e}")
        await status_msg.edit_text("❌ **AI temporarily unavailable.**")
    raise StopPropagation

# ==========================================
# 🌍 2. AI LANGUAGE TRANSLATOR
# ==========================================
@Client.on_message(filters.command("translate") & filters.private)
async def ai_language_translator(client: Client, message: Message):
    if not AI_FEATURES_ENABLED: return
    if len(message.command) < 2: return await message.reply_text("⚠️ **Format:** `/translate <name>`")

    foreign_text = message.text.split(" ", 1)[1]
    status_msg = await message.reply_text("🌍 **Translating...**")

    try:
        client_ai = get_ai_client("facebook/nllb-200-distilled-600M")
        if not client_ai: return await status_msg.edit_text("❌ **AI tokens missing.**")

        result = client_ai.translation(text=foreign_text)
        # InferenceClient translation returns a dict with 'translation_text'
        english_text = result.get('translation_text', foreign_text).strip()

        await status_msg.edit_text(f"🌍 **Translated:** `{english_text}`\n🔍 *Searching...*")
        message.text = english_text
        await auto_filter(client, message)
        await status_msg.delete()
    except Exception as e:
        logger.error(f"Translation Error: {e}")
        await status_msg.edit_text("❌ **Translation Failed.**")
    raise StopPropagation

# ==========================================
# 📸 3. AI POSTER SCANNER
# ==========================================
@Client.on_message(filters.photo & filters.private)
async def ai_poster_scanner(client: Client, message: Message):
    if not AI_FEATURES_ENABLED: return
    status_msg = await message.reply_text("📸 **Scanning image...**")

    try:
        file_path = await message.download()
        client_ai = get_ai_client("naver-clova-ix/donut-base")
        if not client_ai: return await status_msg.edit_text("❌ **AI tokens missing.**")

        extracted_text = client_ai.image_to_text(file_path).strip()
        os.remove(file_path)

        if not extracted_text or len(extracted_text) < 2:
            return await status_msg.edit_text("❌ **No text found.**")

        await status_msg.edit_text(f"📸 **I read:** `{extracted_text}`\n🔍 *Searching...*")
        message.text = extracted_text
        await auto_filter(client, message)
        await status_msg.delete()
    except Exception as e:
        logger.error(f"Image Scan Error: {e}")
        await status_msg.edit_text("❌ **Scanner Failed.**")
    raise StopPropagation
