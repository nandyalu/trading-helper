"""Candidate tickers to consider following, from Webull's screener.

This proposes; it never follows anything on its own. The reason is arithmetic:
one analysis takes about seven minutes of GPU, so an eight-ticker watchlist is
already a fourteen-minute sweep across four cards. A screener that auto-added
forty names would not produce forty opportunities, it would produce a
seventy-minute sweep and a watchlist too diluted to mean anything. The scarce
resource is analysis, not ideas.

**The filter is the entire value.** Raw screener output is dominated by
micro-cap pumps — a live pull returned a stock up 927% in a day — which are the
worst possible thing to put in front of a swing-trading account of a few
thousand dollars. Price and volume floors turn the same feed into names like
INTC, NVDA and SMCI.

Blocking (HTTP + DB) — call via asyncio.to_thread.
"""
import logging
from dataclasses import dataclass

from backend.database import db
from backend.services import listings, quotes

log = logging.getLogger("trading-bot.candidates")

# A share price low enough to be a lottery ticket rather than a position, and a
# volume too thin to get out of. Both floors exist to keep the sub-dollar movers
# out; neither is a view on what is worth buying.
MIN_PRICE = 5.0
MIN_VOLUME = 1_000_000

# A day's move this large is a news event or a pump, not a setup — and a price
# floor alone does not catch it, because the pump is what lifted the price over
# the floor. A live pull surfaced PLAG at $5.81, up 927% from about $0.56, which
# passed every other filter. Applied to falls as well as rises: a stock halved
# in a session is equally not a one-to-two-week swing.
MAX_DAILY_MOVE_PCT = 30.0

# How many to ask each screen for, and how many to propose. The screens return
# a couple of hundred; the point is a shortlist somebody will actually read.
_PAGE_SIZE = 50
MAX_PROPOSED = 8


@dataclass
class Candidate:
    ticker: str
    name: str
    price: float
    volume: float
    change_pct: float | None
    source: str  # which screen surfaced it

    @property
    def volume_m(self) -> float:
        return self.volume / 1_000_000


def _rows(response) -> list[dict]:
    body = response.json() if hasattr(response, "json") else response
    if isinstance(body, dict):
        return [r for r in body.get("data", []) if isinstance(r, dict)]
    return [r for r in body if isinstance(r, dict)] if isinstance(body, list) else []


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_candidate(row: dict, source: str) -> Candidate | None:
    ticker = str(row.get("symbol", "")).strip().upper()
    price = _as_float(row.get("price") or row.get("close"))
    volume = _as_float(row.get("volume"))
    if not ticker or price is None or volume is None:
        return None
    if price < MIN_PRICE or volume < MIN_VOLUME:
        return None
    change = _as_float(row.get("change_ratio"))
    if change is not None and abs(change * 100) > MAX_DAILY_MOVE_PCT:
        return None
    return Candidate(
        ticker=ticker,
        name=str(row.get("name", ""))[:40],
        price=price,
        volume=volume,
        change_pct=change * 100 if change is not None else None,
        source=source,
    )


def fetch_candidates() -> list[Candidate]:
    """Screened names not already tracked, most liquid first.

    Two screens, deliberately: the most active gives liquid names that are
    simply busy, and the day's gainers give names that are moving. Neither is a
    recommendation — they are the raw material an analysis is spent on, and the
    analysis is what decides anything.
    """
    client = quotes.get_api_client()
    if client is None:
        log.info("No Webull client — cannot screen for candidates")
        return []
    from webull.data.quotes.screener import Screener

    screener = Screener(client)
    found: dict[str, Candidate] = {}
    screens = (
        ("most active", lambda: screener.get_most_active("US_STOCK", page_size=_PAGE_SIZE)),
        (
            "day gainers",
            # rank_type/sort_by are enums the SDK does not validate: a wrong
            # value returns zero rows rather than an error, which is how three
            # earlier guesses failed silently.
            lambda: screener.get_gainers_losers(
                "DAY_1", "US_STOCK", "CHANGE_RATIO", page_size=_PAGE_SIZE, direction="DESC"
            ),
        ),
    )
    for source, call in screens:
        try:
            rows = _rows(call())
        except Exception:
            log.exception("Screener call failed for %s", source)
            continue
        for row in rows:
            candidate = _to_candidate(row, source)
            # First screen to surface a name keeps it — most active runs first,
            # so a liquid name is described as liquid rather than as a mover.
            if candidate and candidate.ticker not in found:
                found[candidate.ticker] = candidate

    # The watchlist covers every holding too: the agent may not untrack a
    # position it still owns, and Python refuses the attempt. So one set is
    # enough here — a held name is a tracked name.
    tracked = {t.upper() for t in db.get_watchlist()}
    inactive = {t.upper() for t in listings.inactive_tickers()}
    fresh = [
        c for c in found.values()
        if c.ticker not in tracked and c.ticker not in inactive
    ]
    fresh.sort(key=lambda c: c.volume, reverse=True)
    return fresh[:MAX_PROPOSED]


def format_candidates(candidates: list[Candidate]) -> str:
    if not candidates:
        return (
            "No new candidates passed the screen today — everything liquid enough "
            "is already tracked."
        )
    lines = [
        f"**{len(candidates)} candidate(s)** worth considering "
        f"(over ${MIN_PRICE:.0f}, over {MIN_VOLUME / 1e6:.0f}M shares traded, "
        f"moved under {MAX_DAILY_MOVE_PCT:.0f}% today, not already tracked):",
    ]
    for c in candidates:
        move = f" · {c.change_pct:+.1f}%" if c.change_pct is not None else ""
        lines.append(
            f"- **{c.ticker}** ${c.price:,.2f} · {c.volume_m:,.0f}M shares{move} "
            f"· {c.source}{' · ' + c.name if c.name else ''}"
        )
    lines.append("Use `/track ticker:XYZ` to follow one — each adds about 7 minutes to the sweep.")
    return "\n".join(lines)
