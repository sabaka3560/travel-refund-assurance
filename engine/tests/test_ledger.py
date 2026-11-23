"""Acceptance tests for WP-4: Ledger, confidence rollup, partial totals, and comparison.

Tests Invariants I10, I11, R8, R9, F7.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import pytest
import sys
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine.engine import preset_t_minus  # noqa: E402

from refund_engine import (
    CancellationRequest,
    Comparison,
    Confidence,
    Corpus,
    Money,
    RefundEngine,
    TaxLine,
    Ticket,
    TimeBasis,
    TotalStatus,
    compare,
)

IST = ZoneInfo("Asia/Kolkata")
CORPUS = Corpus()
ENGINE = RefundEngine(CORPUS)


def mk_ticket(**over) -> Ticket:
    d = dict(
        ticket_number="000-0000000000",
        carrier="SG",
        market="DOMESTIC",
        origin="DEL",
        destination="BOM",
        booking_date=date(2025, 11, 20),
        ticket_issue_date=date(2025, 11, 20),
        scheduled_departure=datetime(2026, 1, 15, 18, 0, tzinfo=IST),
        base_fare=Money.rupees("6700.00"),
        taxes=[
            TaxLine("K3", Money.rupees("352.00")),
            TaxLine("UDF", Money.rupees("708.00")),
            TaxLine("PSF", Money.rupees("160.00")),
        ],
        carrier_surcharges=[TaxLine("YR", Money.rupees("250.00"))],
        seller_fees=[TaxLine("CONVENIENCE_ONLINE", Money.rupees("250.00"))],
        total_paid=Money.rupees("8420.00"),
        fare_family="SAVER",
    )
    d.update(over)
    return Ticket(**d)


def test_no_double_count():
    """Invariant I10: A penalty is deducted exactly once."""
    t = mk_ticket()
    r = ENGINE.evaluate(t, preset_t_minus(t, 120))

    pen = [l for l in r.lines if l.label == "Cancellation penalty"]
    assert len(pen) == 1
    assert pen[0].contribution.is_zero()

    base = [l for l in r.lines if l.label == "Base fare"][0]
    assert base.contribution == Money.rupees("6700.00") - Money.rupees("3200.00")

    # Non-refundable fare recorded once as forfeiture
    t_ai = mk_ticket(carrier="AI", fare_family="ECONOMY_VALUE")
    r_ai = ENGINE.evaluate(t_ai, preset_t_minus(t_ai, 120))
    b_ai = [l for l in r_ai.lines if l.label == "Base fare"][0]
    assert b_ai.contribution.is_zero()
    assert r_ai.refund_total == Money.rupees("1220.00")


def test_partial_label():
    """Invariant I11: A total that excludes an abstained material component is labelled PARTIAL."""
    t = mk_ticket(carrier="AI", fare_family=None)  # unknown fare family -> fare component abstains
    r = ENGINE.evaluate(t, preset_t_minus(t, 120))

    assert r.total_status is TotalStatus.PARTIAL
    assert r.refund_total == Money.rupees("1220.00")
    assert any("Base fare" in c for c in r.excluded_components)
    assert r.confidence is Confidence.LOW


def test_rollup_ignores_incidental_lines():
    """F7: Incidental lines must not move or drag case confidence."""
    t = mk_ticket()
    r = ENGINE.evaluate(t, preset_t_minus(t, 120))
    # Incidental lines like YR (contribution 0, confidence INSUFFICIENT) should not drag confidence
    # for lines with real figures.
    material = [l for l in r.lines if not l.contribution.is_zero() or l.label in ("Base fare", "Cancellation penalty")]
    assert all(l.confidence in (Confidence.HIGH, Confidence.MEDIUM) for l in material)


def test_comparison_against_received():
    """P1: Entitled vs actual received comparison."""
    t = mk_ticket()
    r = ENGINE.evaluate(t, preset_t_minus(t, 120))  # entitled = ₹4,720.00, status = PARTIAL due to YR exclusion

    # When total_status is PARTIAL, comparison status must be NOT_COMPARABLE
    cmp = compare(r, Money.rupees("4000.00"), "sha256:refund_receipt")
    assert cmp.status == "NOT_COMPARABLE"

    # For a complete result:
    t_no_surcharges = mk_ticket(carrier_surcharges=[], total_paid=Money.rupees("8170.00"))
    r_complete = ENGINE.evaluate(t_no_surcharges, preset_t_minus(t_no_surcharges, 120))
    assert r_complete.total_status is TotalStatus.COMPLETE

    # Match
    c_match = compare(r_complete, Money.rupees("4720.00"), "rec_1")
    assert c_match.status == "MATCH"

    # Shortfall
    c_short = compare(r_complete, Money.rupees("3720.00"), "rec_2")
    assert c_short.status == "SHORTFALL"
    assert c_short.delta == Money.rupees("1000.00")

    # Excess
    c_excess = compare(r_complete, Money.rupees("5000.00"), "rec_3")
    assert c_excess.status == "EXCESS"
