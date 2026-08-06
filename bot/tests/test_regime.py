"""Unit tests for the pure classification/formatting in bot/regime.py."""
import datetime

from bot.regime import RegimeData, _normalize_yield, classify_regime, format_regime_message


def _data(vix=16.0, spy_price=750.0, spy_ma200=700.0, curve=0.8):
    return RegimeData(
        as_of=datetime.date(2026, 7, 17),
        vix=vix,
        spy_price=spy_price,
        spy_ma200=spy_ma200,
        curve_spread_pct=curve,
    )


def test_all_clear_is_risk_on():
    assert classify_regime(14.0, 5.0, 0.5) == ("Risk-on", "🟢")


def test_one_negative_is_mixed():
    assert classify_regime(27.0, 5.0, 0.5) == ("Mixed", "🟡")  # elevated VIX
    assert classify_regime(14.0, -2.0, 0.5) == ("Mixed", "🟡")  # below 200dma
    assert classify_regime(14.0, 5.0, -0.3) == ("Mixed", "🟡")  # inverted curve


def test_two_or_more_negatives_is_risk_off():
    assert classify_regime(30.0, -5.0, 0.5) == ("Risk-off", "🔴")
    assert classify_regime(30.0, -5.0, -0.5) == ("Risk-off", "🔴")


def test_missing_indicators_are_skipped_not_counted():
    assert classify_regime(None, None, None) == ("Unknown", "⚪")
    assert classify_regime(None, 5.0, None) == ("Risk-on", "🟢")
    assert classify_regime(None, -5.0, None) == ("Mixed", "🟡")


def test_yield_normalization_handles_both_quote_styles():
    assert _normalize_yield(4.57) == 4.57
    assert _normalize_yield(45.7) == 4.57


def test_message_contains_all_available_parts():
    message = format_regime_message(_data())
    assert "Risk-on" in message
    assert "VIX 16.0 (normal)" in message
    assert "7.1% above" in message
    assert "+0.80% (normal)" in message


def test_message_degrades_when_data_missing():
    message = format_regime_message(_data(vix=None, spy_price=None, spy_ma200=None, curve=-0.2))
    assert "Mixed" in message
    assert "VIX" not in message
    assert "inverted" in message
    empty = format_regime_message(_data(vix=None, spy_price=None, spy_ma200=None, curve=None))
    assert "no market data available" in empty
