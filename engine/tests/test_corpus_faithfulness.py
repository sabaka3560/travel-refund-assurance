"""Every figure a rule asserts must be readable in the copy the rule cites.

This is the check that was missing. The evidence store proved a rule's source had not
been *altered*; nothing proved the source actually *said* what the rule claims. Two real
defects lived in that gap:

  * Akasa's rules stated an effective date of 2026-05-12, omitted the 0-24h band
    entirely, recorded the 24-72h fee as "never captured" when the copy states it
    plainly, and used a 4h cut-off where the copy says two hours.
  * Air India Express's Classic and Flex figures could not be checked at all, because
    the PDF text layer was not being read.

Both were found by reading the preserved copies clause by clause on 2026-09-08. This
module keeps them found: it re-reads every artifact and asserts the numbers still
appear. It does not check semantics — a human still has to read the clause — but a fee
that appears nowhere in its own source can no longer reach a ledger unnoticed.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
import re
import sys

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

EVIDENCE_DIR = ENGINE_DIR / "corpus" / "evidence"
POLICIES = json.loads((ENGINE_DIR / "corpus" / "policies.json").read_text(encoding="utf-8"))


def _artifact(sha: str) -> Path:
    hits = [p for p in EVIDENCE_DIR.glob(f"{sha}*") if not p.name.endswith(".meta.json")]
    assert hits, f"no artifact stored for {sha[:12]}"
    return hits[0]


def _text(path: Path) -> str:
    raw = path.read_bytes()
    if path.suffix.lower() == ".pdf":
        pypdf = pytest.importorskip("pypdf", reason="pypdf needed to read PDF evidence")
        from io import BytesIO

        pages = pypdf.PdfReader(BytesIO(raw)).pages
        text = " ".join((p.extract_text() or "") for p in pages)
    else:
        text = raw.decode("utf-8", "ignore")
        text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).replace(",", "")


_CACHE: dict[str, str] = {}


def _source_text(sha: str) -> str:
    if sha not in _CACHE:
        _CACHE[sha] = _text(_artifact(sha))
    return _CACHE[sha]


RULES = [p for p in POLICIES["policies"]]


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["policy_id"])
def test_every_asserted_fee_appears_in_its_own_source(rule):
    """A band fee that is nowhere in the cited copy is either mis-transcribed or
    mis-sourced. Either way it must not be quietly serving refund figures."""
    sha = rule["source"].get("evidence_sha256")
    assert sha, f"{rule['policy_id']} cites no preserved copy"
    text = _source_text(sha)

    for band in rule["bands"]:
        fee = band["fee"]
        amount = fee.get("amount_minor")
        if fee["kind"] in ("UNKNOWN", "FARE_FULLY_FORFEITED") or not amount:
            continue  # nothing numeric is being asserted
        rupees = str(amount // 100)
        assert rupees in text, (
            f"{rule['policy_id']} band {band['from_h']}h asserts a fee of INR {rupees}, "
            f"which does not appear anywhere in its own preserved copy ({sha[:12]})"
        )


@pytest.mark.parametrize("rule", [r for r in RULES if r.get("free_look")],
                         ids=lambda r: r["policy_id"])
def test_free_look_conditions_are_quoted_from_source(rule):
    """A nil-fee condition changes the answer completely, so its wording must be
    traceable to the copy rather than summarised from memory."""
    fl = rule["free_look"]
    assert fl.get("quote"), f"{rule['policy_id']} free_look carries no verbatim quote"
    text = _source_text(rule["source"]["evidence_sha256"])
    assert "24 hours of the booking" in text or "24 hours of booking" in text, (
        f"{rule['policy_id']} asserts a within-24h-of-booking condition that is not in its source"
    )


@pytest.mark.parametrize("rule", [r for r in RULES if r.get("cutoff_hours_before_departure")],
                         ids=lambda r: r["policy_id"])
def test_cutoffs_are_supported_by_source_text(rule):
    """Akasa's cut-off was recorded as 4 hours where the copy says two. A cut-off
    silently governs everything below it, so the number has to come from the page."""
    cut = rule["cutoff_hours_before_departure"]
    text = _source_text(rule["source"]["evidence_sha256"]).lower()
    words = {2: ["two (2) hours", "2 hrs", "2 hours"],
             3: ["three (3) hours", "3 hrs", "3 hours", "3-24"],
             4: ["four (4) hours", "4 hrs", "4 hours"]}
    candidates = words.get(cut, [f"{cut} hours", f"{cut} hrs"])
    assert any(c in text for c in candidates), (
        f"{rule['policy_id']} declares a {cut}h cut-off, but no such interval appears in "
        f"its preserved copy. Akasa's 4h cut-off was wrong this way."
    )


def test_no_rule_claims_verified_without_being_checkable():
    """A `content_verification` starting with VERIFIED is a claim about the evidence.
    It must not be present on a rule whose artifact we cannot even read."""
    for rule in RULES:
        note = rule["source"].get("content_verification", "")
        if note.startswith("VERIFIED"):
            text = _source_text(rule["source"]["evidence_sha256"])
            assert len(text) > 500, (
                f"{rule['policy_id']} claims VERIFIED but its artifact yields no readable text"
            )
