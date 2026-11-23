"""Acceptance tests for abstention, reconciliation, and scope limits.

Tests Invariants I8, I9, R8, R11, R12.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import pytest
import sys
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import Confidence, Corpus, Money, RefundEngine, TaxLine, Ticket, TotalStatus
from refund_engine.engine import preset_t_minus

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


def test_reconciliation_blocks():
    """Invariant I9: Components that do not sum to stated total block the case."""
    t = mk_ticket(total_paid=Money.rupees("9999.00"))  # stated 9999 vs components 8420
    r = ENGINE.evaluate(t, preset_t_minus(t, 120))
    assert r.confidence is Confidence.INSUFFICIENT
    assert r.refund_total is None
    assert r.total_status is TotalStatus.NONE
    assert any("Document does not reconcile" in a for a in r.abstained)


def test_scope_refusals():
    """R11: Scope conditions (passengers, reissue, partial use, currency)."""
    cases = [
        ("reissued", mk_ticket(reissued=True)),
        ("partially used", mk_ticket(partially_used=True)),
        ("multi-passenger", mk_ticket(passengers=2)),
        ("foreign currency", mk_ticket(currency="USD")),
    ]
    for name, t in cases:
        r = ENGINE.evaluate(t, preset_t_minus(t, 120))
        assert r.confidence is Confidence.INSUFFICIENT, f"Expected INSUFFICIENT for {name}"
        assert r.refund_total is None, f"Expected None refund for {name}"
        assert r.total_status is TotalStatus.NONE


def test_uncaptured_band_abstains():
    """Fee kind UNKNOWN must abstain rather than interpolating from adjacent bands.

    This used to point at Akasa's 24-72h band, which the corpus recorded as uncaptured.
    That was a gap in our transcription, not a property of the policy — the preserved
    copy states the fee plainly, and the rule was corrected on 2026-09-08. A test must
    not depend on the corpus staying incomplete, so it now points at the 2023 Akasa
    placeholder, whose amounts genuinely were never transcribed.
    """
    t = mk_ticket(
        carrier="QP",
        fare_family="SAVER",
        booking_date=date(2024, 6, 1),
        scheduled_departure=datetime(2024, 7, 1, 9, 0, tzinfo=IST),
    )
    r = ENGINE.evaluate(t, preset_t_minus(t, 120))
    assert r.rule_id == "QP-DOM-OBS-20230401", r.rule_id
    assert any("never captured" in a or "uncaptured" in a for a in r.abstained), r.abstained
    # the statutory line still pays out — abstention is per line, not per case
    assert r.refund_total is not None
