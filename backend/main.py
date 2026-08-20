"""Entrypoint: runs the FastAPI app (backend/app.py) via uvicorn. FastAPI now
owns the process and event loop; the quiv scheduler and the optional
Discord client both start/stop inside its lifespan (see backend/app.py).
"""
import logging
import os

import uvicorn
from dotenv import load_dotenv

from backend.services import logsetup

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(level=logging.INFO)

# Also to a file in the data volume. Docker's log dies with the container, and
# a run that has been erased cannot explain itself — see backend/services/logsetup.py.
logsetup.configure()

if __name__ == "__main__":
    uvicorn.run("backend.app:app", host="0.0.0.0", port=int(os.environ.get("API_PORT", "8080")))
