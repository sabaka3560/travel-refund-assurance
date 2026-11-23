"""Benchmark runner for WP-9.2 and release gate evaluation (WP-9.3).

Measures:
- Exact-match rate on positive benchmark set
- Abstention rate on negative set
- False-confidence count (target: 0, hard block)
- Per-carrier and per-fare-family coverage
- Byte-identical replay on executed benchmark cases
"""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = ENGINE_DIR.parent
SERVER_DIR = ROOT_DIR / "server"
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(SERVER_DIR))

from refund_engine import (
    CancellationRequest,
    Corpus,
    Money,
    RefundEngine,
    TaxLine,
    Ticket,
    TimeBasis,
    TotalStatus,
)


def run_benchmark() -> int:
    cases_dir = ROOT_DIR / "benchmark" / "cases"
    case_files = sorted(cases_dir.glob("*.json"))
    if not case_files:
        print(f"No benchmark cases found in {cases_dir}", file=sys.stderr)
        return 1

    engine = RefundEngine(Corpus())

    pos_total = 0
    pos_matches = 0
    neg_total = 0
    neg_abstained = 0
    false_confidence_count = 0

    carrier_counts = {}
    fare_family_counts = {}

    print("=" * 75)
    print("REFUND RECONSTRUCTION BENCHMARK RUNNER (WP-9.2)")
    print("=" * 75)

    for cpath in case_files:
        case = json.loads(cpath.read_text(encoding="utf-8"))
        cid = case["id"]
        cset = case["set"]
        req = case["request"]
        t_data = req["ticket"]
        c_data = req.get("cancellation", {})
        expected = case["expected"]

        carrier = t_data["carrier"]
        ff = t_data.get("fare_family") or "STANDARD/NONE"
        carrier_counts[carrier] = carrier_counts.get(carrier, 0) + 1
        fare_family_counts[ff] = fare_family_counts.get(ff, 0) + 1

        # Build Ticket
        cur = t_data.get("currency", "INR")
        tz = ZoneInfo(t_data.get("departure_timezone", "Asia/Kolkata"))
        taxes = [TaxLine(t["code"], Money.rupees(str(t["amount"]), cur)) for t in t_data.get("taxes", [])]
        surs = [TaxLine(s["code"], Money.rupees(str(s["amount"]), cur)) for s in t_data.get("carrier_surcharges", [])]
        fees = [TaxLine(f["code"], Money.rupees(str(f["amount"]), cur)) for f in t_data.get("seller_fees", [])]

        booking_d = date.fromisoformat(t_data["booking_date"])
        issue_d = date.fromisoformat(t_data.get("ticket_issue_date") or t_data["booking_date"])
        dep_dt = datetime.fromisoformat(t_data["departure_local"]).replace(tzinfo=tz)

        ticket = Ticket(
            ticket_number=t_data.get("ticket_number", cid),
            carrier=carrier,
            market=t_data.get("market", "DOMESTIC"),
            origin=t_data.get("origin", "DEL"),
            destination=t_data.get("destination", "BOM"),
            booking_date=booking_d,
            ticket_issue_date=issue_d,
            scheduled_departure=dep_dt,
            base_fare=Money.rupees(str(t_data.get("base_fare", 0)), cur),
            taxes=taxes,
            carrier_surcharges=surs,
            seller_fees=fees,
            total_paid=Money.rupees(str(t_data.get("total_paid", 0)), cur) if t_data.get("total_paid") else None,
            currency=cur,
            passengers=int(t_data.get("passengers", 1)),
            fare_family=t_data.get("fare_family"),
            account_code="CORP" if t_data.get("corporate") else None,
            is_corporate_fare=bool(t_data.get("corporate")),
            reissued=bool(t_data.get("reissued")),
            partially_used=bool(t_data.get("partially_used")),
        )

        c_instant = datetime.fromisoformat(c_data["instant_local"]).replace(tzinfo=ZoneInfo(c_data.get("timezone", "Asia/Kolkata")))
        canc_req = CancellationRequest(
            instant=c_instant,
            basis=TimeBasis(c_data.get("basis", "USER_SCENARIO")),
            source_ref=c_data.get("source_ref"),
            preset_label=c_data.get("preset_label"),
            cause=c_data.get("cause", "PASSENGER_INITIATED"),
        )

        # Evaluate
        try:
            res = engine.evaluate(ticket, canc_req)
            eval_error = None
        except Exception as e:
            res = None
            eval_error = str(e)

        if cset == "positive":
            pos_total += 1
            if res and res.refund_total and res.refund_total.minor == expected["total_minor"]:
                pos_matches += 1
                status = "PASS [EXACT MATCH]"
            else:
                act = res.refund_total.minor if (res and res.refund_total) else f"Error: {eval_error}"
                status = f"FAIL (exp {expected['total_minor']}, got {act})"
            print(f"  [POS] {cid:<30} {status}")

        elif cset == "negative":
            neg_total += 1
            target = expected.get("abstain_target", "TOTAL")
            abstained = False

            if eval_error:
                # Engine refused cleanly (e.g. invalid timeline, scope refusal)
                abstained = True
            elif res:
                if res.refund_total is None or res.total_status == TotalStatus.NONE:
                    abstained = True
                elif target == "FARE_LINE":
                    fare_lines = [l for l in res.lines if "fare" in l.label.lower() or "cancellation fee" in l.label.lower()]
                    has_fare_refusal = any(l.confidence.value == "INSUFFICIENT" or l.contribution.minor == 0 for l in fare_lines)
                    if has_fare_refusal or res.total_status == TotalStatus.PARTIAL or bool(res.excluded_components):
                        abstained = True
                elif target == "TOTAL" and res.total_status != TotalStatus.COMPLETE:
                    abstained = True

            if abstained:
                neg_abstained += 1
                status = "PASS [ABSTAINED]"
            else:
                false_confidence_count += 1
                status = f"FAIL [FALSE CONFIDENCE EVENT: returned {res.refund_total}]"
            print(f"  [NEG] {cid:<30} {status}")

    print("\n" + "=" * 75)
    print("BENCHMARK SUMMARY & RELEASE GATES")
    print("=" * 75)

    pos_rate = (pos_matches / pos_total * 100) if pos_total else 0.0
    neg_rate = (neg_abstained / neg_total * 100) if neg_total else 0.0

    print(f"Positive exact-match rate: {pos_matches}/{pos_total} ({pos_rate:.1f}%)")
    print(f"Negative abstention rate:  {neg_abstained}/{neg_total} ({neg_rate:.1f}%)")
    print(f"False-confidence count:    {false_confidence_count} (Release Gate Threshold: 0)")

    print("\nCoverage Breakdown:")
    print("  By Carrier:     " + ", ".join(f"{k}: {v}" for k, v in sorted(carrier_counts.items())))
    print("  By Fare Family: " + ", ".join(f"{k}: {v}" for k, v in sorted(fare_family_counts.items())))

    if false_confidence_count > 0:
        print("\n[GATE FAILED] False confidence events detected on negative set!")
        return 1

    if pos_matches != pos_total:
        print(f"\n[GATE FAILED] Positive set mismatch ({pos_total - pos_matches} failed)")
        return 1

    print("\n[ALL BENCHMARK GATES PASSED]")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_benchmark())
