from threading import Thread
from web import app
import os

def run_web():
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web, daemon=True).start()

import bot
