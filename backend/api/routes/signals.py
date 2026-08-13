"""Signal history/detail and the follow-as-paper-trade action."""
import datetime

from fastapi import APIRouter, HTTPException

from backend.database import db
from backend.api.schemas import (
    ActionResultOut,
    AgentTradeRowOut,
    SignalDetailOut,
    SignalOut,
)
from backend.services import agent_book
from backend.services.paper import execute_signal_reaction

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("", response_model=list[SignalOut])
def list_signals(ticker: str | None = None, status: str | None = None, limit: int = 20):
    ticker = ticker.upper().strip() if ticker else None
    if status == "pending":
        rows = db.get_pending_signals(datetime.date.today())
        if ticker:
            rows = [s for s in rows if s.ticker == ticker]
        rows = rows[:limit]
    elif status == "resolved":
        rows = db.get_resolved_signals(ticker)[:limit]
    else:
        rows = db.get_recent_signals(ticker, limit=limit)
    return [SignalOut.model_validate(s) for s in rows]


@router.get("/{signal_id}", response_model=SignalDetailOut)
def get_signal(signal_id: int):
    signal = db.get_signal(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found.")
    reports = db.get_signal_reports(signal_id)
    return SignalDetailOut(
        **SignalOut.model_validate(signal).model_dump(),
        reports=reports,
        agent_trades=[
            AgentTradeRowOut.model_validate(r)
            for r in agent_book.trades_for_signal(signal_id)
        ],
    )


@router.post("/{signal_id}/follow", response_model=ActionResultOut)
def follow_signal(signal_id: int):
    signal = db.get_signal(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found.")
    return ActionResultOut(message=execute_signal_reaction(signal))
