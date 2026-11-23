"""Generate golden outputs for the 11 UI sample tickets from server/static/index.html.

Used to freeze engine outputs before refactoring (WP-0) and to detect drift.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import sys
ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import Money, RefundEngine, TaxLine, Ticket

IST = ZoneInfo("Asia/Kolkata")
GOLDEN_DIR = ENGINE_DIR / "tests" / "golden"

SAMPLES = [
    {
        "id": "sg-before",
        "label": "Booked BEFORE the 12-Dec-2025 rule change",
        "car": "SG",
        "ff": "SAVER",
        "route": "DEL→BOM",
        "bk": "2025-11-20",
        "dep": "2026-01-15T18:00",
        "base": 6700,
        "k3": 352,
        "udf": 708,
        "psf": 160,
        "yr": 250,
        "fee": 250,
        "tot": 8420,
    },
    {
        "id": "sg-after",
        "label": "Identical ticket, booked AFTER the change",
        "car": "SG",
        "ff": "SAVER",
        "route": "DEL→BOM",
        "bk": "2025-12-20",
        "dep": "2026-01-15T18:00",
        "base": 6700,
        "k3": 352,
        "udf": 708,
        "psf": 160,
        "yr": 250,
        "fee": 250,
        "tot": 8420,
    },
    {
        "id": "ai-flex",
        "label": "Air India Flex — evidence horizon reached, fare line abstains",
        "car": "AI",
        "ff": "ECONOMY_FLEX",
        "route": "DEL→BOM",
        "bk": "2026-06-01",
        "dep": "2026-09-20T08:15",
        "base": 8900,
        "k3": 445,
        "udf": 708,
        "psf": 160,
        "yr": 0,
        "fee": 0,
        "tot": 10213,
    },
    {
        "id": "qp-flexi",
        "label": "Akasa Flexi — preserved copy predates the stated date, so LOW",
        "car": "QP",
        "ff": "FLEXI",
        "route": "BLR→BOM",
        "bk": "2026-06-10",
        "dep": "2026-09-25T14:40",
        "base": 4800,
        "k3": 240,
        "udf": 560,
        "psf": 0,
        "yr": 0,
        "fee": 0,
        "tot": 5600,
    },
    {
        "id": "6e",
        "label": "IndiGo — table has no fare-family dimension",
        "car": "6E",
        "ff": "",
        "route": "DEL→BLR",
        "bk": "2025-10-15",
        "dep": "2026-01-20T06:20",
        "base": 5400,
        "k3": 270,
        "udf": 708,
        "psf": 0,
        "yr": 0,
        "fee": 0,
        "tot": 6378,
    },
    {
        "id": "ix",
        "label": "AI Express Classic — single undated capture, fare line abstains",
        "car": "IX",
        "ff": "CLASSIC",
        "route": "BLR→COK",
        "bk": "2026-07-01",
        "dep": "2026-10-15T11:05",
        "base": 3400,
        "k3": 170,
        "udf": 560,
        "psf": 0,
        "yr": 0,
        "fee": 0,
        "tot": 4130,
    },
    {
        "id": "qp-gap",
        "label": "Akasa Saver — 24-72h band, capped at 100% of airfare",
        "car": "QP",
        "ff": "SAVER",
        "route": "PNQ→DEL",
        "bk": "2026-03-01",
        "dep": "2026-04-20T19:30",
        "base": 6200,
        "k3": 310,
        "udf": 460,
        "psf": 0,
        "yr": 0,
        "fee": 0,
        "tot": 6970,
    },
    {
        "id": "ai-noff",
        "label": "Fare family not printed — partial answer",
        "car": "AI",
        "ff": "",
        "route": "DEL→BLR",
        "bk": "2026-05-01",
        "dep": "2026-08-18T18:00",
        "base": 6700,
        "k3": 352,
        "udf": 708,
        "psf": 160,
        "yr": 0,
        "fee": 0,
        "tot": 7920,
    },
    {
        "id": "ai-value",
        "label": "Air India Value — statute still applies, fare line abstains",
        "car": "AI",
        "ff": "ECONOMY_VALUE",
        "route": "BOM→DEL",
        "bk": "2026-05-01",
        "dep": "2026-08-18T09:00",
        "base": 5200,
        "k3": 270,
        "udf": 708,
        "psf": 160,
        "yr": 0,
        "fee": 0,
        "tot": 6338,
    },
    {
        "id": "corp",
        "label": "Corporate negotiated fare — statutory PARTIAL, agreement needed",
        "car": "SG",
        "ff": "SAVER",
        "route": "DEL→BOM",
        "bk": "2026-01-10",
        "dep": "2026-04-01T18:00",
        "base": 6700,
        "k3": 352,
        "udf": 708,
        "psf": 160,
        "yr": 0,
        "fee": 0,
        "tot": 7920,
        "corp": True,
    },
    {
        "id": "reissue",
        "label": "Reissued ticket — must refuse",
        "car": "SG",
        "ff": "SAVER",
        "route": "DEL→BOM",
        "bk": "2026-01-10",
        "dep": "2026-04-01T18:00",
        "base": 6700,
        "k3": 352,
        "udf": 708,
        "psf": 160,
        "yr": 0,
        "fee": 0,
        "tot": 7920,
        "reis": True,
    },
]


def sample_to_ticket(s: dict) -> Ticket:
    taxes = [
        TaxLine(c, Money.rupees(f"{v:.2f}", "INR"))
        for c, v in [("K3", s.get("k3", 0)), ("UDF", s.get("udf", 0)), ("PSF", s.get("psf", 0))]
        if v > 0
    ]
    surs = [TaxLine("YR", Money.rupees(f"{s['yr']:.2f}", "INR"))] if s.get("yr", 0) > 0 else []
    fees = [TaxLine("AGENCY", Money.rupees(f"{s['fee']:.2f}", "INR"))] if s.get("fee", 0) > 0 else []

    route = s.get("route", "")
    origin = route.split("→")[0].strip() if "→" in route else route[:3]
    destination = route.split("→")[-1].strip() if "→" in route else ""

    return Ticket(
        ticket_number=route or "sample",
        carrier=s["car"],
        market="DOMESTIC",
        origin=origin,
        destination=destination,
        booking_date=date.fromisoformat(s["bk"]),
        ticket_issue_date=date.fromisoformat(s["bk"]),
        scheduled_departure=datetime.fromisoformat(s["dep"]).replace(tzinfo=IST),
        base_fare=Money.rupees(f"{s['base']:.2f}", "INR"),
        taxes=taxes,
        carrier_surcharges=surs,
        seller_fees=fees,
        total_paid=Money.rupees(f"{s['tot']:.2f}", "INR") if s.get("tot") is not None else None,
        currency="INR",
        passengers=1,
        fare_family=s.get("ff") or None,
        account_code="CORP" if s.get("corp") else None,
        is_corporate_fare=s.get("corp") or None,
        reissued=bool(s.get("reis")),
        partially_used=bool(s.get("part")),
    )


def generate_goldens():
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    engine = RefundEngine()

    for s in SAMPLES:
        t = sample_to_ticket(s)
        # Check evaluate signature to support both baseline (evaluate(t)) and WP-1+ (evaluate(t, req))
        try:
            r = engine.evaluate(t)
        except TypeError:
            from refund_engine import preset_t_minus
            r = engine.evaluate(t, preset_t_minus(t, 120))

        golden = {
            "case_id": s["id"],
            "label": s["label"],
            "rule_id": r.rule_id,
            "refund_minor": None if r.refund_total is None else r.refund_total.minor,
            "refund_formatted": None if r.refund_total is None else str(r.refund_total),
            "confidence": r.confidence.value,
            "lines": [
                {
                    "label": l.label,
                    "contribution_minor": l.contribution.minor,
                    "contribution_formatted": str(l.contribution),
                    "confidence": l.confidence.value,
                }
                for l in r.lines
            ],
            "abstained": r.abstained,
            "warnings": r.warnings,
        }

        out_path = GOLDEN_DIR / f"{s['id']}.json"
        out_path.write_text(json.dumps(golden, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    generate_goldens()
