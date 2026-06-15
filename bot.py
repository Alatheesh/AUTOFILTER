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
        
        # --- THE NEW DIAGNOSTIC PING ---
        # 1. Fetch Bot Profile to prove authentication
        me = await app.get_me()
        logger.info("==================================================")
        logger.info("✅ BOT AUTHENTICATED SUCCESSFULLY!")
        logger.info(f"🤖 Bot Name: {me.first_name}")
        logger.info(f"🔗 Username: @{me.username}")
        logger.info("==================================================")

        # 2. Send Startup Message to Admin
        if Config.ADMINS:
            for admin in Config.ADMINS:
                try:
                    await app.send_message(
                        chat_id=admin,
                        text=f"🚀 **System Alert:**\n\n{me.first_name} (`@{me.username}`) has successfully started on Hugging Face and is ready!"
                    )
                    logger.info(f"📩 Successfully sent startup ping to Admin ID: {admin}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not send startup ping to Admin {admin}. Error: {e}")
        else:
            logger.warning("⚠️ No ADMINS found in Config. Skipping startup ping.")
        # -------------------------------
        
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
