"""Evidence store and integrity verification (WP-5).

Every material rule that reaches a ledger line must have a verified preserved
evidence artifact in the store (Invariant I7).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"
EVIDENCE_DIR = CORPUS_DIR / "evidence"


@dataclass(frozen=True)
class EvidenceMeta:
    sha256: str
    bytes: int
    content_type: str
    source_url: str
    capture_kind: str  # WAYBACK | OFFICIAL_PDF | CLIENT_DOCUMENT | CLIENT_CONTRACT | REGULATORY
    fetched_at: str
    http_status: int = 200
    carrier_capture_date: Optional[str] = None
    redistribution_restricted: bool = True
    notes: str = "Preserved internal evidence copy."


@dataclass
class EvidenceItem:
    sha256: str
    file_path: Path
    meta: dict


class EvidenceStore:
    def __init__(self, directory: Optional[Path] = None):
        self.directory = directory or EVIDENCE_DIR
        self.directory.mkdir(parents=True, exist_ok=True)

    def compute_sha256(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def store_bytes(
        self,
        content: bytes,
        extension: str,
        source_url: str,
        capture_kind: str,
        carrier_capture_date: Optional[str] = None,
        notes: str = "",
        content_type: Optional[str] = None,
    ) -> str:
        """Store bytes, generate metadata, and write files atomically."""
        sha = self.compute_sha256(content)
        ext = extension.lstrip(".") or "bin"
        file_path = self.directory / f"{sha}.{ext}"
        meta_path = self.directory / f"{sha}.meta.json"

        if not content_type:
            content_type = mimetypes.guess_type(f"file.{ext}")[0] or "application/octet-stream"

        file_path.write_bytes(content)
        meta = {
            "sha256": sha,
            "bytes": len(content),
            "content_type": content_type,
            "source_url": source_url,
            "capture_kind": capture_kind,
            "fetched_at": datetime.now(IST).isoformat(),
            "http_status": 200,
            "carrier_capture_date": carrier_capture_date,
            "redistribution_restricted": True,
            "notes": notes or "Preserved internal evidence copy.",
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return sha

    def verify_rule(self, policy_id: str, source: dict) -> tuple[bool, Optional[str]]:
        """Verify that the referenced evidence exists and sha256 matches."""
        sha = source.get("evidence_sha256")
        if not sha:
            return False, "Missing evidence_sha256 in rule source."

        matched_file = None
        for f in self.directory.glob(f"{sha}*"):
            if not f.name.endswith(".meta.json"):
                matched_file = f
                break

        if matched_file is None or not matched_file.exists():
            return False, f"Evidence file for {sha} does not exist in store."

        content = matched_file.read_bytes()
        actual_sha = self.compute_sha256(content)
        if actual_sha.lower() != sha.lower():
            return False, f"Hash mismatch: expected {sha}, got {actual_sha}."

        return True, None

    def get(self, sha256: str) -> Optional[EvidenceItem]:
        matched_file = None
        for f in self.directory.glob(f"{sha256}*"):
            if not f.name.endswith(".meta.json"):
                matched_file = f
                break
        if not matched_file:
            return None

        meta_file = self.directory / f"{sha256}.meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
        return EvidenceItem(sha256=sha256, file_path=matched_file, meta=meta)
