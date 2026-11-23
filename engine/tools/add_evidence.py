"""CLI tool to import a local evidence file into the evidence store."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine.evidence import EvidenceStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Add a local file to the preserved evidence store.")
    parser.add_argument("file_path", type=str, help="Path to local file to import")
    parser.add_argument("--url", type=str, required=True, help="Source URL")
    parser.add_argument(
        "--capture-kind",
        type=str,
        default="WAYBACK",
        choices=["WAYBACK", "OFFICIAL_PDF", "CLIENT_DOCUMENT", "CLIENT_CONTRACT", "REGULATORY"],
        help="Type of capture",
    )
    parser.add_argument("--carrier-capture-date", type=str, default=None, help="YYYY-MM-DD capture date")
    parser.add_argument("--notes", type=str, default="", help="Internal provenance notes")

    args = parser.parse_args()
    p = Path(args.file_path)
    if not p.exists():
        print(f"Error: file not found: {p}", file=sys.stderr)
        return 1

    content = p.read_bytes()
    ext = p.suffix.lstrip(".") or "bin"

    store = EvidenceStore()
    sha = store.store_bytes(
        content=content,
        extension=ext,
        source_url=args.url,
        capture_kind=args.capture_kind,
        carrier_capture_date=args.carrier_capture_date,
        notes=args.notes,
    )
    print(f"Stored evidence: {sha}")
    print(f"Evidence file: engine/corpus/evidence/{sha}.{ext}")
    print(f"Meta file:     engine/corpus/evidence/{sha}.meta.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
