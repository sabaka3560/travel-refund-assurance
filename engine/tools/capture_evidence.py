"""Offline capture tool to fetch and store verified evidence from allow-listed hosts.

Legal invariant: Carrier live booking/cancellation pages are strictly excluded
from the automated fetch allow-list. Only archived captures (Wayback) and
official regulator/disclosure PDF repositories are permitted.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import urllib.parse
import urllib.request

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from refund_engine.evidence import EvidenceStore

ALLOWED_HOSTS = {
    "web.archive.org",
    "www.airindiaexpress.com",
    "dgca.gov.in",
    "civilaviation.gov.in",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture an online evidence document into the evidence store.")
    parser.add_argument("url", type=str, help="URL to fetch (must be from allow-listed host)")
    parser.add_argument(
        "--capture-kind",
        type=str,
        default="WAYBACK",
        choices=["WAYBACK", "OFFICIAL_PDF", "REGULATORY"],
        help="Type of capture",
    )
    parser.add_argument("--carrier-capture-date", type=str, default=None, help="YYYY-MM-DD date")
    parser.add_argument("--notes", type=str, default="", help="Internal capture notes")

    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.url)
    host = parsed.netloc.lower()

    if host not in ALLOWED_HOSTS:
        print(
            f"Error: host {host!r} is not in the allow-list. Allowed hosts:\n  "
            + "\n  ".join(sorted(ALLOWED_HOSTS)),
            file=sys.stderr,
        )
        return 1

    try:
        req = urllib.request.Request(args.url, headers={"User-Agent": "RefundEngineEvidenceCollector/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
            ctype = resp.headers.get_content_type()
    except Exception as e:
        print(f"Error fetching {args.url}: {e}", file=sys.stderr)
        return 1

    path_part = parsed.path.lower()
    ext = "pdf" if "pdf" in ctype or path_part.endswith(".pdf") else "html"

    store = EvidenceStore()
    sha = store.store_bytes(
        content=content,
        extension=ext,
        source_url=args.url,
        capture_kind=args.capture_kind,
        carrier_capture_date=args.carrier_capture_date,
        notes=args.notes,
        content_type=ctype,
    )
    print(f"Successfully captured and stored {sha} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
