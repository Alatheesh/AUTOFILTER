FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y git mediainfo ffmpeg fonts-liberation && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 7860
CMD ["python", "bot.py"]
