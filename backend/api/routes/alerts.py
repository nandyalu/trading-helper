"""Watchdog alert log. The alerts already exist in the ``alert`` table and are
already pushed to Discord as they fire; this exposes the history so the web
dashboard can show it without a Discord account, and so a missed notification
is still recoverable.

Read-only — alerts are written by backend/services/watchdog.py during a scan,
never by a request.
"""
from fastapi import APIRouter

from backend.api.schemas import AlertOut
from backend.database import db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def get_alerts(ticker: str | None = None, alert_type: str | None = None, limit: int = 100):
    """Most recent alerts first. ``ticker`` and ``alert_type`` filter in memory
    rather than in SQL: the log is capped at a few hundred rows in practice, so
    an extra query path isn't worth the maintenance."""
    alerts = db.get_recent_alerts(limit=max(limit, 200))
    if ticker:
        wanted = ticker.upper().strip()
        alerts = [a for a in alerts if a.ticker == wanted]
    if alert_type:
        alerts = [a for a in alerts if a.alert_type == alert_type]
    return [AlertOut.model_validate(a) for a in alerts[:limit]]
