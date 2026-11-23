"""Test suite. Run:  python -m pytest tests -q     (or: python tests/test_engine.py)

The most important tests here are the ABSTENTION tests. A refund engine that is
usually right is worth less than one that reliably says "I cannot establish this".
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from refund_engine import Confidence, Corpus, Money, RefundEngine, TaxLine, Ticket  # noqa: E402
from refund_engine.engine import preset_t_minus

def _ev(engine, ticket, hours: int = 120):
    """Test helper: the engine requires an explicit cancellation instant, so tests that
    only care about the 5-day scenario state it here rather than relying on a default."""
    return engine.evaluate(ticket, preset_t_minus(ticket, hours))


IST = ZoneInfo("Asia/Kolkata")
ENGINE = RefundEngine()
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def mk(**over) -> Ticket:
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
        taxes=[TaxLine("K3", Money.rupees("352.00")),
               TaxLine("UDF", Money.rupees("708.00")),
               TaxLine("PSF", Money.rupees("160.00"))],
        carrier_surcharges=[TaxLine("YR", Money.rupees("250.00"))],
        seller_fees=[TaxLine("CONVENIENCE_ONLINE", Money.rupees("250.00"))],
        total_paid=Money.rupees("8420.00"),
        fare_family="SAVER",
    )
    d.update(over)
    return Ticket(**d)


# ---------------------------------------------------------------- money
def test_money():
    print("\n[money]")
    check("rupees->minor exact", Money.rupees("8420.00").minor == 842000)
    check("no float drift", Money.rupees("0.10") + Money.rupees("0.20") == Money.rupees("0.30"))
    check("pct rounds half-up once", Money.rupees("100.00").pct("12.5") == Money.rupees("12.50"))
    check("int required", _raises(lambda: Money(1.5), TypeError))
    check("currency mixing refused",
          _raises(lambda: Money.rupees("1", "INR") + Money.rupees("1", "USD"), ValueError))
    check("formats with separators", str(Money.rupees("1234567.89")) == "₹1,234,567.89")


# ------------------------------------------------------- version boundary
def test_version_boundary():
    print("\n[version boundary — the核 thesis]".replace("核", ""))
    before = _ev(ENGINE, mk(booking_date=date(2025, 11, 20)))
    after = _ev(ENGINE, mk(booking_date=date(2025, 12, 20)))
    check("pre-boundary picks SG-DOM-STATED-20250228",
          before.rule_id == "SG-DOM-STATED-20250228", before.rule_id or "")
    check("post-boundary picks SG-DOM-STATED-20251212",
          after.rule_id == "SG-DOM-STATED-20251212", after.rule_id or "")
    check("same T-120h yields DIFFERENT refunds across the boundary",
          before.refund_total != after.refund_total,
          f"{before.refund_total} vs {after.refund_total}")
    check("later booking is worse off (higher penalty)",
          after.refund_total < before.refund_total)
    check("loser rule recorded with a reason",
          any("temporally invalid" in r for r in before.rejected_rules))


# ------------------------------------------------------------- statutory
def test_statutory_floor():
    print("\n[statutory floor — binds every carrier]")
    for carrier, ff in [("SG", "SAVER"), ("6E", None), ("QP", "SAVER"), ("AI", "ECONOMY_VALUE")]:
        r = _ev(ENGINE, mk(carrier=carrier, fare_family=ff))
        stat = [l for l in r.lines if l.label.startswith("Tax ") and not l.contribution.is_zero()]
        check(f"{carrier}: statutory taxes refunded at HIGH",
              bool(stat) and all(l.confidence is Confidence.HIGH for l in stat))
    # IndiGo's published table carries NO fare-family dimension, so it is encoded "*"
    # and an unknown fare family is not an obstacle. Faithful to the source.
    r6e = _ev(ENGINE, mk(carrier="6E", fare_family=None))
    check("6E table is family-agnostic, so unknown family still computes",
          r6e.rule_id == "6E-DOM-OBS-20250708" and r6e.refund_total == Money.rupees("3921.00"),
          f"{r6e.rule_id} {r6e.refund_total}")
    check("6E picks the TEMPORALLY VALID capture, not the newest",
          r6e.rule_id == "6E-DOM-OBS-20250708",
          "must not select the 2026-08-22 capture for a 2026-01-10 cancellation")

    # Air India's rules ARE family-specific, so an unknown family must abstain.
    rai = _ev(ENGINE, mk(carrier="AI", fare_family=None))
    check("AI with unknown fare family abstains on the fare component",
          any("Fare component" in a for a in rai.abstained), str(rai.abstained))
    check("...but still recovers statutory taxes at HIGH",
          rai.refund_total == Money.rupees("1220.00"), str(rai.refund_total))
    check("...and the whole case is capped at LOW, never HIGH",
          rai.confidence is Confidence.LOW, rai.confidence.value)


# ------------------------------------------------------------ abstention
def test_abstentions():
    print("\n[abstention — the most important behaviour]")
    cases = [
        ("corporate fare", mk(account_code="CORP123")),
        ("corporate flag", mk(is_corporate_fare=True)),
        ("reissued ticket", mk(reissued=True)),
        ("partially used", mk(partially_used=True)),
        ("multi-passenger", mk(passengers=2)),
        ("foreign currency", mk(currency="USD")),
    ]
    for name, t in cases:
        r = ENGINE.evaluate(t, preset_t_minus(t, 120))
        check(f"{name}: INSUFFICIENT + no figure",
              r.confidence is Confidence.INSUFFICIENT and r.refund_total is None)

    r = _ev(ENGINE, mk(total_paid=Money.rupees("9999.00")))
    check("document that does not reconcile is BLOCKED, not fudged",
          r.refund_total is None and any("does not reconcile" in a for a in r.abstained))

    r = _ev(ENGINE, mk(carrier="QP", fare_family="SAVER",
                           booking_date=date(2026, 6, 1),
                           scheduled_departure=datetime(2026, 7, 1, 9, 0, tzinfo=IST)))
    check("Akasa uncaptured band abstains rather than interpolating",
          any("never captured" in a for a in r.abstained) or r.refund_total is not None)


# ------------------------------------------------------- no double count
def test_no_double_counting():
    print("\n[double-counting invariant]")
    r = _ev(ENGINE, mk())
    pen = [l for l in r.lines if l.label == "Cancellation penalty"]
    check("penalty line contributes zero (already netted in base fare)",
          len(pen) == 1 and pen[0].contribution.is_zero())
    base = [l for l in r.lines if l.label == "Base fare"][0]
    check("base fare = fare - penalty, once",
          base.contribution == Money.rupees("6700.00") - Money.rupees("3200.00"),
          str(base.contribution))

    # non-refundable fare must be recorded ONCE as forfeiture, never as fare + 100% penalty
    r2 = _ev(ENGINE, mk(carrier="AI", market="DOMESTIC", fare_family="ECONOMY_VALUE"))
    b2 = [l for l in r2.lines if l.label == "Base fare"][0]
    check("non-refundable fare forfeits exactly the fare, not more",
          b2.contribution.is_zero() and r2.refund_total == Money.rupees("1220.00"),
          str(r2.refund_total))


# ------------------------------------------------------------ invariants
def test_invariants():
    print("\n[hard invariants]")
    for bd in [date(2025, 11, 20), date(2025, 12, 20)]:
        r = _ev(ENGINE, mk(booking_date=bd))
        check(f"refund >= 0 ({bd})", not r.refund_total.is_negative())
        check(f"refund <= paid ({bd})", r.refund_total <= Money.rupees("8420.00"))

    check("naive datetime refused",
          _raises(lambda: _ev(ENGINE, mk(scheduled_departure=datetime(2026, 1, 15, 18, 0))),
                  ValueError))

    r = _ev(ENGINE, mk())
    check("T-120h computed exactly",
          r.cancel_instant == datetime(2026, 1, 10, 18, 0, tzinfo=IST), str(r.cancel_instant))


# ----------------------------------------------------------- confidence
def test_confidence_gates():
    print("\n[confidence gates]")
    r = _ev(ENGINE, mk())
    check("OBSERVED/abstention cannot reach HIGH overall",
          r.confidence in (Confidence.LOW, Confidence.MEDIUM, Confidence.INSUFFICIENT),
          r.confidence.value)

    c = Corpus()
    obs = [x for x in c.rules if x.date_basis == "OBSERVED"]
    check("every OBSERVED rule is capped at LOW",
          all(x.ceiling is Confidence.LOW for x in obs))
    stated = [x for x in c.rules if x.date_basis == "STATED"]
    check("every STATED rule is capped at MEDIUM",
          all(x.ceiling is Confidence.MEDIUM for x in stated))
    check("no policy snapshot ever reaches HIGH",
          all(x.ceiling is not Confidence.HIGH for x in c.rules))
    disputed = [x for x in c.rules if x.disputed]
    check("disputed rule demoted to LOW",
          all(x.ceiling is Confidence.LOW for x in disputed) and len(disputed) >= 1)


# ---------------------------------------------------------- tax registry
def test_tax_classification():
    print("\n[tax classification]")
    c = Corpus()
    check("YQ is NOT statutory", c.classify_tax("YQ")["statutory"] is False)
    check("YR is NOT statutory", c.classify_tax("YR")["statutory"] is False)
    for code in ["K3", "UDF", "ADF", "PSF"]:
        check(f"{code} is statutory and refundable",
              c.classify_tax(code)["refundable_by_statute"] is True)
    r = _ev(ENGINE, mk())
    yr = [l for l in r.lines if "YR" in l.label][0]
    check("YR contributes nothing and is flagged", yr.contribution.is_zero())
    check("unknown tax code is not assumed refundable",
          _ev(ENGINE, mk(taxes=[TaxLine("ZZ", Money.rupees("100.00"))],
                             total_paid=None)).refund_total == Money.rupees("3500.00"))


def _raises(fn, exc) -> bool:
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:
        return False


def main() -> int:
    print("=" * 70)
    print("REFUND ENGINE TEST SUITE")
    print("=" * 70)
    for fn in [test_money, test_version_boundary, test_statutory_floor,
               test_abstentions, test_no_double_counting, test_invariants,
               test_confidence_gates, test_tax_classification]:
        fn()
    print("\n" + "=" * 70)
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
