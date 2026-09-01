"""Ticker list, detail, and price history for the charts. All read-only.

**There is no route that starts an analysis.** The morning sweep analyses the
watchlist, and the agent decides what is on the watchlist. An analysis started
by hand would cost the agent nothing and appear in the record beside the ones
it paid for, so the charge that makes it choose carefully would stop meaning
anything.

Current price comes from the ticker price cache (``TickerPrice``), kept warm by
the scheduled jobs rather than by this page being open.
"""
from fastapi import APIRouter


from backend.database import db
from backend.database.models import TickerPrice
from backend.services import ticker_book
from backend.api.schemas import (
    AgentPositionOut,
    AlertOut,
    LotOut,
    OhlcBarOut,
    SignalOut,
    TickerDetailOut,
    TickerEventsOut,
    TickerSummaryOut,
    TradeOut,
)
from backend.services.positions import get_price_history

router = APIRouter(prefix="/api/tickers", tags=["tickers"])


def _latest_signal(ticker: str) -> SignalOut | None:
    rows = db.get_recent_signals(ticker, limit=1)
    return SignalOut.model_validate(rows[0]) if rows else None


def _filled_trades(ticker: str) -> list[TradeOut]:
    """The agent's filled orders for one ticker, oldest first.

    Resting exits are excluded until they trigger: a stop that is armed and
    never reached is not a trade, and ``filled_at`` is what tells the two
    apart.
    """
    return [
        TradeOut(
            side=trade.side,
            date=trade.filled_at.date(),
            price=trade.price,
            quantity=trade.quantity,
        )
        for trade in db.get_agent_trades()
        if trade.ticker == ticker
        and trade.status == "filled"
        and trade.filled_at is not None
        and trade.price is not None
    ]


def _ticker_detail(ticker: str, cached: TickerPrice | None) -> TickerDetailOut:
    price = cached.price if cached else None
    status = db.get_ticker_status(ticker)
    return TickerDetailOut(
        ticker=ticker,
        current_price=price,
        price_updated_at=cached.fetched_at if cached else None,
        agent_position=(
            AgentPositionOut.model_validate(position)
            if (position := ticker_book.agent_position(ticker, price))
            else None
        ),
        latest_signal=_latest_signal(ticker),
        inactive=bool(status and status.inactive),
        inactive_reason=status.reason if status and status.inactive else None,
    )


@router.get("", response_model=list[TickerSummaryOut])
def list_tickers():
    watchlist = db.get_watchlist()
    cached = db.get_cached_prices(watchlist)
    statuses = {status.ticker: status for status in db.get_inactive_tickers()}
    return [
        TickerSummaryOut(
            ticker=ticker,
            current_price=cached[ticker].price if ticker in cached else None,
            price_updated_at=cached[ticker].fetched_at if ticker in cached else None,
            latest_signal=_latest_signal(ticker),
            inactive=bool(statuses.get(ticker) and statuses[ticker].inactive),
            inactive_reason=(
                statuses[ticker].reason
                if statuses.get(ticker) and statuses[ticker].inactive
                else None
            ),
        )
        for ticker in watchlist
    ]


@router.get("/{ticker}", response_model=TickerDetailOut)
def get_ticker(ticker: str):
    ticker = ticker.upper().strip()
    return _ticker_detail(ticker, db.get_cached_price(ticker))


@router.get("/{ticker}/chart", response_model=list[OhlcBarOut])
def get_chart(ticker: str, days: int = 90):
    bars = get_price_history(ticker.upper().strip(), days=days)
    return [OhlcBarOut.model_validate(bar) for bar in bars]


@router.get("/{ticker}/events", response_model=TickerEventsOut)
def get_ticker_events(ticker: str, days: int = 180):
    """Price bars plus every signal, alert, and trade for this ticker.

    One call rather than four, because the chart overlays and the timeline
    under them are the same events drawn two ways. Fetching them separately
    would let the chart and the list disagree while one request was still in
    flight, and would put four round trips in front of the page that matters
    most.

    Events older than the chart window are still returned: the timeline is a
    history, and truncating it to whatever the chart happens to show would hide
    the earlier signals that explain a current position.
    """
    ticker = ticker.upper().strip()
    bars = get_price_history(ticker, days=days)
    return TickerEventsOut(
        ticker=ticker,
        bars=[OhlcBarOut.model_validate(bar) for bar in bars],
        signals=[SignalOut.model_validate(s) for s in db.get_recent_signals(ticker, limit=50)],
        alerts=[
            AlertOut.model_validate(a) for a in db.get_recent_alerts(limit=500) if a.ticker == ticker
        ],
        trades=_filled_trades(ticker),
        lots=[LotOut.model_validate(lot) for lot in ticker_book.lots_for(ticker)],
    )
