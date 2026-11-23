"""The deterministic refund engine.

Contract:
  * No LLM output reaches this module. Inputs are validated, provenance-carrying values.
  * Every line is computed once, at its correct scope. Nothing is double-counted.
  * When evidence does not determine an answer, the engine ABSTAINS on that line.
    Abstention is a first-class result, not an error.
  * A reconciliation identity is asserted on every run.
  * Money is strictly integer minor units (Invariant I1).
  * Timing intervals are strictly integer seconds (Invariant I2).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from .corpus import Corpus, Rule
from .model import (
    Assumption,
    CancellationRequest,
    Confidence,
    LedgerLine,
    Result,
    ReviewStatus,
    Ticket,
    TimeBasis,
    TimelineStatus,
    TotalStatus,
)
from .timeline import validate_timeline
from .timeutil import calendar_days_between, elapsed_days, hours_display, seconds_between


def preset_t_minus(ticket: Ticket, hours: int = 120) -> CancellationRequest:
    """Helper for callers requesting a convenience T-minus preset instant."""
    if ticket.scheduled_departure.tzinfo is None:
        raise ValueError(
            "scheduled_departure must be timezone-aware. A naive datetime cannot "
            "be positioned on the real timeline and would silently mis-place the "
            "boundary."
        )
    return CancellationRequest(
        instant=ticket.scheduled_departure - timedelta(hours=hours),
        basis=TimeBasis.PRESET_T_MINUS,
        preset_label=f"T-{hours}h",
    )


def _evidence_for(rule: Rule, why: str, key_used: Optional[str] = None) -> dict:
    """The evidence pack for one ledger line (requirement R9).

    Everything here comes from the corpus record; nothing is generated. `why` states
    why this rule matches this ticket, so a reader can check the match rather than
    trust it.
    """
    src = rule.source
    return {
        "policy_id": rule.policy_id,
        "rule_source_class": rule.rule_source_class,
        "clause_heading": src.get("clause_heading") or f"{rule.carrier} published cancellation terms",
        "clause_quote": src.get("quote") or src.get("clause_quote"),
        "url": src.get("url"),
        "sha256": src.get("evidence_sha256"),
        "capture_date": src.get("evidence_capture_date") or src.get("capture_date"),
        "retrieved_at": src.get("retrieved"),
        "content_verification": src.get("content_verification"),
        "date_basis": rule.date_basis,
        "stated_effective_from": rule.stated_from.isoformat() if rule.stated_from else None,
        "stated_effective_to": rule.stated_to.isoformat() if rule.stated_to else None,
        "observed_from": rule.observed_from.isoformat() if rule.observed_from else None,
        "observed_to": rule.observed_to.isoformat() if rule.observed_to else None,
        "applicability_key": rule.applicability_key,
        "key_used": key_used,
        "why_it_matches": why,
        "caveats": rule.caveats,
        "disputed": rule.disputed,
    }


class RefundEngine:
    def __init__(self, corpus: Optional[Corpus] = None):
        self.corpus = corpus or Corpus()
        self._unevaluated_free_look: list[str] = []

    def evaluate(self, ticket: Ticket, request: CancellationRequest) -> Result:
        warnings: list[str] = []
        abstained: list[str] = []
        assumptions: list[Assumption] = []
        lines: list[LedgerLine] = []
        excluded_components: list[str] = []
        review_status = ReviewStatus.NOT_REQUIRED

        if request is None:
            # The cancellation instant is the client's most sensitive input; it is never
            # defaulted silently. Callers that want the 5-day scenario must say so.
            raise ValueError(
                "evaluate() requires an explicit CancellationRequest. For the 5-day scenario "
                "call preset_t_minus(ticket, 120) and pass the result, so the instant used is "
                "always visible to the caller and to the report."
            )

        # ---- gate 0: timeline validation -----------------------------
        verdict = validate_timeline(ticket, request)

        if verdict.status is TimelineStatus.BEFORE_BOOKING:
            return Result(
                ticket_number=ticket.ticket_number,
                cancel_instant=request.instant,
                hours_before_departure=hours_display(verdict.seconds_to_departure),
                lines=[],
                refund_total=None,
                confidence=Confidence.INSUFFICIENT,
                warnings=[],
                abstained=[
                    f"Cancellation at {request.instant.isoformat()} precedes the booking on {ticket.booking_date}. "
                    "The timeline is invalid; no calculation is possible."
                ],
                basis=request.basis,
                preset_label=request.preset_label,
                source_ref=request.source_ref,
                seconds_to_departure=verdict.seconds_to_departure,
                timeline_status=verdict.status,
                total_status=TotalStatus.NONE,
            )

        # ---- gate 1: scope refusals -----------------------------------
        refusals = self._refusals(ticket)
        if refusals:
            return Result(
                ticket_number=ticket.ticket_number,
                cancel_instant=request.instant,
                hours_before_departure=hours_display(verdict.seconds_to_departure),
                lines=[],
                refund_total=None,
                confidence=Confidence.INSUFFICIENT,
                warnings=warnings,
                abstained=refusals,
                basis=request.basis,
                preset_label=request.preset_label,
                source_ref=request.source_ref,
                seconds_to_departure=verdict.seconds_to_departure,
                timeline_status=verdict.status,
                total_status=TotalStatus.NONE,
            )

        # ---- gate 2: arithmetic integrity of the document -------------
        if ticket.total_paid is not None:
            delta = ticket.component_sum() - ticket.total_paid
            if not delta.is_zero():
                return Result(
                    ticket_number=ticket.ticket_number,
                    cancel_instant=request.instant,
                    hours_before_departure=hours_display(verdict.seconds_to_departure),
                    lines=[],
                    refund_total=None,
                    confidence=Confidence.INSUFFICIENT,
                    warnings=warnings,
                    abstained=[
                        f"Document does not reconcile: components {ticket.component_sum()} "
                        f"vs stated total {ticket.total_paid} (delta {delta}). "
                        "Refusing to adjust components to force a match."
                    ],
                    basis=request.basis,
                    preset_label=request.preset_label,
                    source_ref=request.source_ref,
                    seconds_to_departure=verdict.seconds_to_departure,
                    timeline_status=verdict.status,
                    total_status=TotalStatus.NONE,
                )

        # ---- statutory layer (runs for EVERY carrier) -----------------
        stat_lines, stat_conf, unclassified_taxes = self._statutory_taxes(ticket)
        lines.extend(stat_lines)
        for code, amount in unclassified_taxes:
            # A tax we cannot classify is not a tax we can refuse — it is one we cannot
            # establish. Say so, and never let the total read COMPLETE without it.
            abstained.append(
                f"Tax {code} ({amount}): this code is not in the statutory registry, so its "
                "refundability cannot be established. It is excluded from the total rather than "
                "assumed non-refundable. If the document shows a single combined 'taxes and fees' "
                "figure, itemise it by code to settle this."
            )
            excluded_components.append(f"Tax {code} (code not in the statutory registry)")
            review_status = ReviewStatus.REVIEW_REQUIRED

        # ---- carrier surcharges: never statutory ----------------------
        zero = ticket.base_fare.__class__.zero(ticket.currency)
        for s in ticket.carrier_surcharges:
            lines.append(
                LedgerLine(
                    label=f"Carrier surcharge {s.code}",
                    original=s.amount,
                    treatment="follows fare rule, not statute",
                    contribution=zero,
                    confidence=Confidence.INSUFFICIENT,
                    basis="YQ/YR are carrier-imposed, not statutory taxes. Their refundability "
                    "follows the fare rule, which is not retrievable for this ticket.",
                )
            )
            abstained.append(f"Carrier surcharge {s.code}: refundability not determinable")
            excluded_components.append(f"Carrier surcharge {s.code} (follows fare rule)")

        # ---- fare / penalty layer -------------------------------------
        tz = ZoneInfo(ticket.departure_timezone)
        cancel_date = request.instant.astimezone(tz).date()

        resolution = self.corpus.resolve(
            carrier=ticket.carrier,
            market=ticket.market,
            fare_family=ticket.fare_family,
            booking_date=ticket.booking_date,
            cancel_date=cancel_date,
            cause=request.cause,
            ticket_state={"reissued": ticket.reissued, "partially_used": ticket.partially_used},
        )
        rule = resolution.rule
        conflicts: list[str] = []
        # A version disagreement IS a conflict between sources, not merely a missing
        # value — surface it under its own heading so a reader can see what disagrees.
        if resolution.abstention_reason and "cannot be established" in resolution.abstention_reason:
            conflicts.append(resolution.abstention_reason)
        if rule is not None:
            for cw in getattr(rule, "conflicts_with", []):
                conflicts.append(
                    f"{rule.policy_id} vs {cw.get('policy_id','another source')}: {cw.get('detail','')}"
                )
                review_status = ReviewStatus.REVIEW_REQUIRED
        assumptions.extend(resolution.assumptions)
        if any(a.material for a in resolution.assumptions):
            review_status = ReviewStatus.REVIEW_REQUIRED

        # `detail` already opens with the policy id, so prefixing it again produced
        # "SG-...: SG-...: temporally invalid". Keep the sentence clean, and carry the
        # structured form separately for consumers that render the fields apart.
        rejected = [
            r.detail if r.detail.startswith(r.policy_id) else f"{r.policy_id}: {r.detail}"
            for r in resolution.rejections
        ]
        rejections_structured = [
            {"policy_id": r.policy_id, "reason_code": r.reason_code, "detail": r.detail}
            for r in resolution.rejections
        ]
        rule_id = rule.policy_id if rule else None
        rule_src = rule.source.get("url") if rule else None
        fare_conf = Confidence.INSUFFICIENT

        if ticket.account_code or ticket.is_corporate_fare:
            # A corporate/negotiated fare is governed by the client's agreement, not by
            # the published retail table. That agreement is a supplyable document, so
            # this is a missing-evidence abstention on one line — not an impossibility,
            # and not a statement about what carriers do or do not publish.
            reason = (
                "A corporate or negotiated fare is indicated, so the published retail table does not "
                "govern this ticket. Supply the applicable corporate agreement or the fare conditions "
                "issued with the ticket to compute the fare component."
            )
            abstained.append(f"Fare component: {reason}")
            excluded_components.append("Base fare (corporate agreement not supplied)")
            review_status = ReviewStatus.REVIEW_REQUIRED
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=ticket.base_fare,
                    treatment="undetermined — corporate fare",
                    contribution=zero,
                    confidence=Confidence.INSUFFICIENT,
                    basis=reason,
                )
            )
        elif resolution.abstention_reason:
            abstained.append(f"Fare component: {resolution.abstention_reason}")
            excluded_components.append("Base fare (version disagreement / missing evidence)")
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=ticket.base_fare,
                    treatment="undetermined",
                    contribution=zero,
                    confidence=Confidence.INSUFFICIENT,
                    basis=resolution.abstention_reason,
                )
            )
        elif rule is None:
            reason = (
                "No temporally valid published policy for this carrier/fare/date. "
                if ticket.fare_family
                else "Fare family not present on the ticket, so no policy row can be selected. "
            )
            abstained.append("Fare component: " + reason + "Engine abstains rather than guessing.")
            excluded_components.append("Base fare (fare conditions not established)")
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=ticket.base_fare,
                    treatment="undetermined",
                    contribution=zero,
                    confidence=Confidence.INSUFFICIENT,
                    basis=reason.strip(),
                )
            )
        elif verdict.status is TimelineStatus.AT_OR_AFTER_DEPARTURE and not getattr(rule, "supports_post_departure", False):
            # Post-departure: advance cancellation table does not apply; statutory tax line still applies
            reason = "Cancellation at or after departure. No no-show provision is recorded for this rule, so the advance-cancellation table is not applied."
            abstained.append(f"Fare component: {reason}")
            excluded_components.append("Base fare (post-departure / no-show provision not recorded)")
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=ticket.base_fare,
                    treatment="undetermined (post-departure)",
                    contribution=zero,
                    confidence=Confidence.INSUFFICIENT,
                    basis=reason,
                    source_url=rule.source.get("url"),
                )
            )
        elif rule.requires_booking_instant and (
            ticket.booking_instant is None or verdict.status is TimelineStatus.SAME_DAY_AS_BOOKING_TIME_UNKNOWN
        ):
            reason = "This rule depends on hours since booking; the booking time is not present on the supplied documents and must not be assumed."
            abstained.append(f"Fare component: {reason}")
            excluded_components.append("Base fare (booking time unknown)")
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=ticket.base_fare,
                    treatment="undetermined",
                    contribution=zero,
                    confidence=Confidence.INSUFFICIENT,
                    basis=reason,
                    source_url=rule.source.get("url"),
                )
            )
        else:
            self._unevaluated_free_look = []
            fare_lines, fare_conf, notes, abst = self._fare_component(
                ticket, rule, verdict.seconds_to_departure, request.instant
            )
            # Attach the evidence pack to every line this rule produced (R9). The
            # calculation is already done; this only exposes what backed it.
            key_date = (
                ticket.booking_date
                if resolution.key_used in ("BOOKING_DATE", "BOTH_AGREE")
                else cancel_date
            )
            why = (
                f"Carrier {ticket.carrier} matches; market {ticket.market} matches; "
                f"fare family {ticket.fare_family or 'not printed'} matches {rule.fare_families}; "
                f"applicability keyed to {resolution.key_used} ({key_date}) falls inside this rule's "
                f"{rule.date_basis.lower()} window; cancellation at "
                f"T-{hours_display(verdict.seconds_to_departure)}h selects its band."
            )
            ev = _evidence_for(rule, why, resolution.key_used)
            for line in fare_lines:
                if line.evidence is None:
                    line.evidence = ev
            lines.extend(fare_lines)
            warnings.extend(notes)
            abstained.extend(abst)
            for pid in self._unevaluated_free_look:
                assumptions.append(Assumption(
                    code="NIL_FEE_CONDITION_UNEVALUATED",
                    detail=(f"{pid}: the published nil-fee condition could not be evaluated because the "
                            "booking time is not on the document. The fee shown assumes it does not apply."),
                    material=True,
                ))
                review_status = ReviewStatus.REVIEW_REQUIRED
            if any(l.confidence is Confidence.INSUFFICIENT for l in fare_lines if l.label == "Base fare"):
                excluded_components.append("Base fare (fee not captured or inside cutoff)")
                review_status = ReviewStatus.REVIEW_REQUIRED

        # ---- seller fees ----------------------------------------------
        for f in ticket.seller_fees:
            lines.append(
                LedgerLine(
                    label=f"Seller fee {f.code}",
                    original=f.amount,
                    treatment="non-refundable (separately disclosed)",
                    contribution=f.amount.__class__.zero(ticket.currency),
                    confidence=Confidence.MEDIUM,
                    basis="Separately disclosed intermediary charge; excluded from the airline "
                    "refund pool and not subtracted again from it.",
                )
            )

        # ---- total & confidence (WP-4.2) -----------------------------
        refund = None
        overall = Confidence.INSUFFICIENT
        total_status = TotalStatus.NONE

        if fare_conf is not Confidence.INSUFFICIENT or stat_conf is not Confidence.INSUFFICIENT:
            contributions = [l.contribution for l in lines]
            refund = contributions[0].__class__.total(contributions, ticket.currency) if contributions else None

            # Material lines determine confidence rollup (WP-4.2)
            material = [l for l in lines if not l.contribution.is_zero() or l.label in ("Base fare", "Cancellation penalty")]
            determined = [l.confidence for l in material if l.confidence is not Confidence.INSUFFICIENT]

            overall = min(determined, key=lambda c: _rank(c)) if determined else Confidence.INSUFFICIENT

            has_abstained_material = any(
                l.confidence is Confidence.INSUFFICIENT for l in material
            ) or bool(excluded_components)

            if has_abstained_material:
                total_status = TotalStatus.PARTIAL
            else:
                total_status = TotalStatus.COMPLETE

            if abstained:
                overall = overall.cap(Confidence.LOW)

        # ---- invariants ------------------------------------------------
        if refund is not None:
            if refund.is_negative():
                raise AssertionError("INVARIANT VIOLATED: refund is negative")
            if ticket.total_paid is not None and ticket.total_paid < refund:
                raise AssertionError("INVARIANT VIOLATED: refund exceeds amount paid")

        return Result(
            ticket_number=ticket.ticket_number,
            cancel_instant=request.instant,
            hours_before_departure=hours_display(verdict.seconds_to_departure),
            lines=lines,
            refund_total=refund,
            confidence=overall,
            warnings=warnings,
            abstained=abstained,
            rule_id=rule_id,
            rule_source=rule_src,
            rejected_rules=rejected,
            rejections=rejections_structured,
            conflicts=conflicts,
            basis=request.basis,
            preset_label=request.preset_label,
            source_ref=request.source_ref,
            seconds_to_departure=verdict.seconds_to_departure,
            timeline_status=verdict.status,
            total_status=total_status,
            excluded_components=excluded_components,
            assumptions=assumptions,
            review_status=review_status,
        )

    def _refusals(self, t: Ticket) -> list[str]:
        out = []
        if t.reissued:
            out.append("Ticket was reissued. The exchange chain is required and is out of scope.")
        if t.partially_used:
            out.append("Ticket is partially used. Flown value must be repriced, not prorated. Out of scope.")
        if t.passengers != 1:
            out.append(
                f"Scope limit: {t.passengers} passengers. Per-passenger vs per-ticket penalty scope is not "
                "determinable from the documents supplied. Supply the fare conditions or a per-passenger refund breakdown to lift this."
            )
        # NOTE: a corporate/negotiated fare is deliberately NOT a whole-case refusal.
        # It abstains on the fare line only (see _fare_component), because the statutory
        # line is computable for it and a partial result is more useful than none.
        if t.currency != "INR":
            out.append(f"Currency {t.currency}. Multi-currency is out of scope.")
        return out

    def _statutory_taxes(self, t: Ticket):
        """The one line that reaches HIGH for every Indian carrier.

        Returns (lines, best_confidence, unclassified) — `unclassified` names any tax
        code we could not place in the registry. Those amounts contribute nothing, and
        the caller MUST surface them: an OTA invoice that prints one lumped
        "Taxes & fees" figure lands here, and silently dropping it understates the
        refund while the total still reads COMPLETE.
        """
        prov = self.corpus.statutory_tax_provision()
        stat_ev = {
            "policy_id": prov["instrument"],
            "rule_source_class": "REGULATORY_INSTRUMENT",
            "clause_heading": prov.get("provision_id"),
            "clause_quote": prov.get("rule"),
            "url": (prov.get("source") or {}).get("url"),
            "sha256": (prov.get("source") or {}).get("evidence_sha256"),
            "capture_date": None,
            "retrieved_at": (prov.get("source") or {}).get("retrieved"),
            "content_verification": (prov.get("source") or {}).get("note"),
            "date_basis": "STATUTE",
            "applicability_key": "OPERATING_PERMIT",
            "why_it_matches": (
                f"The obligation derives from {prov['authority']} and attaches to the operating permit, "
                "not to fare filing or distribution technology, so it binds this carrier regardless of PSS."
            ),
            "caveats": [],
            "disputed": False,
        }
        lines: list[LedgerLine] = []
        best = Confidence.INSUFFICIENT
        unclassified: list[tuple[str, object]] = []

        for tax in t.taxes:
            info = self.corpus.classify_tax(tax.code)
            if info is None:
                lines.append(
                    LedgerLine(
                        label=f"Tax {tax.code}",
                        original=tax.amount,
                        treatment="unclassified",
                        contribution=tax.amount.__class__.zero(t.currency),
                        confidence=Confidence.INSUFFICIENT,
                        basis=f"Tax code {tax.code} is not in the registry. Not assumed refundable.",
                        evidence=stat_ev,
                    )
                )
                unclassified.append((tax.code, tax.amount))
                continue

            if info["refundable_by_statute"]:
                lines.append(
                    LedgerLine(
                        label=f"Tax {tax.code} ({info['name']})",
                        original=tax.amount,
                        treatment="refundable by statute",
                        contribution=tax.amount,
                        confidence=Confidence.HIGH,
                        basis=(
                            f"{prov['instrument']} — {prov['rule']} "
                            f"Obligation attaches to the operating permit ({prov['authority']}), "
                            "not to fare filing, so it binds this carrier regardless of PSS."
                        ),
                        source_url=None,
                        classification_confidence=Confidence.HIGH,
                        evidence=stat_ev,
                    )
                )
                best = Confidence.HIGH
            else:
                lines.append(
                    LedgerLine(
                        label=f"Tax {tax.code} ({info['name']})",
                        original=tax.amount,
                        treatment="not statutory",
                        contribution=tax.amount.__class__.zero(t.currency),
                        confidence=Confidence.HIGH,
                        basis=info["note"],
                        evidence=stat_ev,
                        classification_confidence=Confidence.HIGH,
                    )
                )
        return lines, best, unclassified

    def _fare_component(
        self,
        t: Ticket,
        rule: Rule,
        seconds_before: int,
        canc_instant: datetime,
    ):
        lines: list[LedgerLine] = []
        notes: list[str] = []
        abst: list[str] = []
        unevaluated_free_look: list[str] = self._unevaluated_free_look
        zero = t.base_fare.__class__.zero(t.currency)

        # ---- published nil-fee condition, where the rule carries one ----------
        # Some carriers publish a condition that zeroes the cancellation fee — e.g.
        # SpiceJet condition A: cancelled within 24h of booking AND departure more than
        # seven days away. It keys off the booking TIME, which most documents do not
        # print. When we cannot evaluate it we say so; we never assume it does not apply,
        # because that assumption silently costs the passenger the whole fee.
        fl = rule.free_look
        fl_applies = False
        if fl:
            far_enough = seconds_before >= int(fl.get("min_seconds_to_departure", 0))
            if t.booking_instant is not None:
                since_booking = seconds_between(t.booking_instant, canc_instant)
                within = 0 <= since_booking <= int(fl.get("within_hours_of_booking", 0)) * 3600
                if within and far_enough:
                    fl_applies = True
                    notes.append(
                        f"{rule.policy_id}: the published nil-fee condition applies "
                        f"(cancelled {hours_display(since_booking)}h after booking, departure "
                        f"{hours_display(seconds_before)}h away). {fl.get('condition_note','')}".strip()
                    )
                else:
                    notes.append(
                        f"{rule.policy_id}: the published nil-fee condition was evaluated and does "
                        "not apply to this cancellation."
                    )
            elif far_enough:
                # Booking time unknown and the departure test passes, so the condition
                # MIGHT apply. The banded fee below is therefore conditional, not settled.
                unevaluated_free_look.append(rule.policy_id)
                abst.append(
                    f"{rule.policy_id}: this fare carries a published NIL cancellation fee where the "
                    f"cancellation is made within {fl.get('within_hours_of_booking')}h of booking and "
                    "departure is more than seven days away. The booking TIME is not present on the "
                    "supplied documents, so this condition could not be evaluated. The fee below assumes "
                    "it does not apply — supply the booking timestamp to settle it."
                )

        if fl_applies:
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=t.base_fare,
                    treatment="refundable in full under the published nil-fee condition",
                    contribution=t.base_fare,
                    confidence=rule.ceiling,
                    basis=f"{rule.policy_id}: {fl.get('quote','')}",
                    source_url=rule.source.get("url"),
                )
            )
            lines.append(
                LedgerLine(
                    label="Cancellation penalty",
                    original=None,
                    treatment="nil under the published condition",
                    contribution=zero,
                    confidence=rule.ceiling,
                    basis=f"No cancellation fee. {fl.get('condition_note','')}".strip(),
                    source_url=rule.source.get("url"),
                )
            )
            return lines, rule.ceiling, notes, abst

        # Cutoff check (WP-3.2)
        cutoff_sec = rule.cutoff_seconds
        if cutoff_sec and seconds_before < cutoff_sec:
            abst.append(
                f"Cancellation at T-{hours_display(seconds_before)}h is inside the carrier's "
                f"{rule.cutoff_h}h cut-off; a different regime applies."
            )
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=t.base_fare,
                    treatment="inside carrier cut-off",
                    contribution=zero,
                    confidence=Confidence.INSUFFICIENT,
                    basis=f"Cancellation inside carrier cut-off ({rule.cutoff_h}h prior to departure).",
                    source_url=rule.source.get("url"),
                )
            )
            return lines, Confidence.INSUFFICIENT, notes, abst

        # Day-denominated rule check (WP-3.3)
        band = None
        if rule.band_unit == "DAYS" and rule.day_boundary is None:
            tz = ZoneInfo(t.departure_timezone)
            band_elapsed = rule.band_for_days(elapsed_days(seconds_before))
            band_cal = rule.band_for_days(
                calendar_days_between(t.scheduled_departure, canc_instant, tz)
            )
            if band_elapsed is not None and band_cal is not None and band_elapsed == band_cal:
                band = band_elapsed
                notes.append(
                    f"{rule.policy_id}: rule is day-denominated; 24h-elapsed and calendar-day readings agree."
                )
            else:
                fee_a = (
                    band_elapsed["fee"].get("amount_minor", "N/A")
                    if band_elapsed and "fee" in band_elapsed
                    else "None"
                )
                fee_b = (
                    band_cal["fee"].get("amount_minor", "N/A")
                    if band_cal and "fee" in band_cal
                    else "None"
                )
                abst_msg = (
                    f"{rule.policy_id}: day-denominated rule has ambiguous reading. "
                    f"Elapsed-days reading yields band fee {fee_a}; calendar-days reading yields fee {fee_b}. "
                    "The source does not define the day-boundary."
                )
                abst.append(abst_msg)
                lines.append(
                    LedgerLine(
                        label="Base fare",
                        original=t.base_fare,
                        treatment="ambiguous day-unit reading",
                        contribution=zero,
                        confidence=Confidence.INSUFFICIENT,
                        basis=abst_msg,
                        source_url=rule.source.get("url"),
                    )
                )
                return lines, Confidence.INSUFFICIENT, notes, abst
        elif rule.band_unit == "DAYS" and rule.day_boundary == "MIDNIGHT_LOCAL":
            tz = ZoneInfo(t.departure_timezone)
            band = rule.band_for_days(
                calendar_days_between(t.scheduled_departure, canc_instant, tz)
            )
        elif rule.band_unit == "DAYS" and rule.day_boundary == "SAME_TIME_OF_DAY":
            band = rule.band_for_days(elapsed_days(seconds_before))
        else:
            band = rule.band_for(seconds_before)

        if band is None:
            abst.append(f"No band in {rule.policy_id} covers T-{hours_display(seconds_before)}h.")
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=t.base_fare,
                    treatment="undetermined",
                    contribution=zero,
                    confidence=Confidence.INSUFFICIENT,
                    basis=f"No band in {rule.policy_id} covers T-{hours_display(seconds_before)}h.",
                    source_url=rule.source.get("url"),
                )
            )
            return lines, Confidence.INSUFFICIENT, notes, abst

        fee_spec = band["fee"]
        kind = fee_spec["kind"]
        ceiling = rule.ceiling

        for c in rule.caveats:
            notes.append(f"{rule.policy_id}: {c}")
        if rule.date_basis == "OBSERVED":
            notes.append(
                f"{rule.policy_id}: effective date is OBSERVED, not stated by the carrier. "
                "We know the rule was visible on the capture date; we do not know when it "
                "started. Confidence capped at LOW."
            )
        if any("DAY-based" in c or "Days" in c for c in rule.caveats) and rule.band_unit != "DAYS":
            notes.append(
                "Rule is day-denominated. '5 days' and '120 hours' are not guaranteed to be "
                "the same instant under a day-unit rule with a time-of-day cutoff."
            )

        if kind == "UNKNOWN":
            abst_msg = (
                f"{rule.policy_id}: the fee for this band was never captured. "
                "Abstaining rather than interpolating from adjacent bands."
            )
            abst.append(abst_msg)
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=t.base_fare,
                    treatment="uncaptured band fee",
                    contribution=zero,
                    confidence=Confidence.INSUFFICIENT,
                    basis=abst_msg,
                    source_url=rule.source.get("url"),
                )
            )
            return lines, Confidence.INSUFFICIENT, notes, abst

        if kind == "FARE_FULLY_FORFEITED":
            lines.append(
                LedgerLine(
                    label="Base fare",
                    original=t.base_fare,
                    treatment="wholly forfeited under the fare rule",
                    contribution=zero,
                    confidence=ceiling,
                    basis=f"{rule.policy_id}: {rule.source.get('quote', '')[:180]}",
                    source_url=rule.source.get("url"),
                )
            )
            notes.append(
                "Fare is non-refundable. Recorded ONCE as a forfeited fare — no separate "
                "100% penalty line is added, which would double-count the same restriction."
            )
            return lines, ceiling, notes, abst

        # FIXED or LESSER_OF
        penalty = t.base_fare.__class__(fee_spec["amount_minor"], t.currency)
        cap_note = ""
        if kind == "LESSER_OF" and fee_spec.get("cap") == "BASE_PLUS_FUEL_SURCHARGE":
            fuel = (
                t.base_fare.__class__.total([s.amount for s in t.carrier_surcharges], t.currency)
                if t.carrier_surcharges
                else zero
            )
            cap = t.base_fare + fuel
            if cap < penalty:
                penalty = cap
                cap_note = (
                    " Capped at base fare + fuel surcharge, per the carrier's own "
                    "published wording ('whichever is lower')."
                )
        elif kind == "LESSER_OF" and fee_spec.get("cap") == "AIRFARE_100PCT":
            # "INR X or 100% of the airfare charge (whichever is lower)" — Akasa's wording.
            # The cap is the fare itself, so a cheap ticket can never owe more than it cost.
            if t.base_fare < penalty:
                penalty = t.base_fare
                cap_note = (
                    " Capped at 100% of the airfare, per the carrier's own published wording "
                    "('whichever is lower')."
                )
        elif kind == "LESSER_OF":
            # An unrecognised cap must not be silently ignored — that would overstate the fee.
            raise ValueError(
                f"Unsupported LESSER_OF cap {fee_spec.get('cap')!r}. Refusing to apply the "
                "uncapped amount, which would overstate the cancellation charge."
            )

        refundable_pool = t.base_fare
        contribution = refundable_pool - penalty
        if contribution.is_negative():
            contribution = zero
            notes.append(
                "Penalty exceeds the base fare; fare contribution floored at zero "
                "rather than allowed to go negative."
            )

        lines.append(
            LedgerLine(
                label="Base fare",
                original=t.base_fare,
                treatment="refundable, less cancellation penalty",
                contribution=contribution,
                confidence=ceiling,
                basis=(
                    f"{rule.policy_id}: band T-{band.get('from_h', band.get('from_seconds', 0)//3600)}h"
                    f"{'+' if (band.get('to_h') is None and band.get('to_seconds') is None) else '–' + str(band.get('to_h', (band.get('to_seconds') or 0)//3600)) + 'h'}, "
                    f"penalty {penalty}.{cap_note}"
                ),
                source_url=rule.source.get("url"),
            )
        )
        lines.append(
            LedgerLine(
                label="Cancellation penalty",
                original=None,
                treatment="applied once, per ticket",
                contribution=zero,
                confidence=ceiling,
                basis=f"{penalty} — shown for transparency; already deducted from the base-fare "
                "line above and deliberately NOT subtracted a second time.",
                source_url=rule.source.get("url"),
            )
        )
        return lines, ceiling, notes, abst


def _rank(c: Confidence) -> int:
    return [
        Confidence.INSUFFICIENT,
        Confidence.LOW,
        Confidence.MEDIUM,
        Confidence.HIGH,
        Confidence.AUTHORITATIVE,
    ].index(c)
