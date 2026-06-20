from threading import Thread
from server import app
import os
import asyncio
import bot

def run_web():
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web, daemon=True).start()

asyncio.run(bot.main())
