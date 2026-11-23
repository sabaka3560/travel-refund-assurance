"""Timeline validation gate.

Validates the relationship between booking instant, cancellation instant, and scheduled departure.
Refuses impossible timelines (e.g. cancellation before booking) and categorizes boundary states
(e.g. post-departure, same-day unknown booking time).
"""
from __future__ import annotations

from zoneinfo import ZoneInfo

from .model import CancellationRequest, Ticket, TimeBasis, TimelineStatus, TimelineVerdict
from .timeutil import seconds_between


def validate_timeline(ticket: Ticket, req: CancellationRequest) -> TimelineVerdict:
    """Validate cancellation instant against booking date/instant and scheduled departure."""
    if ticket.scheduled_departure.tzinfo is None:
        raise ValueError(
            "scheduled_departure must be timezone-aware. A naive datetime cannot "
            "be positioned on the real timeline and would silently mis-place the "
            "boundary."
        )
    if req.instant.tzinfo is None:
        raise ValueError(
            "cancellation instant must be timezone-aware. A naive datetime cannot "
            "be positioned on the real timeline and would silently mis-place the "
            "boundary."
        )
    if req.basis is TimeBasis.ACTUAL_RECORD and not req.source_ref:
        raise ValueError(
            "An actual cancellation timestamp requires a source reference (document id or evidence sha256). "
            "A claimed historical fact must point to a stored artifact."
        )

    tz = ZoneInfo(ticket.departure_timezone)
    seconds_to_departure = seconds_between(req.instant, ticket.scheduled_departure)

    # Pre-booking checks
    if ticket.booking_instant is not None:
        if req.instant < ticket.booking_instant:
            return TimelineVerdict(
                status=TimelineStatus.BEFORE_BOOKING,
                seconds_to_departure=seconds_to_departure,
                detail=f"Cancellation at {req.instant.isoformat()} precedes booking at {ticket.booking_instant.isoformat()}.",
            )
    else:
        canc_date = req.instant.astimezone(tz).date()
        if canc_date < ticket.booking_date:
            return TimelineVerdict(
                status=TimelineStatus.BEFORE_BOOKING,
                seconds_to_departure=seconds_to_departure,
                detail=f"Cancellation date {canc_date} precedes booking date {ticket.booking_date}.",
            )
        elif canc_date == ticket.booking_date and ticket.booking_instant is None:
            # Note: SAME_DAY_AS_BOOKING_TIME_UNKNOWN is not fatal unless a rule requires booking time
            if seconds_to_departure <= 0:
                return TimelineVerdict(
                    status=TimelineStatus.AT_OR_AFTER_DEPARTURE,
                    seconds_to_departure=seconds_to_departure,
                    detail=f"Cancellation instant {req.instant.isoformat()} is at or after scheduled departure.",
                )
            return TimelineVerdict(
                status=TimelineStatus.SAME_DAY_AS_BOOKING_TIME_UNKNOWN,
                seconds_to_departure=seconds_to_departure,
                detail=f"Cancellation on {canc_date} is same day as booking date ({ticket.booking_date}) with booking time unknown.",
            )

    if seconds_to_departure <= 0:
        return TimelineVerdict(
            status=TimelineStatus.AT_OR_AFTER_DEPARTURE,
            seconds_to_departure=seconds_to_departure,
            detail=f"Cancellation instant {req.instant.isoformat()} is at or after scheduled departure ({ticket.scheduled_departure.isoformat()}).",
        )

    return TimelineVerdict(
        status=TimelineStatus.VALID,
        seconds_to_departure=seconds_to_departure,
        detail="Timeline is valid.",
    )
