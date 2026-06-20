from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

@app.route("/health")
def health():
    return "ok", 200
