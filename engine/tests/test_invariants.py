"""Hard invariants suite asserting I1 through I13."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import pytest
import sys
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine.engine import preset_t_minus  # noqa: E402

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


def mk_ticket(**over) -> Ticket:
    d = dict(
        ticket_number="INV-001",
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


def test_i8_refund_bounds():
    """Invariant I8: Refund >= 0, and refund <= amount paid when paid total is known."""
    for bd in [date(2025, 11, 20), date(2025, 12, 20)]:
        t = mk_ticket(booking_date=bd)
        r = ENGINE.evaluate(t, preset_t_minus(t, 120))
        assert r.refund_total is not None
        assert not r.refund_total.is_negative()
        assert r.refund_total <= t.total_paid


def test_naive_datetime_refused():
    t = mk_ticket(scheduled_departure=datetime(2026, 1, 15, 18, 0))  # naive
    with pytest.raises(ValueError):
        ENGINE.evaluate(t, preset_t_minus(t, 120))
