from __future__ import annotations

"""Locked immutable store for company-intelligence runs."""

from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import tempfile
from contextlib import contextmanager
from typing import Any, Iterator, Mapping

from .agency_contracts import canonical_bytes, canonical_json, sha256_hex, strict_json_loads

SCHEMA_COMPANY_RUN_MANIFEST_V1 = "mlab-company-run.v1"
SCHEMA_COMPANY_AUDIT_V1 = "mlab-company-audit.v1"


class CompanyStoreError(ValueError):
    pass


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _artifact_digest(payload: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_bytes(payload))


@dataclass(frozen=True)
class ReplayResult:
    ok: bool
    semantic_digest: str
    artifact_digests: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "semantic_digest": self.semantic_digest,
            "artifact_digests": list(self.artifact_digests),
            "reason_codes": list(self.reason_codes),
        }


class CompanyIntelligenceRunStore:
    def __init__(self, root: Path, run_id: str) -> None:
        if not run_id or "/" in run_id or run_id.startswith("."):
            raise ValueError("run_id must be a simple non-empty path segment")
        self.root = Path(root)
        self.run_id = run_id
        self.run_dir = self.root / run_id
        self.lock_path = self.run_dir / ".lock"

    def ensure(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "company_packets" / "drafts").mkdir(parents=True, exist_ok=True)
        _fsync_dir(self.run_dir)

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.ensure()
        handle = self.lock_path.open("a+", encoding="utf-8")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield None
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def write_json(self, relative_path: str, payload: Mapping[str, Any], *, immutable: bool = True) -> str:
        self.ensure()
        destination = self.run_dir / relative_path
        if immutable and destination.exists():
            existing = self.read_json(relative_path)
            existing_digest = _artifact_digest(existing)
            new_digest = _artifact_digest(payload)
            if existing_digest != new_digest:
                raise CompanyStoreError(f"immutable artifact already exists with different digest: {relative_path}")
            return existing_digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical_bytes(payload)
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(destination.parent), prefix=f".{destination.name}.", suffix=".tmp") as tmp:
            tmp.write(encoded)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_name = tmp.name
        os.replace(tmp_name, destination)
        _fsync_dir(destination.parent)
        verified = self.read_json(relative_path)
        if canonical_bytes(verified) != encoded:
            raise CompanyStoreError(f"artifact verify failed: {relative_path}")
        return sha256_hex(encoded)

    def read_json(self, relative_path: str) -> dict[str, Any]:
        raw = (self.run_dir / relative_path).read_bytes()
        try:
            text = raw.decode("utf-8")
            payload = strict_json_loads(text)
        except Exception as exc:
            raise CompanyStoreError(f"malformed JSON artifact: {relative_path}") from exc
        if not isinstance(payload, dict):
            raise CompanyStoreError(f"JSON artifact must be an object: {relative_path}")
        if canonical_json(payload).encode("utf-8") != raw:
            raise CompanyStoreError(f"noncanonical or truncated JSON artifact: {relative_path}")
        return payload

    def append_jsonl(self, relative_path: str, payload: Mapping[str, Any]) -> str:
        self.ensure()
        path = self.run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        line = canonical_json(payload) + "\n"
        with path.open("ab") as handle:
            handle.write(line.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(path.parent)
        self.read_jsonl(relative_path)
        return sha256_hex(line)

    def read_jsonl(self, relative_path: str) -> tuple[dict[str, Any], ...]:
        path = self.run_dir / relative_path
        if not path.exists():
            return ()
        raw = path.read_bytes()
        if raw and not raw.endswith(b"\n"):
            raise CompanyStoreError(f"truncated JSONL artifact: {relative_path}")
        rows: list[dict[str, Any]] = []
        for index, line in enumerate(raw.decode("utf-8").splitlines(), start=1):
            payload = strict_json_loads(line)
            if not isinstance(payload, dict):
                raise CompanyStoreError(f"JSONL row {index} must be an object: {relative_path}")
            if canonical_json(payload) != line:
                raise CompanyStoreError(f"JSONL row {index} is noncanonical: {relative_path}")
            rows.append(payload)
        return tuple(rows)

    def audit(self, event_type: str, payload: Mapping[str, Any]) -> str:
        rows = self.read_jsonl("audit_log.jsonl")
        previous_hash = rows[-1]["event_hash"] if rows else ""
        event = {
            "schema_version": SCHEMA_COMPANY_AUDIT_V1,
            "event_type": event_type,
            "run_id": self.run_id,
            "previous_event_hash": previous_hash,
            "payload": dict(payload),
        }
        event["event_hash"] = sha256_hex(canonical_bytes({key: value for key, value in event.items() if key != "event_hash"}))
        self.append_jsonl("audit_log.jsonl", event)
        return str(event["event_hash"])

    def verify_audit(self) -> str:
        previous = ""
        head = ""
        for row in self.read_jsonl("audit_log.jsonl"):
            if row.get("previous_event_hash") != previous:
                raise CompanyStoreError("audit chain previous_event_hash mismatch")
            expected = sha256_hex(canonical_bytes({key: value for key, value in row.items() if key != "event_hash"}))
            if row.get("event_hash") != expected:
                raise CompanyStoreError("audit chain event_hash mismatch")
            previous = expected
            head = expected
        return head

    def replay(self) -> ReplayResult:
        reasons: list[str] = []
        digests: list[str] = []
        required_artifacts = (
            "manifest.json",
            "policy_snapshot.json",
            "input_refs.json",
            "issuer_discovery.json",
            "company_packets/drafts/all_drafts.json",
            "gate_report.json",
            "status.json",
        )
        optional_artifacts = (
            "independent_review.json",
            "publication.json",
        )
        for relative in (*required_artifacts, *optional_artifacts):
            path = self.run_dir / relative
            if not path.exists():
                if relative in required_artifacts:
                    reasons.append(f"missing:{relative}")
                continue
            try:
                digests.append(_artifact_digest(self.read_json(relative)))
            except CompanyStoreError as exc:
                reasons.append(str(exc))
        try:
            digests.append(self.verify_audit())
        except CompanyStoreError as exc:
            reasons.append(str(exc))
        semantic_digest = sha256_hex(canonical_bytes({"artifact_digests": sorted(digests), "run_id": self.run_id}))
        return ReplayResult(ok=not reasons, semantic_digest=semantic_digest, artifact_digests=tuple(sorted(digests)), reason_codes=tuple(reasons))
