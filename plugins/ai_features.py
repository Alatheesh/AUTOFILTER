import os
import logging
import aiohttp
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from config import Config

logger = logging.getLogger(__name__)

# Fetch the Token from your Config file or Environment
HF_TOKEN = getattr(Config, "HF_TOKEN", os.environ.get("HF_TOKEN", ""))
HEADERS = {"Authorization": f"Bearer {HF_TOKEN}"}

async def fetch_with_retry(url, data=None, json=None, retries=3):
    """Helper function to retry requests if the host network glitches (DNS failures)."""
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as session:
                kwargs = {"headers": HEADERS, "timeout": 30}
                if data: kwargs["data"] = data
                if json: kwargs["json"] = json
                
                async with session.post(url, **kwargs) as resp:
                    result = await resp.json()
                    return resp.status, result
        except aiohttp.ClientError as e:
            if attempt == retries - 1:
                raise e # If it fails 3 times, finally raise the error
            await asyncio.sleep(2) # Wait 2 seconds and try again


# ==========================================
# 🎤 1. AI VOICE SEARCH (Whisper)
# ==========================================
@Client.on_message(filters.voice & filters.private)
async def ai_voice_search(client: Client, message: Message):
    if not HF_TOKEN:
        return await message.reply_text("❌ AI Token not configured.")
        
    msg = await message.reply_text("🎧 **Listening to your voice...**")
    
    try:
        # Download voice note directly into RAM
        audio_file = await message.download(in_memory=True)
        audio_bytes = audio_file.getvalue()
        
        # Direct, fast aiohttp request with Auto-Retry
        status, result = await fetch_with_retry(
            "https://api-inference.huggingface.co/models/openai/whisper-tiny",
            data=audio_bytes
        )
                
        # Handle Sleeping Models Gracefully
        if status == 503:
            return await msg.edit_text("⏳ **AI is warming up!**\nModels go to sleep when inactive. Please try again in 20 seconds.")
        elif status != 200:
            return await msg.edit_text(f"❌ **API Error:** `{result.get('error', 'Unknown Error')}`")
                    
        # Extract Text and redirect to your Search Engine
        text = result.get("text", "").strip()
        if not text:
            return await msg.edit_text("❌ Could not understand the audio. Please speak clearly.")
            
        await msg.edit_text(f"🗣 **You searched for:** `{text}`\n\n*🔍 Fetching results...*")
        
        # Trick the bot into thinking the user typed this text manually
        message.text = text
        from plugins.search import auto_filter
        await auto_filter(client, message)
        
    except Exception as e:
        logger.error(f"Voice Search Error: {e}")
        await msg.edit_text("❌ **Network Error:** Could not connect to AI server. Please try again.")


# ==========================================
# 🌍 2. AI TRANSLATOR (NLLB-200)
# ==========================================
@Client.on_message(filters.command("translate"))
async def ai_language_translator(client: Client, message: Message):
    if not HF_TOKEN:
        return await message.reply_text("❌ AI Token not configured.")
        
    # Grab text from command or replied message
    query = " ".join(message.command[1:])
    if not query and message.reply_to_message:
        query = message.reply_to_message.text or message.reply_to_message.caption
        
    if not query:
        return await message.reply_text("⚠️ **Usage:** `/translate [text]` or reply to a message.")
        
    msg = await message.reply_text("🌍 **Translating...**")
    
    try:
        payload = {"inputs": query}
        
        status, result = await fetch_with_retry(
            "https://api-inference.huggingface.co/models/facebook/nllb-200-distilled-600M",
            json=payload
        )
                
        if status == 503:
            return await msg.edit_text("⏳ **Translator AI is warming up!**\nPlease try again in 20 seconds.")
        elif status != 200:
            return await msg.edit_text(f"❌ **API Error:** `{result.get('error', 'Unknown')}`")
                    
        # Parse the JSON response
        translated_text = ""
        if isinstance(result, list) and len(result) > 0:
            translated_text = result[0].get("translation_text", result[0].get("generated_text", ""))
        else:
            translated_text = str(result)
            
        if not translated_text:
            return await msg.edit_text("❌ Translation returned empty.")
            
        await msg.edit_text(f"🌍 **Translation:**\n\n`{translated_text}`")
        
    except Exception as e:
        logger.error(f"Translation Error: {e}")
        await msg.edit_text("❌ **Network Error:** Could not connect to translation server.")


# ==========================================
# 👁️ 3. AI POSTER SCANNER (Donut Base OCR)
# ==========================================
@Client.on_message(filters.photo & filters.private)
async def ai_poster_scanner(client: Client, message: Message):
    if not HF_TOKEN:
        return
        
    msg = await message.reply_text("👁️ **Scanning image for text...**")
    
    try:
        # Load image into memory
        photo_file = await message.download(in_memory=True)
        image_bytes = photo_file.getvalue()
        
        status, result = await fetch_with_retry(
            "https://api-inference.huggingface.co/models/naver-clova-ix/donut-base",
            data=image_bytes
        )
                
        if status == 503:
            return await msg.edit_text("⏳ **Scanner AI is warming up!**\nPlease try again in 20 seconds.")
        elif status != 200:
            return await msg.edit_text(f"❌ **API Error:** `{result.get('error', 'Unknown')}`")
                    
        # Parse Document QA / OCR response
        text = ""
        if isinstance(result, list) and len(result) > 0:
            text = result[0].get("generated_text", "")
        elif isinstance(result, dict):
            text = result.get("generated_text", "")
            
        if not text:
            return await msg.edit_text("❌ **No readable text found in image.**")
            
        await msg.edit_text(f"👁️ **Scanned Text:**\n\n`{text}`")
        
    except Exception as e:
        logger.error(f"Image Scan Error: {e}")
        await msg.edit_text("❌ **Network Error:** Could not connect to scanner server.")
