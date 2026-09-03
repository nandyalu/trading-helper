"""Read-through cache for daily OHLCV bars.

Every yfinance history call in the app goes through here. Before this existed,
each caller fetched independently: the intraday watchdog pulled roughly a month
of bars per ticker *every 15 minutes* to use two closes and a volume average,
while the chart, the ATR, and signal grading each refetched overlapping ranges
of the same bars. On an 8-ticker watchlist that was a few hundred fetches a day
to persist eight numbers.

The saving is possible because **a completed session never changes**. Only the
bar for the day in progress moves, and that one is deliberately never cached —
storing it would serve a frozen mid-session snapshot as though it were a close.
Callers that need today ask for it explicitly and get a live fetch.

Everything here is blocking (network + DB) — call via asyncio.to_thread.
"""
import datetime
import logging

import yfinance as yf
from tradingagents.dataflows.stockstats_utils import yf_retry

from backend.database import db
from backend.services import listings
from backend.services.positions import OhlcBar, drop_incomplete_bars

log = logging.getLogger("trading-experiment.bars")

# How long to wait before asking yfinance again for a ticker whose cache
# already looks current. Only matters on days when no new session closes —
# market holidays, mostly — where the "is the cache behind?" check can never be
# satisfied and would otherwise refetch on every call. In-process and lost on
# restart, which is fine: the cost of a redundant fetch is one request.
_RECHECK_INTERVAL = datetime.timedelta(minutes=30)
_last_fetch: dict[str, datetime.datetime] = {}

# The earliest start already requested per ticker. Without this, a ticker whose
# history is shorter than the caller asks for — a recent listing, or simply a
# 365-day chart of a stock that has traded for 200 — looks permanently
# incomplete and refetches on every single call, which is the opposite of what
# a cache is for. Recording the attempt rather than the result is what makes
# "we asked and this is all there is" distinguishable from "we never asked".
_earliest_attempt: dict[str, datetime.date] = {}

# Extra history pulled beyond what the caller asked for. A fetch is one request
# whatever its span, so widening it slightly means the next caller asking for a
# little more is served from cache instead of triggering another round trip.
_FETCH_MARGIN = datetime.timedelta(days=30)


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def last_completed_session(today: datetime.date | None = None) -> datetime.date:
    """The most recent weekday strictly before ``today``.

    Deliberately ignores market holidays. Getting this wrong in the
    conservative direction only means the cache looks stale and one extra fetch
    happens, which the recheck interval then absorbs. Modeling the NYSE
    calendar to save that request would not pay for itself.
    """
    day = (today or datetime.date.today()) - datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day -= datetime.timedelta(days=1)
    return day


def _to_bars(history, cutoff: datetime.date) -> list[dict]:
    """Frame rows strictly before ``cutoff``, as plain dicts."""
    rows = []
    for timestamp, row in history.iterrows():
        date = timestamp.date()
        if date >= cutoff:
            continue  # the session in progress; never cached
        rows.append(
            {
                "date": date,
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            }
        )
    return rows


def _fetch_history(ticker: str, start: datetime.date):
    try:
        history = yf_retry(lambda: yf.Ticker(ticker).history(start=start.isoformat()))
        return drop_incomplete_bars(history, ("Open", "High", "Low", "Close"))
    except Exception:
        log.warning("Bar fetch failed for %s from %s", ticker, start, exc_info=True)
        return None


def refresh(ticker: str, start: datetime.date, today: datetime.date | None = None) -> int:
    """Fetch and store completed sessions from ``start``. Returns rows written.

    Also judges whether the ticker still trades. This is the right place for
    that: it is the one function that sees what the provider actually returned,
    and a delisted symbol is invisible from anywhere else — the provider keeps
    answering, just with bars months old.
    """
    today = today or datetime.date.today()
    history = _fetch_history(ticker, start)
    _last_fetch[ticker] = _now()
    previous_attempt = _earliest_attempt.get(ticker)
    _earliest_attempt[ticker] = min(start, previous_attempt) if previous_attempt else start

    newest = None
    if history is not None and not history.empty:
        newest = history.index[-1].date()
    listings.record_fetch(ticker, newest, today)

    if history is None or history.empty:
        return 0
    bars = _to_bars(history, cutoff=today)
    return db.upsert_daily_bars(ticker, bars) if bars else 0


def _asked_recently(ticker: str) -> bool:
    last_checked = _last_fetch.get(ticker)
    return last_checked is not None and _now() - last_checked < _RECHECK_INTERVAL


def _needs_fetch(ticker: str, start: datetime.date, today: datetime.date) -> datetime.date | None:
    """The date to fetch from, or None when the cache already covers the ask."""
    # A ticker that has stopped trading is asked at most once a day, and only
    # so a resumed listing can be noticed. Whatever bars it has are already
    # cached and will not grow.
    if not listings.should_fetch(ticker):
        return None

    oldest, newest = db.get_bar_coverage(ticker)

    # Nothing cached. Throttled too, so a ticker yfinance has no data for
    # (delisted, mistyped) is not re-asked on every call.
    if oldest is None:
        return None if _asked_recently(ticker) else start - _FETCH_MARGIN

    # Reaching further back than we have ever asked for. Not throttled: a user
    # switching the chart from 90 days to 365 should get the older bars now,
    # not in half an hour.
    attempted = _earliest_attempt.get(ticker)
    if start < oldest and (attempted is None or start < attempted):
        return start - _FETCH_MARGIN

    # Waiting for a new session to close. Throttled, because on a market
    # holiday this condition can never be satisfied.
    if newest < last_completed_session(today) and not _asked_recently(ticker):
        # Only the gap, plus a day of overlap so a revised bar is picked up.
        return newest - datetime.timedelta(days=1)

    return None


def get_bars(
    ticker: str,
    start: datetime.date,
    end: datetime.date | None = None,
    include_today: bool = False,
    today: datetime.date | None = None,
) -> list[OhlcBar]:
    """Daily bars in [start, end], oldest first, served from cache.

    Fetches only what the cache is missing. ``include_today`` appends the
    session in progress with a separate live request — it is never stored,
    because it is not final.
    """
    ticker = ticker.upper().strip()
    today = today or datetime.date.today()

    fetch_from = _needs_fetch(ticker, start, today)
    if fetch_from is not None:
        refresh(ticker, fetch_from, today)

    bars = [
        OhlcBar(
            date=row.date.isoformat(),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in db.get_daily_bars(ticker, start, end)
    ]

    if include_today and (end is None or end >= today):
        current = _todays_bar(ticker, today)
        if current is not None:
            bars.append(current)
    return bars


def _todays_bar(ticker: str, today: datetime.date) -> OhlcBar | None:
    """The session in progress, fetched live. None outside a session, or when
    the day's bar carries no prices yet (pre-market).

    Skips the request entirely at the weekend. yfinance answers a Saturday
    range with an empty frame and a "possibly delisted" warning, so asking is
    both wasted and alarming to read in the logs.
    """
    if today.weekday() >= 5:
        return None
    if not listings.should_fetch(ticker):
        return None
    history = _fetch_history(ticker, today)
    if history is None or history.empty:
        return None
    timestamp = history.index[-1]
    if timestamp.date() != today:
        return None
    row = history.iloc[-1]
    return OhlcBar(
        date=today.isoformat(),
        open=float(row["Open"]),
        high=float(row["High"]),
        low=float(row["Low"]),
        close=float(row["Close"]),
        volume=float(row["Volume"]),
    )


def reset_fetch_memo() -> None:
    """Clear the in-process fetch bookkeeping. For tests, and for a caller that
    knows the cache is stale (a fresh watchlist entry, say)."""
    _last_fetch.clear()
    _earliest_attempt.clear()
