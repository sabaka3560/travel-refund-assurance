"""Acceptance tests for WP-2: Resolver hardening, dual reading, horizon, precedence, and ambiguity.

Tests Invariants I4, I5, R5, R7, R8, R13.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import pytest
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import Corpus, Rule
from refund_engine.corpus import RuleRejection


def test_unknown_key_agreement():
    """When both booking date and cancellation date select the same rule, proceed with key_used='BOTH_AGREE'."""
    corpus = Corpus()
    # 6E rule 6E-DOM-OBS-20250708 has window [2025-07-08, 2026-08-22]
    # Booking 2025-11-20, cancel 2026-01-10: both fall in this window
    res = corpus.resolve(
        carrier="6E",
        market="DOMESTIC",
        fare_family=None,
        booking_date=date(2025, 11, 20),
        cancel_date=date(2026, 1, 10),
        dual_reading=True,
    )
    assert res.rule is not None
    assert res.rule.policy_id == "6E-DOM-OBS-20250708"
    assert res.key_used == "BOTH_AGREE"


def test_unknown_key_disagreement_abstains():
    """Invariant I5: A rule whose applicability key is unknown is selected only when both readings agree."""
    corpus = Corpus()
    # Booking 2024-01-01 falls in 6E-DOM-OBS-20230530
    # Cancel 2026-01-10 falls in 6E-DOM-OBS-20250708
    res = corpus.resolve(
        carrier="6E",
        market="DOMESTIC",
        fare_family=None,
        booking_date=date(2024, 1, 1),
        cancel_date=date(2026, 1, 10),
        dual_reading=True,
    )
    assert res.rule is None
    assert res.key_used == "UNKNOWN"
    assert res.abstention_reason is not None
    assert "6E-DOM-OBS-20230530" in res.abstention_reason
    assert "6E-DOM-OBS-20250708" in res.abstention_reason
    assert "The applicable policy version cannot be established" in res.abstention_reason


def test_temporal_absolute():
    """Invariant I4: A rule is never selected whose evidence window does not cover key date."""
    corpus = Corpus()
    # Booking in 2024 for SpiceJet (earliest rule in 2025-02-28)
    res = corpus.resolve(
        carrier="SG",
        market="DOMESTIC",
        fare_family="SAVER",
        booking_date=date(2024, 1, 1),
        cancel_date=date(2024, 6, 1),
        dual_reading=True,
    )
    assert res.rule is None


def test_projection_horizon():
    """F4: Evidence horizon for open-ended observed windows."""
    corpus = Corpus()
    corpus.max_projection_days = 30

    # Any rule whose observed window is open-ended exercises the horizon. This used to
    # name the IndiGo 2026 rule, which is now quarantined as mis-transcribed.
    rule = next(r for r in corpus.rules
                if r.date_basis == "OBSERVED" and r.observed_to is None)
    horizon = corpus.carrier_observed_through[rule.carrier]

    from datetime import timedelta as _td
    # Within horizon (10 days after observed_through)
    ok, rej, assumption = rule.check_temporal(horizon + _td(days=10), horizon, 30)
    assert ok is True
    assert assumption is not None
    assert assumption.code == "FORWARD_PROJECTION"

    # Beyond horizon (40 days after observed_through)
    ok, rej, assumption = rule.check_temporal(date(2026, 10, 5), corpus.carrier_observed_through["6E"], 30)
    assert ok is False
    assert rej is not None
    assert rej.reason_code == "HORIZON"


def test_ambiguity_abstains():
    """F6: Equal precedence candidates must abstain rather than picking arbitrary sort order."""
    corpus = Corpus()
    # Create two artificial rules with identical rank
    raw_a = dict(corpus.rules[0].raw)
    raw_a["policy_id"] = "RULE-A"
    raw_a["carrier"] = "TEST"
    raw_a["market"] = "DOMESTIC"
    raw_a["fare_family"] = "TEST"
    raw_a["stated_effective_from"] = "2026-01-01"
    raw_a["date_basis"] = "STATED"
    raw_a["applicability_key"] = "BOOKING_DATE"

    raw_b = dict(raw_a)
    raw_b["policy_id"] = "RULE-B"

    corpus.rules = [Rule(raw_a), Rule(raw_b)]
    res = corpus.resolve(
        carrier="TEST",
        market="DOMESTIC",
        fare_family="TEST",
        booking_date=date(2026, 2, 1),
        cancel_date=date(2026, 2, 10),
        dual_reading=True,
    )
    assert res.rule is None
    assert len(res.ambiguous_with) == 2
    assert "RULE-A" in res.ambiguous_with
    assert "RULE-B" in res.ambiguous_with


def test_applies_to_disruption():
    """R13: Rule does not apply if scope conditions mismatch."""
    corpus = Corpus()
    res = corpus.resolve(
        carrier="SG",
        market="DOMESTIC",
        fare_family="SAVER",
        booking_date=date(2025, 11, 20),
        cancel_date=date(2026, 1, 10),
        cause="CARRIER_DISRUPTION",
        dual_reading=True,
    )
    assert res.rule is None
    assert any(r.reason_code == "APPLIES_TO" for r in res.rejections)
