import subprocess
import time

print("STARTING WEB")

web = subprocess.Popen(
    ["python", "web.py"],
    stdout=None,
    stderr=None
)

print("WEB PROCESS STARTED")

print("STARTING BOT")

bot = subprocess.Popen(
    ["python", "bot.py"],
    stdout=None,
    stderr=None
)

print("BOT PROCESS STARTED")

while True:
    print(
        "WEB:", web.poll(),
        "BOT:", bot.poll()
    )
    time.sleep(30)
