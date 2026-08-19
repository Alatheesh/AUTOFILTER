import os
import time
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
    return FAST_MODE_ACTIVE

def toggle_fast_mode():
    global FAST_MODE_ACTIVE
    FAST_MODE_ACTIVE = not FAST_MODE_ACTIVE
    return FAST_MODE_ACTIVE

# ==========================================
# 🔄 RECHECK ENGINE (For Skipped/Corrupted)
# ==========================================
RECHECK_MODE_ACTIVE = False
RECHECK_SESSION_ID = 0

def is_recheck_mode_active():
    return RECHECK_MODE_ACTIVE

def start_recheck_mode():
    global RECHECK_MODE_ACTIVE, RECHECK_SESSION_ID
    RECHECK_MODE_ACTIVE = True
    RECHECK_SESSION_ID = int(time.time())

def stop_recheck_mode():
    global RECHECK_MODE_ACTIVE
    RECHECK_MODE_ACTIVE = False

LANGUAGE_MAP = {
    # 🇮🇳 Indian & South Asian
    "tamil": ["tamil", "'ta'", "'tam'"],
    "telugu": ["telugu", "'te'", "'tel'"],
    "hindi": ["hindi", "'hi'", "'hin'"],
    "malayalam": ["malayalam", "'ml'", "'mal'"],
    "kannada": ["kannada", "'kn'", "'kan'"],
    "bengali": ["bengali", "'bn'", "'ben'"],
    "marathi": ["marathi", "'mr'", "'mar'"],
    "gujarati": ["gujarati", "'gu'", "'guj'"],
    "punjabi": ["punjabi", "'pa'", "'pan'"],
    "urdu": ["urdu", "'ur'", "'urd'"],
    "odia": ["odia", "oriya", "'or'", "'ori'"],
    "assamese": ["assamese", "'as'", "'asm'"],
    "bhojpuri": ["bhojpuri", "'bho'"],
    "sindhi": ["sindhi", "'sd'", "'snd'"],
    "nepali": ["nepali", "'ne'", "'nep'"],
    "sinhala": ["sinhala", "sinhalese", "'si'", "'sin'"],
    "pashto": ["pashto", "'ps'", "'pus'"],

    # 🌐 Core International
    "english": ["english", "'en'", "'eng'"],
    "spanish": ["spanish", "'es'", "'spa'"],
    "french": ["french", "'fr'", "'fre'", "'fra'"],
    "german": ["german", "'de'", "'ger'", "'deu'"],
    "russian": ["russian", "'ru'", "'rus'"],
    "portuguese": ["portuguese", "'pt'", "'por'"],
    "italian": ["italian", "'it'", "'ita'"],

    # ⛩️ East Asian & Southeast Asian
    "japanese": ["japanese", "'ja'", "'jpn'"],
    "korean": ["korean", "'ko'", "'kor'"],
    "chinese": ["chinese", "mandarin", "cantonese", "'zh'", "'chi'", "'zho'", "'yue'", "'cmn'"],
    "indonesian": ["indonesian", "'id'", "'ind'"],
    "malay": ["malay", "'ms'", "'may'", "'msa'"],
    "thai": ["thai", "'th'", "'tha'"],
    "vietnamese": ["vietnamese", "'vi'", "'vie'"],
    "tagalog": ["tagalog", "filipino", "'tl'", "'tgl'", "'fil'"],
    "burmese": ["burmese", "'my'", "'mya'", "'bur'"],
    "khmer": ["khmer", "cambodian", "'km'", "'khm'"],

    # 🌍 Middle Eastern & African
    "arabic": ["arabic", "'ar'", "'ara'"],
    "turkish": ["turkish", "'tr'", "'tur'"],
    "persian": ["persian", "farsi", "'fa'", "'per'", "'fas'"],
    "hebrew": ["hebrew", "'he'", "'heb'"],
    "kurdish": ["kurdish", "'ku'", "'kur'"],
    "swahili": ["swahili", "'sw'", "'swa'"],
    "amharic": ["amharic", "'am'", "'amh'"],
    "afrikaans": ["afrikaans", "'af'", "'afr'"],

    # 🇪🇺 Expanded European
    "dutch": ["dutch", "flemish", "'nl'", "'dut'", "'nld'"],
    "polish": ["polish", "'pl'", "'pol'"],
    "ukrainian": ["ukrainian", "'uk'", "'ukr'"],
    "greek": ["greek", "'el'", "'gre'", "'ell'"],
    "swedish": ["swedish", "'sv'", "'swe'"],
    "norwegian": ["norwegian", "'no'", "'nor'", "'nob'", "'nno'"],
    "danish": ["danish", "'da'", "'dan'"],
    "finnish": ["finnish", "'fi'", "'fin'"],
    "czech": ["czech", "'cs'", "'cze'", "'ces'"],
    "hungarian": ["hungarian", "'hu'", "'hun'"],
    "romanian": ["romanian", "'ro'", "'rum'", "'ron'"],
    "slovak": ["slovak", "'sk'", "'slo'", "'slk'"],
    "croatian": ["croatian", "'hr'", "'hrv'"],
    "serbian": ["serbian", "'sr'", "'srp'"],
    "bulgarian": ["bulgarian", "'bg'", "'bul'"],

    # 🏛️ Miscellaneous & Classic
    "latin": ["latin", "'la'", "'lat'"],
    "esperanto": ["esperanto", "'eo'", "'epo'"]
}

async def extract_language_micro_chunk(client: Client, file_id: str, unique_id: str) -> tuple[str, str]:
    chunk_limit = 2 * 1024 * 1024  
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

        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            return "unknown", "none"

        media_info = await asyncio.to_thread(MediaInfo.parse, temp_path)

        for track in media_info.tracks:
            if track.track_type == "Audio":
                if getattr(track, 'other_language', None):
                    lang = track.other_language[0].lower()
                    if lang != 'und': audio_found.add(lang)
                elif getattr(track, 'language', None):
                    lang = track.language.lower()
                    if lang != 'und': audio_found.add(lang)

                track_data = str(track.to_data()).lower()
                for lang, keywords in LANGUAGE_MAP.items():
                    if any(keyword in track_data for keyword in keywords):
                        audio_found.add(lang)

            elif track.track_type == "Text":
                if getattr(track, 'other_language', None):
                    lang = track.other_language[0].lower()
                    if lang != 'und': subs_found.add(lang)
                elif getattr(track, 'language', None):
                    lang = track.language.lower()
                    if lang != 'und': subs_found.add(lang)

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
    global RECHECK_MODE_ACTIVE
    logger.info("🟢 Background Metadata Worker Started!")

    consecutive_errors = 0

    while True:
        try:
            target_file = None
            target_collection = None

            # 🚀 PRIORITY 1: Always check for NEW pending files first!
            for coll in db.collections:
                doc = await coll.find_one({"language": "pending"})
                if doc:
                    target_file = doc
                    target_collection = coll
                    break

            # 🔄 PRIORITY 2: If no pending files, check the Skipped Queue
            if not target_file and RECHECK_MODE_ACTIVE:
                for coll in db.collections:
                    doc = await coll.find_one({
                        "language": {"$in": ["unknown", "corrupted"]},
                        "recheck_session": {"$ne": RECHECK_SESSION_ID}
                    })
                    if doc:
                        target_file = doc
                        target_collection = coll
                        break
                
                if not target_file:
                    RECHECK_MODE_ACTIVE = False
                    logger.info("✅ Recheck session completed! All skipped files scanned.")

            if not target_file:
                consecutive_errors = 0
                await asyncio.sleep(30)
                continue

            file_id = target_file.get("file_id")
            unique_id = target_file.get("file_unique_id", "UNKNOWN")

            # 🚀 FIX: Reduced timeout to 15s to prevent long DC long-polling stalls
            try:
                audio_langs, sub_langs = await asyncio.wait_for(
                    extract_language_micro_chunk(client, file_id, unique_id),
                    timeout=15.0
                )
                consecutive_errors = 0
            except asyncio.TimeoutError:
                logger.warning(f"⚠️ Worker TIMEOUT on {unique_id}. Marking as corrupted to skip.")
                audio_langs, sub_langs = "corrupted", "corrupted"
                consecutive_errors += 1
            except FloodWait as fw:
                logger.warning(f"⚠️ Worker hit Rate Limit. Sleeping for {fw.value}s")
                await asyncio.sleep(fw.value)
                continue
            except Exception as e:
                logger.warning(f"⚠️ Worker unhandled issue on {unique_id}: {e}")
                audio_langs, sub_langs = "corrupted", "corrupted"
                consecutive_errors += 1

            # 📝 Update database
            update_data = {
                "language": audio_langs,
                "subtitle": sub_langs
            }
            
            if RECHECK_MODE_ACTIVE and target_file.get("language") in ["unknown", "corrupted"]:
                update_data["recheck_session"] = RECHECK_SESSION_ID

            await target_collection.update_one(
                {"_id": target_file["_id"]},
                {"$set": update_data}
            )

            # 🚀 FIX: Smart dynamic backoff to protect MTProto connection
            if consecutive_errors >= 3:
                logger.warning("⚠️ Multiple media errors detected. Pausing worker for 5s to stabilize connection...")
                await asyncio.sleep(5.0)
                consecutive_errors = 0
            else:
                sleep_time = 1.0 if FAST_MODE_ACTIVE else 2.5
                await asyncio.sleep(sleep_time)

        except Exception as e:
            logger.error(f"Background loop crashed: {e}. Restarting in 10s...")
            await asyncio.sleep(10)
