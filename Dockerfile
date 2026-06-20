FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y mediainfo && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 7860

# 🚀 THE FIX: Start the web server in the background, and the bot in the foreground
CMD python web.py & exec python bot.py
