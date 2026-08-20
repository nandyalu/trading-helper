"""Runs TradingAgents for a ticker, persists the resulting signal, and
formats/optionally-posts a Discord embed. Also provides one-off Q&A over
stored analysis text via a shared quick-think LLM client.
"""
import asyncio
import datetime
import json
import logging
import os
import threading
import time
import urllib.request
from collections.abc import Awaitable, Callable

import discord
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.llm_clients.openai_client import OPENAI_COMPATIBLE_PROVIDERS

from backend.database import db
from backend.database.models import Signal
from backend.discord_bot.notify import notify
from backend.services import bars, llm_usage, watchdog
from backend.services.paper import PAPER_EMOJI
from backend.services.positions import Position, compute_position, describe_position, get_current_price
from backend.services.signals import (
    BUYISH_DECISIONS,
    SELLISH_DECISIONS,
    DEFAULT_HORIZON,
    HORIZONS,
    extract_entry_price,
    extract_expected_value,
    extract_price_target,
    extract_risk_reward,
    extract_stop_loss,
    extract_time_horizon,
    extract_trader_target,
    extract_win_probability,
    horizon_params,
    parse_time_horizon_days,
    plausible_level,
)
from backend.services.sizing import build_sizing_field, get_atr, suggest_position

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

# Which trade horizon every analysis runs at. TradingAgents takes this as a
# propagate() argument and threads it into the research manager, trader,
# portfolio manager, and (in this fork) the market analyst's indicator choice.
# Stored as a setting rather than an env var so it can be changed without a
# redeploy, and recorded on each Signal so the scorecard can tell signals
# generated under different horizons apart.
_HORIZON_SETTING_KEY = "horizon"

# Which LLM every analysis runs on. Stored as a setting for the same reason the
# horizon is — a different model can be tried without a redeploy — and recorded
# on each Signal, so the scorecard can tell one model's track record from
# another's instead of blending them. Unset means whatever the stack's env vars
# configured: DEFAULT_CONFIG already has TRADINGAGENTS_DEEP_THINK_LLM applied.
#
# Both think stages get the same model, matching how the deployed env vars are
# set. Splitting them would double the number of things to compare while the
# question being asked is only "is this model any good at all".
_MODEL_SETTING_KEY = "llm_model"
DEFAULT_MODEL = DEFAULT_CONFIG["deep_think_llm"]

# The settings page asks for the model list on every load, and the answer only
# changes when someone pulls a model, so a short cache is enough to keep the
# page off the LLM server.
_MODEL_LIST_TTL_SECONDS = 300
_MODEL_LIST_TIMEOUT_SECONDS = 5
_model_list_cache: tuple[float, list[str]] = (0.0, [])

# final_state keys worth persisting per signal (backend/database/models.py SignalReport):
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
# Built on first use and rebuilt whenever the model setting changes, so an
# answer about an analysis comes from the model currently selected.
_qa_graph: TradingAgentsGraph | None = None
_qa_graph_model: str | None = None
_qa_graph_lock = threading.Lock()


def get_horizon() -> str:
    """The configured trade horizon, defaulting to swing. An unrecognized
    stored value falls back to the default rather than raising — a bad setting
    should not stop analysis from running."""
    stored = (db.get_setting(_HORIZON_SETTING_KEY) or "").strip().lower()
    return stored if stored in HORIZONS else DEFAULT_HORIZON


def set_horizon(horizon: str) -> None:
    horizon = horizon.strip().lower()
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {sorted(HORIZONS)}, got {horizon!r}")
    db.set_setting(_HORIZON_SETTING_KEY, horizon)


def get_model() -> str:
    """The LLM every analysis runs on. An unset setting means the model the
    stack's env vars configured."""
    return (db.get_setting(_MODEL_SETTING_KEY) or "").strip() or DEFAULT_MODEL


def _canonical(model: str) -> str:
    """Ollama's implicit tag: ``foo`` and ``foo:latest`` name the same model,
    and the endpoint always reports the tagged form. Without this the
    deployment's own default (TRADINGAGENTS_DEEP_THINK_LLM=gemma4-e2b-96k)
    would be rejected as unavailable by the very endpoint serving it."""
    return model if ":" in model else f"{model}:latest"


def set_model(model: str) -> None:
    """Rejects a model the endpoint doesn't serve, but only when the endpoint
    could actually be asked — see list_models() for why an empty list is not
    evidence of anything."""
    model = model.strip()
    if not model:
        raise ValueError("Model must not be empty.")
    available = list_models()
    if available and _canonical(model) not in {_canonical(name) for name in available}:
        raise ValueError(f"{model} isn't served by the LLM endpoint — pull it there first.")
    db.set_setting(_MODEL_SETTING_KEY, model)


def model_choices() -> list[str]:
    """What the settings page offers: every model the endpoint serves, with the
    current one always present under the exact name it is stored as.

    A dropdown with no option matching the current value shows some other model
    as if it were selected, and the endpoint's spelling need not match the
    setting's — it reports ``gemma4-e2b-96k:latest`` for a setting that reads
    ``gemma4-e2b-96k``. Substituting rather than appending keeps one entry per
    model instead of two names for the same weights."""
    available = list_models()
    if not available:
        return []
    current = get_model()
    others = [name for name in available if _canonical(name) != _canonical(current)]
    return sorted([*others, current])


def _models_endpoint() -> str | None:
    """The ``/models`` URL of whichever OpenAI-compatible endpoint the graph
    will talk to, or None for a provider that isn't one.

    Base-URL precedence (config > provider env var > provider default) is read
    from the same registry OpenAIClient.get_llm() uses, so the list can never
    describe a different server than the one that runs the analysis."""
    spec = OPENAI_COMPATIBLE_PROVIDERS.get(str(DEFAULT_CONFIG.get("llm_provider") or "").lower())
    if spec is None:
        return None
    env_base_url = os.environ.get(spec.base_url_env) if spec.base_url_env else None
    base_url = DEFAULT_CONFIG.get("backend_url") or env_base_url or spec.base_url
    return f"{base_url.rstrip('/')}/models" if base_url else None


def list_models(*, force: bool = False) -> list[str]:
    """Every model the configured LLM endpoint currently serves, sorted.

    An empty list means "couldn't ask", never "there are no models". Every
    caller treats it that way, so an unreachable Ollama pool degrades the
    settings page to showing the current model on its own — it never blocks a
    save and never stops an analysis. Blocking (one HTTP request) — run from a
    thread when called off the event loop."""
    global _model_list_cache
    cached_at, cached = _model_list_cache
    if not force and cached and time.monotonic() - cached_at < _MODEL_LIST_TTL_SECONDS:
        return cached
    url = _models_endpoint()
    if url is None:
        return []
    try:
        with urllib.request.urlopen(url, timeout=_MODEL_LIST_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
        models = sorted(
            str(entry["id"])
            for entry in payload.get("data", [])
            if isinstance(entry, dict) and entry.get("id")
        )
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        log.warning("Couldn't list models from %s: %s", url, exc)
        return cached
    _model_list_cache = (time.monotonic(), models)
    return models


def _build_graph(
    model: str | None = None, tracker: llm_usage.UsageTracker | None = None
) -> TradingAgentsGraph:
    """A fresh instance per analysis run. TradingAgentsGraph.propagate()
    mutates its own state in place (self.graph — recompiled every call,
    self.curr_state, self.ticker, self._checkpointer_ctx), so two concurrent
    propagate() calls sharing one instance would corrupt each other's run.
    Construction itself is cheap (in-memory client/graph wiring, no network
    I/O) — the expense is entirely in propagate()'s LLM calls.

    ``model`` overrides the configured LLM for both think stages; None reads
    the current setting. ``tracker`` counts the tokens every stage spends —
    attached here because this is the only place that sees both clients before
    the agents start sharing them."""
    config = DEFAULT_CONFIG.copy()
    config["deep_think_llm"] = config["quick_think_llm"] = model or get_model()
    graph = TradingAgentsGraph(config=config)
    if tracker is not None:
        llm_usage.attach(tracker, graph.deep_thinking_llm, graph.quick_thinking_llm)
    return graph


def _quick_think_llm():
    """The shared Q&A client, rebuilt when the model setting changes."""
    global _qa_graph, _qa_graph_model
    model = get_model()
    with _qa_graph_lock:
        if _qa_graph is None or _qa_graph_model != model:
            _qa_graph = _build_graph(model)
            _qa_graph_model = model
        return _qa_graph.quick_thinking_llm


async def propagate_ticker(ticker: str) -> tuple[dict, str]:
    """Runs the graph — the one place every caller (API routes, Discord
    /analyze, the daily sweep, analyze-all) goes through, building a fresh
    graph (see _build_graph) and bounding concurrent runs via
    _analysis_semaphore. Returns (final_state, decision); recording and
    Discord posting are the caller's job (order matters — see
    run_analysis_and_notify).

    ``horizon`` reaches the prompts through propagate(), and comes back out in
    final_state, which is where record_signal reads it from — so the recorded
    signal always carries the horizon the run actually used, even if the
    setting changes while the analysis is in flight. The model and what the run
    cost are put into final_state here for exactly the same reason;
    TradingAgents has no reason to report either itself.

    The clock starts after the graph is built and the semaphore is acquired, so
    the recorded duration is the analysis itself — not the queue behind three
    other analyses holding the GPUs."""
    async with _analysis_semaphore:
        trade_date = datetime.date.today().isoformat()
        horizon = await asyncio.to_thread(get_horizon)
        model = await asyncio.to_thread(get_model)
        tracker = llm_usage.UsageTracker()
        graph = await asyncio.to_thread(_build_graph, model, tracker)
        started = time.monotonic()
        final_state, decision = await asyncio.to_thread(
            graph.propagate, ticker, trade_date, horizon=horizon
        )
        final_state["llm_model"] = model
        final_state["llm_usage"] = tracker.finish(time.monotonic() - started)
        return final_state, decision


def _resolve_stop_loss(
    ticker: str, decision: str, stated_stop: float | None, price: float
) -> float | None:
    """The stop the trader named (already checked for plausibility by the
    caller), or an ATR-derived one when there isn't a usable one.

    Every actionable Buy needs a defined exit, and a usable stop is missing
    twice as often as it looks: ``stop_loss`` is optional on TraderProposal,
    *and* a stated one is discarded when it is nowhere near the traded price.
    Falling back to the same 2×ATR(14) level the sizing suggestion already
    shows means the watchdog has something real to watch either way.

    Only for Buy-ish decisions. A stop below the current price is meaningless
    on a Sell, and this app is long-only.
    """
    if stated_stop is not None or decision not in BUYISH_DECISIONS:
        return stated_stop
    atr = get_atr(ticker)
    if atr is None:
        return None
    suggestion = suggest_position(price, atr, equity=None)
    return suggestion.stop if suggestion else None


def _levels_on_the_wrong_side(
    decision: str, stop: float | None, target: float | None, price: float
) -> tuple[float | None, float | None]:
    """Drop a stop at or above the traded price, and a target at or below it.

    The deviation check asks only *how far* a level is from the price, never
    *which side* of it the level is on, and a plan can be entirely reasonable
    for an entry that never happened. ZBH on 2026-08-12 is the case: the trader
    proposed buying a pullback to $91.00 with a stop at $90.76 and a target at
    $92.00, and the stock was at $97.89. Every level is within 8% of the price,
    so all three survived, and the signal was stored with a target the market
    had already passed.

    Levels are only ever read from the traded price forward — the watchdog
    watches from there, the auto trader buys from there. A target under it is
    reached the instant it is written; a stop over it triggers the same way.
    Neither describes anything that can still happen.

    Sell-ish decisions are left alone. This app is long-only, so it takes no
    action on them and their levels point the other way by design.
    """
    if decision in SELLISH_DECISIONS:
        return stop, target
    if stop is not None and stop >= price:
        stop = None
    if target is not None and target <= price:
        target = None
    return stop, target


def _trade_plan_levels(
    trader_plan: str, rationale: str, price: float | None, decision: str, params: dict
) -> dict:
    """Entry / stop / target and the two derived numbers, with anything the
    model invented removed.

    The derived numbers go out with their inputs. ``risk_reward`` and
    ``expected_value_r`` are computed by TradingAgents *from* the entry, stop,
    and target, so once one of those is discarded the pair no longer describes
    anything — keeping them would put a confident "2.40 : 1, +1.21R" beside a
    trade that has no levels at all. ``win_probability`` is the model's own
    estimate rather than a derivation, so it survives.
    """
    max_deviation = params["max_level_deviation_pct"]
    stated = {
        "entry_price": extract_entry_price(trader_plan),
        "stop_loss": extract_stop_loss(trader_plan),
        # The trader first, the final decision only as a fallback. These four
        # numbers have to describe one plan: risk_reward and expected_value are
        # derived by TradingAgents from the *trader's* target, so taking the
        # target from the portfolio manager instead stores arithmetic that
        # cannot be explained by the levels beside it. ADT on 2026-08-12 was
        # recorded with the trader's entry 7.28 and stop 6.90, the manager's
        # target 6.80, and a 0.08 risk/reward that only makes sense against the
        # trader's own 7.31.
        "price_target": extract_trader_target(trader_plan) or extract_price_target(rationale),
    }
    # No price to check against means no basis for rejecting anything. Dropping
    # every level would be the wrong call — an unknown price is not evidence
    # that the model invented them.
    kept = (
        {name: plausible_level(value, price, max_deviation) for name, value in stated.items()}
        if price
        else dict(stated)
    )

    discarded = {
        name: value for name, value in stated.items() if value is not None and kept[name] is None
    }
    if discarded:
        log.warning(
            "Discarded implausible level(s) on a signal priced at %.4f (over %.0f%% away): %s",
            price,
            max_deviation,
            ", ".join(f"{name}={value}" for name, value in discarded.items()),
        )

    stop, target = (
        _levels_on_the_wrong_side(decision, kept["stop_loss"], kept["price_target"], price)
        if price
        else (kept["stop_loss"], kept["price_target"])
    )
    if stop is None and kept["stop_loss"] is not None:
        log.warning(
            "Discarded a stop at %.4f on a %s priced at %.4f — it is at or above the price",
            kept["stop_loss"], decision, price,
        )
    if target is None and kept["price_target"] is not None:
        log.warning(
            "Discarded a target at %.4f on a %s priced at %.4f — the price is already past it",
            kept["price_target"], decision, price,
        )
    kept["stop_loss"], kept["price_target"] = stop, target

    levels_intact = not discarded and stop is not None and target is not None
    return {
        **kept,
        "win_probability": extract_win_probability(trader_plan),
        "risk_reward": extract_risk_reward(trader_plan) if levels_intact else None,
        "expected_value_r": extract_expected_value(trader_plan) if levels_intact else None,
    }


def signal_price(ticker: str, today: datetime.date | None = None) -> float | None:
    """The price to record a signal against.

    While the market is open this is simply the current quote. While it is shut
    it is the last completed session's close instead, and the difference
    matters as soon as analyses run before the open.

    Webull's snapshot reports the last trade, and pre-market sessions begin at
    4:00 ET — so a sweep at 7:00 or 8:30 ET would price a signal off a thin
    print with a wide spread, hours before the market agrees what the stock is
    worth. Every level on the trade plan is then drawn against a number that
    was never really the price, and the agent buys at the open into a different
    one. That is the same failure the wrong-side guard exists to catch, arriving
    by a new route.

    A completed close is the price the whole market settled on, which is the
    same reasoning the bar cache already follows: today's bar is never stored,
    because it is still moving.
    """
    if watchdog.is_us_market_hours():
        return get_current_price(ticker)

    today = today or datetime.date.today()
    window = bars.get_bars(ticker, today - datetime.timedelta(days=10), today=today)
    if window:
        return window[-1].close
    # No cached history — a newly added ticker, or one the fetch failed for.
    # A live quote is better than refusing to record the signal at all.
    log.info("No completed bar for %s — falling back to the live quote", ticker)
    return get_current_price(ticker)


def record_signal(ticker: str, final_state: dict, decision: str, message_id: str | None = None) -> Signal | None:
    price = signal_price(ticker)
    if price is None:
        log.warning("Could not fetch a price for %s, skipping signal record", ticker)
        return None
    rationale = final_state.get("final_trade_decision", "")
    time_horizon_text = extract_time_horizon(rationale)
    # The exit level and the quality of the bet come from the trader's
    # proposal, one stage before the portfolio manager — PortfolioDecision
    # carries only a rating, summary, thesis, price target, and time horizon.
    trader_plan = final_state.get("trader_investment_plan") or ""
    # The run's own horizon and model, not the current settings — see
    # propagate_ticker.
    horizon = final_state.get("horizon") or get_horizon()
    model = final_state.get("llm_model") or get_model()
    # Absent for a signal recorded outside propagate_ticker (a replayed
    # final_state, a test), which stores NULL rather than a fabricated zero.
    usage = final_state.get("llm_usage") or llm_usage.Usage()
    params = horizon_params(horizon)
    evaluation_date = datetime.date.today() + datetime.timedelta(
        days=parse_time_horizon_days(
            time_horizon_text,
            default_days=params["eval_days"],
            max_days=params["max_eval_days"],
        )
    )
    levels = _trade_plan_levels(trader_plan, rationale, price, decision, params)
    signal_id = db.record_signal(
        ticker=ticker,
        decision=decision,
        rationale=rationale,
        price_at_signal=price,
        evaluation_date=evaluation_date,
        time_horizon_text=time_horizon_text,
        price_target=levels["price_target"],
        message_id=message_id,
        horizon=horizon,
        model=model,
        duration_seconds=usage.duration_seconds,
        prompt_tokens=usage.prompt_tokens or None,
        completion_tokens=usage.completion_tokens or None,
        llm_calls=usage.llm_calls or None,
        entry_price=levels["entry_price"],
        stop_loss=_resolve_stop_loss(ticker, decision, levels["stop_loss"], price),
        win_probability=levels["win_probability"],
        risk_reward=levels["risk_reward"],
        expected_value_r=levels["expected_value_r"],
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
    + record_signal() directly (see backend/discord_bot/client.py)."""
    ticker = ticker.upper().strip()
    final_state, decision = await propagate_ticker(ticker)
    position = compute_position(db.get_transactions(ticker))
    sizing_field = await asyncio.to_thread(build_sizing_field, ticker, decision)
    # Fetched here as well as in record_signal so the embed's trade plan is
    # checked against the same price the stored one is.
    price = await asyncio.to_thread(get_current_price, ticker)
    embed = format_decision_embed(ticker, final_state, decision, position, sizing_field, price)
    message = await notify(embed=embed)
    signal = record_signal(ticker, final_state, decision, message_id=str(message.id) if message else None)
    if message is not None:
        try:
            await message.add_reaction(PAPER_EMOJI)
        except discord.HTTPException:
            log.warning("Couldn't seed the ✅ reaction (missing Add Reactions permission?)")
    return signal


async def run_analyses(
    tickers: list[str], on_failure: Callable[[str], Awaitable[None]] | None = None
) -> list[Signal]:
    """Analyze several tickers at once, one failure never stopping the rest.

    Concurrency is bounded by ``_analysis_semaphore`` inside propagate_ticker,
    not by the caller — which is the whole point. A caller that awaits each
    ticker in a loop keeps exactly one LLM request in flight no matter how many
    backends the Ollama pool has, so every extra GPU sits idle. Dispatching
    them together lets the semaphore admit as many as
    TRADINGAGENTS_MAX_CONCURRENT_ANALYSES allows.

    ``on_failure`` is awaited once per failed ticker, for callers that want to
    report it (the scheduler posts to Discord; the API route just logs).
    """

    async def _one(ticker: str) -> Signal | None:
        try:
            return await run_analysis_and_notify(ticker)
        except Exception:
            log.exception("Analysis failed for %s", ticker)
            if on_failure is not None:
                try:
                    await on_failure(ticker)
                except Exception:
                    log.exception("Failure notification failed for %s", ticker)
            return None

    results = await asyncio.gather(*(_one(ticker) for ticker in tickers))
    return [signal for signal in results if signal is not None]


def answer_question(context: str, question: str) -> str:
    """One-shot Q&A over stored analysis text using the shared quick-think
    LLM client. Blocking — run from a thread."""
    response = _quick_think_llm().invoke(
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


def build_trade_plan_field(levels: dict) -> str | None:
    """The trade's exit level and the quality of the bet, as one embed field.
    None when nothing survived — an empty section is worse than no section.

    Takes the already-checked levels from _trade_plan_levels rather than
    re-reading the trader plan, so the embed and the stored signal can never
    disagree about what the plan was. The embed is posted before record_signal
    runs, so a level the database rejects would otherwise still be the thing
    the reader acts on.
    """
    entry = levels["entry_price"]
    stop = levels["stop_loss"]
    probability = levels["win_probability"]
    risk_reward = levels["risk_reward"]
    expected_value = levels["expected_value_r"]

    lines = []
    if entry is not None:
        lines.append(f"Entry: ${entry:,.2f}")
    if stop is not None:
        risk_line = f"Stop: ${stop:,.2f}"
        if entry:
            risk_line += f" ({(stop / entry - 1) * 100:+.1f}% from entry)"
        lines.append(risk_line)
    if probability is not None:
        lines.append(f"Win probability: {probability:.0f}% (the model's own estimate)")
    if risk_reward is not None:
        lines.append(f"Risk/reward: {risk_reward:.2f} : 1")
    if expected_value is not None:
        verdict = "favorable" if expected_value > 0 else "unfavorable"
        lines.append(f"Expected value: {expected_value:+.2f}R — {verdict}")
    return "\n".join(lines) if lines else None


def format_decision_embed(
    ticker: str,
    final_state: dict,
    decision: str,
    position: Position | None = None,
    sizing_field: str | None = None,
    price: float | None = None,
) -> discord.Embed:
    """``price`` is the current quote. Without it the trade-plan levels are
    shown unchecked, which is only right for callers that have no price to
    check against."""
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

    trade_plan = build_trade_plan_field(
        _trade_plan_levels(
            final_state.get("trader_investment_plan") or "",
            rationale,
            price,
            decision,
            horizon_params(final_state.get("horizon")),
        )
    )
    if trade_plan:
        embed.add_field(name="Trade plan", value=trade_plan[:_FIELD_MAX], inline=False)

    if position is not None and position.quantity > 0:
        lines = describe_position(ticker, position)
        action = _ACTION_FOR_DECISION.get(decision, "").format(qty=position.quantity)
        if action:
            lines.append(f"\n**{action}**")
        embed.add_field(name="Your Position", value="\n".join(lines), inline=False)

    if sizing_field:
        embed.add_field(name="Suggested sizing", value=sizing_field[:_FIELD_MAX], inline=False)

    footer = ["TradingAgents", final_state.get("trade_date", "")]
    if final_state.get("llm_model"):
        footer.append(final_state["llm_model"])
    cost = format_run_cost(final_state.get("llm_usage"))
    if cost:
        footer.append(cost)
    embed.set_footer(text=" · ".join(part for part in footer if part))
    return embed


def format_run_cost(usage) -> str | None:
    """What the run cost, for the embed footer — "2m 14s · 48.2k tokens
    (44.1k in / 4.1k out)". None when nothing was measured, so an unmeasured
    run shows no cost rather than a confident zero."""
    if usage is None or (not usage.duration_seconds and not usage.total_tokens):
        return None
    parts = []
    if usage.duration_seconds:
        minutes, seconds = divmod(int(usage.duration_seconds), 60)
        parts.append(f"{minutes}m {seconds}s" if minutes else f"{seconds}s")
    if usage.total_tokens:
        parts.append(
            f"{_thousands(usage.total_tokens)} tokens "
            f"({_thousands(usage.prompt_tokens)} in / {_thousands(usage.completion_tokens)} out)"
        )
    return " · ".join(parts)


def _thousands(count: int) -> str:
    return f"{count / 1000:.1f}k" if count >= 1000 else str(count)
