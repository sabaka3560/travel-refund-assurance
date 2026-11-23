"""Refund Reconstruction Console — standalone server API v2.

Serves the UI and exposes:
    POST /api/extract              upload document -> store in evidence -> structured fields
    POST /api/compute              structured fields -> deterministic engine -> ledger + persistence
    GET  /api/cases/{case_id}      retrieve stored case and audit trail
    POST /api/cases/{case_id}/review record reviewer decision and audit event
    GET  /api/evidence/{sha256}    retrieve verified preserved evidence copy (attachment)
    GET  /api/corpus/coverage      corpus coverage matrix per carrier and market
    GET  /api/corpus               raw corpus rules and tax registry
    GET  /api/health               health check with engine/corpus versions & quarantine status
"""
from __future__ import annotations

from datetime import date, datetime
import asyncio
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional, Union
import uuid
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
ENGINE_DIR = ROOT.parent / "engine"
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine import (
    CancellationRequest,
    Comparison,
    Confidence,
    Corpus,
    Money,
    RefundEngine,
    ReviewStatus,
    TaxLine,
    Ticket,
    TimeBasis,
    TimelineStatus,
    TotalStatus,
    compare,
    preset_t_minus,
)
from refund_engine.evidence import EvidenceStore
from refund_engine.model import Assumption
from refund_engine.version import ENGINE_VERSION, SEMANTICS_VERSION
from tools.coverage_report import generate_coverage

MODEL = os.environ.get("REFUND_EXTRACT_MODEL", "gemini-3.5-flash")
IST = ZoneInfo("Asia/Kolkata")
CASES_DIR = ROOT / "cases"
CASES_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_FILE = CASES_DIR / "audit.jsonl"

EVIDENCE_STORE = EvidenceStore(ENGINE_DIR / "corpus" / "evidence")
CORPUS = Corpus()
ENGINE = RefundEngine(CORPUS)

app = FastAPI(title="Refund Reconstruction Console", version=ENGINE_VERSION)


# --------------------------------------------------------------------------- #
# One error shape, everywhere.
#
# FastAPI wraps HTTPException payloads in {"detail": ...}, and `detail` may be a
# string or an object depending on the call site. Three shapes reached the browser,
# so the UI could not read an error message reliably and rendered "[object Object]".
# Every error now leaves as: {"error_code": str, "message": str, ...extras}
# --------------------------------------------------------------------------- #
@app.exception_handler(StarletteHTTPException)
async def _normalise_http_error(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        body = {"error_code": "HTTP_ERROR", "message": ""}
        body.update(detail)
        body["message"] = str(body.get("message", "") or exc.__class__.__name__)
    else:
        body = {
            "error_code": _DEFAULT_ERROR_CODES.get(exc.status_code, "HTTP_ERROR"),
            "message": str(detail),
        }
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def _normalise_validation_error(request: Request, exc: RequestValidationError):
    first = (exc.errors() or [{}])[0]
    loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
    return JSONResponse(
        status_code=400,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": f"{loc + ': ' if loc else ''}{first.get('msg', 'Invalid request')}",
            "field": loc or None,
        },
    )


_DEFAULT_ERROR_CODES = {
    400: "VALIDATION_ERROR",
    401: "AUTH_REQUIRED",
    404: "NOT_FOUND",
    413: "FILE_TOO_LARGE",
    415: "UNSUPPORTED_FILE_TYPE",
    422: "UNPROCESSABLE",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "UPSTREAM_ERROR",
}


# --------------------------------------------------------------------------- #
# API key resolution
# --------------------------------------------------------------------------- #
_ENV_CANDIDATES = [
    os.environ.get("GEMINI_ENV_FILE"),
    str(Path.home() / "Downloads" / "tanmaybohra" / "chatbot" / ".env"),
    str(ROOT / ".env"),
]


def _read_key_from_env_file(path: str) -> str | None:
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == "GEMINI_API_KEY":
                return v.strip().strip("'\"") or None
    except OSError:
        return None
    return None


def gemini_key() -> str | None:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    for cand in _ENV_CANDIDATES:
        if cand and (key := _read_key_from_env_file(cand)):
            return key
    return None


def key_source() -> str | None:
    if os.environ.get("GEMINI_API_KEY"):
        return "environment"
    for cand in _ENV_CANDIDATES:
        if cand and _read_key_from_env_file(cand):
            return cand
    return None


# --------------------------------------------------------------------------- #
# Input models (API v2 & legacy fallback)
# --------------------------------------------------------------------------- #
def _parse_rupees(val: Any, field_name: str, cur: str = "INR") -> Money:
    if val is None:
        return Money.zero(cur)
    if isinstance(val, bool):
        raise ValueError(f"Field {field_name} must be a decimal string amount, got a boolean")
    if isinstance(val, float):
        # A JSON float has already lost exactness before it reached us, and silently
        # rounding it here is how a wrong figure enters a ledger. Amounts must be sent
        # as decimal strings (Invariant I1 applies at the boundary, not just inside).
        raise ValueError(
            f"Field {field_name} was sent as a JSON number ({val!r}). Send monetary amounts as "
            f'decimal strings, e.g. "{val:.2f}", so no floating-point value ever enters the '
            "calculation path."
        )
    if isinstance(val, int):
        s = str(val)
    elif isinstance(val, str):
        s = val.strip().replace(",", "").replace("₹", "")
    else:
        raise ValueError(f"Field {field_name} must be a string amount, got {type(val).__name__}")

    try:
        return Money.rupees(s, cur)
    except Exception as e:
        raise ValueError(f"Invalid monetary amount for {field_name}: {val!r} ({e})")


def _record_audit_event(event: str, case_id: str, **kwargs):
    entry = {
        "event": event,
        "case_id": case_id,
        "timestamp": datetime.now(IST).isoformat(),
        "engine_version": ENGINE_VERSION,
        "corpus_version": CORPUS.version,
        **kwargs,
    }
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


@app.post("/api/compute")
async def compute(request: Request):
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, {"error_code": "INVALID_JSON", "message": "Request body must be valid JSON"})

    # Check if nested v2 or flat legacy
    if "ticket" in body:
        t_data = body["ticket"]
        c_data = body.get("cancellation")
        actual_received_str = body.get("actual_refund_received")
        persist_case = body.get("persist", True)
        extraction_ref = body.get("extraction_ref")
    else:
        t_data = body
        c_data = None
        actual_received_str = None
        persist_case = True
        extraction_ref = None

    cur = t_data.get("currency", "INR")

    # Strict string money validation (WP-6.1)
    for k in ["base_fare", "total", "total_paid"]:
        if k in t_data and isinstance(t_data[k], float):
            # Check if float was passed
            pass  # Allowed for legacy compatibility, converted safely

    try:
        route = t_data.get("route", "")
        import re
        parts = [p.strip() for p in re.split(r"[→\-/–]|to", route) if p.strip()]
        origin = t_data.get("origin") or (parts[0] if parts else (route[:3] if len(route) >= 3 else "DEL"))
        destination = t_data.get("destination") or (parts[-1] if len(parts) > 1 else "BOM")

        dep_str = t_data.get("departure_local") or t_data.get("departure")
        if not dep_str:
            raise ValueError("Departure datetime is required")

        tz_str = t_data.get("departure_timezone")
        if not tz_str:
            raise ValueError(
                "ticket.departure_timezone is required (IANA name, e.g. 'Asia/Kolkata'). "
                "It is not defaulted, because the timezone decides which side of a band "
                "boundary the cancellation instant falls on."
            )
        tz = ZoneInfo(tz_str)
        scheduled_dep = datetime.fromisoformat(dep_str)
        if scheduled_dep.tzinfo is None:
            scheduled_dep = scheduled_dep.replace(tzinfo=tz)

        # Parse taxes
        taxes: list[TaxLine] = []
        if "taxes" in t_data and isinstance(t_data["taxes"], list):
            for item in t_data["taxes"]:
                taxes.append(TaxLine(item["code"], _parse_rupees(item["amount"], f"taxes.{item['code']}", cur)))
        else:
            for code, key in [("K3", "tax_k3"), ("UDF", "tax_udf"), ("PSF", "tax_psf")]:
                v = t_data.get(key, 0)
                if v and float(v) > 0:
                    taxes.append(TaxLine(code, _parse_rupees(v, key, cur)))

        surs: list[TaxLine] = []
        if "carrier_surcharges" in t_data and isinstance(t_data["carrier_surcharges"], list):
            for item in t_data["carrier_surcharges"]:
                surs.append(TaxLine(item["code"], _parse_rupees(item["amount"], f"carrier_surcharges.{item['code']}", cur)))
        elif t_data.get("surcharge_yr") and float(t_data["surcharge_yr"]) > 0:
            surs.append(TaxLine("YR", _parse_rupees(t_data["surcharge_yr"], "surcharge_yr", cur)))

        fees: list[TaxLine] = []
        if "seller_fees" in t_data and isinstance(t_data["seller_fees"], list):
            for item in t_data["seller_fees"]:
                fees.append(TaxLine(item["code"], _parse_rupees(item["amount"], f"seller_fees.{item['code']}", cur)))
        elif (t_data.get("agency_fee") and float(t_data["agency_fee"]) > 0) or (t_data.get("fee") and float(t_data["fee"]) > 0):
            fee_val = t_data.get("agency_fee") or t_data.get("fee")
            fees.append(TaxLine("AGENCY", _parse_rupees(fee_val, "agency_fee", cur)))

        total_val = t_data.get("total_paid") or t_data.get("total")
        total_paid_money = _parse_rupees(total_val, "total_paid", cur) if total_val is not None else None

        booking_dt_str = t_data.get("booking_date")
        if not booking_dt_str:
            raise ValueError("booking_date is required")
        booking_d = date.fromisoformat(booking_dt_str)

        issue_dt_str = t_data.get("ticket_issue_date")
        issue_d = date.fromisoformat(issue_dt_str) if issue_dt_str else booking_d

        booking_instant = None
        if t_data.get("booking_time"):
            booking_instant = datetime.fromisoformat(f"{booking_dt_str}T{t_data['booking_time']}").replace(tzinfo=tz)

        ticket = Ticket(
            ticket_number=t_data.get("ticket_number") or route or "unspecified",
            carrier=t_data["carrier"],
            market=t_data.get("market", "DOMESTIC"),
            origin=origin,
            destination=destination,
            booking_date=booking_d,
            ticket_issue_date=issue_d,
            scheduled_departure=scheduled_dep,
            base_fare=_parse_rupees(t_data.get("base_fare", 0), "base_fare", cur),
            taxes=taxes,
            carrier_surcharges=surs,
            seller_fees=fees,
            total_paid=total_paid_money,
            currency=cur,
            passengers=int(t_data.get("passengers", 1)),
            fare_family=t_data.get("fare_family") or None,
            fare_basis=t_data.get("fare_basis") or None,
            booking_class=t_data.get("booking_class") or None,
            account_code="CORP" if t_data.get("corporate") else None,
            is_corporate_fare=t_data.get("corporate") or None,
            reissued=bool(t_data.get("reissued")),
            partially_used=bool(t_data.get("partially_used")),
            booking_instant=booking_instant,
            departure_timezone=tz_str,
            booking_channel=t_data.get("booking_channel"),
        )
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse(status_code=400, content={"error_code": "VALIDATION_ERROR", "message": f"Could not build ticket: {e}"})

    # Build CancellationRequest
    try:
        if "ticket" in body and not c_data:
            raise ValueError("Choose a cancellation date and time before computing.")
        if c_data:
            c_tz_str = c_data.get("timezone", tz_str)
            c_tz = ZoneInfo(c_tz_str)
            c_instant_str = c_data.get("instant_local")
            if not c_instant_str:
                raise ValueError("cancellation.instant_local is required")
            c_instant = datetime.fromisoformat(c_instant_str)
            if c_instant.tzinfo is None:
                c_instant = c_instant.replace(tzinfo=c_tz)

            canc_req = CancellationRequest(
                instant=c_instant,
                basis=TimeBasis(c_data.get("basis", "USER_SCENARIO")),
                source_ref=c_data.get("source_ref"),
                preset_label=c_data.get("preset_label"),
                cause=c_data.get("cause", "PASSENGER_INITIATED"),
            )
        else:
            canc_req = preset_t_minus(ticket, 120)
    except (ValueError, KeyError) as e:
        return JSONResponse(status_code=400, content={"error_code": "VALIDATION_ERROR", "message": f"Invalid cancellation request: {e}"})

    # Deterministic calculation with invariant protection (WP-6.3)
    case_id = uuid.uuid4().hex[:12]
    now = datetime.now(IST)
    month_str = now.strftime("%Y-%m")
    case_folder = CASES_DIR / month_str
    case_folder.mkdir(parents=True, exist_ok=True)

    try:
        r = ENGINE.evaluate(ticket, canc_req)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error_code": "VALIDATION_ERROR", "message": str(e)})
    except AssertionError as e:
        # Invariant violated: save failed case and return HTTP 500
        fail_record = {
            "case_id": case_id,
            "status": "FAILED_INVARIANT_VIOLATED",
            "error": str(e),
            "created_at": now.isoformat(),
            "request": body,
        }
        (case_folder / f"{case_id}.json").write_text(json.dumps(fail_record, indent=2), encoding="utf-8")
        _record_audit_event("case_failed", case_id, error=str(e))
        raise HTTPException(500, {"error_code": "INVARIANT_VIOLATED", "message": str(e), "case_id": case_id})

    # Optional Comparison against actual refund (P1)
    if canc_req.basis is TimeBasis.ACTUAL_RECORD:
        reference = (canc_req.source_ref or "").removeprefix("sha256:")
        valid_reference = len(reference) == 64 and all(c in "0123456789abcdef" for c in reference.lower())
        verified = valid_reference and EVIDENCE_STORE.verify_rule("cancellation", {"evidence_sha256": reference})[0]
        if not verified:
            r.review_status = ReviewStatus.REVIEW_REQUIRED
            r.assumptions.append(Assumption(
                code="ACTUAL_RECORD_UNVERIFIED",
                detail="The cancellation reference is not linked to a preserved document. Verify the recorded time against the original confirmation.",
                material=True,
            ))

    comp_obj = None
    if actual_received_str:
        rec_money = _parse_rupees(actual_received_str, "actual_refund_received", cur)
        comp_res = compare(r, rec_money, canc_req.source_ref or extraction_ref)
        comp_obj = {
            "status": comp_res.status,
            "entitled": str(comp_res.entitled) if comp_res.entitled else None,
            "received": str(comp_res.received) if comp_res.received else None,
            "delta": str(comp_res.delta) if comp_res.delta else None,
            "detail": comp_res.detail,
        }

    response_data = {
        "case_id": case_id,
        "engine_version": ENGINE_VERSION,
        "semantics_version": SEMANTICS_VERSION,
        "corpus_version": CORPUS.version,
        "cancellation": {
            "instant": r.cancel_instant.isoformat(),
            "basis": r.basis.value,
            "preset_label": r.preset_label,
            "source_ref": r.source_ref,
        },
        "timeline": {
            "status": r.timeline_status.value,
            "seconds_to_departure": r.seconds_to_departure,
            "hours_to_departure": str(r.hours_before_departure),
            "days_to_departure_display": str(r.seconds_to_departure // 86400),
        },
        "total": {
            "amount": None if r.refund_total is None else str(r.refund_total),
            "minor": None if r.refund_total is None else r.refund_total.minor,
            "status": r.total_status.value,
            "excludes": r.excluded_components,
        },
        "confidence": r.confidence.value,
        "review_status": r.review_status.value,
        "lines": [
            {
                "label": l.label,
                "original": None if l.original is None else str(l.original),
                "original_minor": None if l.original is None else l.original.minor,
                "contribution": str(l.contribution),
                "contribution_minor": l.contribution.minor,
                "confidence": l.confidence.value,
                "classification_confidence": l.classification_confidence.value if l.classification_confidence else None,
                "basis": l.basis,
                "source_url": l.source_url,
                "evidence": l.evidence,
            }
            for l in r.lines
        ],
        "assumptions": [
            {"code": a.code, "detail": a.detail, "material": a.material}
            for a in r.assumptions
        ],
        "unresolved": r.unresolved,
        "conflicts": r.conflicts,
        # Structured, because the UI renders policy id, reason code and detail in
        # separate fields. Sending sentences here rendered an empty row per rule.
        "rules_rejected": r.rejections or [
            {"policy_id": "", "reason_code": "REJECTED", "detail": s} for s in r.rejected_rules
        ],
        "comparison": comp_obj,
        # Legacy/UI compatibility fields
        "cancel_instant": r.cancel_instant.isoformat(),
        "hours_before": float(r.hours_before_departure),
        "refund_total": None if r.refund_total is None else str(r.refund_total),
        "refund_total_minor": None if r.refund_total is None else r.refund_total.minor,
        "abstained": r.abstained,
        "warnings": r.warnings,
        "rule_id": r.rule_id,
        "rule_source": r.rule_source,
    }

    if persist_case:
        canon_req_bytes = json.dumps(body, sort_keys=True).encode("utf-8")
        canon_sha = hashlib.sha256(canon_req_bytes).hexdigest()
        stored_record = {
            "case_id": case_id,
            "created_at": now.isoformat(),
            "engine_version": ENGINE_VERSION,
            "semantics_version": SEMANTICS_VERSION,
            "corpus_version": CORPUS.version,
            "request_canonical_sha256": canon_sha,
            "request": body,
            "response": response_data,
        }
        case_file = case_folder / f"{case_id}.json"
        case_file.write_text(json.dumps(stored_record, indent=2, ensure_ascii=False), encoding="utf-8")
        _record_audit_event("case_created", case_id)

    return JSONResponse(response_data)


# --------------------------------------------------------------------------- #
# Case Management and Review Endpoints (WP-6.4)
# --------------------------------------------------------------------------- #
@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    matches = list(CASES_DIR.glob(f"**/{case_id}.json"))
    if not matches:
        raise HTTPException(404, {"error_code": "CASE_NOT_FOUND", "message": f"Case {case_id} not found"})

    case_data = json.loads(matches[0].read_text(encoding="utf-8"))

    # Read relevant audit trail
    audit_events = []
    if AUDIT_FILE.exists():
        for line in AUDIT_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    ev = json.loads(line)
                    if ev.get("case_id") == case_id:
                        audit_events.append(ev)
                except Exception:
                    pass

    return {"case": case_data, "audit_trail": audit_events}


class ReviewIn(BaseModel):
    reviewer: str
    decision: str  # APPROVED | REJECTED | ESCALATED
    reason: str
    evidence_ref: Optional[str] = None


@app.post("/api/cases/{case_id}/review")
def review_case(case_id: str, review: ReviewIn):
    matches = list(CASES_DIR.glob(f"**/{case_id}.json"))
    if not matches:
        raise HTTPException(404, {"error_code": "CASE_NOT_FOUND", "message": f"Case {case_id} not found"})

    case_file = matches[0]
    case_data = json.loads(case_file.read_text(encoding="utf-8"))

    case_data["response"]["review_status"] = ReviewStatus.REVIEWED.value
    case_data["review"] = {
        "reviewer": review.reviewer,
        "decision": review.decision,
        "reason": review.reason,
        "evidence_ref": review.evidence_ref,
        "reviewed_at": datetime.now(IST).isoformat(),
    }
    case_file.write_text(json.dumps(case_data, indent=2, ensure_ascii=False), encoding="utf-8")

    _record_audit_event(
        "review_recorded",
        case_id,
        reviewer=review.reviewer,
        decision=review.decision,
        reason=review.reason,
        evidence_ref=review.evidence_ref,
    )
    return {"ok": True, "case_id": case_id, "review_status": ReviewStatus.REVIEWED.value}


# --------------------------------------------------------------------------- #
# Evidence Retrieval Endpoint (WP-6.5)
# --------------------------------------------------------------------------- #
@app.get("/api/evidence/{sha256}")
def get_evidence(sha256: str):
    item = EVIDENCE_STORE.get(sha256)
    if not item or not item.file_path.exists():
        raise HTTPException(404, {"error_code": "EVIDENCE_NOT_FOUND", "message": f"Evidence artifact {sha256} not found"})

    content_type = item.meta.get("content_type", "application/octet-stream")
    return FileResponse(
        item.file_path,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{item.file_path.name}"'},
    )


# --------------------------------------------------------------------------- #
# Corpus & Coverage Endpoints (WP-6.5, WP-9.4)
# --------------------------------------------------------------------------- #
@app.get("/api/corpus/coverage")
def coverage():
    return generate_coverage(CORPUS)


@app.get("/api/corpus")
def corpus():
    out = []
    for r in CORPUS.rules:
        out.append({
            "policy_id": r.policy_id,
            "carrier": r.carrier,
            "market": r.market,
            "fare_families": r.fare_families,
            "date_basis": r.date_basis,
            "applicability_key": r.applicability_key,
            "stated_from": r.stated_from.isoformat() if r.stated_from else None,
            "stated_to": r.stated_to.isoformat() if r.stated_to else None,
            "observed_from": r.observed_from.isoformat() if r.observed_from else None,
            "observed_to": r.observed_to.isoformat() if r.observed_to else None,
            "ceiling": r.ceiling.value,
            "disputed": r.disputed,
            "cutoff_h": r.cutoff_h,
            "cutoff_seconds": r.cutoff_seconds,
            "bands": r.bands,
            "source": r.source,
            "caveats": r.caveats,
            "rule_source_class": r.rule_source_class,
            "applies_to": r.applies_to,
        })
    return {
        "version": CORPUS.version,
        "carriers": CORPUS.carriers,
        "rules": out,
        "tax_codes": list(CORPUS.tax_codes.values()),
        "quarantined": CORPUS.quarantined,
    }


# --------------------------------------------------------------------------- #
# Extraction (WP-8)
# --------------------------------------------------------------------------- #
def _s(t: str, desc: str = "") -> dict:
    d = {"type": t, "nullable": True}
    if desc:
        d["description"] = desc
    return d


EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": _s("string", "E_TICKET | OTA_INVOICE | CREDIT_NOTE | CANCELLATION_CONFIRMATION | REFUND_STATEMENT | FARE_CONDITIONS | CORPORATE_CONTRACT | UNKNOWN"),
        "carrier": _s("string", "6E IndiGo, AI Air India, IX Air India Express, QP Akasa Air, SG SpiceJet. null for any other airline."),
        "carrier_seen": _s("string", "Airline name exactly as printed"),
        "ticket_number": _s("string", "Ticket number if present"),
        "pnr": _s("string", "Booking reference / PNR if present"),
        "route": _s("string", "IATA codes, e.g. DEL-BOM"),
        "fare_family": _s("string", "Fare brand exactly as printed, else null"),
        "fare_basis": _s("string", "Fare basis code if present"),
        "booking_date": _s("string", "YYYY-MM-DD"),
        "booking_time": _s("string", "HH:MM if present, else null"),
        "departure": _s("string", "YYYY-MM-DDTHH:MM local time"),
        "cancellation_datetime": _s("string", "Cancellation date and time if printed on refund statement / credit note"),
        "refund_amount_received": _s("number", "Actual refund received if printed"),
        "passenger_count": _s("integer", "Number of passengers"),
        "currency": _s("string", "Printed ISO currency, e.g. INR. Do not convert currencies."),
        "booking_channel": _s("string", "DIRECT | AGENT | OTA | CORPORATE_PORTAL"),
        "base_fare": _s("number", "Rupees, plain number"),
        "tax_k3": _s("number", "GST / K3 in rupees"),
        "tax_udf": _s("number", "User Development Fee in rupees"),
        "tax_psf": _s("number", "Passenger Service Fee in rupees"),
        "surcharge_yr": _s("number", "YQ or YR carrier surcharge in rupees"),
        "agency_fee": _s("number", "Convenience or agency fee in rupees"),
        "total": _s("number", "Total paid in rupees"),
        "taxes_only_lumped": {"type": "boolean", "description": "True if one combined tax figure is shown instead of itemised codes"},
        "corporate": {"type": "boolean"},
        "reissued": {"type": "boolean"},
        "partially_used": {"type": "boolean"},
        "missing": {"type": "array", "items": {"type": "string"}, "description": "Important fields not present on the document"},
    },
    "required": [
        "carrier", "carrier_seen", "route", "fare_family", "booking_date",
        "departure", "base_fare", "tax_k3", "tax_udf", "tax_psf",
        "surcharge_yr", "agency_fee", "total", "taxes_only_lumped",
        "corporate", "reissued", "missing", "passenger_count", "currency", "partially_used"
    ],
}

EXTRACT_PROMPT = """You are reading an airline ticket, e-ticket receipt, credit note or travel invoice for an Indian domestic flight.

Extract ONLY what is actually printed on the document.

This is the critical instruction: if a field is not visibly present, return null for it. Never infer, never estimate, never fill in a plausible value. A null is correct and useful; a guess is a defect, because a downstream engine will compute a refund from these numbers and a wrong input produces a confident wrong answer.

Notes:
- doc_type: classify document format
- carrier: "6E" IndiGo, "AI" Air India, "IX" Air India Express, "QP" Akasa Air, "SG" SpiceJet. Any other airline -> null.
- Amounts are rupees as plain numbers: no currency symbol, no thousands separators.
- If the document shows a single combined "Taxes and fees" figure instead of itemised tax codes, set taxes_only_lumped true and leave the individual tax fields null. Do not split a lump sum yourself.
- corporate: true if there is a corporate account code, negotiated fare marking or corporate booking reference.
- reissued: true if it references an exchange or a previous ticket.
- cancellation_datetime: extract if this document is a cancellation confirmation or credit note recording an actual cancellation instant.
- missing: short names of the important fields that are not on this document."""


def _read_document(raw: bytes, mime: str, key: str):
    """Run blocking provider work off the server event loop, with a bounded timeout."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise HTTPException(500, "google-generativeai not installed — pip install google-generativeai")
    genai.configure(api_key=key, transport="rest")
    model = genai.GenerativeModel(MODEL)
    return model.generate_content(
        [{"mime_type": mime, "data": raw}, EXTRACT_PROMPT],
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            response_schema=EXTRACT_SCHEMA,
            temperature=0,
        ),
        request_options={"timeout": 45, "retry": None},
    )


@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "The uploaded file is empty. Choose a ticket PDF or image.")
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "File larger than 20 MB.")

    BY_EXT = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }
    ALLOWED = set(BY_EXT.values())

    ctype = (file.content_type or "").lower().split(";")[0].strip()
    if ctype not in ALLOWED:
        ctype = BY_EXT.get(Path(file.filename or "").suffix.lower(), "")
    if ctype not in ALLOWED:
        raise HTTPException(415, f"Unsupported file {file.filename!r}. Upload a PDF, PNG, JPEG or WebP.")
    mime = ctype

    # Save uploaded document to evidence store (WP-8)
    ext = Path(file.filename or "").suffix.lstrip(".") or "bin"
    extraction_ref = EVIDENCE_STORE.store_bytes(
        content=raw,
        extension=ext,
        source_url=f"client_upload:{file.filename}",
        capture_kind="CLIENT_DOCUMENT",
        notes=f"Uploaded client document for extraction: {file.filename}",
        content_type=mime,
    )

    key = gemini_key()
    if not key:
        raise HTTPException(
            401,
            "No GEMINI_API_KEY found, so documents cannot be read. Set GEMINI_API_KEY, "
            "or point GEMINI_ENV_FILE at a .env that contains it, then restart. "
            "You can also enter the ticket details manually.",
        )

    try:
        resp = await asyncio.wait_for(
            asyncio.to_thread(_read_document, raw, mime, key), timeout=55,
        )
    except HTTPException:
        raise
    except TimeoutError:
        raise HTTPException(504, "Reading the document timed out. Retry the upload or enter the ticket details manually.")
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "api key" in low or "permission" in low or "unauthenticated" in low:
            raise HTTPException(401, "The Gemini API key was rejected.")
        if "quota" in low or "429" in low or "rate" in low:
            raise HTTPException(429, "Rate limited by the Gemini API. Try again shortly.")
        raise HTTPException(502, f"Gemini API error: {msg[:300]}")

    try:
        text = resp.text
    except Exception:
        raise HTTPException(422, "The model returned no usable text — it may have declined the document.")
    if not text:
        raise HTTPException(502, "Empty response from the model.")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise HTTPException(502, "The model did not return valid JSON.")

    um = getattr(resp, "usage_metadata", None)
    data["_usage"] = {
        "input_tokens": getattr(um, "prompt_token_count", None),
        "output_tokens": getattr(um, "candidates_token_count", None),
        "model": MODEL,
    }
    data["extraction_ref"] = extraction_ref
    return JSONResponse(data)


@app.get("/api/health")
def health():
    src = key_source()
    quarantined = len(CORPUS.quarantined)
    total_rules = len(CORPUS.rules) + quarantined
    # Count rules whose preserved copy actually exists and hash-matches right now.
    # This must never be inferred from "the rule loaded" — that is what it is checking.
    verified = 0
    for rule in CORPUS.rules:
        ok, _ = EVIDENCE_STORE.verify_rule(rule.policy_id, rule.source)
        if ok:
            verified += 1
    verified_str = f"{verified}/{total_rules}"
    return {
        "ok": True,
        "engine_version": ENGINE_VERSION,
        "semantics_version": SEMANTICS_VERSION,
        "corpus_version": CORPUS.version,
        "rules": len(CORPUS.rules),
        "quarantined_rules": quarantined,
        "evidence_verified": verified_str,
        "extract_model": MODEL,
        "provider": "gemini",
        "api_key_set": src is not None,
        "api_key_source": src,
    }


# --------------------------------------------------------------------------- #
# Static UI Mount
# --------------------------------------------------------------------------- #
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print("\n  Refund Reconstruction Console API v2")
    print(f"  engine {ENGINE_VERSION} · corpus {CORPUS.version} · {len(CORPUS.rules)} rules")
    src = key_source()
    if src:
        print(f"  Gemini key loaded from: {src}")
    else:
        print("  ! No GEMINI_API_KEY found — upload/extract will return 401")
    print(f"  http://127.0.0.1:{port}\n")
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=port)
