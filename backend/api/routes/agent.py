"""The autonomous paper-trading agent's book and trade log.

Read-only apart from ``/run``, which triggers a decision pass by hand — the
same one the 13:35 UTC job runs. Placing orders is never exposed directly:
the agent decides what to trade, and there is no endpoint that lets the
dashboard place an order of its own.
"""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from backend.api.schemas import (
    AgentEventOut,
    JourneyEntryOut,
    AgentBookOut,
    AgentComparisonOut,
    AgentEquityPointOut,
    AgentRunOut,
    AgentTradeOut,
    AgentTradeRowOut,
    ActionResultOut,
    UnprotectedPositionOut,
)
from backend.database import db
from backend.services import agent, agent_book, agent_performance, journey, quotes, ticker_book
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
        adjusted=run.adjusted,
        researched=run.researched,
        untracked=run.untracked,
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


@router.get("/curve", response_model=list[AgentEquityPointOut])
def get_curve():
    """The agent's equity, one point per trading day since its first fill.

    Rebuilt from the ledger and the bar cache on each request rather than read
    from stored snapshots — see agent_book.equity_curve for why. Cheap: a
    completed session's close is served from the cache, so a repeat call
    fetches nothing.
    """
    return [AgentEquityPointOut.model_validate(p) for p in agent_book.equity_curve()]


@router.get("/unprotected", response_model=list[UnprotectedPositionOut])
def get_unprotected():
    """Holdings with nothing resting under them at the broker.

    Its own endpoint rather than a flag on the book, because the Overview page
    needs the answer without needing the book, and because the rule for what
    counts as protected belongs in one place — two pages computing it from
    holdings and orders separately is how they come to disagree.
    """
    return [
        UnprotectedPositionOut(
            ticker=ticker,
            quantity=position.quantity,
            avg_cost=position.avg_cost,
            held_days=position.held_days,
        )
        for ticker, position in ticker_book.unprotected_positions()
    ]


@router.post("/exits/{ticker}", response_model=ActionResultOut)
def arm_exits(ticker: str):
    """Place the missing exits on a position the agent already holds.

    A write, unlike everything else here except /run — but it places no trade
    and opens no position. It rests a stop and a take-profit under shares that
    are already owned, which is the one action that can only reduce exposure.
    """
    result = agent.arm_exits_now(ticker)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return ActionResultOut(message=result["message"])


@router.get("/events", response_model=list[AgentEventOut])
def get_events(limit: int = 30):
    """Decision passes, newest first, with the prompt and the answer verbatim.

    The counts and the one-line reasoning already had a home. These are the
    words behind them, and they are the point: behaviour here is mostly
    prompt, so a month of runs across three prompt revisions cannot be told
    apart afterwards without the text each run actually saw.

    Passes before 2026-09-01 carry no prompt or response and cannot be
    backfilled — the prompt is assembled from a book, a watchlist and a signal
    list that have all moved since. They are still listed, so the record has no
    hole in it.
    """
    events = []
    # Newest first for a page that reads as a feed.
    for row in reversed(db.get_agent_runs(limit=limit)):
        events.append(AgentEventOut(
            id=row.id,
            ran_at=row.ran_at,
            reasoning=row.reasoning or "",
            skipped=row.skipped,
            equity=row.equity,
            cash=row.cash,
            research_spent=row.research_spent,
            prompt=row.prompt,
            response=row.response,
            orders=json.loads(row.orders) if row.orders else [],
            refused=json.loads(row.refusals) if row.refusals else [],
        ))
    return events


@router.get("/journey/entries", response_model=list[JourneyEntryOut])
def get_journey_entries(days: int = 10):
    """The last ``days`` days of the generated journal, newest first.

    Built from the same `journey.build()` the markdown files come from, so the
    page and the files can never disagree. One entry per day that has one: a
    day the agent did nothing still gets a line, because "nothing happened" is
    a fact about the day rather than a gap in the record.
    """
    entries = journey.build()[-days:]
    return [
        JourneyEntryOut(date=day.date, markdown=journey.to_markdown([day], title=""))
        for day in reversed(entries)
    ]


@router.get("/journey", response_class=PlainTextResponse)
def get_journey():
    """The agent's story so far, as markdown.

    Plain text rather than JSON because the point is to read it, or paste it
    somewhere. Every sentence is derived from a trade, a charge, a decision
    pass or a graded signal that already exists, so it cannot drift from the
    book — and the half it cannot write, why *we* changed something, belongs
    to a person in JOURNEY.md.
    """
    return journey.to_markdown(journey.build())
