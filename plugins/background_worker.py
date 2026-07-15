import os
import asyncio
import logging
import aiofiles
from pymediainfo import MediaInfo
from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from database.multi_db import db
from config import Config

logger = logging.getLogger(__name__)

# ==========================================
# ⚡ DYNAMIC FAST MODE ENGINE
# ==========================================
FAST_MODE_ACTIVE = False 

def is_fast_mode_active():
    """Returns the current state of the Fast Mode."""
    global FAST_MODE_ACTIVE
    return FAST_MODE_ACTIVE

def toggle_fast_mode():
    """Flips the Fast Mode state and returns the new state."""
    global FAST_MODE_ACTIVE
    FAST_MODE_ACTIVE = not FAST_MODE_ACTIVE
    return FAST_MODE_ACTIVE

# A clean, scalable dictionary of languages and their MKV abbreviations
LANGUAGE_MAP = {
    "tamil": ["tamil", "'ta'", "'tam'"],
    "telugu": ["telugu", "'te'", "'tel'"],
    "hindi": ["hindi", "'hi'", "'hin'"],
    "english": ["english", "'en'", "'eng'"],
    "malayalam": ["malayalam", "'ml'", "'mal'"],
    "kannada": ["kannada", "'kn'", "'kan'"],
    "bengali": ["bengali", "'bn'", "'ben'"],
    "marathi": ["marathi", "'mr'", "'mar'"],
    "gujarati": ["gujarati", "'gu'", "'guj'"],
    "punjabi": ["punjabi", "'pa'", "'pan'"],
    "urdu": ["urdu", "'ur'", "'urd'"],
    "odia": ["odia", "oriya", "'or'", "'ori'"],
    "japanese": ["japanese", "'ja'", "'jpn'"],
    "korean": ["korean", "'ko'", "'kor'"],
    "chinese": ["chinese", "mandarin", "cantonese", "'zh'", "'chi'", "'zho'"],
    "french": ["french", "'fr'", "'fre'", "'fra'"],
    "spanish": ["spanish", "'es'", "'spa'"],
    "german": ["german", "'de'", "'ger'", "'deu'"],
    "russian": ["russian", "'ru'", "'rus'"],
    "arabic": ["arabic", "'ar'", "'ara'"]
}

async def extract_language_micro_chunk(client: Client, file_id: str, unique_id: str) -> tuple[str, str]:
    """Streams a 2MB chunk and extracts both Audio and Subtitle tracks."""
    chunk_limit = 2 * 1024 * 1024  # 2MB limits bandwidth usage safely
    temp_path = f"temp_{unique_id}.mkv"
    downloaded = 0

    audio_found = set()
    subs_found = set()

    try:
        async with aiofiles.open(temp_path, 'wb') as f:
            async for chunk in client.stream_media(file_id):
                await f.write(chunk)
                downloaded += len(chunk)
                if downloaded >= chunk_limit:
                    break 

        media_info = await asyncio.to_thread(MediaInfo.parse, temp_path)

        for track in media_info.tracks:
            if track.track_type == "Audio":
                track_data = str(track.to_data()).lower()
                for lang, keywords in LANGUAGE_MAP.items():
                    if any(keyword in track_data for keyword in keywords):
                        audio_found.add(lang)

            elif track.track_type == "Text":
                track_data = str(track.to_data()).lower()
                for lang, keywords in LANGUAGE_MAP.items():
                    if any(keyword in track_data for keyword in keywords):
                        subs_found.add(lang)

        final_audio = " ".join(list(audio_found)) if audio_found else "unknown"
        final_subs = " ".join(list(subs_found)) if subs_found else "none"

        return final_audio, final_subs

    except FloodWait as fw:
        raise fw  
    except Exception as e:
        logger.error(f"Worker extraction error on {unique_id}: {e}")
        return "corrupted", "corrupted"
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

async def start_background_language_indexer(client: Client):
    """The 24/7 invisible loop that processes files one by one."""
    logger.info("🟢 Background Metadata Worker Started!")

    while True:
        try:
            target_file = None
            target_collection = None

            for coll in db.collections:
                doc = await coll.find_one({"language": "pending"})
                if doc:
                    target_file = doc
                    target_collection = coll
                    break

            if not target_file:
                await asyncio.sleep(60)
                continue

            file_id = target_file.get("file_id")
            unique_id = target_file.get("file_unique_id", "UNKNOWN")

            try:
                audio_langs, sub_langs = await asyncio.wait_for(
                    extract_language_micro_chunk(client, file_id, unique_id),
                    timeout=45.0
                )
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ Worker TIMEOUT on {unique_id}. Marking as corrupted to skip.")
                audio_langs, sub_langs = "corrupted", "corrupted"
            except FloodWait as fw:
                logger.warning(f"⚠️ Worker hit Rate Limit. Sleeping for {fw.value}s")
                await asyncio.sleep(fw.value)
                continue

            await target_collection.update_one(
                {"_id": target_file["_id"]},
                {"$set": {
                    "language": audio_langs,
                    "subtitle": sub_langs
                }}
            )

            # 🛡️ DYNAMIC SAFETY TIMER
            sleep_time = 1.0 if FAST_MODE_ACTIVE else 3.0
            await asyncio.sleep(sleep_time)

        except Exception as e:
            logger.error(f"Background loop crashed: {e}. Restarting in 10s...")
            await asyncio.sleep(10)
