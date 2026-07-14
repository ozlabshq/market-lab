from __future__ import annotations

"""Versioned agency budgets, compatibility, source integrity, and safety paths."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
import json

from . import config
from .agency_contracts import sha256_hex, strict_json_loads, validate_sha256

SOURCE_MANIFEST_SCHEMA = "slice0-source-authority"
DEFAULT_SOURCE_MANIFEST_PATH = config.ROOT / "research" / "agency_source_manifest.json"
FROZEN_FIXTURE_PATH = config.ROOT / "tests" / "market_lab" / "fixtures" / "web_evidence" / "benchmark_v1.jsonl"
CHAOS_FIXTURE_PATH = config.ROOT / "tests" / "market_lab" / "fixtures" / "web_evidence" / "chaos_v1.jsonl"


@dataclass(frozen=True)
class BudgetProfile:
    profile_id: str = "mlab-agency-budget.v1"
    cases_per_run: int = 1
    material_claims: int = 12
    company_candidates: int = 10
    committee_cohort_candidates: int = 10
    quant_requests: int = 3
    paper_candidates_per_queue_command: int = 1
    global_wall_time_seconds: int = 1_800
    revision_attempts_per_stage: int = 2
    paid_provider_cost_usd: str = "0.00"


@dataclass(frozen=True)
class FixtureCatalog:
    lane: str
    path: Path
    expected_cases: int
    network_allowed: bool = False

    def count(self) -> int:
        if not self.path.is_file():
            return 0
        count = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                json.loads(line)
                count += 1
        return count

    def verify(self) -> tuple[bool, str]:
        actual = self.count()
        if self.network_allowed:
            return False, "foundation fixture catalog must be zero-network"
        if actual == 0:
            return False, "fixture corpus missing or empty"
        if actual != self.expected_cases:
            return False, f"fixture count mismatch: expected {self.expected_cases}, got {actual}"
        return True, ""


def foundation_fixture_catalog(repo_root: Path | None = None) -> tuple[FixtureCatalog, ...]:
    root = Path(repo_root or config.ROOT)
    fixture_root = root / "tests" / "market_lab" / "fixtures" / "web_evidence"
    return (
        FixtureCatalog("frozen", fixture_root / "benchmark_v1.jsonl", 2),
        FixtureCatalog("chaos", fixture_root / "chaos_v1.jsonl", 8),
    )


POLICY_COMPATIBILITY: Mapping[str, frozenset[str]] = {
    "agency": frozenset({"mlab-agency-budget.v1", "mlab-agency-safety.v1"}),
    "source_thesis": frozenset({"mlab-source-thesis.v1"}),
    "web_evidence": frozenset({"mlab-web-evidence.v2"}),
}


def is_policy_compatible(subsystem: str, policy_version: str) -> bool:
    return policy_version in POLICY_COMPATIBILITY.get(subsystem, frozenset())


TOP_LEVEL_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "CREATED": frozenset({"INPUTS_PINNED", "BLOCKED", "PARKED", "REJECTED", "ABORTED"}),
    "INPUTS_PINNED": frozenset({"SOURCE_CAPTURED", "BLOCKED", "PARKED", "REJECTED", "ABORTED"}),
    "SOURCE_CAPTURED": frozenset({"EVIDENCE_PENDING", "BLOCKED", "PARKED", "REJECTED", "ABORTED"}),
    "EVIDENCE_PENDING": frozenset({"EVIDENCE_ACCEPTED", "BLOCKED", "PARKED", "REJECTED", "ABORTED"}),
    "EVIDENCE_ACCEPTED": frozenset({"COMPANY_PUBLISHED", "BLOCKED", "PARKED", "REQUEST_CHANGES", "REJECTED"}),
    "BLOCKED": frozenset({"REQUEST_CHANGES", "PARKED", "REJECTED", "ABORTED", "SUPERSEDED"}),
    "REQUEST_CHANGES": frozenset({"SUPERSEDED", "ABORTED"}),
    "PARKED": frozenset({"SUPERSEDED", "REJECTED"}),
    "REJECTED": frozenset({"SUPERSEDED"}),
    "ABORTED": frozenset(),
    "SUPERSEDED": frozenset(),
    "FINALIZED": frozenset({"SUPERSEDED"}),
}


def is_transition_allowed(current_status: str, next_status: str) -> bool:
    return next_status in TOP_LEVEL_TRANSITIONS.get(current_status, frozenset())


_PROTECTED_RELATIVE_PATHS = (
    "mock_portfolio_state.json",
    "mock_ledger.jsonl",
    "pending_order_candidates.jsonl",
    "options/paper_options_state.json",
    "options/paper_options_ledger.jsonl",
    "options/paper_options_candidates.jsonl",
    "vt_trend/portfolio_state.json",
    "vt_trend/ledger.jsonl",
    "vt_trend/pending_candidates.jsonl",
    "tsmom/portfolio_state.json",
    "tsmom/ledger.jsonl",
    "tsmom/pending_candidates.jsonl",
)


def protected_state_paths(data_dir: Path | None = None) -> tuple[Path, ...]:
    root = Path(data_dir or config.DATA_DIR).expanduser().resolve()
    return tuple(root / relative for relative in _PROTECTED_RELATIVE_PATHS)


def snapshot_protected_state(data_dir: Path | None = None) -> dict[str, dict[str, Any]]:
    root = Path(data_dir or config.DATA_DIR).expanduser().resolve()
    snapshot: dict[str, dict[str, Any]] = {}
    for path in protected_state_paths(root):
        relative = path.relative_to(root).as_posix()
        if path.exists():
            payload = path.read_bytes()
            snapshot[relative] = {"exists": True, "bytes": len(payload), "sha256": sha256_hex(payload)}
        else:
            snapshot[relative] = {"exists": False, "bytes": 0, "sha256": None}
    return snapshot


def _safe_manifest_path(repo_root: Path, relative: str) -> Path | None:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not relative.startswith("research/"):
        return None
    resolved = (repo_root / path).resolve()
    research_root = (repo_root / "research").resolve()
    if resolved != research_root and research_root not in resolved.parents:
        return None
    return resolved


def verify_source_manifest(
    manifest_path: Path | None = None,
    *,
    expected_artifact_count: int = 13,
) -> tuple[bool, list[str], dict[str, str]]:
    path = Path(manifest_path or DEFAULT_SOURCE_MANIFEST_PATH)
    if not path.is_file():
        return False, [f"manifest_missing:{path}"], {}
    try:
        payload = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, [f"manifest_unreadable:{type(exc).__name__}"], {}
    reasons: list[str] = []
    digests: dict[str, str] = {}
    if payload.get("mode") != SOURCE_MANIFEST_SCHEMA:
        reasons.append("manifest_mode_invalid")
    if payload.get("all_ok") is not True:
        reasons.append("source_manifest_all_ok_false")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return False, [*reasons, "manifest_artifacts_type_invalid"], {}
    if len(artifacts) != expected_artifact_count:
        reasons.append(f"manifest_artifact_count:{len(artifacts)}")
    repo_root = path.parent.parent
    seen: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            reasons.append("manifest_artifact_type_invalid")
            continue
        relative = artifact.get("path")
        if not isinstance(relative, str) or relative in seen:
            reasons.append(f"manifest_path_invalid_or_duplicate:{relative}")
            continue
        seen.add(relative)
        file_path = _safe_manifest_path(repo_root, relative)
        if file_path is None:
            reasons.append(f"manifest_path_unsafe:{relative}")
            continue
        expected = artifact.get("expected_sha256")
        recorded = artifact.get("sha256")
        try:
            validate_sha256(str(expected), "expected_sha256")
            validate_sha256(str(recorded), "sha256")
        except ValueError:
            reasons.append(f"manifest_hash_invalid:{relative}")
            continue
        if expected != recorded:
            reasons.append(f"manifest_recorded_hash_disagrees:{relative}")
        if not file_path.is_file():
            reasons.append(f"missing:{relative}")
            continue
        actual = sha256_hex(file_path.read_bytes())
        digests[relative] = actual
        if actual != expected:
            reasons.append(f"digest_mismatch:{relative}")
        expected_bytes = artifact.get("bytes")
        if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) or expected_bytes != file_path.stat().st_size:
            reasons.append(f"byte_count_mismatch:{relative}")
        if artifact.get("ok") is not True:
            reasons.append(f"artifact_ok_false:{relative}")
    return not reasons, reasons, digests
