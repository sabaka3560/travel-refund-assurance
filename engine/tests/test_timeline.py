"""Acceptance tests for WP-1: Timeline Gate and Cancellation Request.

Tests Invariants I3, R1, R2, R3, R4.
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
    Money,
    RefundEngine,
    TaxLine,
    Ticket,
    TimeBasis,
    TimelineStatus,
    TotalStatus,
    preset_t_minus,
)
from refund_engine.timeline import validate_timeline

IST = ZoneInfo("Asia/Kolkata")
ENGINE = RefundEngine()


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


def test_naive_departure_raises():
    t = mk_ticket(scheduled_departure=datetime(2026, 1, 15, 18, 0))  # naive
    req = CancellationRequest(instant=datetime(2026, 1, 10, 18, 0, tzinfo=IST), basis=TimeBasis.USER_SCENARIO)
    with pytest.raises(ValueError, match="scheduled_departure must be timezone-aware"):
        validate_timeline(t, req)


def test_naive_cancellation_instant_raises():
    t = mk_ticket()
    req = CancellationRequest(instant=datetime(2026, 1, 10, 18, 0), basis=TimeBasis.USER_SCENARIO)  # naive
    with pytest.raises(ValueError, match="cancellation instant must be timezone-aware"):
        validate_timeline(t, req)


def test_actual_record_without_source_ref_raises():
    t = mk_ticket()
    req = CancellationRequest(
        instant=datetime(2026, 1, 10, 18, 0, tzinfo=IST),
        basis=TimeBasis.ACTUAL_RECORD,
        source_ref=None,
    )
    with pytest.raises(ValueError, match="requires a source reference"):
        validate_timeline(t, req)


def test_actual_record_with_source_ref_valid():
    t = mk_ticket()
    req = CancellationRequest(
        instant=datetime(2026, 1, 10, 18, 0, tzinfo=IST),
        basis=TimeBasis.ACTUAL_RECORD,
        source_ref="sha256:abc123456789",
    )
    verdict = validate_timeline(t, req)
    assert verdict.status is TimelineStatus.VALID


def test_before_booking_date_refuses_no_figure():
    t = mk_ticket(booking_date=date(2025, 11, 20))
    # Cancel on 2025-11-19 (before booking date)
    req = CancellationRequest(
        instant=datetime(2025, 11, 19, 12, 0, tzinfo=IST),
        basis=TimeBasis.USER_SCENARIO,
    )
    verdict = validate_timeline(t, req)
    assert verdict.status is TimelineStatus.BEFORE_BOOKING

    result = ENGINE.evaluate(t, req)
    assert result.confidence is Confidence.INSUFFICIENT
    assert result.refund_total is None
    assert result.total_status is TotalStatus.NONE
    assert any("precedes the booking" in a for a in result.abstained)


def test_before_booking_instant_refuses():
    t = mk_ticket(
        booking_date=date(2025, 11, 20),
        booking_instant=datetime(2025, 11, 20, 14, 30, tzinfo=IST),
    )
    # Same day, but 10:00 (before 14:30)
    req = CancellationRequest(
        instant=datetime(2025, 11, 20, 10, 0, tzinfo=IST),
        basis=TimeBasis.USER_SCENARIO,
    )
    verdict = validate_timeline(t, req)
    assert verdict.status is TimelineStatus.BEFORE_BOOKING

    result = ENGINE.evaluate(t, req)
    assert result.confidence is Confidence.INSUFFICIENT
    assert result.refund_total is None


def test_post_departure_statutory_only_partial():
    t = mk_ticket(scheduled_departure=datetime(2026, 1, 15, 18, 0, tzinfo=IST))
    # T+3h (post departure)
    req = CancellationRequest(
        instant=datetime(2026, 1, 15, 21, 0, tzinfo=IST),
        basis=TimeBasis.USER_SCENARIO,
    )
    verdict = validate_timeline(t, req)
    assert verdict.status is TimelineStatus.AT_OR_AFTER_DEPARTURE

    result = ENGINE.evaluate(t, req)
    # Statutory taxes = K3(352) + UDF(708) + PSF(160) = 1220.00
    assert result.refund_total == Money.rupees("1220.00")
    assert result.total_status is TotalStatus.PARTIAL
    assert any("post-departure" in a or "at or after departure" in a for a in result.abstained)


def test_preset_fills_field_and_runs():
    t = mk_ticket(scheduled_departure=datetime(2026, 1, 15, 18, 0, tzinfo=IST))
    req = preset_t_minus(t, 120)
    assert req.basis is TimeBasis.PRESET_T_MINUS
    assert req.preset_label == "T-120h"
    assert req.instant == datetime(2026, 1, 10, 18, 0, tzinfo=IST)

    res = ENGINE.evaluate(t, req)
    assert res.refund_total == Money.rupees("4720.00")
    assert res.basis is TimeBasis.PRESET_T_MINUS
