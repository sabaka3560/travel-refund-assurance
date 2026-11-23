"""Acceptance tests for WP-5: Evidence store, cryptographic integrity gate, and quarantine.

Tests Invariant I7, F5, R6.
"""
from __future__ import annotations

import os
from pathlib import Path
import pytest
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine.evidence import EvidenceStore


def test_evidence_store_and_verify(tmp_path: Path):
    store = EvidenceStore(tmp_path)

    # 1. Store a test evidence artifact
    dummy_content = b"Official cancellation disclosure PDF text content"
    sha = store.store_bytes(
        content=dummy_content,
        extension="pdf",
        source_url="https://web.archive.org/web/2026/test.pdf",
        capture_kind="OFFICIAL_PDF",
        carrier_capture_date="2026-09-01",
        notes="Test artifact",
    )

    assert len(sha) == 64
    item = store.get(sha)
    assert item is not None
    assert item.meta["capture_kind"] == "OFFICIAL_PDF"
    assert item.meta["source_url"] == "https://web.archive.org/web/2026/test.pdf"

    # 2. Verify rule with correct hash
    ok, err = store.verify_rule("TEST-RULE", {"evidence_sha256": sha})
    assert ok is True
    assert err is None

    # 3. Invariant I7: Verify rule with tampered hash quarantines
    ok_bad, err_bad = store.verify_rule("TEST-RULE", {"evidence_sha256": "0" * 64})
    assert ok_bad is False
    assert "does not exist" in err_bad

    # 4. Tamper file content to trigger hash mismatch
    item.file_path.write_bytes(b"Tampered content!")
    ok_tampered, err_tampered = store.verify_rule("TEST-RULE", {"evidence_sha256": sha})
    assert ok_tampered is False
    assert "Hash mismatch" in err_tampered


def test_missing_evidence_sha_fails():
    store = EvidenceStore()
    ok, err = store.verify_rule("TEST-RULE", {})
    assert ok is False
    assert "Missing evidence_sha256" in err
