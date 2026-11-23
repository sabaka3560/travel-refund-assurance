# Refund Reconstruction Console — Server & UI v2.1.0

FastAPI backend and single-page web console for scenario-time refund reconstruction with preserved evidence.

**Server Version:** `2.1.0` | **Semantics Version:** `2026-09-07.2`

---

## 1. Quick Start

```bash
pip install -r requirements.txt
python server/app.py       # Starts server at http://127.0.0.1:8000
```

---

## 2. API v2 Specification

### `POST /api/compute`
Reconstructs the refund ledger from ticket and cancellation parameters.

**Two rules the endpoint enforces rather than papers over:**
- Monetary amounts must be **decimal strings**. A JSON number is rejected with 400 — by the
  time a float reaches the server its exactness is already gone, and rounding it silently is
  how a wrong figure enters a ledger.
- `ticket.departure_timezone` is **required** (IANA name). It is not defaulted, because the
  timezone decides which side of a band boundary the cancellation instant falls on.

**Request Schema:**
```json
{
  "ticket": {
    "carrier": "SG",
    "market": "DOMESTIC",
    "origin": "DEL",
    "destination": "BOM",
    "ticket_number": "775-1234567890",
    "booking_date": "2025-11-20",
    "booking_time": null,
    "departure_local": "2026-01-15T18:00:00",
    "departure_timezone": "Asia/Kolkata",
    "currency": "INR",
    "passengers": 1,
    "base_fare": "6700.00",
    "taxes": [
      {"code": "K3", "amount": "352.00"},
      {"code": "UDF", "amount": "708.00"},
      {"code": "PSF", "amount": "160.00"}
    ],
    "carrier_surcharges": [{"code": "YR", "amount": "250.00"}],
    "seller_fees": [{"code": "CONVENIENCE_ONLINE", "amount": "250.00"}],
    "total_paid": "8420.00",
    "fare_family": "SAVER",
    "corporate": false,
    "reissued": false,
    "partially_used": false
  },
  "cancellation": {
    "instant_local": "2026-01-10T18:00:00",
    "timezone": "Asia/Kolkata",
    "basis": "USER_SCENARIO",
    "source_ref": null,
    "preset_label": "T-120h",
    "cause": "PASSENGER_INITIATED"
  },
  "actual_refund_received": null,
  "persist": true
}
```

**Response:**
Returns `case_id`, `timeline`, `total` (amount, minor, status `COMPLETE|PARTIAL|NONE`, excludes), `confidence`, `review_status`, `lines` (with nested `evidence` objects), `assumptions`, `unresolved`, `conflicts`, and `rules_rejected`.

### `GET /api/cases/{case_id}`
Retrieves persisted case record and associated audit events.

### `POST /api/cases/{case_id}/review`
Records an auditor decision (`APPROVED`, `REJECTED`, `ESCALATED`) without modifying computed figures. Appends an entry to `server/cases/audit.jsonl`.

### `GET /api/evidence/{sha256}`
Downloads preserved evidence copy as attachment (`Content-Disposition: attachment`).

### `GET /api/corpus/coverage`
Generates live carrier coverage matrix directly from corpus data (R15).

### `GET /api/health`
Reports engine/corpus versions, quarantined rule count, and `evidence_verified`.

`evidence_verified` is computed by re-hashing each rule's preserved copy at request time. It
is **not** a count of loaded rules — if an artifact is altered or removed, the figure drops and
the affected rules are quarantined out of resolution.

### `POST /api/extract`
Uploads document, hashes and stores it in evidence store (`capture_kind: CLIENT_DOCUMENT`), and calls Gemini to extract structured ticket fields.

---

## 3. Case Persistence & Audit Trail (WP-6.4, Invariant I12)

- Every evaluated case with `persist: true` is saved to `server/cases/YYYY-MM/<case_id>.json`.
- All system events are logged to append-only `server/cases/audit.jsonl`:
  - `case_created`
  - `review_recorded`
  - `case_replayed`
  - `case_failed`
- `engine/tools/replay.py <case_id>` verifies byte-identical reproduction.

---

## 4. Manual UI Verification Script (WP-7 Acceptance)

Follow these 8 steps in the browser console at `http://127.0.0.1:8000`:

1. **Load Console**: Open `http://127.0.0.1:8000`. Confirm the brand header shows "Refund Reconstruction Console v2" and the default ticket `sg-before` is rendered.
2. **Inspect Timeline Strip**: Verify the `#timeline` strip displays:
   - Node 1: Booking date `2025-11-20 (time not stated)`.
   - Node 2: Cancellation instant `2026-01-10 18:00 IST` with `USER_SCENARIO` label.
   - Node 3: Departure `2026-01-15 18:00 IST` with interval `120.00 h remaining (5.0 days)`.
3. **Verify Presets**:
   - Click `#bar-preset-72h`. Observe the cancellation date/time update to `2026-01-12 18:00`.
   - Click `#bar-preset-24h`. Observe update to `2026-01-14 18:00`.
   - Click `#bar-preset-120h` to reset to 5 days.
4. **Evidence Drawer**:
   - In the refund ledger, locate the `Tax K3` or `Base fare` line.
   - Click `▾ Evidence & Provenance`. Confirm the drawer reveals clause heading, verbatim quote, capture date, applicability key, and preserved artifact download link.
5. **Partial Result Display**:
   - Select the `corp` sample ticket (Corporate negotiated fare).
   - Verify the headline displays `PARTIAL` with the amber callout naming both exclusions:
     `Excludes: Carrier surcharge YR (follows fare rule), Base fare (corporate agreement not supplied)`.
   - The abstention text must ask for the corporate agreement — it must not claim that carriers
     do not publish corporate terms.
6. **Corpus & Coverage Tab**:
   - Click the "Policy corpus" tab.
   - Confirm the Carrier Coverage Matrix renders rows for all 5 carriers with PSS, earliest and latest evidence dates, and quarantined count.
7. **Manual Entry & Actual Basis Validation**:
   - Click "Or enter details manually".
   - Select "Actual cancellation (from a document)". Notice the document reference input appears and `#runBtn` is disabled.
   - Enter `CR-98765` in the document reference field; confirm `#runBtn` is now enabled.
   - Check "Booking time unknown"; confirm `#f-book-time` is disabled.
   - Click "Cancel" to close modal.
8. **Timing Boundary One-Minute Shift Test**:
   - Select sample ticket `sg-before` (SpiceJet booked `2025-11-20`, departure `2026-01-15 18:00`).
   - Set cancellation time to `2026-01-11 18:00` (exact T−96h 00m). Total refund is **₹4,720.00**.
   - Change cancellation time by **one minute** to `2026-01-11 18:01` (T−95h 59m).
   - Observe the live recalculation immediately: the total drops to **₹3,645.00** (penalty increases from ₹3,200 to ₹4,275 across the 96-hour boundary).
