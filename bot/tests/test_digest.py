"""Unit tests for the pure formatting in bot/digest.py."""
import datetime

from bot.digest import DigestData, format_digest_embed
from bot.models import Alert, Signal

_WEEK_START = datetime.date(2026, 7, 10)


def _signal(ticker="NVDA", decision="Buy", outcome="pass", vs_benchmark="pass",
            price_at_signal=100.0, price_at_evaluation=105.0):
    return Signal(
        ticker=ticker,
        signal_date=datetime.date(2026, 6, 15),
        decision=decision,
        rationale="",
        price_at_signal=price_at_signal,
        evaluation_date=_WEEK_START,
        price_at_evaluation=price_at_evaluation,
        outcome=outcome,
        outcome_vs_benchmark=vs_benchmark,
        evaluated_at=datetime.datetime(2026, 7, 15, 21, 30),
    )


def _alert(alert_type="big_move"):
    return Alert(
        ticker="NVDA",
        alert_type=alert_type,
        dedupe_key=f"{alert_type}:NVDA:x",
        message="",
        created_at=datetime.datetime(2026, 7, 15, 14, 0),
    )


def test_empty_week_still_renders():
    embed = format_digest_embed(DigestData(week_start=_WEEK_START))
    names = [f.name for f in embed.fields]
    assert "Signals resolved this week" in names
    assert "New signals" in names
    assert "Win rate" in names
    assert "Alerts this week" not in names  # omitted when none fired
    resolved_field = next(f for f in embed.fields if f.name == "Signals resolved this week")
    assert resolved_field.value == "None"


def test_full_week_renders_all_sections():
    data = DigestData(
        week_start=_WEEK_START,
        resolved=[_signal(), _signal(ticker="AAPL", decision="Sell", outcome="fail", vs_benchmark=None,
                          price_at_evaluation=103.0)],
        new_signals=[_signal(), _signal(decision="Hold"), _signal(decision="Hold")],
        alerts=[_alert(), _alert("stop_loss"), _alert()],
        win_rate_30d=(3, 4),
        win_rate_all=(10, 20),
        real_book_line="Open value $5,000.00 · unrealized +$250.00 (+5.3%)",
        paper_lines=["NVDA: 2.1 @ $470.00 → $482.00 (+2.6%)"],
    )
    embed = format_digest_embed(data)
    text = "\n".join(f"{f.name}\n{f.value}" for f in embed.fields)
    assert "NVDA Buy (2026-06-15): **PASS** (+5.0%) · vs SPY PASS" in text
    assert "AAPL Sell (2026-06-15): **FAIL** (+3.0%)" in text
    assert "3 — 2 Hold, 1 Buy" in text
    assert "Last 30 days: **3/4 (75%)** · all-time: 10/20 (50%)" in text
    assert "3 — 2 move, 1 stop" in text
    assert "Open value $5,000.00" in text
    assert "NVDA: 2.1 @ $470.00" in text


def test_resolved_list_truncates_at_ten():
    data = DigestData(week_start=_WEEK_START, resolved=[_signal() for _ in range(13)])
    embed = format_digest_embed(data)
    resolved_field = next(f for f in embed.fields if f.name == "Signals resolved this week")
    assert "…and 3 more" in resolved_field.value
