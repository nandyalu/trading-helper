"""Runs TradingAgents for a ticker, persists the resulting signal, and
formats/optionally-posts a Discord embed. Also provides one-off Q&A over
stored analysis text via a shared quick-think LLM client.
"""
import asyncio
import datetime
import logging
import os

import discord
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

from bot import db
from bot.models import Signal
from bot.notify import notify
from bot.paper import PAPER_EMOJI
from bot.positions import Position, compute_position, describe_position, get_current_price
from bot.signals import extract_price_target, extract_time_horizon, parse_time_horizon_days
from bot.sizing import build_sizing_field

log = logging.getLogger("trading-bot.analysis")

_DECISION_COLOR = {
    "Buy": discord.Color.green(),
    "Overweight": discord.Color.teal(),
    "Hold": discord.Color.gold(),
    "Underweight": discord.Color.orange(),
    "Sell": discord.Color.red(),
}

# Rule-based only — no LLM involved in combining a real position with the
# generic AI signal, this is just a lookup table.
_ACTION_FOR_DECISION = {
    "Sell": "Consider selling/trimming your {qty:g} shares.",
    "Underweight": "Consider selling/trimming your {qty:g} shares.",
    "Buy": "Consider adding to your position.",
    "Overweight": "Consider adding to your position.",
    "Hold": "Maintain your current position.",
}

# Discord hard limits: embed description <= 4096 chars, a field value <= 1024,
# and the total of every embed in one message <= 6000. We put the bulk of the
# rationale in the description (much roomier than a field) and spill any
# overflow into one continuation field. Worst case (4096 + 1024 + position
# field + footer + title) stays comfortably under the 6000 total.
_DESCRIPTION_MAX = 4096
_FIELD_MAX = 1024

# Bounds how many analyses (graph.propagate() calls) run at once, regardless
# of how many callers ask for one concurrently — matches the Ollama pool's
# real GPU count (2 today; bump this env var, no code change, once more
# backends exist). propagate_ticker() acquires it internally so every caller
# (API routes, Discord /analyze, the daily sweep, analyze-all) is bounded
# uniformly.
_MAX_CONCURRENT_ANALYSES = int(os.environ.get("TRADINGAGENTS_MAX_CONCURRENT_ANALYSES", "2"))
_analysis_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_ANALYSES)

# final_state keys worth persisting per signal (bot/models.py SignalReport):
# the four analyst reports plus both researcher/trader plans. The final
# decision text is already stored as Signal.rationale.
REPORT_KEYS = (
    "market_report",
    "sentiment_report",
    "news_report",
    "fundamentals_report",
    "investment_plan",
    "trader_investment_plan",
)

# Used only for its .quick_thinking_llm — never call .propagate() on this.
# A plain LLM client's .invoke() doesn't mutate shared state, so reusing one
# instance across concurrent /ask calls is safe (unlike the graph itself,
# see _build_graph below for why analysis needs a fresh instance per run).
_qa_graph = TradingAgentsGraph(config=DEFAULT_CONFIG.copy())


def _build_graph() -> TradingAgentsGraph:
    """A fresh instance per analysis run. TradingAgentsGraph.propagate()
    mutates its own state in place (self.graph — recompiled every call,
    self.curr_state, self.ticker, self._checkpointer_ctx), so two concurrent
    propagate() calls sharing one instance would corrupt each other's run.
    Construction itself is cheap (in-memory client/graph wiring, no network
    I/O) — the expense is entirely in propagate()'s LLM calls."""
    return TradingAgentsGraph(config=DEFAULT_CONFIG.copy())


async def propagate_ticker(ticker: str) -> tuple[dict, str]:
    """Runs the graph — the one place every caller (API routes, Discord
    /analyze, the daily sweep, analyze-all) goes through, building a fresh
    graph (see _build_graph) and bounding concurrent runs via
    _analysis_semaphore. Returns (final_state, decision); recording and
    Discord posting are the caller's job (order matters — see
    run_analysis_and_notify)."""
    async with _analysis_semaphore:
        trade_date = datetime.date.today().isoformat()
        graph = await asyncio.to_thread(_build_graph)
        return await asyncio.to_thread(graph.propagate, ticker, trade_date)


def record_signal(ticker: str, final_state: dict, decision: str, message_id: str | None = None) -> Signal | None:
    price = get_current_price(ticker)
    if price is None:
        log.warning("Could not fetch a price for %s, skipping signal record", ticker)
        return None
    rationale = final_state.get("final_trade_decision", "")
    time_horizon_text = extract_time_horizon(rationale)
    evaluation_date = datetime.date.today() + datetime.timedelta(
        days=parse_time_horizon_days(time_horizon_text)
    )
    signal_id = db.record_signal(
        ticker=ticker,
        decision=decision,
        rationale=rationale,
        price_at_signal=price,
        evaluation_date=evaluation_date,
        time_horizon_text=time_horizon_text,
        price_target=extract_price_target(rationale),
        message_id=message_id,
    )
    reports = {
        key: final_state[key]
        for key in REPORT_KEYS
        if isinstance(final_state.get(key), str) and final_state[key].strip()
    }
    if reports:
        db.add_signal_reports(signal_id, reports)
    return db.get_signal(signal_id)


async def run_analysis_and_notify(ticker: str) -> Signal | None:
    """propagate -> format embed -> notify() (a no-op if Discord isn't
    configured/connected) -> record the signal, embedding the posted
    message's id if there is one -> seed the paper-trade reaction. This is
    what the API's analyze/analyze-all routes and the scheduled
    sweep/triggered-analysis jobs use. Discord's own /analyze command does
    NOT use this — it replies via the interaction it's responding to
    instead of the configured notify channel, so it calls propagate_ticker()
    + record_signal() directly (see bot/discord_client.py)."""
    ticker = ticker.upper().strip()
    final_state, decision = await propagate_ticker(ticker)
    position = compute_position(db.get_transactions(ticker))
    sizing_field = await asyncio.to_thread(build_sizing_field, ticker, decision)
    embed = format_decision_embed(ticker, final_state, decision, position, sizing_field)
    message = await notify(embed=embed)
    signal = record_signal(ticker, final_state, decision, message_id=str(message.id) if message else None)
    if message is not None:
        try:
            await message.add_reaction(PAPER_EMOJI)
        except discord.HTTPException:
            log.warning("Couldn't seed the ✅ reaction (missing Add Reactions permission?)")
    return signal


def answer_question(context: str, question: str) -> str:
    """One-shot Q&A over stored analysis text using the shared quick-think
    LLM client. Blocking — run from a thread."""
    response = _qa_graph.quick_thinking_llm.invoke(
        [
            (
                "system",
                "You answer questions about a previously generated stock analysis. "
                "Use ONLY the analysis text provided; if it doesn't contain the answer, "
                "say so plainly. Be concise.",
            ),
            ("human", f"{context}\n\n---\nQuestion: {question}"),
        ]
    )
    content = response.content
    if isinstance(content, list):  # some providers return content blocks
        content = " ".join(str(part) for part in content)
    return str(content)


def format_decision_embed(
    ticker: str,
    final_state: dict,
    decision: str,
    position: Position | None = None,
    sizing_field: str | None = None,
) -> discord.Embed:
    rationale = final_state.get("final_trade_decision", "") or "(none)"
    embed = discord.Embed(
        title=f"{ticker} — {decision}",
        description=rationale[:_DESCRIPTION_MAX],
        color=_DECISION_COLOR.get(decision, discord.Color.blurple()),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if len(rationale) > _DESCRIPTION_MAX:
        overflow = rationale[_DESCRIPTION_MAX : _DESCRIPTION_MAX + _FIELD_MAX]
        embed.add_field(name="Rationale (cont.)", value=overflow, inline=False)

    if position is not None and position.quantity > 0:
        lines = describe_position(ticker, position)
        action = _ACTION_FOR_DECISION.get(decision, "").format(qty=position.quantity)
        if action:
            lines.append(f"\n**{action}**")
        embed.add_field(name="Your Position", value="\n".join(lines), inline=False)

    if sizing_field:
        embed.add_field(name="Suggested sizing", value=sizing_field[:_FIELD_MAX], inline=False)

    embed.set_footer(text=f"TradingAgents · {final_state.get('trade_date', '')}")
    return embed
