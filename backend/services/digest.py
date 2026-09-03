"""Weekly digest: one post wrapping up the week — signals resolved and
created, win-rate trend (last 30 days vs all-time), alerts fired, and a
snapshot of both books. ``gather_digest`` does the blocking collection
(DB + prices — call via asyncio.to_thread); ``format_digest_embed`` is pure
formatting so it can be unit-tested with constructed data.
"""
import datetime
from collections import Counter
from dataclasses import dataclass, field


from backend.database import db
from backend.database.models import Alert, Signal
from backend.services import ticker_book
from backend.services.positions import get_current_price
from backend.notifications.embed import Color, Embed

_ALERT_WORDS = {"big_move": "move", "volume": "volume", "stop_loss": "stop", "target": "target"}


def _as_naive_utc(moment: datetime.datetime) -> datetime.datetime:
    """SQLite round-trips datetimes inconsistently (aware when stored with an
    offset, naive otherwise) — normalize before comparing."""
    return moment.replace(tzinfo=None) if moment.tzinfo else moment


@dataclass
class DigestData:
    week_start: datetime.date
    resolved: list[Signal] = field(default_factory=list)
    new_signals: list[Signal] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    win_rate_30d: tuple[int, int] = (0, 0)  # (passes, resolved)
    win_rate_all: tuple[int, int] = (0, 0)
    book_lines: list[str] = field(default_factory=list)


def gather_digest(now: datetime.datetime | None = None) -> DigestData:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    week_ago = _as_naive_utc(now) - datetime.timedelta(days=7)
    month_ago = _as_naive_utc(now) - datetime.timedelta(days=30)

    all_resolved = db.get_resolved_signals()
    resolved_week = [
        s for s in all_resolved if s.evaluated_at and _as_naive_utc(s.evaluated_at) >= week_ago
    ]
    resolved_month = [
        s for s in all_resolved if s.evaluated_at and _as_naive_utc(s.evaluated_at) >= month_ago
    ]

    data = DigestData(week_start=week_ago.date())
    data.resolved = resolved_week
    data.new_signals = db.get_signals_created_since(week_ago.date())
    data.alerts = [
        a for a in db.get_recent_alerts() if _as_naive_utc(a.created_at) >= week_ago
    ]
    data.win_rate_30d = (sum(s.outcome == "pass" for s in resolved_month), len(resolved_month))
    data.win_rate_all = (sum(s.outcome == "pass" for s in all_resolved), len(all_resolved))
    for ticker in sorted(db.get_watchlist()):
        position = ticker_book.agent_position(ticker, get_current_price(ticker))
        if position is None:
            continue
        line = f"{ticker}: {position.quantity:g} @ ${position.avg_cost:,.2f}"
        if position.price is not None:
            pct = position.unrealized_pct
            line += f" → ${position.price:,.2f}" + (f" ({pct:+.1f}%)" if pct is not None else "")
        data.book_lines.append(line)
    return data


def _rate_text(passes: int, total: int) -> str:
    return f"{passes}/{total} ({passes / total * 100:.0f}%)" if total else "n/a"


def format_digest_embed(data: DigestData) -> Embed:
    embed = Embed(
        title=f"🗞️ Weekly Digest — week of {data.week_start}",
        color=Color.blurple(),
    )

    if data.resolved:
        lines = []
        for signal in data.resolved[:10]:
            pct = (
                (signal.price_at_evaluation / signal.price_at_signal - 1) * 100
                if signal.price_at_signal and signal.price_at_evaluation is not None
                else 0.0
            )
            line = (
                f"{signal.ticker} {signal.decision} ({signal.signal_date}): "
                f"**{signal.outcome.upper()}** ({pct:+.1f}%)"
            )
            if signal.outcome_vs_benchmark:
                line += f" · vs SPY {signal.outcome_vs_benchmark.upper()}"
            lines.append(line)
        if len(data.resolved) > 10:
            lines.append(f"…and {len(data.resolved) - 10} more")
        embed.add_field(name="Signals resolved this week", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Signals resolved this week", value="None", inline=False)

    decisions = Counter(s.decision for s in data.new_signals)
    new_text = (
        f"{len(data.new_signals)} — " + ", ".join(f"{n} {d}" for d, n in decisions.most_common())
        if data.new_signals
        else "None"
    )
    embed.add_field(name="New signals", value=new_text, inline=False)

    embed.add_field(
        name="Win rate",
        value=f"Last 30 days: **{_rate_text(*data.win_rate_30d)}** · all-time: {_rate_text(*data.win_rate_all)}",
        inline=False,
    )

    if data.alerts:
        counts = Counter(a.alert_type for a in data.alerts)
        alert_text = f"{len(data.alerts)} — " + ", ".join(
            f"{n} {_ALERT_WORDS.get(t, t)}" for t, n in counts.most_common()
        )
        embed.add_field(name="Alerts this week", value=alert_text, inline=False)

    if data.book_lines:
        embed.add_field(name="What the agent holds", value="\n".join(data.book_lines), inline=False)

    return embed


def build_weekly_digest_embed() -> Embed:
    """Blocking — gather + format in one call for main.py."""
    return format_digest_embed(gather_digest())
