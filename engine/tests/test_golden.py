"""Test that engine output on the 11 sample tickets matches the frozen golden files."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import RefundEngine
from refund_engine.engine import preset_t_minus
from tools.make_golden import SAMPLES, sample_to_ticket, GOLDEN_DIR


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda s: s["id"])
def test_sample_matches_golden(sample: dict):
    golden_file = GOLDEN_DIR / f"{sample['id']}.json"
    assert golden_file.exists(), f"Golden file missing: {golden_file}"
    golden = json.loads(golden_file.read_text(encoding="utf-8"))

    engine = RefundEngine()
    ticket = sample_to_ticket(sample)
    r = engine.evaluate(ticket, preset_t_minus(ticket, 120))

    actual_minor = None if r.refund_total is None else r.refund_total.minor
    assert r.rule_id == golden["rule_id"], f"Rule ID mismatch for {sample['id']}: {r.rule_id} != {golden['rule_id']}"
    assert actual_minor == golden["refund_minor"], (
        f"Refund total mismatch for {sample['id']}: {actual_minor} != {golden['refund_minor']}"
    )
    assert r.confidence.value == golden["confidence"], (
        f"Confidence mismatch for {sample['id']}: {r.confidence.value} != {golden['confidence']}"
    )

    actual_lines = [
        {
            "label": l.label,
            "contribution_minor": l.contribution.minor,
            "contribution_formatted": str(l.contribution),
            "confidence": l.confidence.value,
        }
        for l in r.lines
    ]
    assert actual_lines == golden["lines"], f"Lines mismatch for {sample['id']}"
    assert r.abstained == golden["abstained"], f"Abstained mismatch for {sample['id']}"
    assert r.warnings == golden["warnings"], f"Warnings mismatch for {sample['id']}"
