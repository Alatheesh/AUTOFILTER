from threading import Thread
from web import app
import os

print("START.PY STARTED")

def run_web():
    port = int(os.environ.get("PORT", 7860))
    print("STARTING FLASK")
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web, daemon=True).start()

print("IMPORTING BOT")

import bot

print("BOT IMPORTED")
