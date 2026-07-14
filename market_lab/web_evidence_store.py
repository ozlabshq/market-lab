from __future__ import annotations

"""Durable storage helpers for web-evidence snapshots and run-local logs."""

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .web_evidence import (
    EvidenceRecord,
    EvidenceSegment,
    FetchResponse,
    SCHEMA_SNAPSHOT_V1,
    audit_hash_payload,
    canonical_hash,
    canonical_json,
    sha256_hex,
    utcnow,
)

RUN_ARTIFACTS = "web_evidence"
_ALLOWED_MANIFEST_HEADERS = {
    "content-type",
    "content-length",
    "content-language",
    "etag",
    "last-modified",
    "cache-control",
    "expires",
    "x-request-id",
}


def web_evidence_dir(run_dir: Path) -> Path:
    return Path(run_dir) / RUN_ARTIFACTS


def ensure_layout(run_dir: Path) -> Path:
    base = web_evidence_dir(Path(run_dir))
    base.mkdir(parents=True, exist_ok=True)
    (base / "snapshots" / "sha256").mkdir(parents=True, exist_ok=True)
    for name in [
        "plan.json",
        "provider_health.json",
        "budgets.json",
        "queries.jsonl",
        "search_results.jsonl",
        "provider_calls.jsonl",
        "segments.jsonl",
        "snapshot_index.jsonl",
    ]:
        path = base / name
        if path.suffix == ".json" and not path.exists():
            path.write_text("{}", encoding="utf-8")
        elif path.suffix == ".jsonl" and not path.exists():
            path.write_text("", encoding="utf-8")
    return base


def _snapshot_dir(base: Path, snapshot_id: str) -> Path:
    if not snapshot_id.startswith("sha256:"):
        raise ValueError("snapshot_id must start with sha256:")
    digest = snapshot_id.split(":", 1)[1]
    if len(digest) < 3:
        raise ValueError("snapshot_id digest is invalid")
    return base / "snapshots" / "sha256" / digest[:2] / digest


def _write_atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="tmp-", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with tmp.open("wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        with path.open("rb") as f:
            os.fsync(f.fileno())
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass


def _write_atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="tmp-", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    os.close(fd)
    with tmp.open("w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    with path.open("rb") as f:
        os.fsync(f.fileno())


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, sort_keys=True))
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        rows.append(json.loads(raw))
    return rows


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return _read_jsonl(Path(path))


def _extract_text_for_snapshot(content: bytes, *, content_type: str = "") -> tuple[str, str, str, str]:
    mime = (content_type or "").lower()
    decoded = content.decode("utf-8", errors="replace") if isinstance(content, (bytes, bytearray)) else ""

    if "application/json" in mime or "application/ld+json" in mime:
        try:
            return "success", json.dumps(json.loads(decoded), ensure_ascii=False, sort_keys=True, indent=2), "json", "json-canonical-v1"
        except Exception:
            return "malformed_document", "", "json", "json-canonical-v1"

    if "pdf" in mime:
        try:
            import io
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            pages: list[str] = []
            for idx, page in enumerate(reader.pages[:25], start=1):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(f"[page {idx}]\n{text.strip()}")
            extracted = "\n\n".join(pages).strip()
            if not extracted:
                return "pdf_scanned_ocr_required", "", "pdf", "pypdf"
            return "success", extracted[:200000], "pdf", "pypdf"
        except Exception:
            return "extractor_error", "", "pdf", "pypdf"

    if "text/html" in mime or "application/xhtml" in mime or "xml" in mime:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(decoded, "html.parser")
            for tag in soup(["script", "style", "noscript", "template"]):
                tag.decompose()
            chunks: list[str] = []
            for node in soup.find_all(["title", "h1", "h2", "h3", "p", "li", "th", "td"]):
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    chunks.append(text)
            extracted = "\n".join(chunks).strip()
            if not extracted:
                return "empty_main_content", "", "html", "beautifulsoup4"
            return "success", extracted[:200000], "html", "beautifulsoup4"
        except Exception:
            return "extractor_error", "", "html", "beautifulsoup4"

    if mime.startswith("text/") or not mime:
        text = decoded.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return "empty_main_content", "", "text", "text-decode-v1"
        return "success", text[:200000], "text", "text-decode-v1"

    return "unsupported_media", "", mime.split(";", 1)[0] or "unknown", ""


def write_plan(run_dir: Path, payload: dict[str, Any]) -> None:
    path = web_evidence_dir(run_dir) / "plan.json"
    ensure_layout(run_dir)
    _write_atomic_text(path, json.dumps(payload, sort_keys=True, indent=2))


def append_provider_health(run_dir: Path, providers: list[dict[str, Any]]) -> None:
    path = web_evidence_dir(run_dir) / "provider_health.json"
    ensure_layout(run_dir)
    _write_atomic_text(path, json.dumps({"providers": providers}, sort_keys=True, indent=2))


def append_budget_report(run_dir: Path, payload: dict[str, Any]) -> None:
    _write_atomic_text(web_evidence_dir(run_dir) / "budgets.json", json.dumps(payload, sort_keys=True, indent=2))


def append_query_event(run_dir: Path, payload: dict[str, Any]) -> None:
    _append_jsonl(web_evidence_dir(run_dir) / "queries.jsonl", payload)


def append_search_results(run_dir: Path, response: SearchResultLike) -> None:
    if isinstance(response, list):
        payload = {"search_rows": response}
    else:
        payload = asdict(response)
    _append_jsonl(web_evidence_dir(run_dir) / "search_results.jsonl", payload)


def append_provider_call(run_dir: Path, payload: dict[str, Any]) -> None:
    _append_jsonl(web_evidence_dir(run_dir) / "provider_calls.jsonl", payload)


def append_segment(run_dir: Path, segment: EvidenceSegment) -> None:
    _append_jsonl(web_evidence_dir(run_dir) / "segments.jsonl", asdict(segment))


def append_snapshot_index(run_dir: Path, payload: dict[str, Any]) -> None:
    _append_jsonl(web_evidence_dir(run_dir) / "snapshot_index.jsonl", payload)


def append_evidence_record(run_dir: Path, record: EvidenceRecord) -> None:
    _append_jsonl(Path(run_dir) / "evidence.jsonl", asdict(record))


def commit_snapshot(
    run_dir: Path,
    *,
    provider_id: str,
    request_id: str,
    claim_ids: list[str],
    query_ids: list[str],
    requested_url: str,
    response: FetchResponse,
    response_body: bytes,
    response_headers: dict[str, str],
    extractor_id: str = "",
    extractor_version: str = "",
    extraction_status: str = "success",
    license_terms_note: str = "",
    robots_status: str = "",
    paywall_status: str = "",
) -> tuple[str, Path]:
    base = ensure_layout(run_dir)
    raw_sha = sha256_hex(response_body)
    snapshot_id = f"sha256:{raw_sha}"
    snapshot_dir = _snapshot_dir(base, snapshot_id)
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    raw_path = snapshot_dir / "raw.bin"
    manifest_path = snapshot_dir / "manifest.json"
    extracted_path = snapshot_dir / "extracted.txt"

    # Ensure canonical content for reuse semantics. Existing snapshot directories are
    # content-addressed and immutable: verify and reuse, never rewrite derived files.
    if raw_path.exists():
        if raw_path.stat().st_size != len(response_body):
            raise RuntimeError("snapshot-size-mismatch")
        existing_raw = raw_path.read_bytes()
        if sha256_hex(existing_raw) != raw_sha:
            raise RuntimeError("snapshot-hash-mismatch")
        if not manifest_path.exists() or not extracted_path.exists():
            raise RuntimeError("snapshot-incomplete")
        append_snapshot_index(
            run_dir,
            {
                "snapshot_id": snapshot_id,
                "manifest_path": str(manifest_path.relative_to(run_dir)),
                "run_id": response.run_id,
                "request_id": request_id,
                "provider_id": provider_id,
                "byte_length": response.byte_length,
                "canonical_url": response.canonical_url,
                "created_at_utc": utcnow(),
                "reused": True,
            },
        )
        return snapshot_id, manifest_path
    else:
        _write_atomic_bytes(raw_path, response_body)

    actual_status, extracted, detected_format, detected_extractor = _extract_text_for_snapshot(response_body, content_type=response.content_type)
    if not extractor_id:
        extractor_id = detected_extractor
    if not extractor_version:
        extractor_version = "1"
    if extraction_status == "success":
        extraction_status = actual_status
    extracted_sha = sha256_hex(extracted.encode("utf-8")) if extracted else None
    _write_atomic_bytes(extracted_path, extracted.encode("utf-8"))

    manifest = {
        "schema_version": SCHEMA_SNAPSHOT_V1,
        "snapshot_id": snapshot_id,
        "run_id": response.run_id,
        "provider_id": provider_id,
        "request_id": request_id,
        "query_ids": query_ids,
        "claim_ids": claim_ids,
        "requested_url": requested_url,
        "canonical_url": response.canonical_url,
        "redirect_chain": response.redirect_chain,
        "http_status": 200 if response.status == "success" else 0,
        "response_headers_allowlist": _allowlist_headers(response_headers),
        "content_type": response.content_type,
        "declared_charset": "",
        "detected_format": detected_format or (response.content_type.split(";")[0].strip() if response.content_type else ""),
        "fetched_at_utc": utcnow(),
        "published_at": "",
        "effective_at": "",
        "valid_from": "",
        "valid_to": "",
        "byte_length": response.byte_length,
        "raw_sha256": raw_sha,
        "extracted_sha256": extracted_sha,
        "extractor_id": extractor_id,
        "extractor_version": extractor_version,
        "extraction_status": extraction_status,
        "license_terms_note": license_terms_note,
        "robots_status": robots_status,
        "paywall_status": paywall_status,
        "source_type": "",
        "publisher": "",
        "issuing_authority": "",
        "source_lineage": "",
        "redactions": [],
    }
    _write_atomic_text(manifest_path, json.dumps(manifest, indent=2, sort_keys=True))

    append_snapshot_index(
        run_dir,
        {
            "snapshot_id": snapshot_id,
            "manifest_path": str(manifest_path.relative_to(run_dir)),
            "run_id": response.run_id,
            "request_id": request_id,
            "provider_id": provider_id,
            "byte_length": response.byte_length,
            "canonical_url": response.canonical_url,
            "created_at_utc": utcnow(),
        },
    )

    return snapshot_id, manifest_path


def read_extracted_text(run_dir: Path, snapshot_id: str) -> str:
    base = ensure_layout(run_dir)
    return (_snapshot_dir(base, snapshot_id) / "extracted.txt").read_text(encoding="utf-8")


def read_snapshot_manifest(run_dir: Path, snapshot_id: str) -> dict[str, Any]:
    base = ensure_layout(run_dir)
    return json.loads((_snapshot_dir(base, snapshot_id) / "manifest.json").read_text(encoding="utf-8"))


def make_text_segment(snapshot_id: str, extracted_text: str, claim_text: str, *, segment_seed: str) -> EvidenceSegment | None:
    lines = extracted_text.splitlines()
    if not lines:
        return None
    normalized_claim_terms = [t.lower() for t in claim_text.split() if len(t) >= 4][:8]
    best_idx = 0
    best_score = -1
    for idx, line in enumerate(lines):
        low = line.lower()
        score = sum(1 for term in normalized_claim_terms if term in low)
        if score > best_score and line.strip():
            best_score = score
            best_idx = idx
    excerpt = lines[best_idx].strip()
    if not excerpt:
        return None
    if len(excerpt) > 1200:
        excerpt = excerpt[:1200].rsplit(" ", 1)[0].strip() or excerpt[:1200]
    locator = f"{best_idx + 1}-{best_idx + 1}"
    segment_id = f"seg-{sha256_hex(f'{snapshot_id}:{segment_seed}:{locator}:{excerpt}')[:16]}"
    return EvidenceSegment(
        segment_id=segment_id,
        snapshot_id=snapshot_id,
        locator_type="text_line_range",
        locator=locator,
        verbatim_excerpt_or_value=excerpt,
        segment_sha256=sha256_hex(excerpt),
    )


def verify_segment_locator(run_dir: Path, segment: EvidenceSegment) -> bool:
    if segment.locator_type != "text_line_range":
        return False
    try:
        start_s, end_s = segment.locator.split("-", 1)
        start, end = int(start_s), int(end_s)
        lines = read_extracted_text(run_dir, segment.snapshot_id).splitlines()
        resolved = "\n".join(lines[start - 1 : end]).strip()
    except Exception:
        return False
    return resolved == segment.verbatim_excerpt_or_value and sha256_hex(segment.verbatim_excerpt_or_value) == segment.segment_sha256


def _allowlist_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    if not headers:
        return {}
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        low = str(key).lower()
        if low in _ALLOWED_MANIFEST_HEADERS:
            normalized[low] = str(value)
    return normalized


def append_audit_chain(run_dir: Path, event: dict[str, Any]) -> str:
    """Append an immutable-style event with hash chaining metadata."""

    base_event = dict(event)
    base_event.setdefault("schema_version", "mlab-audit.v2")
    base_event.setdefault("recorded_at_utc", utcnow())

    path = Path(run_dir) / "audit_log.jsonl"
    previous_hash = ""
    for row in reversed(_read_jsonl(path)):
        if isinstance(row, dict) and row.get("event_hash"):
            previous_hash = str(row["event_hash"])
            break
    base_event["previous_event_hash"] = previous_hash

    event_hash = canonical_hash(audit_hash_payload(base_event))
    base_event["event_id"] = f"wa-{event_hash[:12]}"
    base_event["event_hash"] = event_hash

    _append_jsonl(path, base_event)
    return event_hash


def load_audit_chain(run_dir: Path) -> list[dict[str, Any]]:
    return _read_jsonl(Path(run_dir) / "audit_log.jsonl")


def verify_audit_chain(rows: Iterable[dict[str, Any]]) -> tuple[bool, str]:
    previous = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        payload = audit_hash_payload(row)
        event_hash = row.get("event_hash")
        if not event_hash:
            return False, "missing event_hash"
        if previous and payload.get("previous_event_hash") != previous:
            return False, "previous_event_hash mismatch"
        if canonical_hash(payload) != event_hash:
            return False, "event hash mismatch"
        previous = str(event_hash)
    return True, ""


__all__ = [
    "web_evidence_dir",
    "ensure_layout",
    "write_plan",
    "append_provider_health",
    "append_budget_report",
    "append_query_event",
    "append_search_results",
    "append_provider_call",
    "append_segment",
    "append_snapshot_index",
    "append_evidence_record",
    "commit_snapshot",
    "read_extracted_text",
    "read_snapshot_manifest",
    "make_text_segment",
    "verify_segment_locator",
    "read_jsonl",
    "append_audit_chain",
    "load_audit_chain",
    "verify_audit_chain",
]

# Type alias kept small for mypy compatibility with test fixtures.
SearchResultLike = Any
