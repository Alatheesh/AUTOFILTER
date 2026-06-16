import asyncio
import os
import logging
import aiofiles
from pymediainfo import MediaInfo
from pyrogram import Client
from pyrogram.errors import FloodWait
from database.multi_db import db

logger = logging.getLogger(__name__)

async def extract_language_micro_chunk(client: Client, file_id: str, unique_id: str) -> str:
    """Streams only the first 2MB of a video to read internal audio tracks."""
    chunk_limit = 2 * 1024 * 1024  # 2 Megabytes
    temp_path = f"temp_{unique_id}.mkv"
    downloaded = 0
    languages_found = set()

    try:
        async with aiofiles.open(temp_path, 'wb') as f:
            async for chunk in client.stream_media(file_id):
                await f.write(chunk)
                downloaded += len(chunk)
                if downloaded >= chunk_limit:
                    break 

        media_info = MediaInfo.parse(temp_path)
        for track in media_info.tracks:
            if track.track_type == "Audio" and track.language:
                lang = track.language.lower()
                if "tam" in lang: languages_found.add("tamil")
                elif "tel" in lang: languages_found.add("telugu")
                elif "hin" in lang: languages_found.add("hindi")
                elif "eng" in lang: languages_found.add("english")
                elif "mal" in lang: languages_found.add("malayalam")
                elif "kan" in lang: languages_found.add("kannada")

        if languages_found:
            return " ".join(list(languages_found))
        return "unknown"

    except Exception as e:
        logger.error(f"Worker extraction error on {unique_id}: {e}")
        return "unknown"
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
            
            extracted_langs = await extract_language_micro_chunk(client, file_id, unique_id)
            
            await target_collection.update_one(
                {"_id": target_file["_id"]},
                {"$set": {"language": extracted_langs}}
            )
            
            # SAFE API LIMIT SLEEP
            await asyncio.sleep(4)

        except FloodWait as fw:
            logger.warning(f"⚠️ Worker hit Rate Limit. Sleeping for {fw.value}s")
            await asyncio.sleep(fw.value)
        except Exception as e:
            logger.error(f"Background loop crashed: {e}. Restarting in 10s...")
            await asyncio.sleep(10)
