"""Acceptance tests for Invariant I1 and Money arithmetic.

Tests Invariant I1: No floating-point value ever participates in a monetary calculation.
Fixes F11.
"""
from __future__ import annotations

from pathlib import Path
import pytest
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import Money


def test_no_float():
    """Invariant I1: Floats cannot be used to construct Money."""
    with pytest.raises(TypeError, match="Money must be constructed from int minor units"):
        Money(1.5)  # float minor unit forbidden

    with pytest.raises(TypeError):
        Money(100.0)


def test_rupees_to_minor_exact():
    m = Money.rupees("8420.00")
    assert m.minor == 842000
    assert m.currency == "INR"


def test_no_float_drift():
    assert Money.rupees("0.10") + Money.rupees("0.20") == Money.rupees("0.30")


def test_percentage_rounds_half_up_once():
    assert Money.rupees("100.00").pct("12.5") == Money.rupees("12.50")


def test_currency_mixing_refused():
    with pytest.raises(ValueError, match="Refusing to mix"):
        _ = Money.rupees("1", "INR") + Money.rupees("1", "USD")


def test_formatting_with_separators():
    assert str(Money.rupees("1234567.89")) == "₹1,234,567.89"
    assert str(Money.rupees("100.00", "USD")) == "USD 100.00"


def test_money_total_f11_fix():
    """F11: Money.total([]) requires explicit currency, preventing silent INR fallback."""
    with pytest.raises(ValueError, match="requires an explicit currency"):
        Money.total([])

    m_zero_usd = Money.total([], currency="USD")
    assert m_zero_usd.currency == "USD"
    assert m_zero_usd.minor == 0

    m_sum = Money.total([Money.rupees("10.00"), Money.rupees("20.00")])
    assert m_sum == Money.rupees("30.00")
