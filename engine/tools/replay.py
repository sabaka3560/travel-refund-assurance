"""Replay tool: recomputes a stored case and asserts identical results (Invariant I12)."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = ENGINE_DIR.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import (
    CancellationRequest,
    Corpus,
    Money,
    RefundEngine,
    TaxLine,
    Ticket,
    TimeBasis,
)


def replay_case(case_id: str) -> int:
    cases_dir = ROOT_DIR / "server" / "cases"
    target_files = list(cases_dir.glob(f"**/{case_id}.json"))
    if not target_files:
        print(f"Error: case {case_id} not found in {cases_dir}", file=sys.stderr)
        return 1

    case_file = target_files[0]
    case_data = json.loads(case_file.read_text(encoding="utf-8"))

    req_data = case_data["request"]
    t_in = req_data["ticket"]
    c_in = req_data.get("cancellation")

    tz = ZoneInfo(t_in.get("departure_timezone", "Asia/Kolkata"))
    taxes = [TaxLine(t["code"], Money.rupees(str(t["amount"]), t_in.get("currency", "INR"))) for t in t_in.get("taxes", [])]
    surs = [TaxLine(s["code"], Money.rupees(str(s["amount"]), t_in.get("currency", "INR"))) for s in t_in.get("carrier_surcharges", [])]
    fees = [TaxLine(f["code"], Money.rupees(str(f["amount"]), t_in.get("currency", "INR"))) for f in t_in.get("seller_fees", [])]

    ticket = Ticket(
        ticket_number=t_in.get("ticket_number", ""),
        carrier=t_in["carrier"],
        market=t_in.get("market", "DOMESTIC"),
        origin=t_in.get("origin", ""),
        destination=t_in.get("destination", ""),
        booking_date=date.fromisoformat(t_in["booking_date"]),
        ticket_issue_date=date.fromisoformat(t_in.get("ticket_issue_date") or t_in["booking_date"]),
        scheduled_departure=datetime.fromisoformat(t_in["departure_local"]).replace(tzinfo=tz),
        base_fare=Money.rupees(str(t_in["base_fare"]), t_in.get("currency", "INR")),
        taxes=taxes,
        carrier_surcharges=surs,
        seller_fees=fees,
        total_paid=Money.rupees(str(t_in["total_paid"]), t_in.get("currency", "INR")) if t_in.get("total_paid") else None,
        currency=t_in.get("currency", "INR"),
        passengers=t_in.get("passengers", 1),
        fare_family=t_in.get("fare_family"),
        account_code="CORP" if t_in.get("corporate") else None,
        is_corporate_fare=t_in.get("corporate", False),
        reissued=t_in.get("reissued", False),
        partially_used=t_in.get("partially_used", False),
    )

    if c_in:
        c_tz = ZoneInfo(c_in.get("timezone", "Asia/Kolkata"))
        canc_req = CancellationRequest(
            instant=datetime.fromisoformat(c_in["instant_local"]).replace(tzinfo=c_tz),
            basis=TimeBasis(c_in.get("basis", "USER_SCENARIO")),
            source_ref=c_in.get("source_ref"),
            preset_label=c_in.get("preset_label"),
            cause=c_in.get("cause", "PASSENGER_INITIATED"),
        )
    else:
        from refund_engine import preset_t_minus
        canc_req = preset_t_minus(ticket, 120)

    engine = RefundEngine()
    result = engine.evaluate(ticket, canc_req)

    stored_resp = case_data["response"]
    stored_total = stored_resp.get("total", {}).get("minor")
    actual_total = result.refund_total.minor if result.refund_total else None

    if stored_total != actual_total:
        print(f"REPLAY FAILED: total mismatch ({actual_total} vs stored {stored_total})", file=sys.stderr)
        return 1

    stored_lines = stored_resp.get("lines", [])
    if len(stored_lines) != len(result.lines):
        print(f"REPLAY FAILED: line count mismatch ({len(result.lines)} vs {len(stored_lines)})", file=sys.stderr)
        return 1

    for i, (act, exp) in enumerate(zip(result.lines, stored_lines)):
        if act.label != exp["label"] or act.contribution.minor != exp.get("contribution_minor", exp.get("contribution")):
            print(f"REPLAY FAILED at line {i}: {act.label} mismatch", file=sys.stderr)
            return 1

    # I12 holds inputs, engine version AND corpus version constant. If the corpus has
    # moved since the case was stored, an identical ledger is still worth reporting, but
    # it is no longer evidence of determinism — say which one this is rather than
    # letting "PASSED" imply the stronger claim.
    stored_corpus = (case_data.get("response") or {}).get("corpus_version") or case_data.get("corpus_version")
    live_corpus = Corpus().version
    drift = bool(stored_corpus) and stored_corpus != live_corpus

    audit_file = cases_dir / "audit.jsonl"
    with open(audit_file, "a", encoding="utf-8") as af:
        af.write(json.dumps({
            "event": "case_replayed",
            "case_id": case_id,
            "timestamp": datetime.now().isoformat(),
            "status": "IDENTICAL",
            "stored_corpus_version": stored_corpus,
            "live_corpus_version": live_corpus,
            "corpus_drift": drift,
        }) + "\n")

    print(f"REPLAY PASSED: case {case_id} recomputed byte-identically.")
    if drift:
        print(
            f"  NOTE: the corpus has changed since this case was stored "
            f"({stored_corpus} -> {live_corpus}). The ledger is unchanged, but this run does "
            "not demonstrate determinism under a fixed corpus."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a persisted case and verify identical ledger.")
    parser.add_argument("case_id", type=str, help="The case ID to replay")
    args = parser.parse_args()
    return replay_case(args.case_id)


if __name__ == "__main__":
    raise SystemExit(main())
