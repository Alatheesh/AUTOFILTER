import asyncio
import os
import logging
import aiofiles
from pymediainfo import MediaInfo
from pyrogram import Client
from pyrogram.errors import FloodWait
from database.multi_db import db

logger = logging.getLogger(__name__)

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

        # THE FIX: Generate the raw metadata in a background thread to prevent freezing!
        media_info = await asyncio.to_thread(MediaInfo.parse, temp_path)

        for track in media_info.tracks:
            # Check for AUDIO tracks
            if track.track_type == "Audio":
                track_data = str(track.to_data()).lower()
                for lang, keywords in LANGUAGE_MAP.items():
                    if any(keyword in track_data for keyword in keywords):
                        audio_found.add(lang)

            # Check for SUBTITLE (Text) tracks
            elif track.track_type == "Text":
                track_data = str(track.to_data()).lower()
                for lang, keywords in LANGUAGE_MAP.items():
                    if any(keyword in track_data for keyword in keywords):
                        subs_found.add(lang)

        final_audio = " ".join(list(audio_found)) if audio_found else "unknown"
        final_subs = " ".join(list(subs_found)) if subs_found else "none"

        return final_audio, final_subs

    except Exception as e:
        logger.error(f"Worker extraction error on {unique_id}: {e}")
        return "unknown", "none"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

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
            unique_id = target_file.get("file_unique_id")

            audio_langs, sub_langs = await extract_language_micro_chunk(client, file_id, unique_id)

            await target_collection.update_one(
                {"_id": target_file["_id"]},
                {"$set": {
                    "language": audio_langs,
                    "subtitle": sub_langs
                }}
            )

            # 🛡️ Highly Stable Safety Timer (3.0s)
            await asyncio.sleep(3.0)

        except FloodWait as fw:
            logger.warning(f"⚠️ Worker hit Rate Limit. Sleeping for {fw.value}s")
            await asyncio.sleep(fw.value)
        except Exception as e:
            logger.error(f"Background loop crashed: {e}. Restarting in 10s...")
            await asyncio.sleep(10)
