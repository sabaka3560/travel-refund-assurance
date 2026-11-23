"""Generate positive and negative benchmark test cases for WP-9.2."""
from __future__ import annotations

import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CASES_DIR = ROOT_DIR / "benchmark" / "cases"
CASES_DIR.mkdir(parents=True, exist_ok=True)

CASES = [
    # --- POSITIVE SET ---
    {
        "id": "pos_01_sg_t120",
        "set": "positive",
        "description": "SpiceJet pre-12-Dec-2025 rule, advance cancellation at T-120h",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "SG", "market": "DOMESTIC", "origin": "DEL", "destination": "BOM",
                "booking_date": "2025-11-20", "departure_local": "2026-01-15T18:00:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "6700.00",
                "taxes": [{"code": "K3", "amount": "352.00"}, {"code": "UDF", "amount": "708.00"}, {"code": "PSF", "amount": "160.00"}],
                "carrier_surcharges": [{"code": "YR", "amount": "250.00"}],
                "seller_fees": [{"code": "CONVENIENCE_ONLINE", "amount": "250.00"}],
                "total_paid": "8420.00", "fare_family": "SAVER"
            },
            "cancellation": {
                "instant_local": "2026-01-10T18:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "total_minor": 472000,
            "total_status": "PARTIAL",
            "confidence": "LOW"
        }
    },
    {
        "id": "pos_02_sg_boundary_96h",
        "set": "positive",
        "description": "SpiceJet boundary inclusive lower edge at T-96h",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "SG", "market": "DOMESTIC", "origin": "DEL", "destination": "BOM",
                "booking_date": "2025-11-20", "departure_local": "2026-01-15T18:00:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "6700.00",
                "taxes": [{"code": "K3", "amount": "352.00"}, {"code": "UDF", "amount": "708.00"}, {"code": "PSF", "amount": "160.00"}],
                "carrier_surcharges": [{"code": "YR", "amount": "250.00"}],
                "seller_fees": [{"code": "CONVENIENCE_ONLINE", "amount": "250.00"}],
                "total_paid": "8420.00", "fare_family": "SAVER"
            },
            "cancellation": {
                "instant_local": "2026-01-11T18:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "total_minor": 472000,
            "total_status": "PARTIAL",
            "confidence": "LOW"
        }
    },
    {
        "id": "pos_03_sg_after_rulechange",
        "set": "positive",
        "description": "SpiceJet post-12-Dec-2025 rule at T-120h",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "SG", "market": "DOMESTIC", "origin": "DEL", "destination": "BOM",
                "booking_date": "2025-12-20", "departure_local": "2026-01-15T18:00:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "6700.00",
                "taxes": [{"code": "K3", "amount": "352.00"}, {"code": "UDF", "amount": "708.00"}, {"code": "PSF", "amount": "160.00"}],
                "carrier_surcharges": [{"code": "YR", "amount": "250.00"}],
                "seller_fees": [{"code": "CONVENIENCE_ONLINE", "amount": "250.00"}],
                "total_paid": "8420.00", "fare_family": "SAVER"
            },
            "cancellation": {
                "instant_local": "2026-01-10T18:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "total_minor": 402100,
            "total_status": "PARTIAL",
            "confidence": "LOW"
        }
    },
    {
        "id": "pos_04_6e_t120",
        "set": "positive",
        "description": "IndiGo domestic standard fare at T-120h",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "6E", "market": "DOMESTIC", "origin": "DEL", "destination": "BLR",
                "booking_date": "2025-10-15", "departure_local": "2026-01-20T06:20:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "5400.00",
                "taxes": [{"code": "K3", "amount": "270.00"}, {"code": "UDF", "amount": "708.00"}],
                "carrier_surcharges": [], "seller_fees": [],
                "total_paid": "6378.00", "fare_family": None
            },
            "cancellation": {
                "instant_local": "2026-01-15T06:20:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "total_minor": 237800,
            "total_status": "COMPLETE",
            "confidence": "LOW"
        }
    },
    {
        "id": "pos_05_qp_flexi_t120",
        "set": "positive",
        "description": "Akasa Flexi stated policy with carrier effective date",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "QP", "market": "DOMESTIC", "origin": "BLR", "destination": "BOM",
                "booking_date": "2026-06-10", "departure_local": "2026-09-25T14:40:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "4800.00",
                "taxes": [{"code": "K3", "amount": "240.00"}, {"code": "UDF", "amount": "560.00"}],
                "carrier_surcharges": [], "seller_fees": [],
                "total_paid": "5600.00", "fare_family": "FLEXI"
            },
            "cancellation": {
                "instant_local": "2026-09-20T14:40:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "total_minor": 310100,
            "total_status": "COMPLETE",
            "confidence": "MEDIUM"
        }
    },
    {
        "id": "pos_06_sg_post_departure",
        "set": "positive",
        "description": "SpiceJet post-departure (T+3h) gives statutory refund with PARTIAL status",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "SG", "market": "DOMESTIC", "origin": "DEL", "destination": "BOM",
                "booking_date": "2025-11-20", "departure_local": "2026-01-15T18:00:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "6700.00",
                "taxes": [{"code": "K3", "amount": "352.00"}, {"code": "UDF", "amount": "708.00"}, {"code": "PSF", "amount": "160.00"}],
                "carrier_surcharges": [{"code": "YR", "amount": "250.00"}],
                "seller_fees": [{"code": "CONVENIENCE_ONLINE", "amount": "250.00"}],
                "total_paid": "8420.00", "fare_family": "SAVER"
            },
            "cancellation": {
                "instant_local": "2026-01-15T21:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "total_minor": 122000,
            "total_status": "PARTIAL",
            "confidence": "HIGH"
        }
    },

    # --- NEGATIVE SET (MUST ABSTAIN / 0 FALSE CONFIDENCE) ---
    {
        "id": "neg_01_before_booking",
        "set": "negative",
        "description": "Cancellation timestamp precedes booking date -> BEFORE_BOOKING",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "SG", "market": "DOMESTIC", "origin": "DEL", "destination": "BOM",
                "booking_date": "2025-11-20", "departure_local": "2026-01-15T18:00:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "6700.00",
                "taxes": [{"code": "K3", "amount": "352.00"}, {"code": "UDF", "amount": "708.00"}, {"code": "PSF", "amount": "160.00"}],
                "total_paid": "7920.00", "fare_family": "SAVER"
            },
            "cancellation": {
                "instant_local": "2025-11-10T12:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "must_abstain": True,
            "abstain_target": "TOTAL",
            "prohibit_false_confidence": True
        }
    },
    {
        "id": "neg_02_corporate_unsupported",
        "set": "negative",
        "description": "Corporate negotiated fare without custom contract -> fare line must abstain",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "SG", "market": "DOMESTIC", "origin": "DEL", "destination": "BOM",
                "booking_date": "2026-01-10", "departure_local": "2026-04-01T18:00:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "6700.00",
                "taxes": [{"code": "K3", "amount": "352.00"}, {"code": "UDF", "amount": "708.00"}, {"code": "PSF", "amount": "160.00"}],
                "total_paid": "7920.00", "fare_family": "SAVER",
                "corporate": True
            },
            "cancellation": {
                "instant_local": "2026-03-27T18:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "must_abstain": True,
            "abstain_target": "FARE_LINE",
            "prohibit_false_confidence": True
        }
    },
    {
        "id": "neg_03_reissued_ticket",
        "set": "negative",
        "description": "Reissued ticket requires exchange coupon chain -> full refusal",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "SG", "market": "DOMESTIC", "origin": "DEL", "destination": "BOM",
                "booking_date": "2026-01-10", "departure_local": "2026-04-01T18:00:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "6700.00",
                "taxes": [{"code": "K3", "amount": "352.00"}, {"code": "UDF", "amount": "708.00"}, {"code": "PSF", "amount": "160.00"}],
                "total_paid": "7920.00", "fare_family": "SAVER",
                "reissued": True
            },
            "cancellation": {
                "instant_local": "2026-03-27T18:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "must_abstain": True,
            "abstain_target": "TOTAL",
            "prohibit_false_confidence": True
        }
    },
    {
        "id": "neg_04_multi_passenger",
        "set": "negative",
        "description": "Multi-passenger ticket out of scope -> refusal",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "SG", "market": "DOMESTIC", "origin": "DEL", "destination": "BOM",
                "booking_date": "2026-01-10", "departure_local": "2026-04-01T18:00:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 2,
                "base_fare": "13400.00",
                "taxes": [{"code": "K3", "amount": "704.00"}, {"code": "UDF", "amount": "1416.00"}, {"code": "PSF", "amount": "320.00"}],
                "total_paid": "15840.00", "fare_family": "SAVER"
            },
            "cancellation": {
                "instant_local": "2026-03-27T18:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "must_abstain": True,
            "abstain_target": "TOTAL",
            "prohibit_false_confidence": True
        }
    },
    {
        "id": "neg_05_corpus_gap_qp",
        "set": "negative",
        "description": "Ticket booked before Akasa earliest capture -> corpus gap abstention",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "QP", "market": "DOMESTIC", "origin": "PNQ", "destination": "DEL",
                "booking_date": "2026-03-01", "departure_local": "2026-04-20T19:30:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "6200.00",
                "taxes": [{"code": "K3", "amount": "310.00"}, {"code": "UDF", "amount": "460.00"}],
                "total_paid": "6970.00", "fare_family": "SAVER"
            },
            "cancellation": {
                "instant_local": "2026-04-15T19:30:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "must_abstain": True,
            "abstain_target": "FARE_LINE",
            "prohibit_false_confidence": True
        }
    },
    {
        "id": "neg_06_unprinted_fare_family_ai",
        "set": "negative",
        "description": "Air India without fare family printed -> cannot determine fare rule, must abstain on fare",
        "provenance": "synthetic",
        "expectation_source": "Derived from the corpus and this engine's own semantics. NOT a client-supplied or carrier-supplied reference answer.",
        "request": {
            "ticket": {
                "carrier": "AI", "market": "DOMESTIC", "origin": "DEL", "destination": "BLR",
                "booking_date": "2026-05-01", "departure_local": "2026-08-18T18:00:00",
                "departure_timezone": "Asia/Kolkata", "currency": "INR", "passengers": 1,
                "base_fare": "6700.00",
                "taxes": [{"code": "K3", "amount": "352.00"}, {"code": "UDF", "amount": "708.00"}, {"code": "PSF", "amount": "160.00"}],
                "total_paid": "7920.00", "fare_family": None
            },
            "cancellation": {
                "instant_local": "2026-08-13T18:00:00", "timezone": "Asia/Kolkata", "basis": "USER_SCENARIO"
            }
        },
        "expected": {
            "must_abstain": True,
            "abstain_target": "FARE_LINE",
            "prohibit_false_confidence": True
        }
    }
]

def generate():
    for c in CASES:
        path = CASES_DIR / f"{c['id']}.json"
        path.write_text(json.dumps(c, indent=2), encoding="utf-8")
        print(f"Generated {path.name}")

if __name__ == "__main__":
    generate()
