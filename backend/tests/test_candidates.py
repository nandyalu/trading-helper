"""Screened candidate proposals.

The filter is the whole point. A live pull of the raw gainers screen returned a
stock up 927% in a day; put in front of a few-thousand-dollar swing account
that is not an opportunity, it is a way to lose money. These tests pin the
floors and pin that nothing is ever followed automatically — analysis costs
about seven minutes of GPU per ticker, so the scarce resource is attention, not
ideas.
"""
import pytest

from backend.services import candidates


def _row(symbol="AAA", price=50.0, volume=5_000_000, change=0.03, name="A Corp"):
    return {
        "symbol": symbol,
        "price": str(price),
        "volume": str(volume),
        "change_ratio": str(change),
        "name": name,
    }


@pytest.fixture
def screened(monkeypatch):
    def build(active=(), gainers=(), tracked=(), inactive=()):
        class FakeScreener:
            def __init__(self, _client):
                pass

            def get_most_active(self, *a, **kw):
                return {"data": list(active)}

            def get_gainers_losers(self, *a, **kw):
                return {"data": list(gainers)}

        import sys, types

        module = types.ModuleType("webull.data.quotes.screener")
        module.Screener = FakeScreener
        monkeypatch.setitem(sys.modules, "webull.data.quotes.screener", module)
        monkeypatch.setattr(candidates.quotes, "get_api_client", lambda: object())
        monkeypatch.setattr(candidates.db, "get_watchlist", lambda: list(tracked))
        monkeypatch.setattr(candidates.listings, "inactive_tickers", lambda: list(inactive))
        return candidates.fetch_candidates()

    return build


def test_a_penny_stock_pump_is_filtered_out(screened):
    """The raw screen really did return a stock up 927% at under a dollar."""
    found = screened(gainers=[_row("PLAG", price=0.81, volume=210_000_000, change=9.27)])
    assert found == []


def test_an_illiquid_name_is_filtered_out(screened):
    """Too thin to get out of at any size worth taking."""
    assert screened(active=[_row("THIN", price=50.0, volume=1000)]) == []


def test_a_liquid_name_survives(screened):
    found = screened(active=[_row("NVDA", price=217.5, volume=101_000_000)])

    assert [c.ticker for c in found] == ["NVDA"]
    assert found[0].volume_m == pytest.approx(101.0)


def test_already_tracked_names_are_not_proposed(screened):
    """Proposing what is already followed is noise, and the sweep already
    covers it."""
    assert screened(active=[_row("ZBH", price=97.0)], tracked=["ZBH"]) == []


def test_names_already_tracked_are_not_proposed(screened):
    """One set covers held names too: the agent may not untrack a position it
    still owns, so everything it holds is on the watchlist."""
    assert screened(active=[_row("GOOG", price=350.0)], tracked=["GOOG"]) == []


def test_delisted_names_are_not_proposed(screened):
    """listings already knows these produce no usable data."""
    assert screened(active=[_row("AILEQ", price=50.0)], inactive=["AILEQ"]) == []


def test_the_most_liquid_come_first(screened):
    found = screened(active=[
        _row("LOW", volume=2_000_000),
        _row("HIGH", volume=90_000_000),
        _row("MID", volume=20_000_000),
    ])
    assert [c.ticker for c in found] == ["HIGH", "MID", "LOW"]


def test_a_name_on_both_screens_appears_once_as_the_liquid_one(screened):
    """Most active runs first, so a busy name is described as busy rather than
    as a mover."""
    found = screened(active=[_row("DUP")], gainers=[_row("DUP")])

    assert len(found) == 1
    assert found[0].source == "most active"


def test_the_shortlist_is_capped(screened):
    rows = [_row(f"T{i}", volume=1_000_000 + i) for i in range(30)]
    assert len(screened(active=rows)) == candidates.MAX_PROPOSED


def test_a_failing_screen_does_not_lose_the_other(screened, monkeypatch):
    """One endpoint being down should still leave a usable shortlist."""

    class HalfBroken:
        def __init__(self, _c):
            pass

        def get_most_active(self, *a, **kw):
            raise RuntimeError("503")

        def get_gainers_losers(self, *a, **kw):
            return {"data": [_row("OK")]}

    import sys, types

    module = types.ModuleType("webull.data.quotes.screener")
    module.Screener = HalfBroken
    monkeypatch.setitem(sys.modules, "webull.data.quotes.screener", module)
    monkeypatch.setattr(candidates.quotes, "get_api_client", lambda: object())
    monkeypatch.setattr(candidates.db, "get_watchlist", lambda: [])
    monkeypatch.setattr(candidates.listings, "inactive_tickers", lambda: [])

    assert [c.ticker for c in candidates.fetch_candidates()] == ["OK"]


def test_no_client_means_no_candidates(monkeypatch):
    monkeypatch.setattr(candidates.quotes, "get_api_client", lambda: None)
    assert candidates.fetch_candidates() == []


def test_the_message_says_what_the_screen_was():
    text = candidates.format_candidates(
        [candidates.Candidate("NVDA", "Nvidia", 217.5, 101_000_000, 2.3, "most active")]
    )
    assert "NVDA" in text and "101M shares" in text
    assert "7 minutes" in text, "the cost of following one has to be stated"


def test_an_empty_shortlist_says_so_plainly():
    assert "already tracked" in candidates.format_candidates([])


def test_a_pump_that_cleared_the_price_floor_is_still_filtered(screened):
    """PLAG passed every other filter at $5.81 — because the 927% pump is what
    lifted it over the $5 floor. A price floor alone cannot catch this."""
    assert screened(active=[_row("PLAG", price=5.81, volume=212_000_000, change=9.27)]) == []


def test_a_collapse_is_filtered_too(screened):
    """A stock halved in a session is equally not a one-to-two-week swing."""
    assert screened(active=[_row("CRASH", price=20.0, volume=50_000_000, change=-0.55)]) == []


def test_an_ordinary_move_is_kept(screened):
    found = screened(active=[_row("ACHR", price=6.79, volume=90_000_000, change=0.085)])
    assert [c.ticker for c in found] == ["ACHR"]
