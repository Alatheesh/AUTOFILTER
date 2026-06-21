import logging
import aiohttp
import asyncio
import urllib.parse
import json
import re
from pyrogram import Client, filters
from pyrogram.types import Message
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

VERIFICATION_TOKENS = {}

async def get_shortlink(url: str, api: str, site: str) -> str:
    """🚀 Master Engine: Automatically parses literal developer links!"""
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
                if api and api != "default": 
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

        # 2. RAW DEVELOPER LINK AUTO-PARSER
        async with aiohttp.ClientSession() as session:
            if "{url}" in site:
                # Legacy template support (just in case)
                api_url = site.replace("{api}", api).replace("{url}", safe_url)
            else:
                # 🚀 THE FIX: User pasted the EXACT raw link (e.g. url=yourdestinationlink.com)
                # This Regex finds "url=..." or "link=..." and replaces the fake URL with the real one!
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
    if len(message.command) < 2:
        return await message.reply_text(
            "⚠️ **Format Error!**\nJust paste the EXACT link from your shortener's API documentation!\n\n"
            "**Example:**\n`/setshort https://api.gplinks.com/api?api=35d94...&url=yourdestinationlink.com&alias=CustomAlias`"
        )
    
    # Grab whatever the user pasted after "/setshort "
    raw_input = message.text.split(" ", 1)[1].strip()
    
    template_str = raw_input
    if "||" in raw_input:
        template_str = raw_input.split("||")[0].strip()
        
    # Automatically steal the API key from their string so we don't have to ask for it separately!
    parsed = urllib.parse.urlparse(template_str)
    qs = urllib.parse.parse_qs(parsed.query)
    extracted_api_key = qs.get("api", [""])[0] or qs.get("token", [""])[0] or "default"
    
    status_msg = await message.reply_text("🔄 **Testing exact developer link...**")
    
    # Test link
    test_link = await get_shortlink("https://google.com", extracted_api_key, raw_input)
    
    if test_link and test_link != "https://google.com" and test_link.startswith("http"):
        await db.update_settings({
            "shortener_api": extracted_api_key,
            "shortener_url": raw_input,
            "shortener_enabled": True
        })
        await status_msg.edit_text(
            f"✅ **TEST PASSED & SAVED!**\n\n"
            f"🌍 **Test Link Generated:**\n`{test_link}`\n\n"
            f"⚙️ **Your Bot Configuration is now 🟢 ON.**\n"
            f"I automatically extracted your API Key: `{extracted_api_key}` and configured the engine!"
        )
    else:
        await status_msg.edit_text(
            f"❌ **TEST FAILED! (Not Saved)**\n\n"
            f"The server connected, but failed to return a valid shortlink. Check your URL.\n\n"
            f"Are you sure you pasted the complete string from the documentation?"
        )
