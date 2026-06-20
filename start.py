from server import app
import os

port = int(os.environ.get("PORT", 7860))
app.run(host="0.0.0.0", port=port)
