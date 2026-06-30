import math
from pyrogram.enums import ChatType
from database.multi_db import db

MB = 1024 * 1024
GB = 1024 * MB

# Add new sizes here easily in the future
SIZE_MAP = {
    "small": (0, 500 * MB),
    "medium": (500 * MB, 1 * GB),
    "large": (1 * GB, 2 * GB),
    "xlarge": (2 * GB, float('inf')),
    "all": (0, float('inf'))
}

async def get_filter_settings(user_id: int, chat_id: int, chat_type):
    """
    Resolves conflicts between Group Admin forced settings and User personal settings.
    """
    if chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        g_sett = await db.get_group_settings(chat_id)
        g_mode = g_sett.get("search_mode", "let_members_choose")
        
        if g_mode == "force_default": 
            return "default", "all", "all"
        elif g_mode == "force_interactive": 
            return "interactive", g_sett.get("language_lock", "all"), g_sett.get("size_lock", "all")
            
    # Fallback to User's personal settings
    u_sett = await db.get_user_settings(user_id)
    return u_sett.get("search_mode", "default"), u_sett.get("language", "all"), u_sett.get("size", "all")


def apply_search_filters(raw_results: list, mode: str, language: str, size: str) -> list:
    """
    The Master Filter Engine.
    To add new features (like Year, Quality, Genre), simply add them as arguments here
    and add a simple 'if' check inside the loop.
    """
    min_bytes, max_bytes = SIZE_MAP.get(size, (0, float('inf')))
    filtered_results = []
    
    for file in raw_results:
        # 1. SIZE FILTER (Applies universally based on mapping)
        if not (min_bytes <= file.get("size", 0) <= max_bytes): 
            continue
            
        # 2. INTERACTIVE FILTERS
        if mode == "interactive":
            # --- Language Filter ---
            if language not in ["all", "none"]:
                lang_data = file.get("language", "unknown").lower()
                title_data = file.get("title", "").lower()
                
                if language.lower() not in lang_data and language.lower() not in title_data:
                    continue
            
            # 🚀 FUTURE ADDITIONS GO HERE:
            # if quality != "all" and quality not in file.get("title", "").lower():
            #     continue

        filtered_results.append(file)
        
    return filtered_results
