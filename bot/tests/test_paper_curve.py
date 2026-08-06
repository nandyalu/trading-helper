"""Unit tests for the equity-curve helpers in bot/paper.py."""
from bot.paper import max_drawdown, sparkline


def test_sparkline_shapes():
    assert sparkline([]) == ""
    assert sparkline([5.0, 5.0, 5.0]) == "▄▄▄"  # flat series → mid character
    ramp = sparkline([0.0, 1.0, 2.0, 3.0])
    assert ramp[0] == "▁" and ramp[-1] == "█"
    assert len(ramp) == 4


def test_sparkline_downsamples_long_series():
    assert len(sparkline(list(range(100)), width=20)) == 20


def test_max_drawdown():
    assert max_drawdown([]) == 0.0
    assert max_drawdown([1.0, 2.0, 3.0]) == 0.0  # monotonic rise
    assert max_drawdown([100.0, 150.0, 90.0, 120.0]) == 60.0  # 150 → 90
    assert max_drawdown([0.0, -50.0, -20.0, -80.0]) == 80.0  # from the initial peak
