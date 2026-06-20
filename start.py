import subprocess

subprocess.Popen(["python", "web.py"])
subprocess.Popen(["python", "bot.py"])

import time
while True:
    time.sleep(60)
