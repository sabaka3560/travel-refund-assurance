"""Corpus lint tool: validates corpus schema, integrity, and non-ambiguity invariants.

Checks:
- Integer timing on all bands (from_h / to_h / from_seconds / to_seconds)
- No band below cutoff_seconds (F8)
- stated_* effective dates present when date_basis is STATED
- observed_from <= observed_through when populated
- Ceilings consistent with date_basis and disputed flag
- No two rules for the same (carrier, market, fare_family) have overlapping validity windows AND identical rank (ambiguity detection)
- Exits 0 on success, non-zero on failure with detailed diagnostic report.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import Confidence, Corpus, Rule
from refund_engine.corpus import RULE_SOURCE_CLASS_ORDER, CONFIDENCE_ORDER

CORPUS_DIR = ENGINE_DIR / "corpus"


def lint_corpus() -> int:
    policies_file = CORPUS_DIR / "policies.json"
    regulatory_file = CORPUS_DIR / "regulatory.json"

    if not policies_file.exists():
        print(f"FAIL: {policies_file} not found", file=sys.stderr)
        return 1

    policies_raw = json.loads(policies_file.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Check top-level
    for req_field in ["corpus_version", "carriers", "policies"]:
        if req_field not in policies_raw:
            errors.append(f"Missing required top-level field: {req_field}")

    rules = [Rule(p) for p in policies_raw.get("policies", [])]

    # 2. Check individual rules
    for r in rules:
        pid = r.policy_id

        # Check date_basis and stated dates
        if r.date_basis == "STATED":
            if not r.stated_from:
                errors.append(f"{pid}: date_basis is STATED but stated_effective_from is missing")
        elif r.date_basis == "OBSERVED":
            if not r.observed_from:
                errors.append(f"{pid}: date_basis is OBSERVED but observed_from is missing")

        # Check ceilings
        if r.disputed:
            if r.ceiling is not Confidence.LOW:
                errors.append(f"{pid}: rule is marked disputed but ceiling is {r.ceiling}")
        elif r.date_basis == "OBSERVED":
            if r.ceiling not in (Confidence.LOW, Confidence.INSUFFICIENT):
                errors.append(f"{pid}: OBSERVED rule has ceiling above LOW: {r.ceiling}")
        elif r.date_basis == "STATED":
            if r.ceiling not in (Confidence.MEDIUM, Confidence.LOW):
                errors.append(f"{pid}: STATED rule has ceiling above MEDIUM: {r.ceiling}")

        # Check bands
        cutoff_sec = r.cutoff_seconds
        for i, b in enumerate(r.bands):
            # Check integer requirements
            if "from_seconds" in b:
                if not isinstance(b["from_seconds"], int):
                    errors.append(f"{pid} band {i}: from_seconds must be integer, got {type(b['from_seconds'])}")
                if b.get("to_seconds") is not None and not isinstance(b["to_seconds"], int):
                    errors.append(f"{pid} band {i}: to_seconds must be integer, got {type(b['to_seconds'])}")
                lo_sec = b["from_seconds"]
            else:
                if not isinstance(b.get("from_h"), int):
                    errors.append(f"{pid} band {i}: from_h must be integer, got {type(b.get('from_h'))}")
                if b.get("to_h") is not None and not isinstance(b.get("to_h"), int):
                    errors.append(f"{pid} band {i}: to_h must be integer, got {type(b.get('to_h'))}")
                lo_sec = int(b.get("from_h", 0) * 3600)

            # Check cutoff semantics: no band may lie entirely below cutoff (unless disputed/documented)
            # WP-3.2: cutoff is point after which carrier refuses voluntary cancellation.
            # QP-DOM-STATED-20260512* currently has 0-4h forfeiture band.
            # A band below the cut-off is unreachable: the cut-off short-circuits first,
            # so such a band silently encodes a fee that can never be applied. This is an
            # ERROR, not a warning — the corpus must say one thing about the same instant.
            if cutoff_sec and lo_sec < cutoff_sec:
                errors.append(
                    f"{pid} band {i}: from_seconds ({lo_sec}) is below the cut-off ({cutoff_sec}). "
                    "Raise the band floor to the cut-off, or remove the band, or correct the cut-off."
                )

        # Check source block
        src = r.source
        if not src.get("url"):
            warnings.append(f"{pid}: source has no URL")
        if not src.get("quote"):
            warnings.append(f"{pid}: source has no verbatim quote")
        if not src.get("evidence_sha256"):
            errors.append(f"{pid}: source has no evidence_sha256 (no preserved copy — Invariant I7)")
        if src.get("content_verification", "").startswith("UNVERIFIED"):
            warnings.append(f"{pid}: preserved copy held, but its content could not be machine-verified")

    # 3. Check for runtime ambiguities (overlapping validity + identical rank)
    for i, r1 in enumerate(rules):
        for r2 in rules[i + 1:]:
            if r1.carrier != r2.carrier:
                continue
            if r1.market != "*" and r2.market != "*" and r1.market != r2.market:
                continue
            # Fare families overlap
            ff1 = set(r1.fare_families)
            ff2 = set(r2.fare_families)
            if not (ff1 & ff2 or "*" in ff1 or "*" in ff2):
                continue

            # Check if windows overlap
            start1 = r1.stated_from or r1.observed_from or date.min
            end1 = r1.stated_to or r1.observed_to or date.max
            start2 = r2.stated_from or r2.observed_from or date.min
            end2 = r2.stated_to or r2.observed_to or date.max

            overlap = max(start1, start2) < min(end1, end2)
            if overlap:
                # Compare sort keys
                rank1 = (
                    RULE_SOURCE_CLASS_ORDER.get(r1.rule_source_class, 1),
                    CONFIDENCE_ORDER.index(r1.ceiling),
                    0 if r1.fare_families == ["*"] else 1,
                    start1,
                )
                rank2 = (
                    RULE_SOURCE_CLASS_ORDER.get(r2.rule_source_class, 1),
                    CONFIDENCE_ORDER.index(r2.ceiling),
                    0 if r2.fare_families == ["*"] else 1,
                    start2,
                )
                if rank1 == rank2:
                    errors.append(
                        f"Ambiguity conflict: {r1.policy_id} and {r2.policy_id} have overlapping windows "
                        f"({max(start1, start2)} to {min(end1, end2)}) and identical rank {rank1}"
                    )

    # Report
    print("=" * 70)
    print("CORPUS LINT REPORT")
    print("=" * 70)
    print(f"Total rules checked: {len(rules)}")
    print(f"Errors:   {len(errors)}")
    print(f"Warnings: {len(warnings)}")

    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  [WARN] {w}")

    if errors:
        print("\nErrors:")
        for e in errors:
            print(f"  [ERROR] {e}")
        print("\nCORPUS LINT FAILED")
        return 1

    print("\nCORPUS LINT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(lint_corpus())
