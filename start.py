import subprocess
import time

print("START.PY EXECUTED")

web = subprocess.Popen(["python", "web.py"])

bot = subprocess.Popen(["python", "bot.py"])

while True:
    print(f"WEB={web.poll()} BOT={bot.poll()}")
    time.sleep(30)
