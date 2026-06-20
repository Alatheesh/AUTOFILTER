import subprocess
import time

web = subprocess.Popen(["python", "web.py"])
bot = subprocess.Popen(["python", "bot.py"])

print("WEB PID:", web.pid)
print("BOT PID:", bot.pid)

while True:
    print(
        "WEB STATUS:", web.poll(),
        "BOT STATUS:", bot.poll()
    )
    time.sleep(30)
