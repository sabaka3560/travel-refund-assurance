# Refund Reconstruction Engine v2.1.0

A deterministic financial engine that computes what an Indian domestic airline cancellation would refund under historical scenario-time or actual cancellation conditions, resolved from an evidence-backed policy corpus.

**Engine Version:** `2.1.0` | **Semantics Version:** `2026-09-07.2` | **Corpus:** `2026-09-07.2`

**No dummy data, no LLM in the calculation path.** All 18 rules are anchored in the content-addressed evidence store (`corpus/evidence/<sha256>`) — 2.9 MB of preserved captures fetched from the Internet Archive and Air India Express's official disclosure host on 2026-09-07 — and every rule's hash is re-verified at load time. A rule whose copy is missing or altered is **quarantined** and cannot reach a ledger line. Calculation is deterministic Python over integer paise and integer-second intervals.

What the evidence does and does not establish is recorded per rule in `source.content_verification`: 13 rules had every fee figure they assert machine-checked against the preserved copy; the 4 Air India Express rules rest on a PDF whose text layer could not be read here, so their figures are held but unverified; the 2 Akasa rules are `disputed` because the only capture that exists predates their stated effective date and therefore cannot corroborate it.

```bash
# Verify entire test suite (77 tests across 15 modules)
$env:PYTHONIOENCODING="utf-8"; pytest engine/tests -v

# Run corpus lint tool (asserts 0 errors, integer second bands, cut-off validity)
python engine/tools/corpus_lint.py

# Run benchmark test suite (positive exact matches + 0 false-confidence events on negative set)
python engine/tools/run_benchmark.py

# Generate corpus coverage report (R15)
python engine/tools/coverage_report.py
```

---

## 1. What it demonstrates

Same ticket. Same advance cancellation. Booking dates across policy version boundaries:

| Booked | Rule selected | Penalty | Refund |
|---|---|---|---|
| 2025-11-20 | `SG-DOM-STATED-20250228` | ₹3,200 | **₹4,720.00** |
| 2025-12-20 | `SG-DOM-STATED-20251212` | ₹3,899 | **₹4,021.00** |

And at timing boundaries:
- Cancellation at **T−96h 00m 00s**: ₹4,720.00
- Cancellation at **T−95h 59m 59s**: ₹3,645.00 (one second difference across the 96h boundary shifts the refund by ₹1,075.00)
- Cancellation at **T+3h (post-departure)**: ₹1,220.00 (**PARTIAL**, statutory taxes only; advance cancellation fare table does not apply)

---

## 2. Invariants (I1–I13)

The engine strictly enforces 13 formal invariants:

| Invariant | Description | Verification Suite |
|---|---|---|
| **I1** | Money is strictly integer paise minor units. No floating-point values in the calculation path. | `test_money.py` |
| **I2** | Intervals are integer seconds (`int`). Float hours are strictly presentation only. | `test_bands.py::test_integer_seconds` |
| **I3** | The cancellation instant used in calculation is the one supplied, to the second. Never defaulted or rounded. | `test_bands.py::test_instant_is_honoured_to_the_second` |
| **I4** | A rule is never selected whose evidence window does not cover the applicable key date. | `test_resolver.py::test_temporal_absolute` |
| **I5** | A rule whose applicability key is unknown is selected only when both readings agree. | `test_resolver.py::test_unknown_key_disagreement_abstains` |
| **I6** | Published policy snapshots never reach HIGH; observed rules never exceed LOW; disputed rules never exceed LOW. | `test_confidence.py` |
| **I7** | Every rule reaching a ledger line has a verified preserved evidence copy; hash mismatch quarantines the rule. | `test_evidence.py` |
| **I8** | Refund ≥ 0, and refund ≤ amount paid when total paid is established. | `test_invariants.py` |
| **I9** | Components that do not sum to the stated document total block the case; components are never adjusted. | `test_abstention.py::test_reconciliation_blocks` |
| **I10** | A penalty is deducted exactly once; a non-refundable fare is recorded once as forfeiture, never fare + 100% penalty. | `test_ledger.py::test_no_double_count` |
| **I11** | A total that excludes an abstained material component is labelled `PARTIAL` and explicitly names exclusions inline. | `test_ledger.py::test_partial_label` |
| **I12** | Identical inputs + identical corpus version + identical engine version ⇒ byte-identical ledger. | `test_replay.py` |
| **I13** | No component performs live scraping, live carrier portal interaction, or request-time network calls. | `test_no_network.py` |

---

## 3. Time Model & Timeline Validation (WP-1)

- `timeutil.py`: integer seconds arithmetic (`seconds_between`, `elapsed_days`, `calendar_days_between`, `hours_display`).
- `timeline.py`: `validate_timeline(ticket, req)` enforcing 8 ordered rules:
  1. Departure datetime must be timezone-aware.
  2. Cancellation instant must be timezone-aware.
  3. `ACTUAL_RECORD` cancellation basis requires a non-empty `source_ref`.
  4. Cancellation before booking date/instant is invalid (`BEFORE_BOOKING` → case level refusal).
  5. Same day booking with unknown time triggers `SAME_DAY_AS_BOOKING_TIME_UNKNOWN`.
  6. Cancellation at or after departure triggers `AT_OR_AFTER_DEPARTURE` (statutory taxes compute, fare line abstains with `PARTIAL` total).
  7. Valid timeline computes exact integer `seconds_to_departure`.

---

## 4. Evidence Store & Corpus Integrity (WP-5)

Located at `engine/corpus/evidence/`:
- Every artifact stored as `<sha256>.<ext>` alongside `<sha256>.meta.json`.
- `EvidenceStore.verify(sha256)` checks physical file existence and recalculates SHA-256.
- Startup integrity gate quarantines rules missing valid evidence artifacts.
- Tools:
  - `tools/add_evidence.py`: hashes and adds artifacts to store.
  - `tools/capture_evidence.py`: downloads from allowlisted archive domains (`web.archive.org`, official PDF hosts).
  - `tools/corpus_lint.py`: pre-commit and CI verification tool.

---

## 5. Resolver Hardening & Precedence (WP-2, WP-3)

- Returns structured `Resolution(rule, rejections, key_used, ambiguous_with, assumptions)`.
- Dual reading for rules with `applicability_key: "UNKNOWN"`. Resolves under both `booking_date` and `cancel_date`. If both candidate policy IDs agree, calculation proceeds (`key_used = "BOTH_AGREE"`). If they disagree, the engine abstains and names both candidates.
- Evidence horizon: rules with open-ended observation windows match up to `observed_through`. Projections up to `max_projection_days` (30 days) attach a material `Assumption` and set `review_status = REVIEW_REQUIRED`. Dates beyond reject with `reason_code = HORIZON`.
- Precedence order:
  1. `TICKET_CONDITIONS`
  2. `CLIENT_CONTRACT`
  3. `CARRIER_MANDATORY_DISCLOSURE`
  4. `CARRIER_PUBLISHED_PAGE_STATED`
  5. `CARRIER_PUBLISHED_PAGE_OBSERVED`

---

## 6. Directory Layout

```
engine/
├── corpus/
│   ├── evidence/               # SHA-256 preserved artifacts and metadata
│   ├── policies.json           # 18 rules with bands, quotes, caveats, sha256
│   └── regulatory.json         # Statutory tax schedule, CAR provisions
├── refund_engine/
│   ├── compare.py              # Comparison against actual refund received
│   ├── corpus.py               # Rule loader, resolution, dual reading
│   ├── engine.py               # Deterministic calculation, statutory floor
│   ├── evidence.py             # Content-addressed EvidenceStore
│   ├── model.py                # Ticket, CancellationRequest, Result, LedgerLine
│   ├── money.py                # Integer minor unit Money
│   ├── timeline.py             # validate_timeline gate
│   ├── timeutil.py             # Integer seconds arithmetic
│   └── version.py              # Version constants
├── tests/
│   ├── golden/                 # 11 UI baseline test fixtures
│   ├── test_abstention.py
│   ├── test_api.py
│   ├── test_bands.py
│   ├── test_confidence.py
│   ├── test_corpus_lint.py
│   ├── test_engine.py
│   ├── test_evidence.py
│   ├── test_golden.py
│   ├── test_invariants.py
│   ├── test_ledger.py
│   ├── test_money.py
│   ├── test_no_network.py
│   ├── test_replay.py
│   ├── test_resolver.py
│   └── test_timeline.py
└── tools/
    ├── add_evidence.py
    ├── capture_evidence.py
    ├── corpus_lint.py
    ├── coverage_report.py
    ├── make_benchmark_cases.py
    ├── make_golden.py
    ├── replay.py
    └── run_benchmark.py
```

---

## 7. What the hardening changed, and what it costs

Enabling the resolver hardening on the real corpus (rather than behind a test-only flag)
removed answers that were previously produced without sufficient evidence:

| Case | Before | Now | Why |
|---|---|---|---|
| Air India, cancelled >30 days after 2026-04-15 | a figure | fare line abstains | the whole AI corpus rests on one capture dated 2026-04-15; projecting it months forward is not supported |
| AI Express, most tickets | a figure | fare line abstains | a single undated capture (2026-09-05); a ticket booked before it cannot be shown to be governed by it |
| Akasa Flexi | MEDIUM | LOW | the preserved copy predates the rule's stated effective date |
| Corporate fare | whole-case refusal | statutory PARTIAL | the governing agreement is a document the client can supply |
| IndiGo, booking and cancellation in different capture windows | a figure | fare line abstains | applicability key is unknown and the two readings disagree |

SpiceJet and IndiGo within a single capture window are unaffected: the boundary matrix
(₹4,720 / ₹4,021 / ₹3,645 / ₹3,021 / ₹3,921 / ₹2,921) is unchanged.

This is a real reduction in coverage and it should be reported to the client as one. It
is not a regression: those answers were being produced from evidence that does not
support them. The fix is more captures per carrier, not a looser resolver.
