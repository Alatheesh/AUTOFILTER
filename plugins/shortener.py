import logging
import aiohttp
import asyncio
import urllib.parse
import json
import re
from pyrogram import Client, filters
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

VERIFICATION_TOKENS = {}

async def get_shortlink(url: str, api: str, site: str) -> str:
    """Bulletproof Shortener Engine."""
    try:
        custom_key = None
        if "||" in site:
            parts = site.split("||")
            site = parts[0].strip()
            custom_key = parts[1].strip()
        
        # Ensure URL is clean
        site = site.strip()
        safe_url = urllib.parse.quote(url)

        # 1. TinyURL Logic
        if "tinyurl.com" in site.lower():
            async with aiohttp.ClientSession() as session:
                if api and api != "default": 
                    headers = {"Authorization": f"Bearer {api}", "Content-Type": "application/json"}
                    async with session.post("https://api.tinyurl.com/create", headers=headers, json={"url": url}) as response:
                        try:
                            data = await response.json()
                            if "data" in data and "tiny_url" in data["data"]: return data["data"]["tiny_url"]
                        except: pass
                else: 
                    async with session.get(f"https://tinyurl.com/api-create.php?url={safe_url}") as response:
                        if response.status == 200: return await response.text()
            return url

        # 2. Dynamic Template Engine
        async with aiohttp.ClientSession() as session:
            # If the user provided a full raw API link, perform the template injection
            if "{url}" in site:
                api_url = site.replace("{api}", api).replace("{url}", safe_url)
            else:
                # Fallback to regex injection for user-provided raw links (e.g. url=...)
                api_url = re.sub(r"([?&](url|link)=)[^&]+", r"\g<1>" + safe_url, site, flags=re.IGNORECASE)

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*"
            }

            async with session.get(api_url, headers=headers) as response:
                text_response = await response.text()
                try:
                    data = json.loads(text_response)
                    if custom_key and custom_key in data: return data[custom_key]
                    elif "shortenedUrl" in data: return data["shortenedUrl"]
                    elif "short" in data: return data["short"]
                    elif "url" in data: return data["url"]
                except:
                    if text_response.strip().startswith("http"): return text_response.strip()
    except Exception as e:
        logger.error(f"Shortener Error: {e}")
    return url

@Client.on_message(filters.command("setshort") & filters.private & filters.user(Config.ADMINS))
async def live_test_shortener(client: Client, message: Message):
    # Strip quotes, backticks, and whitespace aggressively
    raw_input = message.text.split(" ", 1)[1].strip().strip("'\"`")
    
    status_msg = await message.reply_text("🔄 **Running bulletproof test...**")
    
    # FORCE TEST: Use google.com so GPLinks API doesn't error out on dummy URLs
    test_template = re.sub(r"(url|link)=[^&]+", r"\1=https://google.com", raw_input, flags=re.IGNORECASE)
    test_link = await get_shortlink("https://google.com", "dummy", test_template)
    
    if test_link and test_link.startswith("http") and ("google" in test_link.lower() or "gplink" in test_link.lower()):
        # Save valid config
        parsed = urllib.parse.urlparse(raw_input)
        qs = urllib.parse.parse_qs(parsed.query)
        extracted_api_key = qs.get("api", [""])[0] or qs.get("token", [""])[0] or "default"
        
        await db.update_settings({"shortener_api": extracted_api_key, "shortener_url": raw_input, "shortener_enabled": True})
        await status_msg.edit_text(f"✅ **SUCCESS!**\n\nConfig saved. The bot will now use this template.")
    else:
        await status_msg.edit_text(f"❌ **FAILED.**\n\nThe API did not return a valid link. Ensure your key is correct and valid.\n\nInput received: `{raw_input}`")
