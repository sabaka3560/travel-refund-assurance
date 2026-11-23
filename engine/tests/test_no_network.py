"""Invariant I13: No component of the system performs airline booking/cancellation or live page fetching at request time.

Verified via AST/grep inspection of the engine and a strict network guard during evaluation.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import socket
import pytest
import sys
from zoneinfo import ZoneInfo

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import Money, RefundEngine, TaxLine, Ticket
from refund_engine.engine import preset_t_minus

IST = ZoneInfo("Asia/Kolkata")


def test_no_network_imports_in_engine():
    """Ensure engine/refund_engine contains no network clients (Invariant I13)."""
    engine_pkg = ENGINE_DIR / "refund_engine"
    forbidden_modules = {"requests", "urllib.request", "httpx", "aiohttp", "playwright", "selenium"}

    for py_file in engine_pkg.glob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        for mod in forbidden_modules:
            assert f"import {mod}" not in text, f"Forbidden network import {mod} found in {py_file.name}"
            assert f"from {mod}" not in text, f"Forbidden network import {mod} found in {py_file.name}"


def test_evaluate_makes_zero_network_calls(monkeypatch):
    """Guard socket.connect to ensure RefundEngine.evaluate is 100% offline."""
    def guarded_connect(*args, **kwargs):
        raise RuntimeError("Network connection attempted during engine evaluation (Invariant I13 violation)!")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)

    ticket = Ticket(
        ticket_number="TEST",
        carrier="SG",
        market="DOMESTIC",
        origin="DEL",
        destination="BOM",
        booking_date=date(2025, 11, 20),
        ticket_issue_date=date(2025, 11, 20),
        scheduled_departure=datetime(2026, 1, 15, 18, 0, tzinfo=IST),
        base_fare=Money.rupees("6700.00"),
        total_paid=Money.rupees("6700.00"),
        fare_family="SAVER",
    )

    engine = RefundEngine()
    result = engine.evaluate(ticket, preset_t_minus(ticket, 120))
    assert result.refund_total is not None
