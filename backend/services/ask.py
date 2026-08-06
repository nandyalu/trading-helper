"""/ask: Q&A over the stored analysis of a ticker's latest signal. Context
assembly and answer cleanup are pure (tested); the LLM call goes through
backend/services/analysis.py's quick-think client and is imported lazily so this module —
and its tests — never construct the TradingAgents graph. Blocking — call via
asyncio.to_thread, holding the analysis lock (same GPU as the graph runs).
"""
import re

from backend.database import db
from backend.database.models import Signal

# Reports in reading order; falls back gracefully for pre-Phase-4 signals
# that only have the rationale.
_REPORT_TITLES = {
    "market_report": "Market/technical report",
    "sentiment_report": "Sentiment report",
    "news_report": "News report",
    "fundamentals_report": "Fundamentals report",
    "investment_plan": "Research team plan (bull/bear debate outcome)",
    "trader_investment_plan": "Trader's plan",
}

_PER_REPORT_MAX = 4000  # chars; keeps the whole prompt inside a small model's context
_CONTEXT_MAX = 24000

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text: str) -> str:
    """qwen3 and friends may emit <think>…</think> blocks — not for chat."""
    return _THINK_RE.sub("", text).strip()


def build_ask_context(signal: Signal, reports: dict[str, str]) -> str:
    parts = [
        f"Analysis of {signal.ticker} from {signal.signal_date} "
        f"(decision: {signal.decision}, price then: ${signal.price_at_signal:,.2f})."
    ]
    parts.append(f"## Final decision rationale\n{signal.rationale[:_PER_REPORT_MAX]}")
    for key, title in _REPORT_TITLES.items():
        content = (reports.get(key) or "").strip()
        if content:
            parts.append(f"## {title}\n{content[:_PER_REPORT_MAX]}")
    return "\n\n".join(parts)[:_CONTEXT_MAX]


def answer_about_ticker(ticker: str, question: str) -> str:
    """Full /ask flow minus Discord: latest signal → context → LLM → cleanup."""
    signals = db.get_recent_signals(ticker=ticker, limit=1)
    if not signals:
        return f"No analysis recorded for {ticker} yet — run /analyze first."
    signal = signals[0]
    reports = db.get_signal_reports(signal.id)
    context = build_ask_context(signal, reports)
    from backend.services.analysis import answer_question  # lazy: building the graph is heavy

    answer = strip_think(answer_question(context, question))
    if not answer:
        return "The model returned an empty answer — try rephrasing."
    suffix = "" if reports else "\n\n*(only the decision rationale was stored for this signal — older analyses lack full reports)*"
    return answer + suffix
