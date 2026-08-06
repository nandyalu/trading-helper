"""The application: FastAPI serving the JSON API (/api), the Zensical docs
build (/docs), and the Angular production build everywhere else (with an
index.html fallback for client-side routes) — plus the quiv scheduler and
the optional Discord client, both started/stopped in the lifespan. This is
the process now; backend/main.py just runs it via uvicorn. Replaces
backend/app.py and the old discord.py-owns-the-loop model entirely.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import (
    digest,
    jobs,
    paper,
    portfolio,
    regime,
    scorecard,
    settings,
    signals,
    tickers,
    transactions,
    watchlist,
)
from backend.discord_bot.client import start_discord, stop_discord
from backend.tasks.scheduler import register_jobs, scheduler

log = logging.getLogger("trading-bot.app")

# backend/app.py -> bot -> /app (repo root in the container, repo root locally)
# — same convention the old docs_server.py used for `site/`.
_BASE_DIR = Path(__file__).resolve().parent.parent
_WEB_DIR = _BASE_DIR / "web"
_SITE_DIR = _BASE_DIR / "site"


@asynccontextmanager
async def lifespan(app: FastAPI):
    register_jobs()
    scheduler.start()
    await start_discord()
    yield
    await stop_discord()
    scheduler.shutdown()  # mandatory per quiv's own docs — cancels jobs, deletes its temp DB


app = FastAPI(title="Trading Helper", lifespan=lifespan)

app.include_router(watchlist.router)
app.include_router(tickers.router)
app.include_router(signals.router)
app.include_router(paper.router)
app.include_router(portfolio.router)
app.include_router(scorecard.router)
app.include_router(digest.router)
app.include_router(regime.router)
app.include_router(settings.router)
app.include_router(transactions.router)
app.include_router(jobs.router)

if _SITE_DIR.is_dir():
    app.mount("/docs", StaticFiles(directory=_SITE_DIR, html=True), name="docs")
else:
    log.info("No built docs at %s — /docs not mounted (run `zensical build`)", _SITE_DIR)

if _WEB_DIR.is_dir():
    # Explicit catch-all rather than `app.mount("/", StaticFiles(...))`: a
    # root Mount intercepts every path (including /api/*) ahead of any route
    # matching, and StaticFiles' own file-not-found 404 doesn't fall through
    # to a later route either way. This serves an exact static asset when
    # the path matches a real file, and index.html otherwise so the Angular
    # Router can handle deep links client-side.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = _WEB_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_WEB_DIR / "index.html")
else:
    log.info("No built frontend at %s — serving API only", _WEB_DIR)
