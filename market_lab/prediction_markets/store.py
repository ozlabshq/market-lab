from __future__ import annotations

import os
from pathlib import Path
import json
import tempfile
from typing import Any

from market_lab.prediction_markets.adapters import FrozenFileAdapter
from market_lab.prediction_markets.config import assert_below_root, assert_write_path
from market_lab.prediction_markets.errors import ConflictError, IntegrityError, NotFoundError, PredictionMarketError, SchemaError, PathEscapeError
from market_lab.prediction_markets.models import canonical_json_bytes, normalize_descriptor, parse_json_bytes, record_from_dict, record_to_dict, sha256_hex, strict_raw_body, validate_record_hash


def atomic_write(path: Path, data: bytes) -> None:
    root = _infer_root(path)
    if root is not None:
        path = assert_write_path(root, path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = path.read_bytes()
        if old == data:
            return
        raise ConflictError("existing content identity has different bytes", path=str(path))
    fd, tmp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        if root is not None:
            assert_write_path(root, tmp)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if tmp.exists():
            tmp.unlink()
        raise
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def atomic_replace(path: Path, data: bytes) -> None:
    root = _infer_root(path)
    if root is not None:
        path = assert_write_path(root, path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return
    fd, tmp_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        if root is not None:
            assert_write_path(root, tmp)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        if tmp.exists():
            tmp.unlink()
        raise
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _infer_root(path: Path) -> Path | None:
    markers = {"raw", "normalized", "quarantine", "reports", "paper"}
    parts = path.absolute().parts
    for idx, part in enumerate(parts):
        if part in markers:
            return Path(*parts[:idx])
    return None


def _canonical_file(path: Path, value: dict[str, Any]) -> None:
    expected = canonical_json_bytes(value) + b"\n"
    if path.read_bytes() != expected:
        raise IntegrityError("stored JSON is not canonical", path=str(path))


def _regular_below(root: Path, path: Path) -> Path:
    target = assert_below_root(root, path)
    if not target.exists():
        raise IntegrityError("required file is missing", path=str(path))
    assert_below_root(root, target)
    return target


def import_descriptor(root: Path, input_path: Path) -> dict[str, Any]:
    raw_descriptor, descriptor = FrozenFileAdapter().read(input_path)
    descriptor_hash = sha256_hex(raw_descriptor)
    try:
        raw_body = strict_raw_body(descriptor)
        raw_hash = descriptor["raw_sha256"]
        raw_dir = assert_below_root(root, root / "raw" / "sha256" / raw_hash[:2] / raw_hash)
        atomic_write(raw_dir / "raw.bin", raw_body)
        _detect_descriptor_identity_conflict(root, raw_dir / "descriptor.json", raw_descriptor, descriptor_hash)
        atomic_write(raw_dir / "descriptor.json", raw_descriptor)
        manifest = {"schema_version": "mlab-pm-raw-manifest.v1", "descriptor_sha256": descriptor_hash, "raw_sha256": raw_hash}
        atomic_write(raw_dir / "manifest.json", canonical_json_bytes(manifest) + b"\n")
        record = normalize_descriptor(descriptor)
        _detect_rules_conflict(root, record, descriptor_hash)
        record_dir = assert_below_root(root, root / "normalized" / "sha256" / record.normalized_record_hash[:2] / record.normalized_record_hash)
        atomic_write(record_dir / "market.json", canonical_json_bytes(record_to_dict(record)) + b"\n")
        return {"status": "imported", "quarantined": False, "market_key": record.market_key, "snapshot_id": record.snapshot_id, "admissibility": record.admissibility, "normalized_record_hash": record.normalized_record_hash}
    except PredictionMarketError as exc:
        qdir = assert_below_root(root, root / "quarantine" / "sha256" / descriptor_hash[:2] / descriptor_hash)
        atomic_write(qdir / "input.bin", raw_descriptor)
        error = {"schema_version": "mlab-pm-quarantine-error.v1", "descriptor_sha256": descriptor_hash, "error_code": exc.error_code, "message": exc.message}
        if exc.error_code == "PM0_CONFLICT" and exc.details:
            error["conflict_context"] = exc.details
        atomic_write(qdir / "error.json", canonical_json_bytes(error) + b"\n")
        return {"status": "quarantined", "quarantined": True, "descriptor_sha256": descriptor_hash, "error_code": exc.error_code, "message": exc.message}


def load_records(root: Path) -> list:
    records = []
    base = root / "normalized" / "sha256"
    assert_below_root(root, base)
    if not base.exists():
        return []
    for path in sorted(base.glob("*/*/market.json")):
        records.append(_read_record_file(path))
    return sorted(records, key=lambda r: (r.market_key, r.snapshot_id))


def find_record(root: Path, market_key: str, snapshot_id: str | None = None):
    matches = [r for r in load_records(root) if r.market_key == market_key and (snapshot_id is None or r.snapshot_id == snapshot_id)]
    if not matches:
        raise NotFoundError("market record not found")
    return matches[-1]


def verify(root: Path, *, strict: bool = False) -> dict[str, Any]:
    errors = []
    records = []
    descriptor_records: dict[tuple[str, str], Any] = {}
    quarantine_errors: dict[str, dict[str, Any]] = {}
    try:
        _verify_inventory(root)
    except PathEscapeError:
        raise
    except PredictionMarketError as exc:
        errors.append({"path": exc.path or str(root), "error_code": exc.error_code, "message": exc.message})
    quarantines = []
    for path in sorted((root / "quarantine" / "sha256").glob("*/*/error.json")) if (root / "quarantine" / "sha256").exists() else []:
        try:
            error = _verify_quarantine(root, path)
            quarantine_errors[error["descriptor_sha256"]] = error
            quarantines.append(path)
        except Exception as exc:
            code = exc.error_code if isinstance(exc, PredictionMarketError) else "PM0_INTEGRITY"
            errors.append({"path": str(path), "error_code": code, "message": str(exc)})
    for path in sorted((root / "raw" / "sha256").glob("*/*/descriptor.json")) if (root / "raw" / "sha256").exists() else []:
        try:
            assert_below_root(root, path)
            desc_bytes = path.read_bytes()
            desc = parse_json_bytes(desc_bytes)
            descriptor_hash = sha256_hex(desc_bytes)
            raw = strict_raw_body(desc)
            raw_hash = sha256_hex(raw)
            if raw_hash != desc["raw_sha256"] or raw_hash != path.parent.name or path.parent.parent.name != raw_hash[:2]:
                raise IntegrityError("raw path/hash mismatch", path=str(path))
            raw_path = _regular_below(root, path.parent / "raw.bin")
            manifest_path = _regular_below(root, path.parent / "manifest.json")
            if raw_path.read_bytes() != raw:
                raise IntegrityError("raw bytes mismatch", path=str(raw_path))
            manifest = parse_json_bytes(manifest_path.read_bytes())
            _canonical_file(manifest_path, manifest)
            if manifest != {"schema_version": "mlab-pm-raw-manifest.v1", "descriptor_sha256": descriptor_hash, "raw_sha256": raw_hash}:
                raise IntegrityError("raw manifest mismatch", path=str(manifest_path))
            try:
                expected = normalize_descriptor(desc)
            except PredictionMarketError as exc:
                qerror = quarantine_errors.get(descriptor_hash)
                if qerror and qerror["error_code"] == exc.error_code and qerror["message"] == exc.message:
                    continue
                raise
            qerror = quarantine_errors.get(descriptor_hash)
            if qerror and qerror["error_code"] == "PM0_CONFLICT":
                continue
            descriptor_records[(expected.market_key, expected.snapshot_id)] = expected
        except Exception as exc:
            code = exc.error_code if isinstance(exc, PredictionMarketError) else "PM0_INTEGRITY"
            errors.append({"path": str(path), "error_code": code, "message": str(exc)})
    for path in sorted((root / "normalized" / "sha256").glob("*/*/market.json")) if (root / "normalized" / "sha256").exists() else []:
        try:
            assert_below_root(root, path)
            record = _read_record_file(path)
            validate_record_hash(record)
            _canonical_file(path, record_to_dict(record))
            if path.parent.name != record.normalized_record_hash or path.parent.parent.name != record.normalized_record_hash[:2]:
                raise IntegrityError("normalized record path/hash mismatch")
            expected = descriptor_records.get((record.market_key, record.snapshot_id))
            if expected is None:
                raise IntegrityError("normalized record has no matching raw descriptor")
            if record_to_dict(record) != record_to_dict(expected):
                raise IntegrityError("normalized record does not match descriptor")
            records.append(record)
        except PredictionMarketError as exc:
            errors.append({"path": str(path), "error_code": exc.error_code, "message": exc.message})
    for key, expected in descriptor_records.items():
        if not any(r.market_key == key[0] and r.snapshot_id == key[1] for r in records):
            errors.append({"error_code": "PM0_INTEGRITY", "message": "raw descriptor has no normalized record", "market_key": key[0]})
    conflicts = _logical_conflicts(records)
    errors.extend(conflicts)
    strict_failures = []
    if strict:
        strict_failures.extend([r.market_key for r in records if r.admissibility != "RESEARCH_ADMISSIBLE"])
        strict_failures.extend([str(q) for q in quarantines])
    ok = not errors and not strict_failures
    return {"ok": ok, "record_count": len(records), "quarantine_count": len(quarantines), "errors": errors, "strict_failures": strict_failures}


def _verify_inventory(root: Path) -> None:
    assert_below_root(root, root)
    if not root.exists():
        return
    allowed_root = {"raw", "normalized", "quarantine", "reports", "paper"}
    for path in sorted(root.rglob("*")):
        # Check both the reported path and its real resolved target (block symlink escapes)
        assert_below_root(root, path)
        # Detect symlinks (including files and folders) explicitly
        if path.is_symlink():
            real_target = path.resolve(strict=True)
            assert_below_root(root, real_target)
        try:
            resolved = path.resolve(strict=True)
        except FileNotFoundError:
            # Maybe a broken symlink, treat as outside root
            raise PathEscapeError("broken symlink or path escapes prediction data root", path=str(path))
        assert_below_root(root, resolved)
        rel = path.relative_to(root).parts
        if not rel:
            continue
        if rel[0] not in allowed_root:
            raise IntegrityError("unexpected entry under prediction root", path=str(path))
        if rel[0] in allowed_root:
            _verify_tree_entry(path, rel)
    for leaf in (root / "raw" / "sha256").glob("*/*") if (root / "raw" / "sha256").exists() else []:
        if leaf.is_dir() and {p.name for p in leaf.iterdir()} != {"raw.bin", "descriptor.json", "manifest.json"}:
            raise IntegrityError("raw artifact set is incomplete or noncanonical", path=str(leaf))
    for leaf in (root / "normalized" / "sha256").glob("*/*") if (root / "normalized" / "sha256").exists() else []:
        if leaf.is_dir() and {p.name for p in leaf.iterdir()} != {"market.json"}:
            raise IntegrityError("normalized artifact set is incomplete or noncanonical", path=str(leaf))
    for leaf in (root / "quarantine" / "sha256").glob("*/*") if (root / "quarantine" / "sha256").exists() else []:
        if leaf.is_dir() and {p.name for p in leaf.iterdir()} != {"input.bin", "error.json"}:
            raise IntegrityError("quarantine artifact set is incomplete or noncanonical", path=str(leaf))


def _verify_tree_entry(path: Path, rel: tuple[str, ...]) -> None:
    lane = rel[0]
    if lane in ("raw", "normalized"):
        if len(rel) == 1 and path.is_dir():
            return
        if len(rel) == 2 and rel[1] == "sha256" and path.is_dir():
            return
        if len(rel) == 3 and len(rel[2]) == 2 and path.is_dir():
            return
        if len(rel) == 4 and len(rel[3]) == 64 and rel[3].startswith(rel[2]) and path.is_dir():
            return
        names = {"raw.bin", "descriptor.json", "manifest.json"} if lane == "raw" else {"market.json"}
        if len(rel) == 5 and rel[4] in names and path.is_file():
            return
    if lane == "quarantine":
        if len(rel) == 1 and path.is_dir():
            return
        if len(rel) == 2 and rel[1] == "sha256" and path.is_dir():
            return
        if len(rel) == 3 and len(rel[2]) == 2 and path.is_dir():
            return
        if len(rel) == 4 and len(rel[3]) == 64 and rel[3].startswith(rel[2]) and path.is_dir():
            return
        if len(rel) == 5 and rel[4] in {"input.bin", "error.json"} and path.is_file():
            return
    if lane == "reports":
        if len(rel) == 1 and path.is_dir():
            return
        if len(rel) == 2 and path.is_file() and (rel[1] == "latest.md" or (len(rel[1]) == 67 and rel[1].endswith(".md") and _is_hash(rel[1][:-3]))):
            return
    if lane == "paper":
        if len(rel) == 1 and path.is_dir():
            return
        if len(rel) == 2 and path.is_file() and rel[1] in {"events.jsonl", "state.json"}:
            return
    raise IntegrityError("unexpected prediction artifact", path=str(path))


def _verify_quarantine(root: Path, path: Path) -> dict[str, Any]:
    assert_below_root(root, path)
    error = parse_json_bytes(path.read_bytes())
    _canonical_file(path, error)
    keys = set(error)
    if error.get("error_code") == "PM0_CONFLICT":
        expected_keys = {"schema_version", "descriptor_sha256", "error_code", "message", "conflict_context"}
    else:
        expected_keys = {"schema_version", "descriptor_sha256", "error_code", "message"}
    if keys != expected_keys:
        raise IntegrityError("quarantine error schema mismatch")
    if error.get("schema_version") != "mlab-pm-quarantine-error.v1" or error.get("descriptor_sha256") != path.parent.name or path.parent.parent.name != path.parent.name[:2]:
        raise IntegrityError("quarantine path/hash mismatch")
    input_path = _regular_below(root, path.parent / "input.bin")
    input_bytes = input_path.read_bytes()
    if sha256_hex(input_bytes) != error["descriptor_sha256"]:
        raise IntegrityError("quarantine input hash mismatch")
    try:
        desc = parse_json_bytes(input_bytes)
        strict_raw_body(desc)
        candidate = normalize_descriptor(desc)
    except PredictionMarketError as exc:
        if error["error_code"] != exc.error_code or error["message"] != exc.message:
            raise IntegrityError("quarantine error classification mismatch") from exc
        return error
    if error["error_code"] == "PM0_CONFLICT":
        _verify_conflict_context(root, error, candidate)
        return error
    raise IntegrityError("quarantine input is not rejected by normalizer")


def _is_hash(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def dataset_digest(records: list) -> str:
    rows = [[r.market_key, r.snapshot_id, r.normalized_record_hash, r.admissibility] for r in sorted(records, key=lambda x: (x.market_key, x.snapshot_id))]
    return sha256_hex(canonical_json_bytes(rows))


def quarantine_count(root: Path) -> int:
    base = root / "quarantine" / "sha256"
    return len(list(base.glob("*/*/error.json"))) if base.exists() else 0


def _read_record_file(path: Path):
    record = record_from_dict(parse_json_bytes(path.read_bytes()))
    validate_record_hash(record)
    return record


def _detect_descriptor_identity_conflict(root: Path, descriptor_path: Path, candidate_bytes: bytes, candidate_descriptor_sha: str) -> None:
    if not descriptor_path.exists() or descriptor_path.read_bytes() == candidate_bytes:
        return
    existing_bytes = descriptor_path.read_bytes()
    existing = normalize_descriptor(parse_json_bytes(existing_bytes))
    candidate = normalize_descriptor(parse_json_bytes(candidate_bytes))
    raise ConflictError(
        "existing content identity has different bytes",
        path=str(descriptor_path),
        details=_conflict_context(
            "raw_descriptor_identity",
            "existing content identity has different bytes",
            existing,
            sha256_hex(existing_bytes),
            candidate,
            candidate_descriptor_sha,
        ),
    )


def _detect_rules_conflict(root: Path, candidate, candidate_descriptor_sha: str) -> None:
    for record in load_records(root):
        if record.market_key == candidate.market_key and record.rules_hash != candidate.rules_hash and record.rules_hash is not None and candidate.rules_hash is not None:
            raise ConflictError(
                "same market_key has conflicting non-null rules_hash",
                details=_conflict_context(
                    "market_rules_hash",
                    "same market_key has conflicting non-null rules_hash",
                    record,
                    _descriptor_sha_for_record(root, record),
                    candidate,
                    candidate_descriptor_sha,
                ),
            )


def _logical_conflicts(records: list) -> list[dict[str, str]]:
    seen = {}
    out = []
    for record in records:
        old = seen.get(record.market_key)
        if old is not None and old != record.rules_hash and old is not None and record.rules_hash is not None:
            out.append({"error_code": "PM0_CONFLICT", "message": "same market_key has conflicting rules_hash", "market_key": record.market_key})
        seen[record.market_key] = record.rules_hash
    return out


def _conflict_context(conflict_type: str, reason: str, existing, existing_descriptor_sha: str, candidate, candidate_descriptor_sha: str) -> dict[str, Any]:
    return {
        "conflict_type": conflict_type,
        "conflict_reason": reason,
        "identity_keys": {
            "provider_id": candidate.provider_id,
            "provider_market_id": candidate.provider_market_id,
            "rules_version": candidate.rules_version,
            "market_key": candidate.market_key,
            "raw_sha256": candidate.raw_sha256,
        },
        "existing_record": _record_ref(existing, existing_descriptor_sha),
        "candidate_record": _record_ref(candidate, candidate_descriptor_sha),
    }


def _record_ref(record, descriptor_sha: str) -> dict[str, Any]:
    return {
        "market_key": record.market_key,
        "snapshot_id": record.snapshot_id,
        "normalized_record_hash": record.normalized_record_hash,
        "rules_hash": record.rules_hash,
        "raw_sha256": record.raw_sha256,
        "descriptor_sha256": descriptor_sha,
    }


def _descriptor_sha_for_record(root: Path, record) -> str:
    manifest_path = root / "raw" / "sha256" / record.raw_sha256[:2] / record.raw_sha256 / "manifest.json"
    manifest = parse_json_bytes(_regular_below(root, manifest_path).read_bytes())
    descriptor_sha = manifest.get("descriptor_sha256")
    if not isinstance(descriptor_sha, str) or not _is_hash(descriptor_sha):
        raise IntegrityError("raw manifest descriptor reference is invalid", path=str(manifest_path))
    return descriptor_sha


def _verify_conflict_context(root: Path, error: dict[str, Any], candidate) -> None:
    context = error.get("conflict_context")
    if not isinstance(context, dict) or set(context) != {"conflict_type", "conflict_reason", "identity_keys", "existing_record", "candidate_record"}:
        raise IntegrityError("conflict quarantine context schema mismatch")
    if context["conflict_reason"] != error["message"]:
        raise IntegrityError("conflict quarantine reason mismatch")
    candidate_ref = _record_ref(candidate, error["descriptor_sha256"])
    if context["candidate_record"] != candidate_ref:
        raise IntegrityError("conflict candidate reference mismatch")
    keys = context["identity_keys"]
    if keys != {
        "provider_id": candidate.provider_id,
        "provider_market_id": candidate.provider_market_id,
        "rules_version": candidate.rules_version,
        "market_key": candidate.market_key,
        "raw_sha256": candidate.raw_sha256,
    }:
        raise IntegrityError("conflict identity keys mismatch")
    existing_ref = context["existing_record"]
    if not isinstance(existing_ref, dict):
        raise IntegrityError("conflict existing reference mismatch")
    existing_hash = existing_ref.get("normalized_record_hash")
    if not isinstance(existing_hash, str) or not _is_hash(existing_hash):
        raise IntegrityError("conflict existing record hash mismatch")
    record_path = root / "normalized" / "sha256" / existing_hash[:2] / existing_hash / "market.json"
    existing = _read_record_file(_regular_below(root, record_path))
    if _record_ref(existing, _descriptor_sha_for_record(root, existing)) != existing_ref:
        raise IntegrityError("conflict existing record reference mismatch")
    conflict_type = context["conflict_type"]
    if conflict_type == "raw_descriptor_identity":
        if existing.raw_sha256 != candidate.raw_sha256 or existing_ref["descriptor_sha256"] == error["descriptor_sha256"]:
            raise IntegrityError("raw descriptor conflict decision mismatch")
    elif conflict_type == "market_rules_hash":
        if existing.market_key != candidate.market_key or existing.rules_hash is None or candidate.rules_hash is None or existing.rules_hash == candidate.rules_hash:
            raise IntegrityError("rules conflict decision mismatch")
    else:
        raise IntegrityError("unknown conflict quarantine type")
