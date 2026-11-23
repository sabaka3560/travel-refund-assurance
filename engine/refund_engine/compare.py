"""Entitled vs actually received refund comparison (P1).

Reconciles the engine's deterministic reconstruction against an airline-issued
or agency-issued refund receipt when supplied.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .model import Result, TotalStatus
from .money import Money


@dataclass(frozen=True)
class Comparison:
    entitled: Optional[Money]
    received: Optional[Money]
    delta: Optional[Money]
    status: str  # MATCH | SHORTFALL | EXCESS | NOT_COMPARABLE
    detail: str
    received_source_ref: Optional[str] = None


def compare(
    result: Result,
    received: Optional[Money],
    received_source_ref: Optional[str] = None,
) -> Comparison:
    """Compare entitled refund against actual refund received.

    A partial total must NEVER be reported as a shortfall (Invariant P1).
    """
    if received is None:
        return Comparison(
            entitled=result.refund_total,
            received=None,
            delta=None,
            status="NOT_COMPARABLE",
            detail="No actual refund receipt supplied for comparison.",
            received_source_ref=received_source_ref,
        )

    if result.total_status is not TotalStatus.COMPLETE or result.refund_total is None:
        return Comparison(
            entitled=result.refund_total,
            received=received,
            delta=None,
            status="NOT_COMPARABLE",
            detail="Entitled refund is incomplete or partial; cannot determine shortfall or excess against a partial total.",
            received_source_ref=received_source_ref,
        )

    delta = result.refund_total - received
    if delta.is_zero():
        status = "MATCH"
        detail = "Actual refund received matches entitled refund exactly."
    elif delta.minor > 0:
        status = "SHORTFALL"
        detail = f"Actual refund received ({received}) is less than entitled refund ({result.refund_total}) by {delta}."
    else:
        status = "EXCESS"
        excess_amt = Money(-delta.minor, delta.currency)
        detail = f"Actual refund received ({received}) exceeds entitled refund ({result.refund_total}) by {excess_amt}."

    return Comparison(
        entitled=result.refund_total,
        received=received,
        delta=delta,
        status=status,
        detail=detail,
        received_source_ref=received_source_ref,
    )
