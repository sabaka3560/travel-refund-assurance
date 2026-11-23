"""Regressions for demo inputs and a slow external document reader."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
server = importlib.import_module("app")
from refund_engine.evidence import EvidenceStore


def payload():
    return {
        "ticket": {"carrier": "SG", "booking_date": "2025-11-20", "departure_local": "2026-01-15T18:00:00", "departure_timezone": "Asia/Kolkata", "base_fare": "6700.00"},
        "cancellation": {"instant_local": "2026-01-10T18:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"},
        "persist": False,
    }


def test_v2_never_silently_defaults_cancellation():
    request = payload()
    del request["cancellation"]
    response = TestClient(server.app).post("/api/compute", json=request)
    assert response.status_code == 400
    assert "cancellation date and time" in response.json()["message"]


def test_actual_reference_requires_preserved_evidence(monkeypatch, tmp_path):
    store = EvidenceStore(tmp_path)
    monkeypatch.setattr(server, "EVIDENCE_STORE", store)
    request = payload()
    request["cancellation"].update(basis="ACTUAL_RECORD", source_ref="external-confirmation-123")
    response = TestClient(server.app).post("/api/compute", json=request)
    assert response.status_code == 200
    assert response.json()["review_status"] == "REVIEW_REQUIRED"
    assert "ACTUAL_RECORD_UNVERIFIED" in [a["code"] for a in response.json()["assumptions"]]
    sha = store.store_bytes(b"Specimen cancellation confirmation", "txt", "test", "CLIENT_DOCUMENT")
    request["cancellation"]["source_ref"] = sha
    response = TestClient(server.app).post("/api/compute", json=request)
    assert response.status_code == 200
    assert "ACTUAL_RECORD_UNVERIFIED" not in [a["code"] for a in response.json()["assumptions"]]


def test_empty_upload_is_actionable():
    response = TestClient(server.app).post("/api/extract", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert response.status_code == 400
    assert "empty" in response.json()["message"]


def test_slow_document_reader_does_not_block_health(monkeypatch, tmp_path):
    entered, release = Event(), Event()

    def slow_reader(*args):
        entered.set()
        assert release.wait(5), "Test failed to release the simulated provider"
        return SimpleNamespace(text=json.dumps({"carrier": "SG"}))

    monkeypatch.setattr(server, "_read_document", slow_reader)
    monkeypatch.setattr(server, "gemini_key", lambda: "test-only")
    monkeypatch.setattr(server, "EVIDENCE_STORE", EvidenceStore(tmp_path))

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            upload = asyncio.create_task(client.post("/api/extract", files={"file": ("specimen.pdf", b"test", "application/pdf")}))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                response = await asyncio.wait_for(client.get("/api/health"), timeout=1)
                assert response.status_code == 200
                assert not upload.done()
            finally:
                release.set()
                response = await upload
            assert response.status_code == 200
            assert len(response.json()["extraction_ref"]) == 64

    asyncio.run(run())
