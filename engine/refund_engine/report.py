"""Presentation. Reads the ledger; never computes anything."""
from __future__ import annotations

from .model import Confidence, Result

_BADGE = {
    Confidence.AUTHORITATIVE: "AUTHORITATIVE",
    Confidence.HIGH: "HIGH",
    Confidence.MEDIUM: "MEDIUM",
    Confidence.LOW: "LOW  (weak evidence)",
    Confidence.INSUFFICIENT: "INSUFFICIENT — no figure asserted",
}


def render(r: Result, width: int = 78) -> str:
    L: list[str] = []
    bar = "=" * width
    L.append(bar)
    L.append(f"HISTORICAL REFUND RECONSTRUCTION — ticket {r.ticket_number}")
    L.append(bar)
    L.append(f"Hypothetical cancellation : {r.cancel_instant:%Y-%m-%d %H:%M %Z} "
             f"(T-{r.hours_before_departure:g}h)")
    if r.rule_id:
        L.append(f"Rule selected             : {r.rule_id}")
        if r.rule_source:
            L.append(f"Source                    : {r.rule_source}")
    L.append("")

    if r.lines:
        L.append(f"{'COMPONENT':<34}{'ORIGINAL':>13}{'REFUND':>13}  CONF")
        L.append("-" * width)
        for ln in r.lines:
            orig = str(ln.original) if ln.original is not None else "—"
            L.append(f"{ln.label[:33]:<34}{orig:>13}{str(ln.contribution):>13}  {ln.confidence.value[:4]}")
        L.append("-" * width)

    if r.refund_total is not None:
        L.append(f"{'CALCULATED REFUND':<34}{'':>13}{str(r.refund_total):>13}")
    else:
        L.append("CALCULATED REFUND                 —  ENGINE ABSTAINED")
    L.append("")
    L.append(f"CONFIDENCE: {_BADGE[r.confidence]}")
    L.append("")

    if r.abstained:
        L.append("ABSTAINED ON:")
        for a in r.abstained:
            L.append(f"  ! {a}")
        L.append("")

    if r.warnings:
        L.append("WARNINGS:")
        for w in r.warnings:
            L.append(f"  - {w}")
        L.append("")

    if r.lines:
        L.append("BASIS FOR EACH LINE:")
        for ln in r.lines:
            L.append(f"  {ln.label}:")
            L.append(f"      {ln.basis}")
        L.append("")

    if r.rejected_rules:
        L.append("RULES CONSIDERED AND REJECTED:")
        for rr in r.rejected_rules:
            L.append(f"  x {rr}")
        L.append("")

    L.append("This is a reconstruction from published policy and statute.")
    L.append("It is NOT an airline-issued refund quote.")
    L.append(bar)
    return "\n".join(L)
