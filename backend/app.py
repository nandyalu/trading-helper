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

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import (
    agent,
    alerts,
    digest,
    jobs,
    regime,
    scorecard,
    settings,
    signals,
    tickers,
    watchlist,
)
from backend.discord_bot.client import start_discord, stop_discord
from backend.services import publish, trade_stream
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
    # Best effort, and never fatal: without it a resting stop or take-profit
    # is noticed by the 15-minute poll instead of within a second.
    trade_stream.start()
    yield
    trade_stream.stop()
    await stop_discord()
    scheduler.shutdown()  # mandatory per quiv's own docs — cancels jobs, deletes its temp DB


# FastAPI's own interactive API reference moves under /api, because /docs
# belongs to the user-facing Zensical site mounted below. FastAPI registers its
# routes at construction, before any mount, so leaving it at the default made
# Swagger UI shadow the real docs entirely — the /docs link in the dashboard
# nav reached the API reference instead.
app = FastAPI(
    title="Trading Helper",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# --- the public read-only guard ------------------------------------------------
#
# Registered before every router, so it sees every request including the ones
# added later. A per-route check would protect only the routes somebody
# remembered to annotate, and the frontend hiding a button stops nobody who can
# type a URL.
#
# GET and HEAD pass. OPTIONS passes because a browser preflight is not a write.
# Everything else is refused with a reason a person can act on, rather than a
# bare 403 that reads like a bug.
_READ_METHODS = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def refuse_writes_when_public(request: Request, call_next):
    if publish.is_public() and request.method not in _READ_METHODS:
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "This is the published copy of the experiment and it is "
                    "read-only. Nothing here can change what the agent does — "
                    "that is the point of it."
                )
            },
        )
    return await call_next(request)


app.include_router(watchlist.router)
app.include_router(tickers.router)
app.include_router(signals.router)
app.include_router(scorecard.router)
app.include_router(digest.router)
app.include_router(regime.router)
app.include_router(settings.router)
app.include_router(alerts.router)
app.include_router(jobs.router)
app.include_router(agent.router)

if _SITE_DIR.is_dir():
    app.mount("/docs", StaticFiles(directory=_SITE_DIR, html=True), name="docs")

    # A Mount at "/docs" only matches "/docs/...", so a bare "/docs" — which is
    # what the dashboard nav links to and what anyone types — falls through to
    # the SPA catch-all below and silently lands on the dashboard home instead
    # of the docs. Starlette would normally redirect, but only for paths its
    # Mount actually matches. Redirect explicitly, before the catch-all.
    @app.get("/docs", include_in_schema=False)
    async def docs_index() -> RedirectResponse:
        return RedirectResponse("/docs/")
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
