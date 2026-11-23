"""Acceptance test for case replay (WP-6.4, WP-9.1, Invariant I12)."""
from __future__ import annotations

from pathlib import Path
import pytest
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
SERVER_DIR = ENGINE_DIR.parent / "server"
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(SERVER_DIR))

from fastapi.testclient import TestClient
from app import app
from tools.replay import replay_case

client = TestClient(app)


def test_replay_persisted_case():
    # 1. Compute a case via API v2
    payload = {
        "ticket": {
            "carrier": "SG",
            "market": "DOMESTIC",
            "origin": "DEL",
            "destination": "BOM",
            "ticket_number": "775-REPLAY-001",
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
    case_id = resp.json()["case_id"]

    # 2. Replay case using replay tool
    exit_code = replay_case(case_id)
    assert exit_code == 0, f"Replay failed for case {case_id}"


def test_replay_all_positive_benchmark_cases():
    cases_dir = ENGINE_DIR.parent / "benchmark" / "cases"
    pos_cases = sorted(cases_dir.glob("pos_*.json"))
    assert len(pos_cases) > 0, "No positive benchmark cases found"

    import json
    for p in pos_cases:
        data = json.loads(p.read_text(encoding="utf-8"))
        req = data["request"]
        req["persist"] = True
        resp = client.post("/api/compute", json=req)
        assert resp.status_code == 200, f"Compute failed for {p.name}: {resp.text}"
        case_id = resp.json()["case_id"]
        exit_code = replay_case(case_id)
        assert exit_code == 0, f"Replay failed for benchmark case {p.name} (case_id: {case_id})"

