import subprocess
import time

web = subprocess.Popen(["python", "web.py"])
bot = subprocess.Popen(["python", "bot.py"])

while True:
    time.sleep(60)
