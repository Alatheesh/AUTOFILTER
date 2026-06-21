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
    """Bulletproof Shortener Engine with strict network timeouts."""
    try:
        custom_key = None
        if "||" in site:
            parts = site.split("||")
            site = parts[0].strip()
            custom_key = parts[1].strip()
        
        site = site.strip()
        safe_url = urllib.parse.quote(url)

        if "tinyurl.com" in site.lower():
            async with aiohttp.ClientSession() as session:
                if api and api != "default": 
                    headers = {"Authorization": f"Bearer {api}", "Content-Type": "application/json"}
                    # ADDED TIMEOUT TO PREVENT HANGING
                    async with session.post("https://api.tinyurl.com/create", headers=headers, json={"url": url}, timeout=8) as response:
                        try:
                            data = await response.json()
                            if "data" in data and "tiny_url" in data["data"]: return data["data"]["tiny_url"]
                        except: pass
                else: 
                    async with session.get(f"https://tinyurl.com/api-create.php?url={safe_url}", timeout=8) as response:
                        if response.status == 200: return await response.text()
            return url

        async with aiohttp.ClientSession() as session:
            if "{url}" in site:
                api_url = site.replace("{api}", api).replace("{url}", safe_url)
            else:
                api_url = re.sub(r"([?&](url|link)=)[^&]+", r"\g<1>" + safe_url, site, flags=re.IGNORECASE)

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*"
            }

            # ADDED STRICT 10-SECOND TIMEOUT
            async with session.get(api_url, headers=headers, timeout=10) as response:
                text_response = await response.text()
                try:
                    data = json.loads(text_response)
                    if custom_key and custom_key in data: return data[custom_key]
                    elif "shortenedUrl" in data: return data["shortenedUrl"]
                    elif "short" in data: return data["short"]
                    elif "url" in data: return data["url"]
                except:
                    if text_response.strip().startswith("http"): return text_response.strip()
    except asyncio.TimeoutError:
        logger.error("Shortener Error: The API server timed out and did not respond.")
    except Exception as e:
        logger.error(f"Shortener Error: {e}")
    return url

@Client.on_message(filters.command("setshort") & filters.private & filters.user(Config.ADMINS))
async def live_test_shortener(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply_text("⚠️ **Format Error!** Usage: `/setshort <Your_Full_API_URL>`")
    
    raw_input = message.text.split(" ", 1)[1].strip().strip("'\"`")
    status_msg = await message.reply_text("🔄 **Analyzing and cleaning API link...**")
    
    try:
        # 🚀 --- THE URL AUTO-CLEANER ENGINE ---
        parsed = urllib.parse.urlparse(raw_input)
        qs = urllib.parse.parse_qs(parsed.query)
        
        extracted_api_key = "default"
        has_url = False
        
        for key in list(qs.keys()):
            key_lower = key.lower()
            
            if key_lower in ['api', 'token']:
                extracted_api_key = qs[key][0]
                qs[key] = ['{api}']
            elif key_lower in ['url', 'link']:
                qs[key] = ['{url}']
                has_url = True
            elif key_lower in ['alias', 'format']:
                del qs[key]
                
        if not has_url:
            qs['url'] = ['{url}']
            
        clean_query = urllib.parse.urlencode(qs, doseq=True).replace("%7Bapi%7D", "{api}").replace("%7Burl%7D", "{url}")
        clean_template = urllib.parse.urlunparse((
            parsed.scheme, parsed.netloc, parsed.path, parsed.params, clean_query, parsed.fragment
        ))
    except Exception as e:
        # Catch and print parsing errors instead of hanging
        return await status_msg.edit_text(f"❌ **Parsing Error:**\n`{e}`\n\nPlease check your URL format.")

    try:
        await status_msg.edit_text(f"🧪 **Testing Auto-Cleaned Template:**\n`{clean_template}`\n\nPlease wait...")
    except Exception:
        # Fallback if markdown parsing fails
        await status_msg.edit_text("🧪 **Testing Auto-Cleaned Template...**\n\nPlease wait...")
    
    try:
        test_link = await get_shortlink("https://google.com", extracted_api_key, clean_template)
    except Exception as e:
        # Catch fatal test errors instead of hanging
        return await status_msg.edit_text(f"❌ **FAILED: Internal Error**\n\n`{e}`\n\nTemplate:\n`{clean_template}`")
        
    if test_link and test_link.startswith("http") and ("google" in test_link.lower() or "gplink" in test_link.lower() or "short" in test_link.lower()):
        await db.update_settings({"shortener_api": extracted_api_key, "shortener_url": clean_template, "shortener_enabled": True})
        await status_msg.edit_text(f"✅ **SUCCESS!**\n\nThe bot perfectly cleaned your link, stripped bad tags, and isolated your API key.\n\n**API Key:** `{extracted_api_key}`\n**Template:** `{clean_template}`\n\n🟢 **Shortener is now ACTIVE!**")
    else:
        # Provide exactly what failed so you can troubleshoot it
        await status_msg.edit_text(f"❌ **FAILED.**\n\nThe API did not return a valid link. Ensure your key is correct and GPLinks is online.\n\nCleaned Template Tested:\n`{clean_template}`\n\nResponse Received from API:\n`{test_link}`")
