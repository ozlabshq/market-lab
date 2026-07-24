from __future__ import annotations

"""Atomic run-local artifact store for valuation outputs."""

import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from .agency_contracts import canonical_bytes, sha256_hex, strict_json_loads


class ValuationStoreError(ValueError):
    pass


def _fsync_dir(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ValuationStore:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _artifact_path(self, name: str) -> Path:
        candidate = Path(name)
        if not name or candidate.is_absolute() or candidate.name != name or name in {".", ".."}:
            raise ValuationStoreError(f"unsafe valuation artifact path: {name}")
        return self.output_dir / candidate

    def write_json(self, name: str, payload: Mapping[str, Any], *, immutable: bool = True) -> str:
        destination = self._artifact_path(name)
        encoded = canonical_bytes(payload)
        if destination.exists() and immutable:
            if destination.read_bytes() != encoded:
                raise ValuationStoreError(f"immutable valuation artifact differs: {name}")
            return sha256_hex(encoded)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, destination)
        _fsync_dir(destination.parent)
        if destination.read_bytes() != encoded:
            raise ValuationStoreError(f"valuation artifact verification failed: {name}")
        return sha256_hex(encoded)

    def write_text(self, name: str, text: str, *, immutable: bool = True) -> str:
        destination = self._artifact_path(name)
        encoded = text.encode("utf-8")
        if destination.exists() and immutable:
            if destination.read_bytes() != encoded:
                raise ValuationStoreError(f"immutable valuation artifact differs: {name}")
            return sha256_hex(encoded)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("wb", delete=False, dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, destination)
        _fsync_dir(destination.parent)
        return sha256_hex(encoded)

    def read_json(self, name: str) -> dict[str, Any]:
        path = self._artifact_path(name)
        payload = strict_json_loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValuationStoreError(f"valuation artifact must be an object: {name}")
        if canonical_bytes(payload) != path.read_bytes():
            raise ValuationStoreError(f"valuation artifact is not canonical: {name}")
        return payload

    def write_manifest(self, *, valuation_id: str, status: str, artifact_names: list[str]) -> dict[str, Any]:
        artifacts = []
        for name in sorted(artifact_names):
            path = self._artifact_path(name)
            artifacts.append({"path": name, "sha256": sha256_hex(path.read_bytes()), "bytes": path.stat().st_size})
        manifest = {
            "schema_version": "mlab-valuation-manifest.v1",
            "valuation_id": valuation_id,
            "status": status,
            "artifacts": artifacts,
        }
        manifest["manifest_digest"] = sha256_hex(canonical_bytes(manifest))
        self.write_json("manifest.json", manifest)
        return manifest

    def verify_manifest(self) -> dict[str, Any]:
        reasons: list[str] = []
        try:
            manifest = self.read_json("manifest.json")
        except (OSError, ValueError) as exc:
            return {"ok": False, "reason_codes": [f"manifest_invalid:{type(exc).__name__}"], "manifest": None}
        unsigned = {key: value for key, value in manifest.items() if key != "manifest_digest"}
        expected_manifest_digest = sha256_hex(canonical_bytes(unsigned))
        if manifest.get("manifest_digest") != expected_manifest_digest:
            reasons.append("manifest_digest_mismatch")
        for row in manifest.get("artifacts", ()):
            try:
                path = self._artifact_path(str(row.get("path", "")))
            except ValuationStoreError:
                reasons.append(f"unsafe_artifact_path:{row.get('path')}")
                continue
            if not path.is_file():
                reasons.append(f"missing_artifact:{row.get('path')}")
                continue
            payload = path.read_bytes()
            if sha256_hex(payload) != row.get("sha256") or len(payload) != row.get("bytes"):
                reasons.append(f"artifact_digest_mismatch:{row.get('path')}")
        return {"ok": not reasons, "reason_codes": reasons, "manifest": manifest}
