"""Acceptance tests for WP-1 and WP-3: Band selection, integer-seconds, and Section 7 matrix.

Tests Invariants I2, I3, R2, R5, Section 7 boundary matrix.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import pytest
import sys
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import (
    CancellationRequest,
    Confidence,
    Corpus,
    Money,
    RefundEngine,
    TaxLine,
    Ticket,
    TimeBasis,
    TotalStatus,
)

IST = ZoneInfo("Asia/Kolkata")
CORPUS = Corpus()
ENGINE = RefundEngine(CORPUS)


def mk_fixture(booking_date: date = date(2025, 11, 20), carrier: str = "SG", fare_family: str = "SAVER") -> Ticket:
    return Ticket(
        ticket_number="000-0000000000",
        carrier=carrier,
        market="DOMESTIC",
        origin="DEL",
        destination="BOM",
        booking_date=booking_date,
        ticket_issue_date=booking_date,
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
        fare_family=fare_family,
    )


def test_integer_seconds():
    """Invariant I2: No float participates in band selection."""
    rule = [r for r in CORPUS.rules if r.policy_id == "SG-DOM-STATED-20250228"][0]
    with pytest.raises(TypeError):
        rule.band_for(96.0)  # float forbidden

    # integer seconds works
    band = rule.band_for(96 * 3600)
    assert band is not None
    assert band["fee"]["amount_minor"] == 320000


def test_spicejet_boundary_20251120():
    """Section 7: SpiceJet booked 2025-11-20 -> SG-DOM-STATED-20250228"""
    t = mk_fixture(booking_date=date(2025, 11, 20))
    dep = t.scheduled_departure

    # T-120h -> ₹4,720.00
    r120 = ENGINE.evaluate(t, CancellationRequest(dep - timedelta(hours=120), TimeBasis.USER_SCENARIO))
    assert r120.refund_total == Money.rupees("4720.00")

    # T-96h 00m 00s -> ₹4,720.00 (inclusive lower bound of upper tier)
    r96 = ENGINE.evaluate(t, CancellationRequest(dep - timedelta(seconds=96 * 3600), TimeBasis.USER_SCENARIO))
    assert r96.refund_total == Money.rupees("4720.00")

    # T-95h 59m 59s -> ₹3,645.00 (one second inside lower band)
    r95 = ENGINE.evaluate(t, CancellationRequest(dep - timedelta(seconds=96 * 3600 - 1), TimeBasis.USER_SCENARIO))
    assert r95.refund_total == Money.rupees("3645.00")

    # T-1h -> ₹3,645.00
    r1 = ENGINE.evaluate(t, CancellationRequest(dep - timedelta(hours=1), TimeBasis.USER_SCENARIO))
    assert r1.refund_total == Money.rupees("3645.00")

    # T+3h (post-departure) -> ₹1,220.00, PARTIAL
    r_post = ENGINE.evaluate(t, CancellationRequest(dep + timedelta(hours=3), TimeBasis.USER_SCENARIO))
    assert r_post.refund_total == Money.rupees("1220.00")
    assert r_post.total_status is TotalStatus.PARTIAL


def test_spicejet_boundary_20251220():
    """Section 7: SpiceJet booked 2025-12-20 -> SG-DOM-STATED-20251212"""
    t = mk_fixture(booking_date=date(2025, 12, 20))
    dep = t.scheduled_departure

    # T-120h -> ₹4,021.00
    r120 = ENGINE.evaluate(t, CancellationRequest(dep - timedelta(hours=120), TimeBasis.USER_SCENARIO))
    assert r120.refund_total == Money.rupees("4021.00")

    # T-96h -> ₹4,021.00
    r96 = ENGINE.evaluate(t, CancellationRequest(dep - timedelta(seconds=96 * 3600), TimeBasis.USER_SCENARIO))
    assert r96.refund_total == Money.rupees("4021.00")

    # T-95h 59m 59s -> ₹3,021.00
    r95 = ENGINE.evaluate(t, CancellationRequest(dep - timedelta(seconds=96 * 3600 - 1), TimeBasis.USER_SCENARIO))
    assert r95.refund_total == Money.rupees("3021.00")


def test_instant_is_honoured_to_the_second():
    """Invariant I3: The instant supplied is honoured to the second."""
    t = mk_fixture(booking_date=date(2025, 11, 20))
    dep = t.scheduled_departure

    t_upper = dep - timedelta(seconds=96 * 3600)
    t_lower = dep - timedelta(seconds=96 * 3600 - 1)

    r_upper = ENGINE.evaluate(t, CancellationRequest(t_upper, TimeBasis.USER_SCENARIO))
    r_lower = ENGINE.evaluate(t, CancellationRequest(t_lower, TimeBasis.USER_SCENARIO))

    assert r_upper.cancel_instant == t_upper
    assert r_lower.cancel_instant == t_lower
    assert r_upper.refund_total != r_lower.refund_total
    assert r_upper.refund_total.minor - r_lower.refund_total.minor == 107500  # ₹1,075.00 diff
