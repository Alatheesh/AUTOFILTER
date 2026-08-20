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

# ==========================================
# 🌍 MASSIVE 100+ GLOBAL LANGUAGE DICTIONARY
# ==========================================
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
    "sanskrit": ["sanskrit", "'sa'", "'san'"],
    "kashmiri": ["kashmiri", "'ks'", "'kas'"],

    # 🌐 Core International
    "english": ["english", "'en'", "'eng'"],
    "spanish": ["spanish", "castilian", "'es'", "'spa'"],
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
    "burmese": ["burmese", "myanmar", "'my'", "'mya'", "'bur'"],
    "khmer": ["khmer", "cambodian", "'km'", "'khm'"],
    "lao": ["lao", "'lo'", "'lao'"],
    "javanese": ["javanese", "'jv'", "'jav'"],
    "sundanese": ["sundanese", "'su'", "'sun'"],
    "cebuano": ["cebuano", "visayan", "'ceb'"],
    "hmong": ["hmong", "'hmn'"],
    "tibetan": ["tibetan", "'bo'", "'tib'", "'bod'"],

    # 🌍 Middle Eastern & African
    "arabic": ["arabic", "'ar'", "'ara'"],
    "turkish": ["turkish", "'tr'", "'tur'"],
    "persian": ["persian", "farsi", "'fa'", "'per'", "'fas'"],
    "hebrew": ["hebrew", "'he'", "'heb'"],
    "kurdish": ["kurdish", "'ku'", "'kur'"],
    "swahili": ["swahili", "'sw'", "'swa'"],
    "amharic": ["amharic", "'am'", "'amh'"],
    "afrikaans": ["afrikaans", "'af'", "'afr'"],
    "zulu": ["zulu", "'zu'", "'zul'"],
    "xhosa": ["xhosa", "'xh'", "'xho'"],
    "yoruba": ["yoruba", "'yo'", "'yor'"],
    "igbo": ["igbo", "'ig'", "'ibo'"],
    "hausa": ["hausa", "'ha'", "'hau'"],
    "shona": ["shona", "'sn'", "'sna'"],
    "somali": ["somali", "'so'", "'som'"],
    "malagasy": ["malagasy", "'mg'", "'mlg'"],
    "kinyarwanda": ["kinyarwanda", "'rw'", "'kin'"],
    "nyanja": ["nyanja", "chichewa", "'ny'", "'nya'"],
    "sotho": ["sotho", "'st'", "'sot'"],
    "tigrinya": ["tigrinya", "'ti'", "'tir'"],

    # 🇪🇺 European, Nordic & Eastern European
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
    "romanian": ["romanian", "moldavian", "'ro'", "'rum'", "'ron'"],
    "slovak": ["slovak", "'sk'", "'slo'", "'slk'"],
    "croatian": ["croatian", "'hr'", "'hrv'"],
    "serbian": ["serbian", "'sr'", "'srp'"],
    "bulgarian": ["bulgarian", "'bg'", "'bul'"],
    "bosnian": ["bosnian", "'bs'", "'bos'"],
    "slovenian": ["slovenian", "'sl'", "'slv'"],
    "macedonian": ["macedonian", "'mk'", "'mac'", "'mkd'"],
    "albanian": ["albanian", "'sq'", "'sqi'", "'alb'"],
    "estonian": ["estonian", "'et'", "'est'"],
    "latvian": ["latvian", "'lv'", "'lav'"],
    "lithuanian": ["lithuanian", "'lt'", "'lit'"],
    "icelandic": ["icelandic", "'is'", "'isl'", "'ice'"],
    "georgian": ["georgian", "'ka'", "'kat'", "'geo'"],
    "armenian": ["armenian", "'hy'", "'hye'", "'arm'"],
    "azerbaijani": ["azerbaijani", "'az'", "'aze'"],
    "belarusian": ["belarusian", "'be'", "'bel'"],
    "kazakh": ["kazakh", "'kk'", "'kaz'"],
    "uzbek": ["uzbek", "'uz'", "'uzb'"],
    "turkmen": ["turkmen", "'tk'", "'tuk'"],
    "tajik": ["tajik", "'tg'", "'tgk'"],
    "kyrgyz": ["kyrgyz", "'ky'", "'kir'"],
    "tatar": ["tatar", "'tt'", "'tat'"],
    "uyghur": ["uyghur", "'ug'", "'uig'"],

    # 🗺️ Regional, Miscellaneous & Classic
    "catalan": ["catalan", "'ca'", "'cat'"],
    "basque": ["basque", "'eu'", "'eus'", "'baq'"],
    "galician": ["galician", "'gl'", "'glg'"],
    "welsh": ["welsh", "'cy'", "'wel'", "'cym'"],
    "irish": ["irish", "'ga'", "'gle'"],
    "scottish gaelic": ["scottish gaelic", "gaelic", "'gd'", "'gla'"],
    "maltese": ["maltese", "'mt'", "'mlt'"],
    "luxembourgish": ["luxembourgish", "'lb'", "'ltz'"],
    "yiddish": ["yiddish", "'yi'", "'yid'"],
    "haitian": ["haitian", "haitian creole", "'ht'", "'hat'"],
    "maori": ["maori", "'mi'", "'mao'", "'mri'"],
    "samoan": ["samoan", "'sm'", "'smo'"],
    "tonga": ["tonga", "'to'", "'ton'"],
    "latin": ["latin", "'la'", "'lat'"],
    "esperanto": ["esperanto", "'eo'", "'epo'"]
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
        logger.error(f"❌ [EXTRACTION_ERROR] Failed on {unique_id}: {e}")
        return "corrupted", "corrupted"
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass

async def start_background_language_indexer(client: Client):
    """The 24/7 invisible loop that processes files one by one."""
    logger.info("🟢 [STARTUP] Background Metadata Worker Started!")

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
                
                # --- [TAGS] CLEAN LOGGING ---
                if audio_langs != "corrupted":
                    logger.info(f"✅ [SUCCESS] File: {unique_id} | Audio: [{audio_langs}] | Subs: [{sub_langs}]")
                    
            except asyncio.TimeoutError:
                logger.warning(f"⏳ [TIMEOUT] File: {unique_id} | Action: Marked corrupted to skip.")
                audio_langs, sub_langs = "corrupted", "corrupted"
            except FloodWait as fw:
                logger.warning(f"🛑 [FLOOD_WAIT] Pausing for {fw.value}s to respect Telegram limits.")
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
            logger.error(f"💥 [CRASH_RECOVERY] Loop failed: {e} | Rebooting in 10s...")
            await asyncio.sleep(10)
