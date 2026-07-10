import os
import random
import aiohttp
import logging
from pyrogram import Client, filters, StopPropagation
from pyrogram.types import Message

# Import your config and existing search engine
from config import Config
from plugins.search import auto_filter

logger = logging.getLogger(__name__)

# ==========================================
# 🎙️ 1. AI VOICE SEARCH (Whisper)
# ==========================================
@Client.on_message((filters.voice | filters.audio) & filters.private)
async def ai_voice_search(client: Client, message: Message):
    if not getattr(Config, "HF_TOKENS", None):
        return await message.reply_text("❌ **AI Offline:** Hugging Face tokens are missing.")

    status_msg = await message.reply_text("🎙️ **Listening to your voice...**")

    try:
        file_path = await message.download()

        # 🔄 Pick a random token to prevent rate limits
        current_token = random.choice(Config.HF_TOKENS)
        
        API_URL = "https://api-inference.huggingface.co/models/openai/whisper-tiny"
        headers = {"Authorization": f"Bearer {current_token}"}

        async with aiohttp.ClientSession() as session:
            with open(file_path, "rb") as f:
                data = f.read()
            async with session.post(API_URL, headers=headers, data=data, timeout=15) as response:
                result = await response.json()

        os.remove(file_path) # Clean up the file

        if "text" in result:
            spoken_text = result["text"].strip()
            clean_text = "".join([c for c in spoken_text if c.isalnum() or c.isspace()])
            
            await status_msg.edit_text(f"🗣️ **You said:** `{clean_text}`\n🔍 *Searching database...*")
            
            # Pass the text to your standard search engine
            message.text = clean_text
            await auto_filter(client, message)
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ **Sorry, I couldn't understand the audio.**")

    except Exception as e:
        logger.error(f"Voice Search Error: {e}")
        await status_msg.edit_text("❌ **AI Processing Failed.** The server might be busy.")
    
    raise StopPropagation


# ==========================================
# 🌍 2. AI LANGUAGE TRANSLATOR (Spanish/Etc -> English)
# ==========================================
@Client.on_message(filters.command("translate") & filters.private)
async def ai_language_translator(client: Client, message: Message):
    if not getattr(Config, "HF_TOKENS", None):
        return await message.reply_text("❌ **AI Offline:** Hugging Face tokens are missing.")

    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Format:** `/translate <foreign movie name>`")

    foreign_text = message.text.split(" ", 1)[1]
    status_msg = await message.reply_text("🌍 **Translating query to English...**")

    try:
        # 🔄 Pick a random token to prevent rate limits
        current_token = random.choice(Config.HF_TOKENS)

        API_URL = "https://api-inference.huggingface.co/models/Helsinki-NLP/opus-mt-mul-en"
        headers = {"Authorization": f"Bearer {current_token}"}
        payload = {"inputs": foreign_text}

        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, headers=headers, json=payload, timeout=10) as response:
                result = await response.json()

        if isinstance(result, list) and "translation_text" in result[0]:
            english_text = result[0]["translation_text"].strip()
            await status_msg.edit_text(f"🌍 **Translated to:** `{english_text}`\n🔍 *Searching database...*")
            
            # Pass the English text to your search engine
            message.text = english_text
            await auto_filter(client, message)
            await status_msg.delete()
        else:
            await status_msg.edit_text("⏳ **The Translation AI is currently waking up.** Please try again in 20 seconds!")

    except Exception as e:
        logger.error(f"Translation Error: {e}")
        await status_msg.edit_text("❌ **Translation Failed.**")
        
    raise StopPropagation


# ==========================================
# 📸 3. AI POSTER SCANNER (OCR Image to Text)
# ==========================================
@Client.on_message(filters.photo & filters.private)
async def ai_poster_scanner(client: Client, message: Message):
    if not getattr(Config, "HF_TOKENS", None):
        return await message.reply_text("❌ **AI Offline:** Hugging Face tokens are missing.")

    status_msg = await message.reply_text("📸 **Scanning image for text...**")

    try:
        file_path = await message.download()

        # 🔄 Pick a random token to prevent rate limits
        current_token = random.choice(Config.HF_TOKENS)
        
        API_URL = "https://api-inference.huggingface.co/models/microsoft/trocr-base-printed"
        headers = {"Authorization": f"Bearer {current_token}"}

        async with aiohttp.ClientSession() as session:
            with open(file_path, "rb") as f:
                data = f.read()
            async with session.post(API_URL, headers=headers, data=data, timeout=15) as response:
                result = await response.json()

        os.remove(file_path) # Clean up memory

        if isinstance(result, list) and "generated_text" in result[0]:
            extracted_text = result[0]["generated_text"].strip()
            
            if not extracted_text or len(extracted_text) < 2:
                return await status_msg.edit_text("❌ **Sorry, I couldn't read any clear text in that image.**")

            await status_msg.edit_text(f"📸 **I read:** `{extracted_text}`\n🔍 *Searching database...*")
            
            # Pass the extracted text to your search engine
            message.text = extracted_text
            await auto_filter(client, message)
            await status_msg.delete()
        else:
            await status_msg.edit_text("❌ **I couldn't process this image right now.**")

    except Exception as e:
        logger.error(f"Image Scan Error: {e}")
        await status_msg.edit_text("❌ **AI Scanner Failed.** The server might be busy.")
    
    raise StopPropagation
