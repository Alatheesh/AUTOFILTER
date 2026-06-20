from flask import Flask
import os

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running"

port = int(os.environ.get("PORT", 7860))

app.run(host="0.0.0.0", port=port)
