"""Acceptance tests for WP-6: API v2, case persistence, review flow, and replay."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import sys

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SERVER_DIR = ROOT_DIR / "server"
ENGINE_DIR = ROOT_DIR / "engine"
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(ENGINE_DIR))

from app import app
from tools.replay import replay_case

client = TestClient(app)


def test_api_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "engine_version" in data
    assert "corpus_version" in data
    assert "quarantined_rules" in data


def test_api_corpus_coverage():
    resp = client.get("/api/corpus/coverage")
    assert resp.status_code == 200
    data = resp.json()
    assert "carriers" in data
    assert "rules_coverage" in data


def test_api_compute_v2_persists_and_replays():
    payload = {
        "ticket": {
            "carrier": "SG",
            "market": "DOMESTIC",
            "origin": "DEL",
            "destination": "BOM",
            "ticket_number": "775-1234567890",
            "booking_date": "2025-11-20",
            "departure_local": "2026-01-15T18:00:00",
            "departure_timezone": "Asia/Kolkata",
            "currency": "INR",
            "passengers": 1,
            "base_fare": "6700.00",
            "taxes": [
                {"code": "K3", "amount": "352.00"},
                {"code": "UDF", "amount": "708.00"},
                {"code": "PSF", "amount": "160.00"},
            ],
            "carrier_surcharges": [{"code": "YR", "amount": "250.00"}],
            "seller_fees": [{"code": "CONVENIENCE_ONLINE", "amount": "250.00"}],
            "total_paid": "8420.00",
            "fare_family": "SAVER",
        },
        "cancellation": {
            "instant_local": "2026-01-10T18:00:00",
            "timezone": "Asia/Kolkata",
            "basis": "USER_SCENARIO",
            "cause": "PASSENGER_INITIATED",
        },
        "persist": True,
    }

    resp = client.post("/api/compute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    case_id = data["case_id"]
    assert case_id is not None
    assert data["total"]["amount"] == "₹4,720.00"
    assert data["total"]["status"] == "PARTIAL"
    assert data["timeline"]["status"] == "VALID"

    # Verify retrieval
    get_resp = client.get(f"/api/cases/{case_id}")
    assert get_resp.status_code == 200
    case_data = get_resp.json()
    assert case_data["case"]["case_id"] == case_id
    assert len(case_data["audit_trail"]) >= 1

    # Verify review flow
    rev_resp = client.post(
        f"/api/cases/{case_id}/review",
        json={
            "reviewer": "TestReviewer",
            "decision": "APPROVED",
            "reason": "Verified against policy",
            "evidence_ref": "ref_123",
        },
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["review_status"] == "REVIEWED"

    # Verify replay
    replay_exit = replay_case(case_id)
    assert replay_exit == 0


def test_api_actual_record_without_source_ref_400():
    payload = {
        "ticket": {
            "carrier": "SG",
            "booking_date": "2025-11-20",
            "departure_local": "2026-01-15T18:00:00",
            "departure_timezone": "Asia/Kolkata",
            "base_fare": "6700.00",
        },
        "cancellation": {
            "instant_local": "2026-01-10T18:00:00",
            "basis": "ACTUAL_RECORD",
            "source_ref": None,
        },
    }
    resp = client.post("/api/compute", json=payload)
    assert resp.status_code == 400
    assert "source reference" in resp.json()["message"]


def test_api_post_departure_200_partial():
    payload = {
        "ticket": {
            "carrier": "SG",
            "booking_date": "2025-11-20",
            "departure_local": "2026-01-15T18:00:00",
            "departure_timezone": "Asia/Kolkata",
            "base_fare": "6700.00",
            "taxes": [{"code": "K3", "amount": "352.00"}],
        },
        "cancellation": {
            "instant_local": "2026-01-15T21:00:00",
            "basis": "USER_SCENARIO",
        },
    }
    resp = client.post("/api/compute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"]["status"] == "PARTIAL"
    assert data["timeline"]["status"] == "AT_OR_AFTER_DEPARTURE"
