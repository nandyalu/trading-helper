"""Pricing one analysis.

The telemetry stored tokens and seconds for one decision — keep self-hosting or
move to a vendor — and pricing them by hand went wrong twice in a week, both
times by blending input and output into a single rate.

Pure.
"""
import pytest

from backend.services import llm_cost


def test_input_and_output_are_priced_separately():
    """Flash-Lite is $0.30 in and $2.50 out. A blended rate is a property of
    the workload's output ratio, not of the model."""
    cost = llm_cost.estimate("gemini-3.5-flash-lite", 1_000_000, 1_000_000, None)

    assert cost.usd == pytest.approx(0.30 + 2.50)


def test_the_measured_sweep_prices_within_a_few_percent_of_the_bill():
    """25 Aug: nine analyses, 911,876 prompt + 84,189 completion, billed
    $0.50. List is an estimate, not the invoice — but it should be close."""
    cost = llm_cost.estimate("gemini-3.5-flash-lite", 911_876, 84_189, None)

    assert cost.usd == pytest.approx(0.484, abs=0.001)
    assert 0.95 < cost.usd / 0.50 < 1.05


def test_a_self_hosted_run_is_priced_in_electricity_not_zero():
    """Reporting $0.00 would be the wrong kind of true: it reads as free when
    it is really paid for in GPU time."""
    cost = llm_cost.estimate("gemma4-e2b-96k", 100_000, 20_000, 3600.0)

    assert cost.basis == "electricity"
    # One GPU-hour at 100 W and $0.22/kWh.
    assert cost.usd == pytest.approx(0.022)


def test_a_local_model_is_never_priced_from_its_tokens():
    """There is no invoice for them, and pricing them at a vendor's rate would
    invent a bill nobody received."""
    cost = llm_cost.estimate("gemma4-e2b-96k", 10_000_000, 5_000_000, 60.0)

    assert cost.basis == "electricity"
    assert cost.usd < 0.01


def test_an_unmeasured_run_has_no_cost_rather_than_zero():
    """Same reason the telemetry stores NULL: a zero reads as a free analysis
    rather than an unrecorded one."""
    assert llm_cost.estimate("gemini-3.5-flash-lite", None, None, None) is None
    assert llm_cost.estimate("gemma4-e2b-96k", None, None, None) is None
    assert llm_cost.estimate(None, None, None, None) is None


def test_an_unknown_vendor_model_falls_back_to_electricity():
    """A model not in the price table is assumed self-hosted. Guessing a
    vendor rate for it would report a bill that may not exist."""
    cost = llm_cost.estimate("some-new-local-build", 100_000, 10_000, 600.0)

    assert cost.basis == "electricity"


def test_the_two_kinds_of_dollar_are_never_added_together():
    """One arrives as an invoice; the other is already being spent to keep a
    home server running. Summing them would state a number nobody pays."""
    class Row:
        def __init__(self, model, p, c, d):
            self.model, self.prompt_tokens, self.completion_tokens = model, p, c
            self.duration_seconds = d

    total = llm_cost.total([
        Row("gemini-3.5-flash-lite", 1_000_000, 0, 90.0),
        Row("gemma4-e2b-96k", 1_000_000, 0, 3600.0),
    ])

    assert total["vendor"] == pytest.approx(0.30)
    assert total["electricity"] == pytest.approx(0.022)
