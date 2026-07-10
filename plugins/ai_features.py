import os
import random
import logging
from pyrogram import Client, filters, StopPropagation
from pyrogram.types import Message
from config import Config
from plugins.search import auto_filter
# Import the robust library
from huggingface_hub import InferenceClient

logger = logging.getLogger(__name__)

# Global Maintenance Toggle
AI_FEATURES_ENABLED = True 

# Helper to get an AI client
def get_ai_client(model_id):
    if not getattr(Config, "HF_TOKENS", None):
        return None
    token = random.choice(Config.HF_TOKENS)
    return InferenceClient(model=model_id, token=token)

# ==========================================
# 📸 AI POSTER SCANNER (Updated to use InferenceClient)
# ==========================================
@Client.on_message(filters.photo & filters.private)
async def ai_poster_scanner(client: Client, message: Message):
    if not AI_FEATURES_ENABLED: return

    status_msg = await message.reply_text("📸 **Scanning image (Optimized)...**")

    try:
        # 1. Download photo
        file_path = await message.download()
        
        # 2. Use official library (handles DNS/connections better)
        ai_client = get_ai_client("microsoft/trocr-base-printed")
        if not ai_client:
            return await status_msg.edit_text("❌ **AI tokens missing.**")

        # 3. Perform OCR
        # InferenceClient handles the image upload and parsing
        result = ai_client.image_to_text(file_path)
        
        os.remove(file_path) # Clean up

        # 4. Result is usually just the text string for this model
        extracted_text = str(result).strip()
        
        if not extracted_text or len(extracted_text) < 2:
            return await status_msg.edit_text("❌ **No text found in image.**")

        await status_msg.edit_text(f"📸 **I read:** `{extracted_text}`\n🔍 *Searching database...*")
        
        message.text = extracted_text
        await auto_filter(client, message)
        await status_msg.delete()

    except Exception as e:
        logger.error(f"Image Scan Error: {e}")
        await status_msg.edit_text(f"❌ **Scanner Failed.** (Check logs for details)")
    
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

# ==========================================
# 🌐 NETWORK DIAGNOSTIC TOOL
# ==========================================
@Client.on_message(filters.command("check_net"))
async def check_network(client: Client, message: Message):
    status_msg = await message.reply_text("🔍 Testing network connection...")
    try:
        async with aiohttp.ClientSession() as session:
            # Try to connect to Google to see if we have internet
            async with session.get("https://www.google.com", timeout=5) as response:
                await status_msg.edit_text(f"✅ **Network is UP!**\nResponse Code: {response.status}")
    except Exception as e:
        await status_msg.edit_text(f"❌ **Network is DOWN!**\nError: `{e}`")
