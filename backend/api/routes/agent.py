"""The autonomous paper-trading agent's book and trade log.

Read-only apart from ``/run``, which triggers a decision pass by hand — the
same one the 13:35 UTC job runs. Placing orders is never exposed directly:
the agent decides what to trade, and there is no endpoint that lets the
dashboard place an order of its own.
"""
from fastapi import APIRouter, HTTPException

from backend.api.schemas import (
    AgentBookOut,
    AgentComparisonOut,
    AgentRunOut,
    AgentTradeOut,
    AgentTradeRowOut,
)
from backend.database import db
from backend.services import agent, agent_book, agent_performance, quotes
from backend.services.positions import get_current_price

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("", response_model=AgentBookOut)
def get_book():
    book = agent_book.build_book(price_lookup=get_current_price)
    return AgentBookOut(
        enabled=agent.is_enabled(),
        sandbox=quotes.is_sandbox(),
        budget=book.budget,
        cash=book.cash,
        invested=book.invested,
        market_value=book.market_value,
        equity=book.equity,
        realized_pnl=book.realized_pnl,
        return_pct=book.return_pct,
        holdings=[
            {
                "ticker": h.ticker,
                "quantity": h.quantity,
                "avg_cost": h.avg_cost,
                "price": h.price,
                "market_value": h.market_value,
                "cost_basis": h.cost_basis,
                "unrealized_pnl": h.unrealized_pnl,
            }
            for h in book.holdings
        ],
    )


@router.get("/trades", response_model=list[AgentTradeOut])
def get_trades():
    """Newest first — the log reads as a history, not a ledger to replay."""
    return [AgentTradeOut.model_validate(t) for t in reversed(db.get_agent_trades())]


@router.post("/run", response_model=AgentRunOut)
def run_now():
    """Run a decision pass immediately. Refused outside the sandbox by
    agent.run_once itself, which reports the reason rather than raising."""
    run = agent.run_once()
    if run.skipped:
        raise HTTPException(status_code=409, detail=run.skipped)
    return AgentRunOut(
        reasoning=run.reasoning,
        placed=[
            {"ticker": o["ticker"], "side": o["side"], "quantity": o["quantity"],
             "reason": o.get("reason")}
            for o in run.placed
        ],
        rejected=[
            {"ticker": r.ticker, "side": r.side, "quantity": r.quantity, "why": r.why}
            for r in run.rejected
        ],
        failed=[
            {"ticker": o["ticker"], "side": o["side"], "quantity": o["quantity"], "why": why}
            for o, why in run.failed
        ],
    )


@router.get("/performance", response_model=AgentComparisonOut)
def get_performance():
    """Whether the model is beating the rules that need no model."""
    result = agent_performance.compare()
    return AgentComparisonOut(
        budget=result.budget,
        since=result.since,
        verdict=result.verdict,
        strategies=[
            {
                "name": s.name,
                "equity": s.equity,
                "invested": s.invested,
                "cash": s.cash,
                "trades": s.trades,
                "note": s.note,
            }
            for s in result.strategies
        ],
    )


@router.get("/history", response_model=list[AgentTradeRowOut])
def get_history():
    """Every lot the agent has opened, newest first — still-held ones included,
    so an open position is visible next to the closed trades rather than only
    in the holdings table."""
    rows = agent_book.trade_history()
    return [AgentTradeRowOut.model_validate(r) for r in reversed(rows)]
