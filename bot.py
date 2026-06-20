import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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

# 🚀 THE FIX: A dedicated, independent HTTP Server just for Hugging Face
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"Bot is running smoothly on Hugging Face!")
    
    # Disable terminal logging so it doesn't spam your logs
    def log_message(self, format, *args):
        pass

def start_web_server():
    server_address = ('0.0.0.0', 7860)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    logger.info("Built-in Threaded HTTP server started on port 7860")
    httpd.serve_forever()

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

        if Config.ADMINS:
            for admin in Config.ADMINS:
                try:
                    await app.send_message(
                        chat_id=admin,
                        text=f"🚀 **System Alert:**\n\n{me.first_name} (`@{me.username}`) has successfully started on Hugging Face!\n⚙️ Background Workers Active."
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
    # Start the web server in an independent background thread before anything else
    threading.Thread(target=start_web_server, daemon=True).start()
    asyncio.run(main())
    
