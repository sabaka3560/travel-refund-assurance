"""Domain model: the ticket, the cancellation request, the resolved rule, the ledger, confidence verdict."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Union

from .money import Money


class Confidence(str, Enum):
    """Hard tiers. Never a score — no accumulation of weak evidence reaches HIGH."""
    AUTHORITATIVE = "AUTHORITATIVE"   # an airline/GDS servicing quote for this ticket state
    HIGH = "HIGH"                     # filed rule, or the statutory floor
    MEDIUM = "MEDIUM"                 # carrier-stated effective-dated policy snapshot
    LOW = "LOW"                       # observed-only snapshot; true rule start unknown
    INSUFFICIENT = "INSUFFICIENT"     # abstain

    def cap(self, ceiling: "Confidence") -> "Confidence":
        order = [Confidence.INSUFFICIENT, Confidence.LOW, Confidence.MEDIUM,
                 Confidence.HIGH, Confidence.AUTHORITATIVE]
        return self if order.index(self) <= order.index(ceiling) else ceiling


class Provenance(str, Enum):
    FILED_RULE = "FILED_RULE"             # ATPCO Cat 33 — Track A
    POLICY_SNAPSHOT = "POLICY_SNAPSHOT"   # published table — Track B
    INFERRED = "INFERRED"
    STATUTE = "STATUTE"


class TimeBasis(str, Enum):
    ACTUAL_RECORD = "ACTUAL_RECORD"    # from a supplied cancellation/refund document
    USER_SCENARIO = "USER_SCENARIO"    # user picked a hypothetical instant
    PRESET_T_MINUS = "PRESET_T_MINUS"   # a convenience preset, still hypothetical


@dataclass(frozen=True)
class CancellationRequest:
    instant: datetime                    # tz-aware, REQUIRED
    basis: TimeBasis
    source_ref: Optional[str] = None     # evidence sha256 / document id — REQUIRED when ACTUAL_RECORD
    preset_label: Optional[str] = None   # e.g. "T-120h" — only when PRESET_T_MINUS
    cause: str = "PASSENGER_INITIATED"   # vs CARRIER_DISRUPTION


class TimelineStatus(str, Enum):
    VALID = "VALID"
    BEFORE_BOOKING = "BEFORE_BOOKING"                 # invalid, refuse
    SAME_DAY_AS_BOOKING_TIME_UNKNOWN = "SAME_DAY_AS_BOOKING_TIME_UNKNOWN"
    AT_OR_AFTER_DEPARTURE = "AT_OR_AFTER_DEPARTURE"   # needs an explicitly supported rule
    INSIDE_CARRIER_CUTOFF = "INSIDE_CARRIER_CUTOFF"   # set later, by the rule layer


@dataclass(frozen=True)
class TimelineVerdict:
    status: TimelineStatus
    seconds_to_departure: int
    detail: str


class TotalStatus(str, Enum):
    COMPLETE = "COMPLETE"   # every material component determined
    PARTIAL = "PARTIAL"     # a determined subtotal; named components excluded
    NONE = "NONE"          # nothing determinable


class ReviewStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVIEWED = "REVIEWED"


@dataclass(frozen=True)
class Assumption:
    code: str          # FORWARD_PROJECTION | DAY_UNIT_READING | TZ_ASSUMED | ...
    detail: str
    material: bool     # does it change a figure?


@dataclass(frozen=True)
class TaxLine:
    code: str
    amount: Money
    # Populated by the corpus, not by the caller.
    statutory: Optional[bool] = None
    refundable_by_statute: Optional[bool] = None


@dataclass
class Ticket:
    """Only what a real document can supply. Fields we usually cannot get are Optional
    and their absence must drive abstention rather than a default."""
    ticket_number: str
    carrier: str                       # validating carrier, IATA 2-char
    market: str                        # DOMESTIC | INTERNATIONAL
    origin: str
    destination: str
    booking_date: date
    ticket_issue_date: date
    scheduled_departure: datetime      # tz-aware
    base_fare: Money
    taxes: list[TaxLine] = field(default_factory=list)
    carrier_surcharges: list[TaxLine] = field(default_factory=list)   # YQ/YR
    total_paid: Money = None                                          # type: ignore[assignment]
    currency: str = "INR"
    passengers: int = 1

    # Frequently missing — absence is meaningful, not a default
    fare_family: Optional[str] = None
    fare_basis: Optional[str] = None
    booking_class: Optional[str] = None
    account_code: Optional[str] = None          # presence ⇒ corporate fare ⇒ abstain
    is_corporate_fare: Optional[bool] = None

    # State
    reissued: bool = False
    partially_used: bool = False
    seller_fees: list[TaxLine] = field(default_factory=list)

    # Added in WP-1: timeline details
    booking_instant: Optional[datetime] = None
    ticket_issue_instant: Optional[datetime] = None
    departure_timezone: str = "Asia/Kolkata"
    booking_channel: Optional[str] = None       # DIRECT | AGENT | OTA | CORPORATE_PORTAL

    def component_sum(self) -> Money:
        return Money.total(
            [self.base_fare]
            + [t.amount for t in self.taxes]
            + [s.amount for s in self.carrier_surcharges]
            + [f.amount for f in self.seller_fees],
            currency=self.currency,
        )


@dataclass
class LedgerLine:
    label: str
    original: Optional[Money]
    treatment: str
    contribution: Money
    confidence: Confidence
    basis: str                      # human-readable reason
    source_url: Optional[str] = None
    classification_confidence: Optional[Confidence] = None
    evidence: Optional[dict] = None


@dataclass
class Result:
    ticket_number: str
    cancel_instant: datetime
    hours_before_departure: Union[float, Decimal]
    lines: list[LedgerLine]
    refund_total: Optional[Money]
    confidence: Confidence
    warnings: list[str] = field(default_factory=list)
    abstained: list[str] = field(default_factory=list)
    rule_id: Optional[str] = None
    rule_source: Optional[str] = None
    rejected_rules: list[str] = field(default_factory=list)
    # Same rejections, structured, for any consumer that renders them as fields
    # rather than as a sentence. The UI needs policy_id/reason_code/detail apart.
    rejections: list[dict] = field(default_factory=list)

    # Added in WP-1 & WP-4
    basis: TimeBasis = TimeBasis.PRESET_T_MINUS
    preset_label: Optional[str] = None
    source_ref: Optional[str] = None
    seconds_to_departure: int = 0
    timeline_status: TimelineStatus = TimelineStatus.VALID
    total_status: TotalStatus = TotalStatus.COMPLETE
    excluded_components: list[str] = field(default_factory=list)
    assumptions: list[Assumption] = field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.NOT_REQUIRED
    unresolved: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # `abstained` is where the engine records what it could not establish, and
        # `unresolved` is the name the API and UI use for the same list. They drifted:
        # the engine filled one, every consumer read the other, so the missing-evidence
        # panel silently never appeared. Mirror unless a caller set it explicitly.
        if not self.unresolved and self.abstained:
            self.unresolved = list(self.abstained)

    def refundable_lines(self) -> list[LedgerLine]:
        return [l for l in self.lines if not l.contribution.is_zero()]
