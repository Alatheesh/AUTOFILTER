import logging
import aiohttp
import asyncio
import urllib.parse
import json
from pyrogram import Client, filters
from pyrogram.types import Message
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# Shared memory for verification loops
VERIFICATION_TOKENS = {}

async def get_shortlink(url: str, api: str, site: str) -> str:
    """🚀 The Ultimate Dynamic Shortener Engine with '|| Custom Key' Support"""
    try:
        custom_key = None
        if "||" in site:
            parts = site.split("||")
            site = parts[0].strip()
            custom_key = parts[1].strip()
            
        site = site.strip()
        safe_url = urllib.parse.quote(url)

        # 1. TINYURL ENGINE
        if "tinyurl.com" in site.lower():
            async with aiohttp.ClientSession() as session:
                if api: 
                    headers = {"Authorization": f"Bearer {api}", "Content-Type": "application/json"}
                    async with session.post("https://api.tinyurl.com/create", headers=headers, json={"url": url}) as response:
                        try:
                            data = await response.json()
                            if "data" in data and "tiny_url" in data["data"]: return data["data"]["tiny_url"]
                        except Exception: pass
                else: 
                    async with session.get(f"https://tinyurl.com/api-create.php?url={safe_url}") as response:
                        if response.status == 200: return await response.text()
            return url 

        # 2. DYNAMIC TEMPLATE ENGINE
        async with aiohttp.ClientSession() as session:
            if "{url}" in site and "{api}" in site:
                api_url = site.replace("{api}", api).replace("{url}", safe_url)
            else:
                if not site.startswith("http"): site = f"https://{site}"
                if "gplinks.in" in site or "gplinks.com" in site: site = "https://api.gplinks.com/api"
                api_url = f"{site}?api={api}&url={safe_url}&format=json"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*"
            }

            async with session.get(api_url, headers=headers) as response:
                text_response = await response.text()
                
                try:
                    data = json.loads(text_response)
                    # Hunt for the Custom Key first!
                    if custom_key and custom_key in data: return data[custom_key]
                    elif "shortenedUrl" in data: return data["shortenedUrl"]
                    elif "short" in data: return data["short"]
                    elif "url" in data: return data["url"]
                    elif data.get("status") == "error":
                        logger.error(f"Shortener API Error: {data.get('message')}")
                except Exception:
                    # Fallback for plain text responses (like format=text)
                    if text_response.strip().startswith("http"): return text_response.strip()

    except Exception as e:
        logger.error(f"Shortener Network Error: {e}")
        
    return url

@Client.on_message(filters.command("setshort") & filters.private & filters.user(Config.ADMINS))
async def live_test_shortener(client: Client, message: Message):
    """Admin command to dynamically test and save a shortener configuration."""
    if len(message.command) < 3:
        return await message.reply_text(
            "⚠️ **Format Error!**\nUse this format to test and set your shortener:\n\n"
            "`/setshort [API_KEY] [URL_TEMPLATE] || [OPTIONAL_JSON_KEY]`\n\n"
            "**Example 1 (Standard):**\n`/setshort 35d945... https://api.gplinks.com/api?api={api}&url={url}&format=text`\n\n"
            "**Example 2 (Custom JSON Key):**\n`/setshort 12345xyz https://weirdsite.com/api?token={api}&link={url} || resulting_url`"
        )
    
    api_key = message.command[1]
    template_str = message.text.split(" ", 2)[2].strip()
    
    status_msg = await message.reply_text("🔄 **Testing API Connection...**\nPlease wait, checking if your formula works...")
    
    # Run a LIVE TEST using Google as the dummy link
    test_link = await get_shortlink("https://google.com", api_key, template_str)
    
    if test_link and test_link != "https://google.com" and test_link.startswith("http"):
        # Test Passed! Save to Database
        await db.update_settings({
            "shortener_api": api_key,
            "shortener_url": template_str,
            "shortener_enabled": True
        })
        await status_msg.edit_text(
            f"✅ **TEST PASSED & SAVED!**\n\n"
            f"🌍 **Test Link Generated:**\n`{test_link}`\n\n"
            f"⚙️ **Your Bot Configuration is now 🟢 ON and set to:**\n"
            f"**API:** `{api_key}`\n"
            f"**Template:** `{template_str}`"
        )
    else:
        await status_msg.edit_text(
            f"❌ **TEST FAILED! (Not Saved)**\n\n"
            f"The server connected, but failed to return a valid shortlink. Check your formula or JSON key.\n\n"
            f"Make sure you are using `{{api}}` and `{{url}}` exactly as written!"
        )
