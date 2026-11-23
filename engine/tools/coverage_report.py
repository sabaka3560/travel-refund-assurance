"""Compute coverage report directly from the corpus (R15).

Replaces arbitrary claimed percentages with honest (carrier x fare_family x market)
supported date intervals, ceilings, and identified gaps.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import Corpus


def generate_coverage(corpus: Corpus = None) -> dict:
    c = corpus or Corpus()
    coverage_rows = []

    for r in c.rules:
        start_date = (r.stated_from or r.observed_from or "").isoformat() if (r.stated_from or r.observed_from) else None
        end_date = (r.stated_to or r.observed_to or "").isoformat() if (r.stated_to or r.observed_to) else None
        obs_through = c.carrier_observed_through.get(r.carrier)
        obs_str = obs_through.isoformat() if obs_through else None

        coverage_rows.append({
            "policy_id": r.policy_id,
            "carrier": r.carrier,
            "carrier_name": c.carriers.get(r.carrier, {}).get("name", r.carrier),
            "market": r.market,
            "fare_families": r.fare_families,
            "date_basis": r.date_basis,
            "applicability_key": r.applicability_key,
            "valid_from": start_date,
            "valid_to": end_date,
            "observed_through": obs_str,
            "ceiling": r.ceiling.value,
            "rule_source_class": r.rule_source_class,
            "disputed": r.disputed,
            "caveats": r.caveats,
        })

    # Summary per carrier
    carrier_summary = {}
    for code, info in c.carriers.items():
        rules_for_carrier = [r for r in coverage_rows if r["carrier"] == code]
        dates = [r["valid_from"] for r in rules_for_carrier if r["valid_from"]]
        earliest = min(dates) if dates else "None"
        latest = max(dates) if dates else "None"
        carrier_summary[code] = {
            "name": info.get("name", code),
            "pss": info.get("pss", "Unknown"),
            "rules_count": len(rules_for_carrier),
            "earliest_evidence": earliest,
            "latest_evidence": latest,
            "quarantined_count": len([q for q in c.quarantined if q.get("policy_id", "").startswith(code)]),
        }

    return {
        "corpus_version": c.version,
        "carriers": carrier_summary,
        "rules_coverage": coverage_rows,
        "quarantined": c.quarantined,
    }


def main():
    data = generate_coverage()
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
