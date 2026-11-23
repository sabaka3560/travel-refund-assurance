#!/usr/bin/env python3
"""Run the engine over a ticket JSON file.

    python cli.py samples/6e_domestic.json
    python cli.py --corpus-info
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows consoles default to cp1252 and cannot encode the rupee sign.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from refund_engine import Corpus, Money, RefundEngine, TaxLine, Ticket  # noqa: E402
from refund_engine.engine import preset_t_minus
from refund_engine.report import render  # noqa: E402


def load_ticket(path: Path) -> Ticket:
    d = json.loads(path.read_text(encoding="utf-8"))
    cur = d.get("currency", "INR")
    tz = ZoneInfo(d.get("departure_timezone", "Asia/Kolkata"))
    dep = datetime.fromisoformat(d["scheduled_departure"]).replace(tzinfo=tz)

    def lines(key):
        return [TaxLine(code=x["code"], amount=Money.rupees(x["amount"], cur))
                for x in d.get(key, [])]

    return Ticket(
        ticket_number=d["ticket_number"],
        carrier=d["carrier"],
        market=d.get("market", "DOMESTIC"),
        origin=d["origin"],
        destination=d["destination"],
        booking_date=date.fromisoformat(d["booking_date"]),
        ticket_issue_date=date.fromisoformat(d.get("ticket_issue_date", d["booking_date"])),
        scheduled_departure=dep,
        base_fare=Money.rupees(d["base_fare"], cur),
        taxes=lines("taxes"),
        carrier_surcharges=lines("carrier_surcharges"),
        seller_fees=lines("seller_fees"),
        total_paid=Money.rupees(d["total_paid"], cur) if "total_paid" in d else None,
        currency=cur,
        passengers=d.get("passengers", 1),
        fare_family=d.get("fare_family"),
        fare_basis=d.get("fare_basis"),
        booking_class=d.get("booking_class"),
        account_code=d.get("account_code"),
        is_corporate_fare=d.get("is_corporate_fare"),
        reissued=d.get("reissued", False),
        partially_used=d.get("partially_used", False),
    )


def corpus_info() -> None:
    c = Corpus()
    print(f"Corpus version : {c.version}")
    print(f"Policy rules   : {len(c.rules)}")
    names = ", ".join("{} ({})".format(k, v["name"]) for k, v in c.carriers.items())
    print("Carriers       : " + names)
    print(f"Tax codes      : {len(c.tax_codes)}")
    print()
    print(f"{'RULE ID':<34}{'BASIS':<10}{'KEY':<15}{'CEILING':<9}BANDS")
    print("-" * 88)
    for r in sorted(c.rules, key=lambda x: x.policy_id):
        print(f"{r.policy_id:<34}{r.date_basis:<10}{r.applicability_key:<15}"
              f"{r.ceiling.value:<9}{len(r.bands)}")
    print()
    stated = sum(1 for r in c.rules if r.date_basis == "STATED")
    print(f"{stated}/{len(c.rules)} rules carry a carrier-stated effective date. "
          "The rest are OBSERVED-only and capped at LOW confidence.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Historical refund reconstruction engine")
    ap.add_argument("ticket", nargs="?", type=Path)
    ap.add_argument("--corpus-info", action="store_true")
    ap.add_argument("--json", action="store_true", help="emit machine-readable result")
    a = ap.parse_args()

    if a.corpus_info:
        corpus_info()
        return 0
    if not a.ticket:
        ap.print_help()
        return 2

    result = RefundEngine().evaluate(_t := load_ticket(a.ticket), preset_t_minus(_t, 120))

    if a.json:
        print(json.dumps({
            "ticket_number": result.ticket_number,
            "cancel_instant": result.cancel_instant.isoformat(),
            "refund_total_minor": None if result.refund_total is None else result.refund_total.minor,
            "refund_total": None if result.refund_total is None else str(result.refund_total),
            "confidence": result.confidence.value,
            "rule_id": result.rule_id,
            "abstained": result.abstained,
            "warnings": result.warnings,
            "lines": [{"label": l.label,
                       "original_minor": None if l.original is None else l.original.minor,
                       "contribution_minor": l.contribution.minor,
                       "confidence": l.confidence.value,
                       "basis": l.basis} for l in result.lines],
        }, indent=2))
    else:
        print(render(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
