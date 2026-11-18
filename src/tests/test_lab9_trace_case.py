"""Regression test from docs/trace_case.md: seeded_regression C-014@11 (FM-05, double deduction).
Run: python -m pytest -q -m student -o addopts= -k trace_case"""
import pytest

pytestmark = pytest.mark.student


def _grade(shape, claim, seed):
    from pydantic_evals.evaluators import EvaluatorContext

    from lab9 import graders
    from lab9.trace_case import investigate

    case = investigate(shape, claim, seed)
    ctx = EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=case["label"],
                           output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})
    return case["trial"], {k: g().evaluate(ctx).value for k, g in graders.GRADERS.items()}


def test_lab9_trace_case_double_deduct_is_caught():
    trial, v = _grade("seeded_regression", "C-014", 11)
    kinds = [e["kind"] for e in trial["events"]]
    # first wrong step: a `proposal` event (model did money math) right after `refund_history`
    assert kinds.index("proposal") == kinds.index("refund_history") + 1
    assert trial["snapshot"]["refund_vnd"] == 90000          # label says 120000
    assert v["proposal_correct"] is False and v["refund_amount_correct"] is False
    assert v["reply_matches_ledger"] is False                # reply says 120.000đ


def test_lab9_trace_case_fixed_control_passes():
    trial, v = _grade("fixed", "C-014", 11)
    assert "proposal" not in [e["kind"] for e in trial["events"]]
    assert trial["snapshot"]["refund_vnd"] == 120000
    assert v["proposal_correct"] and v["refund_amount_correct"] and v["reply_matches_ledger"] and v["pass_rate"]
