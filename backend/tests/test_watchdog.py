"""Unit tests for the pure parts of backend/services/watchdog.py — alert evaluation and
the market-hours gate. Snapshots and positions are constructed in memory."""
import datetime
from zoneinfo import ZoneInfo

from backend.database.models import Signal
from backend.services.positions import Position
from backend.services.watchdog import AlertConfig, DailySnapshot, evaluate_ticker, is_us_market_hours

_TODAY = datetime.date(2026, 7, 17)
_NY = ZoneInfo("America/New_York")


def _snapshot(price=100.0, prev_close=100.0, today_volume=1_000_000, avg_volume=1_000_000):
    return DailySnapshot(
        price=price,
        prev_close=prev_close,
        day_change_pct=(price / prev_close - 1) * 100 if prev_close else 0.0,
        last_bar_date=_TODAY,
        today_volume=today_volume,
        avg_volume=avg_volume,
    )


def _position(quantity=10.0, avg_cost=100.0):
    return Position(open_lots=[], quantity=quantity, avg_cost=avg_cost, realized_pnl=0.0)


def _target_signal(price_target=120.0, price_at_signal=100.0, decision="Buy"):
    return Signal(
        id=7,
        ticker="NVDA",
        signal_date=datetime.date(2026, 7, 1),
        decision=decision,
        rationale="",
        price_at_signal=price_at_signal,
        price_target=price_target,
        evaluation_date=datetime.date(2026, 8, 1),
    )


def _evaluate(snapshot, real=None, paper=None, target_signal=None, config=None):
    return evaluate_ticker(
        "NVDA", snapshot, real, paper, target_signal, config or AlertConfig(), _TODAY
    )


# --- market hours -------------------------------------------------------------


def test_market_hours_weekday_session():
    open_time = datetime.datetime(2026, 7, 17, 10, 0, tzinfo=_NY)  # Friday 10:00 ET
    assert is_us_market_hours(open_time)
    pre_market = datetime.datetime(2026, 7, 17, 9, 0, tzinfo=_NY)
    assert not is_us_market_hours(pre_market)
    after_close = datetime.datetime(2026, 7, 17, 16, 30, tzinfo=_NY)
    assert not is_us_market_hours(after_close)
    saturday = datetime.datetime(2026, 7, 18, 12, 0, tzinfo=_NY)
    assert not is_us_market_hours(saturday)


def test_market_hours_converts_timezone():
    # 14:00 UTC on a Friday == 10:00 ET → open
    assert is_us_market_hours(datetime.datetime(2026, 7, 17, 14, 0, tzinfo=datetime.timezone.utc))


# --- alert evaluation -----------------------------------------------------------


def test_quiet_day_produces_nothing():
    assert _evaluate(_snapshot(price=101.0, prev_close=100.0)) == []


def test_big_move_alerts_and_triggers():
    alerts = _evaluate(_snapshot(price=94.0, prev_close=100.0))
    assert [a.alert_type for a in alerts] == ["big_move"]
    assert alerts[0].trigger_analysis is True
    assert alerts[0].dedupe_key == f"big_move:NVDA:{_TODAY}"
    assert "-6.0%" in alerts[0].message


def test_volume_spike_alerts_and_triggers():
    alerts = _evaluate(_snapshot(today_volume=2_500_000, avg_volume=1_000_000))
    assert [a.alert_type for a in alerts] == ["volume"]
    assert alerts[0].trigger_analysis is True
    assert "2.5×" in alerts[0].message


def test_zero_avg_volume_never_divides():
    assert _evaluate(_snapshot(today_volume=100, avg_volume=0)) == []


def test_stop_loss_covers_both_books_in_one_alert():
    # Small day move (−1.2%) so only the stop rule fires, not big_move.
    snapshot = _snapshot(price=85.0, prev_close=86.0)
    alerts = _evaluate(snapshot, real=_position(avg_cost=100.0), paper=_position(avg_cost=98.0))
    assert [a.alert_type for a in alerts] == ["stop_loss"]
    assert alerts[0].trigger_analysis is False
    assert "real avg cost $100.00" in alerts[0].message
    assert "paper avg cost $98.00" in alerts[0].message


def test_stop_loss_ignores_closed_positions():
    alerts = _evaluate(
        _snapshot(price=85.0, prev_close=86.0), real=_position(quantity=0.0, avg_cost=100.0)
    )
    assert alerts == []


def test_target_touch_requires_open_position():
    snapshot = _snapshot(price=121.0, prev_close=119.0)
    assert _evaluate(snapshot, target_signal=_target_signal()) == []
    alerts = _evaluate(snapshot, paper=_position(), target_signal=_target_signal())
    assert [a.alert_type for a in alerts] == ["target"]
    assert alerts[0].dedupe_key == "target:7"
    assert "$120.00" in alerts[0].message


def test_downside_target_uses_low_side():
    # avg cost near price so the stop rule stays quiet and isolates the target rule.
    signal = _target_signal(price_target=80.0, price_at_signal=100.0, decision="Sell")
    no_touch = _evaluate(
        _snapshot(price=90.0, prev_close=91.0), real=_position(avg_cost=91.0), target_signal=signal
    )
    assert no_touch == []
    touched = _evaluate(
        _snapshot(price=79.0, prev_close=81.0), real=_position(avg_cost=80.0), target_signal=signal
    )
    assert [a.alert_type for a in touched] == ["target"]


def test_multiple_alerts_stack():
    alerts = _evaluate(
        _snapshot(price=85.0, prev_close=100.0, today_volume=3_000_000, avg_volume=1_000_000),
        real=_position(avg_cost=100.0),
    )
    assert sorted(a.alert_type for a in alerts) == ["big_move", "stop_loss", "volume"]


def test_thresholds_come_from_config():
    config = AlertConfig(move_pct=2.0, stop_pct=3.0, volume_mult=1.5)
    alerts = _evaluate(
        _snapshot(price=97.5, prev_close=100.0, today_volume=1_600_000),
        real=_position(avg_cost=101.0),
        config=config,
    )
    assert sorted(a.alert_type for a in alerts) == ["big_move", "stop_loss", "volume"]
