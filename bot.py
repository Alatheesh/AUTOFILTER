import asyncio
import logging
from aiohttp import web
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

async def web_server():
    async def handle_request(request):
        # 🚀 UPDATE: Serve the actual HTML website file!
        try:
            return web.FileResponse('./web/index.html')
        except Exception:
            # Fallback just in case the folder isn't found
            return web.Response(text="Bot is running, but website file is missing!", content_type='text/html')

    web_app = web.Application()
    web_app.router.add_get('/', handle_request)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', Config.PORT)
    await site.start()
    logger.info(f"Aiohttp web server started on port {Config.PORT}")

async def main():
    logger.info("Initializing multi-DB connections and starting bot...")
    asyncio.create_task(web_server())

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

        if Config.ADMINS:
            for admin in Config.ADMINS:
                try:
                    await app.send_message(
                        chat_id=admin,
                        text=f"🚀 **System Alert:**\n\n{me.first_name} (`@{me.username}`) has successfully started!\n⚙️ Website and Background Workers are Active."
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Could not send startup ping to Admin {admin}. Error: {e}")
        
        await idle()
    except (ApiIdInvalid, ApiIdPublishedFlood, AccessTokenInvalid) as e:
        logger.error(f"Telegram API Configuration Error: {e}")
    except Exception as e:
        logger.error(f"Unexpected bot startup error: {e}")
        raise
    finally:
        if app.is_initialized:
            await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
    
