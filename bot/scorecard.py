"""Aggregates resolved signals into a track record: absolute and vs-SPY win
rates, price-target hit rate, and per-decision/per-ticker breakdowns. The
aggregation itself is pure (``aggregate``); ``build_scorecard`` adds the DB
reads and ``format_scorecard_embed`` the Discord rendering, mirroring how
bot/analysis.py splits logic from presentation.
"""
from collections import defaultdict
from dataclasses import dataclass, field

import discord

from bot import db
from bot.models import Signal

# Display order for the by-decision breakdown; unknown decisions sort last.
_DECISION_ORDER = ["Buy", "Overweight", "Hold", "Underweight", "Sell"]


@dataclass
class DecisionStats:
    total: int = 0
    passes: int = 0
    vs_benchmark_total: int = 0
    vs_benchmark_passes: int = 0
    sum_move_pct: float = 0.0
    moves_counted: int = 0

    @property
    def avg_move_pct(self) -> float | None:
        return self.sum_move_pct / self.moves_counted if self.moves_counted else None


@dataclass
class ScorecardStats:
    resolved: int = 0
    pending: int = 0
    passes: int = 0
    vs_benchmark_total: int = 0  # resolved rows that actually got a benchmark grade
    vs_benchmark_passes: int = 0
    sum_alpha_pct: float = 0.0
    alphas_counted: int = 0
    target_total: int = 0  # rows that had a price target and got graded
    target_hits: int = 0
    by_decision: dict[str, DecisionStats] = field(default_factory=dict)
    by_ticker: dict[str, tuple[int, int]] = field(default_factory=dict)  # ticker -> (passes, total)

    @property
    def avg_alpha_pct(self) -> float | None:
        return self.sum_alpha_pct / self.alphas_counted if self.alphas_counted else None


def aggregate(resolved: list[Signal], pending: int = 0) -> ScorecardStats:
    stats = ScorecardStats(resolved=len(resolved), pending=pending)
    ticker_counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [passes, total]

    for signal in resolved:
        passed = signal.outcome == "pass"
        stats.passes += passed
        decision = stats.by_decision.setdefault(signal.decision, DecisionStats())
        decision.total += 1
        decision.passes += passed
        ticker_counts[signal.ticker][0] += passed
        ticker_counts[signal.ticker][1] += 1

        if signal.price_at_evaluation is not None and signal.price_at_signal:
            move = (signal.price_at_evaluation / signal.price_at_signal - 1) * 100
            decision.sum_move_pct += move
            decision.moves_counted += 1

        if signal.outcome_vs_benchmark is not None:
            benchmark_passed = signal.outcome_vs_benchmark == "pass"
            stats.vs_benchmark_total += 1
            stats.vs_benchmark_passes += benchmark_passed
            decision.vs_benchmark_total += 1
            decision.vs_benchmark_passes += benchmark_passed
        if signal.alpha_pct is not None:
            stats.sum_alpha_pct += signal.alpha_pct
            stats.alphas_counted += 1

        if signal.price_target_hit is not None:
            stats.target_total += 1
            stats.target_hits += signal.price_target_hit

    stats.by_ticker = {t: (p, n) for t, (p, n) in ticker_counts.items()}
    return stats


def build_scorecard(ticker: str | None = None) -> ScorecardStats:
    """Blocking (DB reads) — run from a thread when called off the event loop."""
    return aggregate(db.get_resolved_signals(ticker), pending=db.count_pending_signals(ticker))


def _rate(passes: int, total: int) -> str:
    return f"{passes}/{total} ({passes / total * 100:.0f}%)" if total else "n/a"


def format_scorecard_embed(stats: ScorecardStats, ticker: str | None = None) -> discord.Embed:
    win_pct = stats.passes / stats.resolved * 100 if stats.resolved else 0.0
    color = (
        discord.Color.green() if win_pct >= 60
        else discord.Color.gold() if win_pct >= 40
        else discord.Color.red()
    )
    embed = discord.Embed(
        title="Signal Scorecard" + (f" — {ticker}" if ticker else ""),
        color=color,
    )

    overall = [
        f"Resolved: **{stats.resolved}** · Pending: {stats.pending}",
        f"Absolute win rate: **{_rate(stats.passes, stats.resolved)}**",
        f"vs SPY win rate: **{_rate(stats.vs_benchmark_passes, stats.vs_benchmark_total)}**",
    ]
    if stats.vs_benchmark_total < stats.resolved:
        overall[-1] += f" ({stats.resolved - stats.vs_benchmark_total} without benchmark data)"
    if stats.avg_alpha_pct is not None:
        overall.append(f"Avg alpha vs SPY: {stats.avg_alpha_pct:+.1f}%")
    overall.append(f"Price targets hit: {_rate(stats.target_hits, stats.target_total)}")
    embed.add_field(name="Overall", value="\n".join(overall), inline=False)

    if stats.by_decision:
        ordered = sorted(
            stats.by_decision.items(),
            key=lambda kv: _DECISION_ORDER.index(kv[0]) if kv[0] in _DECISION_ORDER else len(_DECISION_ORDER),
        )
        lines = []
        for decision, ds in ordered:
            line = f"{decision}: {_rate(ds.passes, ds.total)}"
            if ds.avg_move_pct is not None:
                line += f" · avg move {ds.avg_move_pct:+.1f}%"
            if ds.vs_benchmark_total:
                line += f" · vs SPY {_rate(ds.vs_benchmark_passes, ds.vs_benchmark_total)}"
            lines.append(line)
        embed.add_field(name="By decision", value="\n".join(lines), inline=False)

    if not ticker and stats.by_ticker:
        top = sorted(stats.by_ticker.items(), key=lambda kv: kv[1][1], reverse=True)[:10]
        embed.add_field(
            name="By ticker",
            value="\n".join(f"{t}: {_rate(p, n)}" for t, (p, n) in top),
            inline=False,
        )

    return embed
