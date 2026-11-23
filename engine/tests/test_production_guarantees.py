"""Guarantees checked through the PRODUCTION path only.

Every test here drives `RefundEngine.evaluate` or the corpus loader exactly as the
server does. Nothing sets a flag the product does not set.

This module exists because the earlier suite proved a set of behaviours that the
shipped code never executed: the resolver hardening was reachable only by passing
`dual_reading=True`, which only the tests did, and the evidence gate was disabled by a
literal `and False` that no test touched. A guarantee that is only exercised through a
test-only switch is not a guarantee.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import re
import sys

import pytest
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import Confidence, Corpus, Money, RefundEngine, TaxLine, Ticket
from refund_engine.engine import preset_t_minus
from refund_engine.model import CancellationRequest, TimeBasis, TotalStatus

IST = ZoneInfo("Asia/Kolkata")
EVIDENCE_DIR = ENGINE_DIR / "corpus" / "evidence"


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


def at(ticket: Ticket, delta: timedelta):
    return CancellationRequest(ticket.scheduled_departure - delta, TimeBasis.USER_SCENARIO)


# --------------------------------------------------------------------------- #
# The resolver hardening must run without anyone opting in
# --------------------------------------------------------------------------- #
def test_engine_never_resolves_with_the_legacy_reading():
    """`evaluate` must not pass dual_reading=False, and must not rely on the default
    being False. Checked structurally, because the failure is invisible at runtime."""
    src = (ENGINE_DIR / "refund_engine" / "engine.py").read_text(encoding="utf-8")
    assert "dual_reading=False" not in src, "engine must never request the legacy reading"

    corpus_src = (ENGINE_DIR / "refund_engine" / "corpus.py").read_text(encoding="utf-8")
    m = re.search(r"dual_reading: bool = (True|False)", corpus_src)
    assert m and m.group(1) == "True", "resolve() must default to the hardened reading"


def test_unknown_applicability_disagreement_abstains_through_evaluate():
    """I5, via the production path: booked under one IndiGo capture, cancelled under a
    later one. The applicability key is unknown, the two readings pick different rules,
    so the fare line must abstain instead of silently choosing the cancellation-date rule."""
    t = mk(
        carrier="6E",
        fare_family=None,
        booking_date=date(2025, 6, 1),
        scheduled_departure=datetime(2025, 8, 6, 18, 0, tzinfo=IST),
    )
    r = RefundEngine().evaluate(t, at(t, timedelta(hours=120)))

    assert r.rule_id is None
    assert any("cannot be established" in a for a in r.abstained)
    # the computable part survives: statutory taxes are still refunded
    assert r.refund_total == Money.rupees("1220.00")
    assert r.total_status is TotalStatus.PARTIAL


def test_open_ended_capture_is_not_projected_past_the_horizon():
    """F4, via the production path: a capture from 2026 must not govern a 2030
    cancellation just because its observed window has no end date."""
    t = mk(
        carrier="6E",
        fare_family=None,
        booking_date=date(2029, 12, 1),
        scheduled_departure=datetime(2030, 1, 6, 18, 0, tzinfo=IST),
    )
    r = RefundEngine().evaluate(t, at(t, timedelta(hours=120)))

    assert r.rule_id is None, "a 2026 capture must not be projected into 2030"
    assert r.total_status is TotalStatus.PARTIAL
    assert r.refund_total == Money.rupees("1220.00")


# --------------------------------------------------------------------------- #
# The evidence gate must bite on the real corpus
# --------------------------------------------------------------------------- #
def test_every_resolvable_rule_has_a_hash_matching_preserved_copy():
    """I7. Not 'the store has files' — every rule the engine can reach is checked."""
    c = Corpus()
    assert c.rules, "corpus loaded no rules at all"
    for rule in c.rules:
        sha = rule.source.get("evidence_sha256")
        assert sha, f"{rule.policy_id} reached resolution with no preserved copy"
        matches = [p for p in EVIDENCE_DIR.glob(f"{sha}*") if not p.name.endswith(".meta.json")]
        assert matches, f"{rule.policy_id} references evidence {sha[:12]} that is not in the store"


def test_tampering_with_an_artifact_quarantines_its_rules(tmp_path):
    """A byte changed in a preserved copy must remove every rule that cites it from
    resolution — not warn, not continue."""
    c = Corpus()
    baseline = {q["policy_id"] for q in c.quarantined}
    target = next(r for r in c.rules if r.carrier == "SG")
    sha = target.source["evidence_sha256"]
    artifact = next(p for p in EVIDENCE_DIR.glob(f"{sha}*") if not p.name.endswith(".meta.json"))
    original = artifact.read_bytes()
    try:
        artifact.write_bytes(original + b"<!-- tampered -->")
        tampered = Corpus()
        quarantined_ids = {q["policy_id"] for q in tampered.quarantined} - baseline
        assert target.policy_id in quarantined_ids
        assert all(r.policy_id not in quarantined_ids for r in tampered.rules)

        res = tampered.resolve(
            carrier="SG", market="DOMESTIC", fare_family="SAVER",
            booking_date=date(2025, 11, 20), cancel_date=date(2026, 1, 10),
        )
        assert res.rule is None, "a quarantined rule must never be resolved"
    finally:
        artifact.write_bytes(original)
    assert {q["policy_id"] for q in Corpus().quarantined} == baseline, (
        "corpus did not return to its baseline quarantine set")


def test_rule_without_evidence_is_quarantined(tmp_path):
    """The gate that was disabled by `and False`. A rule with no evidence_sha256 must
    not load, regardless of how well-formed it otherwise is."""
    import json

    src = json.loads((ENGINE_DIR / "corpus" / "policies.json").read_text(encoding="utf-8"))
    src["policies"][0]["source"].pop("evidence_sha256", None)
    p = tmp_path / "policies.json"
    p.write_text(json.dumps(src), encoding="utf-8")

    c = Corpus(policies_path=p)
    assert any(q["policy_id"] == src["policies"][0]["policy_id"] for q in c.quarantined)
    assert all(r.policy_id != src["policies"][0]["policy_id"] for r in c.rules)


# --------------------------------------------------------------------------- #
# The evidence has to reach the output, or the client cannot check it
# --------------------------------------------------------------------------- #
def test_every_material_line_carries_its_evidence():
    """R9: a figure the client is asked to rely on must arrive with the clause, the
    source, the capture date and the hash of the preserved copy."""
    t = mk()
    r = RefundEngine().evaluate(t, preset_t_minus(t, 120))

    material = [l for l in r.lines if l.contribution.minor != 0 or l.label == "Base fare"]
    assert material
    for line in material:
        ev = line.evidence
        assert ev, f"line {line.label!r} carries a figure with no evidence pack"
        assert ev.get("clause_quote"), f"line {line.label!r} has no verbatim clause"
        assert ev.get("why_it_matches"), f"line {line.label!r} does not say why the rule matches"

    base = next(l for l in r.lines if l.label == "Base fare")
    assert base.evidence["sha256"], "the fare line must name the preserved copy it rests on"
    assert base.evidence["capture_date"]
    assert base.evidence["applicability_key"] == "BOOKING_DATE"


# --------------------------------------------------------------------------- #
# Scope statements must describe our evidence, not the world
# --------------------------------------------------------------------------- #
def test_corporate_fare_yields_a_partial_result_not_a_refusal():
    """R12: the corporate agreement is a document the client can supply, so this is a
    missing-evidence abstention on one line — the statutory line still computes."""
    t = mk(account_code="CORP123")
    r = RefundEngine().evaluate(t, preset_t_minus(t, 120))

    assert r.refund_total == Money.rupees("1220.00")
    assert r.total_status is TotalStatus.PARTIAL
    assert any("corporate agreement not supplied" in e for e in r.excluded_components)


def test_no_universal_claims_about_carrier_publishing_in_user_facing_text():
    """The client corrected this specific claim. It must not survive anywhere a user
    can read it."""
    banned = re.compile(r"no carrier publishes", re.I)
    for path in [
        ENGINE_DIR / "refund_engine" / "engine.py",
        ENGINE_DIR.parent / "server" / "static" / "index.html",
    ]:
        text = path.read_text(encoding="utf-8")
        assert not banned.search(text), f"unsupported universal claim still present in {path.name}"


# --------------------------------------------------------------------------- #
# The cancellation instant is never defaulted
# --------------------------------------------------------------------------- #
def test_evaluate_refuses_to_default_the_cancellation_instant():
    t = mk()
    with pytest.raises((TypeError, ValueError)):
        RefundEngine().evaluate(t)  # type: ignore[call-arg]


def test_benchmark_expectations_are_not_labelled_as_external_references():
    """The benchmark is generated from this engine's own semantics. Labelling those
    expectations `client_reference` or `carrier_statement` would let a reader believe
    the system had been validated against data nobody has supplied."""
    import json

    cases_dir = ENGINE_DIR.parent / "benchmark" / "cases"
    if not cases_dir.exists():
        pytest.skip("benchmark cases not present")
    for f in cases_dir.glob("*.json"):
        prov = json.loads(f.read_text(encoding="utf-8")).get("provenance")
        assert prov == "synthetic", (
            f"{f.name} claims provenance {prov!r}; no client- or carrier-sourced reference "
            "answers exist in this project yet"
        )


# --------------------------------------------------------------------------- #
# API/UI contract — the shapes the browser actually consumes
#
# These were all live defects: the UI rendered "[object Object]" from an error body
# whose shape varied by call site, showed empty rows for rejected rules because the
# backend sent sentences where the UI read fields, and never showed the missing-evidence
# panel at all because the engine filled `abstained` while every consumer read
# `unresolved`. None of it was visible from Python; all of it was visible in a browser.
# --------------------------------------------------------------------------- #
def _client():
    import sys as _sys
    _sys.path.insert(0, str(ENGINE_DIR.parent / "server"))
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def _valid_body():
    return {
        "ticket": {
            "carrier": "SG", "market": "DOMESTIC", "origin": "DEL", "destination": "BOM",
            "ticket_number": "775-1", "booking_date": "2025-11-20",
            "departure_local": "2026-01-15T18:00:00", "departure_timezone": "Asia/Kolkata",
            "currency": "INR", "passengers": 1, "base_fare": "6700.00",
            "taxes": [{"code": "K3", "amount": "352.00"}, {"code": "UDF", "amount": "708.00"},
                      {"code": "PSF", "amount": "160.00"}],
            "carrier_surcharges": [{"code": "YR", "amount": "250.00"}],
            "seller_fees": [{"code": "CONVENIENCE_ONLINE", "amount": "250.00"}],
            "total_paid": "8420.00", "fare_family": "SAVER",
            "corporate": False, "reissued": False, "partially_used": False,
        },
        "cancellation": {
            "instant_local": "2026-01-10T18:00:00", "timezone": "Asia/Kolkata",
            "basis": "USER_SCENARIO", "cause": "PASSENGER_INITIATED",
        },
        "persist": False,
    }


def test_every_error_uses_one_shape():
    """A UI cannot read an error whose shape depends on which layer raised it.
    `new Error(someObject)` renders as "[object Object]" — that was the bug."""
    c = _client()
    cases = [
        c.post("/api/compute", content=b"not json", headers={"Content-Type": "application/json"}),
        c.post("/api/compute", json={"ticket": {"carrier": "SG"}, "cancellation": {}}),
        c.get("/api/cases/definitely-not-a-case"),
        c.get("/api/evidence/" + "0" * 64),
    ]
    for resp in cases:
        assert resp.status_code >= 400
        body = resp.json()
        assert isinstance(body, dict), f"error body is not an object: {body!r}"
        assert isinstance(body.get("error_code"), str) and body["error_code"], body
        assert isinstance(body.get("message"), str) and body["message"], body
        assert "detail" not in body, f"error still nested under 'detail': {body!r}"


def test_rejected_rules_are_structured_for_the_ui():
    """The UI prints reason code, policy id and detail in separate fields. Sending a
    sentence produced a row of empty spans."""
    d = _client().post("/api/compute", json=_valid_body()).json()
    rejected = d["rules_rejected"]
    assert rejected, "expected at least one rejected rule for this ticket"
    for row in rejected:
        assert isinstance(row, dict), f"rules_rejected entry is not an object: {row!r}"
        assert row.get("policy_id") and row.get("reason_code") and row.get("detail")


def test_missing_evidence_reaches_the_response():
    """`abstained` and `unresolved` are the same list under two names. The engine filled
    one and the UI read the other, so the missing-evidence panel never rendered."""
    d = _client().post("/api/compute", json=_valid_body()).json()
    assert d["abstained"], "this ticket abstains on the YR surcharge"
    assert d["unresolved"] == d["abstained"], "unresolved must carry the abstentions"


def test_line_evidence_is_an_object_not_a_string():
    d = _client().post("/api/compute", json=_valid_body()).json()
    base = next(l for l in d["lines"] if l["label"] == "Base fare")
    assert isinstance(base["evidence"], dict) and base["evidence"].get("clause_quote")


def test_unclassified_tax_is_disclosed_not_silently_dropped():
    """An OTA invoice often prints one combined "Taxes & fees" figure instead of codes.

    That amount cannot be classified, so it contributes nothing — but the total used to
    still read COMPLETE, understating the refund by the whole tax line with nothing on
    screen to say so. A figure we cannot establish must be excluded *visibly*.
    """
    t = mk(taxes=[TaxLine("TAXES_AND_FEES", Money.rupees("1220.00"))],
           carrier_surcharges=[], seller_fees=[], total_paid=Money.rupees("7920.00"))
    r = RefundEngine().evaluate(t, preset_t_minus(t, 120))

    assert r.total_status is TotalStatus.PARTIAL, "a dropped tax must not leave a COMPLETE total"
    assert any("TAXES_AND_FEES" in e for e in r.excluded_components)
    assert any("registry" in a for a in r.abstained)
    assert r.review_status.value == "REVIEW_REQUIRED"
