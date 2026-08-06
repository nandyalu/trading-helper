"""Ticker list/detail, price history for charts, and the analyze trigger.

Now that FastAPI and the (optional) Discord client share one event loop —
no more discord.py owning the process with FastAPI bolted on in a
background thread — the analyze/analyze-all/ask routes need none of the
run_coroutine_threadsafe/wrap_future cross-thread bridging this file used
to. analyze/analyze-all dispatch via plain asyncio.create_task(); a full
analysis can take minutes, far too long for a single HTTP request, so both
return 202 immediately and the frontend polls GET /api/signals?ticker=...
to see the result land. Discord posting (if configured) happens
transparently inside backend.services.analysis.run_analysis_and_notify — this route
never checks whether Discord is set up, since it isn't required either way.

Current price for these routes comes from the ticker price cache
(backend/database/db.py's TickerPrice table), not a live quote call — see
POST /{ticker}/refresh for the one route here that still fetches live.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException

from backend.database import db
from backend.database.models import TickerPrice
from backend.services import analysis
from backend.api.schemas import (
    ActionResultOut,
    AnalyzeAllQueuedOut,
    AnalyzeQueuedOut,
    AskIn,
    OhlcBarOut,
    PaperPositionOut,
    PortfolioPositionOut,
    SignalOut,
    TickerDetailOut,
    TickerSummaryOut,
)
from backend.services.ask import answer_about_ticker
from backend.services.positions import compute_position, get_current_price, get_price_history

log = logging.getLogger("trading-bot.api")

router = APIRouter(prefix="/api/tickers", tags=["tickers"])


def _latest_signal(ticker: str) -> SignalOut | None:
    rows = db.get_recent_signals(ticker, limit=1)
    return SignalOut.model_validate(rows[0]) if rows else None


def _real_position(ticker: str, price: float | None) -> PortfolioPositionOut | None:
    """Single-ticker equivalent of backend.services.portfolio.get_portfolio_positions() —
    duplicated rather than filtering that function's output, since it prices
    every held ticker to answer a lookup for just one."""
    transactions = db.get_transactions(ticker)
    if not transactions:
        return None
    position = compute_position(transactions)
    if position.quantity <= 0:
        return None
    value = price * position.quantity if price is not None else None
    unrealized = (value - position.avg_cost * position.quantity) if value is not None else None
    unrealized_pct = (
        (price / position.avg_cost - 1) * 100 if price is not None and position.avg_cost else None
    )
    return PortfolioPositionOut(
        ticker=ticker, quantity=position.quantity, avg_cost=position.avg_cost,
        weight_pct=None, price=price, value=value, unrealized=unrealized, unrealized_pct=unrealized_pct,
    )


def _paper_position(ticker: str, price: float | None) -> PaperPositionOut | None:
    """Single-ticker equivalent of backend.services.paper.get_paper_positions() — see
    _real_position for why this isn't a filter over that function instead."""
    transactions = db.get_paper_transactions(ticker)
    if not transactions:
        return None
    position = compute_position(transactions)
    if position.quantity <= 0:
        return None
    cost_basis = position.avg_cost * position.quantity
    value = price * position.quantity if price is not None else None
    unrealized = (value - cost_basis) if value is not None else None
    unrealized_pct = (
        (price / position.avg_cost - 1) * 100 if price is not None and position.avg_cost else None
    )
    return PaperPositionOut(
        ticker=ticker, quantity=position.quantity, avg_cost=position.avg_cost,
        cost_basis=cost_basis, price=price, value=value, unrealized=unrealized, unrealized_pct=unrealized_pct,
    )


def _ticker_detail(ticker: str, cached: TickerPrice | None) -> TickerDetailOut:
    price = cached.price if cached else None
    return TickerDetailOut(
        ticker=ticker,
        current_price=price,
        price_updated_at=cached.fetched_at if cached else None,
        real_position=_real_position(ticker, price),
        paper_position=_paper_position(ticker, price),
        latest_signal=_latest_signal(ticker),
    )


@router.get("", response_model=list[TickerSummaryOut])
def list_tickers():
    watchlist = db.get_watchlist()
    cached = db.get_cached_prices(watchlist)
    return [
        TickerSummaryOut(
            ticker=ticker,
            current_price=cached[ticker].price if ticker in cached else None,
            price_updated_at=cached[ticker].fetched_at if ticker in cached else None,
            latest_signal=_latest_signal(ticker),
        )
        for ticker in watchlist
    ]


@router.get("/{ticker}", response_model=TickerDetailOut)
def get_ticker(ticker: str):
    ticker = ticker.upper().strip()
    return _ticker_detail(ticker, db.get_cached_price(ticker))


@router.post("/{ticker}/refresh", response_model=TickerDetailOut)
def refresh_ticker(ticker: str):
    """The one route here that still fetches a live quote — for when the
    cached price (kept warm by scheduled jobs, not by this page being open)
    is too stale to act on. get_current_price() writes the fresh value into
    the cache as a side effect, so this doubles as a manual cache warm-up."""
    ticker = ticker.upper().strip()
    price = get_current_price(ticker)
    if price is None:
        raise HTTPException(status_code=502, detail=f"Couldn't fetch a live price for {ticker}.")
    return _ticker_detail(ticker, db.get_cached_price(ticker))


@router.get("/{ticker}/chart", response_model=list[OhlcBarOut])
def get_chart(ticker: str, days: int = 90):
    bars = get_price_history(ticker.upper().strip(), days=days)
    return [OhlcBarOut.model_validate(bar) for bar in bars]


@router.post("/analyze-all", response_model=AnalyzeAllQueuedOut, status_code=202)
async def trigger_analyze_all():
    """Fire-and-forget over the whole watchlist, all tickers dispatched
    concurrently — bounded by analysis.propagate_ticker()'s own semaphore
    (TRADINGAGENTS_MAX_CONCURRENT_ANALYSES), not by this loop, so this
    actually uses however many GPUs the Ollama pool has instead of running
    one ticker at a time. One ticker failing doesn't stop the rest
    (asyncio.gather below swallows each task's own exception)."""
    tickers = db.get_watchlist()

    async def _one(ticker: str) -> None:
        try:
            await analysis.run_analysis_and_notify(ticker)
        except Exception:
            log.exception("analyze-all: analysis failed for %s", ticker)

    async def _dispatch_all():
        await asyncio.gather(*(_one(ticker) for ticker in tickers))

    asyncio.create_task(_dispatch_all())
    return AnalyzeAllQueuedOut(count=len(tickers))


@router.post("/{ticker}/analyze", response_model=AnalyzeQueuedOut, status_code=202)
async def trigger_analyze(ticker: str):
    ticker = ticker.upper().strip()

    async def _dispatch():
        try:
            await analysis.run_analysis_and_notify(ticker)
        except Exception:
            log.exception("analyze: analysis failed for %s", ticker)

    asyncio.create_task(_dispatch())
    return AnalyzeQueuedOut(ticker=ticker)


@router.post("/{ticker}/ask", response_model=ActionResultOut)
async def ask_ticker(ticker: str, payload: AskIn):
    ticker = ticker.upper().strip()
    try:
        answer = await asyncio.to_thread(answer_about_ticker, ticker, payload.question)
    except Exception as exc:
        log.exception("ask failed for %s", ticker)
        raise HTTPException(status_code=502, detail=f"Couldn't answer that: {exc}")
    return ActionResultOut(message=answer)
