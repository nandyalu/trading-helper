"""Entrypoint: runs the FastAPI app (bot/app.py) via uvicorn. FastAPI now
owns the process and event loop; the quiv scheduler and the optional
Discord client both start/stop inside its lifespan (see bot/app.py).
"""
import logging
import os

import uvicorn
from dotenv import load_dotenv

from bot.migrate_legacy import migrate_if_needed

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    migrate_if_needed()
    uvicorn.run("bot.app:app", host="0.0.0.0", port=int(os.environ.get("API_PORT", "8080")))
