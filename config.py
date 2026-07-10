import os
from typing import List

class Config(object):
    # Bot identity
    BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")
    API_ID: int = int(os.environ.get("API_ID", "0"))
    API_HASH: str = os.environ.get("API_HASH", "")

    # Multi-Database Configuration 
    DB_URIS: List[str] = [uri.strip() for uri in os.environ.get("DB_URIS", "").split(",") if uri.strip()]
    DB_NAME: str = os.environ.get("DB_NAME", "AutoFilter")
    
    # Hugging Face deployment
    PORT: int = int(os.environ.get("PORT", "7860"))

    # Admin & Moderation Controls
    ADMINS: List[int] = [int(admin) for admin in os.environ.get("ADMINS", "0").split(",") if admin and admin.isdigit()]
    FSUB_CHANNELS: List[int] = [int(ch) for ch in os.environ.get("FSUB_CHANNELS", "").split(",") if ch]
    
    # Discovery & Premium Settings
    USE_SHORTENERS: bool = os.environ.get("USE_SHORTENERS", "False").lower() == "true"
    PREMIUM_TIER: bool = os.environ.get("PREMIUM_TIER", "False").lower() == "true"
    MAX_RESULTS: int = int(os.environ.get("MAX_RESULTS", "50"))
    
    # 🚀 NEW: TMDB Multi-Key & Poster Config
    TMDB_API_KEYS: List[str] = [k.strip() for k in os.environ.get("TMDB_API_KEYS", "").split(",") if k.strip()]
    DEFAULT_POSTER: str = os.environ.get("DEFAULT_POSTER", "https://images.unsplash.com/photo-1536440136628-849c177e76a1?q=80&w=600")

    # Web App Link Configuration
    BULK_LINK: str = os.environ.get("BULK_LINK", "https://YOUR_GITHUB_USERNAME.github.io/autofilter-web/")
    
    # Ghost mode parameter (Auto-delete links)
    GHOST_MODE_EXPIRY: int = int(os.environ.get("GHOST_MODE_EXPIRY", "86400")) # Default 24 hours

    # Logging channel
    LOG_CHANNEL: int = int(os.environ.get("LOG_CHANNEL", "0"))

    # Default File Caption Engine
    DEFAULT_CAPTION: str = os.environ.get(
        "DEFAULT_CAPTION", 
        "<b>{file_name}</b>\n\n📁 Size: {size}\n👤 Requested by: {mention}"
    )
    raw_tokens = os.environ.get("HF_TOKENS", "")
    HF_TOKENS = [t.strip() for t in raw_tokens.split(",") if t.strip()]
