"""Corpus loader and the temporal rule resolver.

The resolver is the safety-critical part: it must never return a rule that was not in
force for the ticket in question. Temporal filtering happens FIRST and is absolute —
there is no similarity scoring anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import json
import os
from pathlib import Path
from typing import Optional

from .model import Assumption, Confidence, Provenance

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"

RULE_SOURCE_CLASS_ORDER = {
    "TICKET_CONDITIONS": 5,
    "CLIENT_CONTRACT": 4,
    "CARRIER_MANDATORY_DISCLOSURE": 3,
    "CARRIER_PUBLISHED_PAGE_STATED": 2,
    "CARRIER_PUBLISHED_PAGE_OBSERVED": 1,
}

CONFIDENCE_ORDER = [
    Confidence.INSUFFICIENT,
    Confidence.LOW,
    Confidence.MEDIUM,
    Confidence.HIGH,
    Confidence.AUTHORITATIVE,
]


def _d(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


@dataclass(frozen=True)
class RuleRejection:
    policy_id: str
    reason_code: str  # MARKET | FARE_FAMILY | TEMPORAL | WEAKER_EVIDENCE | HORIZON | QUARANTINED | APPLIES_TO | AMBIGUOUS
    detail: str


@dataclass(frozen=True)
class Resolution:
    rule: Optional["Rule"]
    rejections: list[RuleRejection]
    key_used: str  # BOOKING_DATE | CANCELLATION_DATE | BOTH_AGREE | UNKNOWN
    ambiguous_with: list[str] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    abstention_reason: Optional[str] = None

    def __iter__(self):
        # Backward compatibility with `rule, rejections = corpus.resolve(...)`
        yield self.rule
        yield [r.detail for r in self.rejections]


class Rule:
    def __init__(self, raw: dict):
        self.raw = raw
        self.policy_id: str = raw["policy_id"]
        self.carrier: str = raw["carrier"]
        self.market: str = raw["market"]
        self.fare_families: list[str] = raw["fare_family"].split("|")
        self.provenance = Provenance(raw["provenance"])
        self.date_basis: str = raw["date_basis"]          # STATED | OBSERVED
        self.applicability_key: str = raw["applicability_key"]
        self.stated_from = _d(raw.get("stated_effective_from"))
        self.stated_to = _d(raw.get("stated_effective_to"))
        self.observed_from = _d(raw.get("observed_from"))
        self.observed_to = _d(raw.get("observed_to"))
        self.bands: list[dict] = raw["bands"]
        self.source: dict = raw["source"]
        self.caveats: list[str] = raw.get("caveats", [])
        self.disputed: bool = raw.get("disputed", False)
        self.cutoff_h = raw.get("cutoff_hours_before_departure")
        self.cutoff_seconds = raw.get(
            "cutoff_seconds_before_departure",
            (int(self.cutoff_h * 3600)) if self.cutoff_h is not None else None,
        )
        self.non_refundable_fees: list[dict] = raw.get("non_refundable_fees", [])
        # A published condition that can zero the fee but depends on the booking TIME.
        # Absent from the corpus until 2026-09-08; see the SpiceJet caveat.
        self.free_look: Optional[dict] = raw.get("free_look")
        # Sources that disagree with this one for an overlapping period. Recorded so a
        # reader sees the disagreement rather than only the winner.
        self.conflicts_with: list[dict] = raw.get("conflicts_with", [])

        # Schema v2 / WP additions
        self.supports_post_departure: bool = raw.get("supports_post_departure", False)
        self.requires_booking_instant: bool = raw.get("requires_booking_instant", False)
        default_source_class = (
            "CARRIER_PUBLISHED_PAGE_STATED"
            if self.date_basis == "STATED"
            else "CARRIER_PUBLISHED_PAGE_OBSERVED"
        )
        self.rule_source_class: str = raw.get("rule_source_class", default_source_class)
        self.applies_to: dict = raw.get(
            "applies_to",
            {
                "passenger_initiated": True,
                "carrier_disruption": False,
                "unused_only": True,
                "single_sector": True,
            },
        )
        self.band_unit: str = raw.get("band_unit", "HOURS")
        self.day_boundary: Optional[str] = raw.get("day_boundary", None)

    @property
    def ceiling(self) -> Confidence:
        if self.disputed:
            return Confidence.LOW
        if self.provenance is Provenance.FILED_RULE:
            return Confidence.HIGH
        if self.date_basis == "STATED":
            return Confidence.MEDIUM
        return Confidence.LOW           # OBSERVED — true rule start unknown

    def matches_fare_family(self, ff: Optional[str]) -> bool:
        if self.fare_families == ["*"]:
            return True
        if ff is None:
            return False                 # cannot pick a row without knowing the fare
        return ff.upper() in [f.upper() for f in self.fare_families]

    def check_temporal(
        self,
        key_date: date,
        carrier_observed_through: Optional[date] = None,
        max_projection_days: int = 30,
    ) -> tuple[bool, Optional[RuleRejection], Optional[Assumption]]:
        """Temporal check against a given key date, taking into account stated vs observed and evidence horizons."""
        if self.date_basis == "STATED":
            if self.stated_from and key_date < self.stated_from:
                return (
                    False,
                    RuleRejection(
                        self.policy_id,
                        "TEMPORAL",
                        f"{self.policy_id}: temporally invalid (key date {key_date} precedes stated effective date {self.stated_from})",
                    ),
                    None,
                )
            if self.stated_to and key_date >= self.stated_to:
                return (
                    False,
                    RuleRejection(
                        self.policy_id,
                        "TEMPORAL",
                        f"{self.policy_id}: temporally invalid (key date {key_date} is on or after stated superseded date {self.stated_to})",
                    ),
                    None,
                )
            return True, None, None

        # OBSERVED
        if self.observed_from and key_date < self.observed_from:
            return (
                False,
                RuleRejection(
                    self.policy_id,
                    "TEMPORAL",
                    f"{self.policy_id}: temporally invalid (key date {key_date} precedes earliest capture held {self.observed_from})",
                ),
                None,
            )
        if self.observed_to and key_date >= self.observed_to:
            return (
                False,
                RuleRejection(
                    self.policy_id,
                    "TEMPORAL",
                    f"{self.policy_id}: temporally invalid (key date {key_date} is on or after next capture date {self.observed_to})",
                ),
                None,
            )
        if self.observed_to is None:
            if carrier_observed_through is not None and key_date > carrier_observed_through:
                delta_days = (key_date - carrier_observed_through).days
                if delta_days <= max_projection_days:
                    assumption = Assumption(
                        code="FORWARD_PROJECTION",
                        detail=f"No capture exists after {carrier_observed_through}; this result assumes the rule was unchanged for a further {delta_days} days",
                        material=True,
                    )
                    return True, None, assumption
                else:
                    return (
                        False,
                        RuleRejection(
                            self.policy_id,
                            "HORIZON",
                            f"{self.policy_id}: key date {key_date} is {delta_days} days beyond evidence horizon {carrier_observed_through} (limit {max_projection_days} days)",
                        ),
                        None,
                    )
        return True, None, None

    def band_for(self, seconds: int) -> Optional[dict]:
        """Integer-second band evaluation (Invariant I2)."""
        if not isinstance(seconds, int):
            raise TypeError(f"seconds must be an integer, got {type(seconds).__name__}")
        for b in self.bands:
            if "from_seconds" in b:
                lo = b["from_seconds"]
                hi = b.get("to_seconds")
            else:
                lo = int(b["from_h"] * 3600)
                hi = int(b["to_h"] * 3600) if b.get("to_h") is not None else None
            if seconds >= lo and (hi is None or seconds < hi):
                return b
        return None

    def band_for_days(self, days: int) -> Optional[dict]:
        """Day-unit band evaluation."""
        if not isinstance(days, int):
            raise TypeError(f"days must be an integer, got {type(days).__name__}")
        for b in self.bands:
            if "from_days" in b:
                lo = b["from_days"]
                hi = b.get("to_days")
            elif "from_seconds" in b:
                lo = b["from_seconds"] // 86400
                hi = (b["to_seconds"] // 86400) if b.get("to_seconds") is not None else None
            else:
                lo = b["from_h"] // 24
                hi = (b["to_h"] // 24) if b.get("to_h") is not None else None
            if days >= lo and (hi is None or days < hi):
                return b
        return None

    def __repr__(self) -> str:
        return f"<Rule {self.policy_id} {self.date_basis} ceiling={self.ceiling.value}>"


class Corpus:
    def __init__(self, policies_path: Path = None, regulatory_path: Path = None):
        p = policies_path or CORPUS_DIR / "policies.json"
        r = regulatory_path or CORPUS_DIR / "regulatory.json"
        self.policies_path = p
        self.regulatory_path = r
        self.policies_raw = json.loads(p.read_text(encoding="utf-8"))
        self.regulatory = json.loads(r.read_text(encoding="utf-8"))
        self.carriers = self.policies_raw["carriers"]
        self.tax_codes = {t["code"]: t for t in self.regulatory["tax_codes"]}
        self.version = self.policies_raw["corpus_version"]
        self.max_projection_days = self.policies_raw.get("max_projection_days", 30)

        # Build observed_through per carrier
        self.carrier_observed_through: dict[str, Optional[date]] = {}
        for car, cdata in self.carriers.items():
            ot = cdata.get("observed_through")
            self.carrier_observed_through[car] = _d(ot) if ot else None

        # Evidence verification and quarantine (WP-5)
        self.rules: list[Rule] = []
        self.quarantined: list[dict] = []
        self._load_rules()

    def _load_rules(self):
        allow_unverified = os.environ.get("ALLOW_UNVERIFIED_EVIDENCE") == "1"
        evidence_dir = CORPUS_DIR / "evidence"

        for raw_rule in self.policies_raw["policies"]:
            rule = Rule(raw_rule)
            # The evidence horizon is a declared property of the corpus, not something
            # inferred from rule dates. Only fall back to a derived value where the
            # carrier block does not declare one, and never let a rule date widen a
            # declared horizon — that would project past the evidence actually held.
            car = rule.carrier
            if self.carrier_observed_through.get(car) is None:
                cand_date = rule.observed_to or rule.observed_from or rule.stated_to or rule.stated_from
                if cand_date:
                    self.carrier_observed_through[car] = cand_date

            # A rule we have positive reason to believe is mis-transcribed must not
            # serve figures at ANY confidence. LOW is a statement about the strength of
            # the source, not a licence to publish a number read off the wrong axis.
            if raw_rule.get("structurally_unverified"):
                self.quarantined.append({
                    "policy_id": rule.policy_id,
                    "reason": "Structurally unverified: " + raw_rule["structurally_unverified"]["reason"],
                })
                continue

            # Evidence integrity gate (Invariant I7). A rule with no preserved,
            # hash-matching copy is quarantined and never reaches resolution.
            source = raw_rule.get("source", {})
            sha = source.get("evidence_sha256")
            if not sha:
                if not allow_unverified:
                    self.quarantined.append(
                        {"policy_id": rule.policy_id, "reason": "No evidence_sha256 recorded on the rule source"}
                    )
                    continue
            else:
                # Verify file in evidence_dir
                import hashlib
                matched_file = None
                if evidence_dir.exists():
                    for f in evidence_dir.glob(f"{sha}*"):
                        if not f.name.endswith(".meta.json"):
                            matched_file = f
                            break
                if matched_file is None or not matched_file.exists():
                    if not allow_unverified:
                        self.quarantined.append({"policy_id": rule.policy_id, "reason": f"Evidence file {sha} not found"})
                        continue
                else:
                    file_bytes = matched_file.read_bytes()
                    computed = hashlib.sha256(file_bytes).hexdigest()
                    if computed.lower() != sha.lower():
                        self.quarantined.append({"policy_id": rule.policy_id, "reason": f"Hash mismatch: expected {sha}, got {computed}"})
                        continue

            self.rules.append(rule)

    def resolve(
        self,
        carrier: str,
        market: str,
        fare_family: Optional[str],
        booking_date: date,
        cancel_date: date,
        cause: str = "PASSENGER_INITIATED",
        ticket_state: Optional[dict] = None,
        dual_reading: bool = True,
    ) -> Resolution:
        """Structured rule resolver implementing temporal filtering, dual-reading, horizon, precedence, and ambiguity."""
        rejections: list[RuleRejection] = []

        for q in self.quarantined:
            rejections.append(RuleRejection(q["policy_id"], "QUARANTINED", f"Rule quarantined: {q['reason']}"))

        def candidates_for_key(key_date: date) -> tuple[list[Rule], list[Assumption], list[RuleRejection]]:
            cands = []
            assumps = []
            local_rejs = []
            for r in self.rules:
                if r.carrier != carrier:
                    continue
                if r.market != "*" and r.market != market:
                    local_rejs.append(RuleRejection(r.policy_id, "MARKET", f"{r.policy_id}: market {r.market} != {market}"))
                    continue
                if not r.matches_fare_family(fare_family):
                    why = (
                        "fare family unknown on ticket"
                        if fare_family is None
                        else f"fare family {fare_family} not in {r.fare_families}"
                    )
                    local_rejs.append(RuleRejection(r.policy_id, "FARE_FAMILY", f"{r.policy_id}: {why}"))
                    continue

                if cause == "CARRIER_DISRUPTION" and not r.applies_to.get("carrier_disruption", False):
                    local_rejs.append(RuleRejection(r.policy_id, "APPLIES_TO", f"{r.policy_id}: does not apply to carrier disruption"))
                    continue
                if ticket_state and ticket_state.get("partially_used") and r.applies_to.get("unused_only", True):
                    local_rejs.append(RuleRejection(r.policy_id, "APPLIES_TO", f"{r.policy_id}: applies to unused tickets only"))
                    continue

                obs_through = self.carrier_observed_through.get(r.carrier) if dual_reading else None
                ok, rej, assumption = r.check_temporal(key_date, obs_through, self.max_projection_days)
                if not ok and rej:
                    local_rejs.append(rej)
                    continue
                if assumption:
                    assumps.append(assumption)
                cands.append(r)
            return cands, assumps, local_rejs

        def sort_candidates(cands: list[Rule]) -> list[Rule]:
            def sort_key(r: Rule):
                src_rank = RULE_SOURCE_CLASS_ORDER.get(r.rule_source_class, 1)
                conf_rank = CONFIDENCE_ORDER.index(r.ceiling)
                specific = 0 if r.fare_families == ["*"] else 1
                eff = r.stated_from or r.observed_from or date.min
                return (src_rank, conf_rank, specific, eff)

            return sorted(cands, key=sort_key, reverse=True)

        if not dual_reading:
            # LEGACY PATH — retained only for regression comparison. It selects on the
            # cancellation date whenever the applicability key is UNKNOWN, which is the
            # unsafe assumption WP-2 exists to remove. Never call this from production code.
            cands = []
            assumps = []
            for r in self.rules:
                if r.carrier != carrier:
                    continue
                if r.market != "*" and r.market != market:
                    rejections.append(RuleRejection(r.policy_id, "MARKET", f"{r.policy_id}: market {r.market} != {market}"))
                    continue
                if not r.matches_fare_family(fare_family):
                    why = "fare family unknown on ticket" if fare_family is None else f"fare family {fare_family} not in {r.fare_families}"
                    rejections.append(RuleRejection(r.policy_id, "FARE_FAMILY", f"{r.policy_id}: {why}"))
                    continue
                key_date = booking_date if r.applicability_key == "BOOKING_DATE" else cancel_date
                ok, rej, assumption = r.check_temporal(key_date, None, self.max_projection_days)
                if not ok and rej:
                    rejections.append(rej)
                    continue
                if assumption:
                    assumps.append(assumption)
                cands.append(r)

            if not cands:
                return Resolution(rule=None, rejections=rejections, key_used="UNKNOWN")

            sorted_cands = sort_candidates(cands)
            winner = sorted_cands[0]
            for c in sorted_cands[1:]:
                rejections.append(RuleRejection(c.policy_id, "WEAKER_EVIDENCE", f"{c.policy_id}: weaker evidence or less specific than {winner.policy_id}"))
            return Resolution(rule=winner, rejections=rejections, key_used=winner.applicability_key, assumptions=assumps)

        # First, find if rules applicable are BOOKING_DATE or CANCELLATION_DATE
        # If any applicable rule has UNKNOWN, we resolve under both readings (WP-2.2)
        # Check candidate rules
        cands_booking, assumps_booking, rejs_booking = candidates_for_key(booking_date)
        cands_cancel, assumps_cancel, rejs_cancel = candidates_for_key(cancel_date)

        sorted_booking = sort_candidates(cands_booking)
        sorted_cancel = sort_candidates(cands_cancel)

        winner_booking = sorted_booking[0] if sorted_booking else None
        winner_cancel = sorted_cancel[0] if sorted_cancel else None

        # Check applicability key determination
        # If the carrier's relevant rule declares BOOKING_DATE:
        if winner_booking and winner_booking.applicability_key == "BOOKING_DATE":
            candidates = sorted_booking
            assumptions = assumps_booking
            rejections.extend(rejs_booking)
            key_used = "BOOKING_DATE"
        elif winner_cancel and winner_cancel.applicability_key == "CANCELLATION_DATE":
            candidates = sorted_cancel
            assumptions = assumps_cancel
            rejections.extend(rejs_cancel)
            key_used = "CANCELLATION_DATE"
        else:
            # UNKNOWN key — dual reading resolution (Invariant I5)
            if winner_booking is None and winner_cancel is None:
                rejections.extend(rejs_booking)
                # Say WHY nothing matched. "No temporally valid rule" sent the reader
                # after the dates when the actual blocker is often a fare family the
                # document never printed — a different problem with a different fix.
                only_family = bool(rejs_booking) and all(
                    r.reason_code == "FARE_FAMILY" for r in rejs_booking
                )
                if only_family and fare_family is None:
                    reason = (
                        f"No fare family is recorded on this ticket, and {carrier}'s published table "
                        "sets a different cancellation charge for each fare family, so no row can be "
                        "selected. The fare brand (or the fare conditions issued with the ticket) is "
                        "needed — the dates are not the problem here."
                    )
                elif only_family:
                    reason = (
                        f"Fare family {fare_family!r} does not appear in {carrier}'s published table, so "
                        "no row matches it. Check the brand name as printed, or supply the fare conditions."
                    )
                else:
                    reason = (
                        "No rule covers this ticket under either the booking date or the cancellation "
                        "date. The evidence held for this carrier does not reach these dates."
                    )
                return Resolution(
                    rule=None,
                    rejections=rejections,
                    key_used="UNKNOWN",
                    abstention_reason=reason,
                )
            if winner_booking and winner_cancel and winner_booking.policy_id == winner_cancel.policy_id:
                candidates = sorted_booking
                assumptions = list({a.code: a for a in assumps_booking + assumps_cancel}.values())
                rejections.extend(rejs_booking)
                key_used = "BOTH_AGREE"
            else:
                cand_a = winner_booking.policy_id if winner_booking else "None"
                cand_b = winner_cancel.policy_id if winner_cancel else "None"
                abst_msg = (
                    f"The applicable policy version cannot be established: keyed to the booking date the applicable rule is {cand_a}; "
                    f"keyed to the cancellation date it is {cand_b}. The source does not state which date governs. "
                    "Supply the fare conditions issued with the ticket, or a source that states the effective-date basis."
                )
                rejections.extend(rejs_booking)
                rejections.extend(rejs_cancel)
                return Resolution(
                    rule=None,
                    rejections=rejections,
                    key_used="UNKNOWN",
                    abstention_reason=abst_msg,
                )

        if not candidates:
            return Resolution(
                rule=None,
                rejections=rejections,
                key_used=key_used,
                abstention_reason="No candidates survived filtering.",
            )

        # Check Ambiguity (WP-2.4)
        def sort_key(r: Rule):
            src_rank = RULE_SOURCE_CLASS_ORDER.get(r.rule_source_class, 1)
            conf_rank = CONFIDENCE_ORDER.index(r.ceiling)
            specific = 0 if r.fare_families == ["*"] else 1
            eff = r.stated_from or r.observed_from or date.min
            return (src_rank, conf_rank, specific, eff)

        if len(candidates) > 1 and sort_key(candidates[0]) == sort_key(candidates[1]) and candidates[0].policy_id != candidates[1].policy_id:
            ambiguous_ids = [candidates[0].policy_id, candidates[1].policy_id]
            abst_msg = (
                f"Ambiguous resolution: {candidates[0].policy_id} and {candidates[1].policy_id} "
                "have identical precedence rank and overlapping validity windows. Engine refuses to select by arbitrary sort order."
            )
            rejections.append(RuleRejection(candidates[0].policy_id, "AMBIGUOUS", abst_msg))
            rejections.append(RuleRejection(candidates[1].policy_id, "AMBIGUOUS", abst_msg))
            return Resolution(
                rule=None,
                rejections=rejections,
                key_used=key_used,
                ambiguous_with=ambiguous_ids,
                abstention_reason=abst_msg,
            )

        winner = candidates[0]
        for c in candidates[1:]:
            rejections.append(
                RuleRejection(
                    c.policy_id,
                    "WEAKER_EVIDENCE",
                    f"{c.policy_id}: weaker evidence or less specific than {winner.policy_id}",
                )
            )

        return Resolution(
            rule=winner,
            rejections=rejections,
            key_used=key_used,
            assumptions=assumptions,
        )

    def statutory_tax_provision(self) -> dict:
        for inst in self.regulatory["instruments"]:
            for prov in inst["provisions"]:
                if prov["provision_id"] == "STATUTORY_TAX_REFUND":
                    return {
                        **prov,
                        "instrument": inst["instrument_id"],
                        "authority": inst["authority"],
                        "technology_neutral": inst["technology_neutral"],
                    }
        raise RuntimeError("statutory tax provision missing from regulatory corpus")

    def classify_tax(self, code: str) -> Optional[dict]:
        return self.tax_codes.get(code.upper())
