import asyncio
import logging
from pyrogram import Client, idle
from pyrogram.errors import ApiIdInvalid, ApiIdPublishedFlood, AccessTokenInvalid
from config import Config

# IMPORT THE INVISIBLE WORKERS
from plugins.indexer import process_indexing_queue
from plugins.background_worker import start_background_language_indexer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

if not Config.BOT_TOKEN or not Config.API_ID or not Config.API_HASH:
    logger.error("Missing essential configuration attributes.")
    exit(1)

app = Client(
    "AutoFilterBot_V3", 
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    plugins=dict(root="plugins"),
    workers=100
)

async def main():
    logger.info("Initializing multi-DB connections and starting bot...")

    try:
        await app.start()
        
        me = await app.get_me()
        logger.info("==================================================")
        logger.info("✅ BOT AUTHENTICATED SUCCESSFULLY!")
        logger.info(f"🤖 Bot Name: {me.first_name}")
        logger.info(f"🔗 Username: @{me.username}")
        logger.info("==================================================")

        # 🔥 START THE QUEUE AND METADATA WORKERS HERE 🔥
        asyncio.create_task(process_indexing_queue(app))
        asyncio.create_task(start_background_language_indexer(app))
        
        await idle()
    except (ApiIdInvalid, ApiIdPublishedFlood, AccessTokenInvalid) as e:
        logger.error(f"Telegram API Configuration Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected bot startup error: {e}")
        raise
    finally:
        if app.is_initialized:
            await app.stop()

def run_bot():
    asyncio.run(main())

if __name__ == "__main__":
    run_bot()
