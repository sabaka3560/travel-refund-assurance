"""Money as integer minor units (paise). No floating point ever touches a rupee.

ISO 4217 gives INR two minor units. Every amount in this system is an int of paise.
Formatting to rupees happens only at the presentation boundary.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

MINOR_UNITS = {"INR": 2, "USD": 2, "AED": 2, "SGD": 2, "NPR": 2}


class Money:
    """An exact monetary amount in minor units. Immutable."""

    __slots__ = ("minor", "currency")

    def __init__(self, minor: int, currency: str = "INR") -> None:
        if not isinstance(minor, int):
            raise TypeError(f"Money must be constructed from int minor units, got {type(minor).__name__}")
        self.minor = minor
        self.currency = currency

    # -- construction ----------------------------------------------------
    @classmethod
    def rupees(cls, value: str | int, currency: str = "INR") -> "Money":
        """Build from a major-unit string like '8420.50'. Strings, never floats."""
        exp = MINOR_UNITS.get(currency)
        if exp is None:
            raise ValueError(f"Unknown currency {currency!r}")
        d = Decimal(str(value)).scaleb(exp).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        return cls(int(d), currency)

    @classmethod
    def zero(cls, currency: str = "INR") -> "Money":
        return cls(0, currency)

    # -- arithmetic ------------------------------------------------------
    def _check(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise ValueError(
                f"Refusing to mix {self.currency} and {other.currency}. "
                "Multi-currency is out of scope; the engine must abstain."
            )

    def __add__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._check(other)
        return Money(self.minor - other.minor, self.currency)

    def __neg__(self) -> "Money":
        return Money(-self.minor, self.currency)

    def pct(self, percent: Decimal | str | int) -> "Money":
        """A percentage of this amount, rounded half-up once, at the leaf."""
        p = Decimal(str(percent))
        raw = (Decimal(self.minor) * p / Decimal(100)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        return Money(int(raw), self.currency)

    # -- comparison ------------------------------------------------------
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Money) and self.minor == other.minor and self.currency == other.currency

    def __lt__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor < other.minor

    def __le__(self, other: "Money") -> bool:
        self._check(other)
        return self.minor <= other.minor

    def __hash__(self) -> int:
        return hash((self.minor, self.currency))

    def is_zero(self) -> bool:
        return self.minor == 0

    def is_negative(self) -> bool:
        return self.minor < 0

    @staticmethod
    def min(a: "Money", b: "Money") -> "Money":
        a._check(b)
        return a if a.minor <= b.minor else b

    @staticmethod
    def max(a: "Money", b: "Money") -> "Money":
        a._check(b)
        return a if a.minor >= b.minor else b

    @staticmethod
    def total(items, currency: Optional[str] = None) -> "Money":
        items = list(items)
        if not items:
            if currency is None:
                raise ValueError("Money.total on empty sequence requires an explicit currency")
            return Money.zero(currency)
        cur = currency or items[0].currency
        out = Money.zero(cur)
        for it in items:
            out = out + it
        return out

    # -- presentation ----------------------------------------------------
    def __str__(self) -> str:
        exp = MINOR_UNITS[self.currency]
        sign = "-" if self.minor < 0 else ""
        whole, frac = divmod(abs(self.minor), 10**exp)
        sym = "₹" if self.currency == "INR" else self.currency + " "
        return f"{sign}{sym}{whole:,}.{frac:0{exp}d}"

    def __repr__(self) -> str:
        return f"Money({self.minor}, {self.currency!r})"
