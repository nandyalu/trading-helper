"""Watchlist add/remove/list — mirrors backend/discord_bot/client.py's /track,
/untrack, /watchlist commands (backend/discord_bot/client.py:56-84)."""
from fastapi import APIRouter, HTTPException

from backend.database import db
from backend.api.schemas import ActionResultOut

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=list[str])
def list_watchlist():
    return db.get_watchlist()


@router.post("/{ticker}", response_model=ActionResultOut)
def add_ticker(ticker: str):
    ticker = ticker.upper().strip()
    if ticker in db.get_watchlist():
        raise HTTPException(status_code=409, detail=f"{ticker} is already tracked.")
    db.add_to_watchlist(ticker)
    return ActionResultOut(message=f"Tracking {ticker}.")


@router.delete("/{ticker}", response_model=ActionResultOut)
def remove_ticker(ticker: str):
    ticker = ticker.upper().strip()
    if ticker not in db.get_watchlist():
        raise HTTPException(status_code=404, detail=f"{ticker} isn't tracked.")
    db.remove_from_watchlist(ticker)
    return ActionResultOut(message=f"Stopped tracking {ticker}.")
