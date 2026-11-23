"""Acceptance tests for Invariant I6 and confidence tier enforcement."""
from __future__ import annotations

from pathlib import Path
import pytest
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import Confidence, Corpus, Provenance


def test_confidence_ceilings():
    """Invariant I6: Hard confidence ceilings by provenance and evidence class."""
    corpus = Corpus()

    obs_rules = [r for r in corpus.rules if r.date_basis == "OBSERVED"]
    assert all(r.ceiling is Confidence.LOW for r in obs_rules)

    stated_rules = [r for r in corpus.rules if r.date_basis == "STATED"]
    # A STATED rule reaches MEDIUM only while nothing disputes it. A rule whose
    # preserved copy cannot corroborate its stated effective date is disputed, and
    # a disputed rule is capped at LOW (I6).
    assert all(
        r.ceiling is (Confidence.LOW if r.disputed else Confidence.MEDIUM)
        for r in stated_rules
    )

    # No snapshot policy reaches HIGH
    assert all(r.ceiling is not Confidence.HIGH for r in corpus.rules)

    # Assert the rule, not the inventory. The corpus previously always held a disputed
    # rule, so this passed by accident; once Akasa's flags were cleared and IndiGo's
    # mis-transcribed rule was quarantined, there were none left to find.
    disputed_rules = [r for r in corpus.rules if r.disputed]
    assert all(r.ceiling is Confidence.LOW for r in disputed_rules)

    from refund_engine.corpus import Rule
    sample = dict(corpus.policies_raw["policies"][0])
    sample["disputed"] = True
    assert Rule(sample).ceiling is Confidence.LOW, "a disputed rule must be capped at LOW"
    sample["disputed"] = False
    assert Rule(sample).ceiling is not Confidence.HIGH, "a policy snapshot must never reach HIGH"
