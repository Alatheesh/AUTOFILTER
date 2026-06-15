import asyncio
import logging
from aiohttp import web
from pyrogram import Client, idle
from pyrogram.errors import ApiIdInvalid, ApiIdPublishedFlood, AccessTokenInvalid
from config import Config

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Verify required config
if not Config.BOT_TOKEN or not Config.API_ID or not Config.API_HASH:
    logger.error("Missing essential configuration attributes. Please check BOT_TOKEN, API_ID, API_HASH.")
    exit(1)

# Initialize Pyrogram Bot Client
app = Client(
    "AutoFilterBot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    plugins=dict(root="plugins")
)

# Hugging Face Health Check Aiohttp Server
async def web_server():
    async def handle_request(request):
        return web.Response(text="Bot is running smoothly!", content_type='text/html')

    web_app = web.Application()
    web_app.router.add_get('/', handle_request)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', Config.PORT)
    await site.start()
    logger.info(f"Aiohttp web server started on port {Config.PORT}")

async def main():
    logger.info("Initializing multi-DB connections and starting bot...")
    
    # Start web server concurrently
    asyncio.create_task(web_server())

    try:
        await app.start()
        logger.info("Bot Started successfully.")
        
        # Load Ghost mode cleanup tasks or scheduled events here if any
        
        await idle()
    except (ApiIdInvalid, ApiIdPublishedFlood, AccessTokenInvalid) as e:
        logger.error(f"Telegram API Configuration Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected bot startup error: {e}")
    finally:
        await app.stop()
        logger.info("Bot Stopped.")

if __name__ == "__main__":
    asyncio.run(main())
