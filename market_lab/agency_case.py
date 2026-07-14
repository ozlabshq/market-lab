from __future__ import annotations

"""Read-only AgencyCaseManifest projection over canonical agency events."""

from dataclasses import dataclass, field
from typing import Any, Mapping

from .agency_contracts import (
    SCHEMA_CASE_MANIFEST_V1,
    ArtifactRef,
    NextAction,
    TypedID,
    canonical_bytes,
    sha256_hex,
    validate_sha256,
    validate_timestamp,
)
from .agency_events import replay_status

AGENCY_MODES = frozenset({"offline_inspection", "frozen_replay", "live_research"})
SAFETY_MODE = "research_mock_only"


@dataclass(frozen=True)
class AgencyCaseManifest:
    agency_case_id: TypedID
    created_at_utc: str
    analysis_cutoff_utc: str
    mode: str
    status: str
    input_artifact_hashes: tuple[str, ...]
    audit_head_hash: str | None
    status_projection_hash: str
    blockers: tuple[str, ...] = ()
    next_actions: tuple[NextAction, ...] = ()
    artifact_refs: Mapping[str, tuple[ArtifactRef, ...]] = field(default_factory=dict)
    supersedes_agency_case_id: TypedID | None = None
    safety_mode: str = SAFETY_MODE
    schema_version: str = SCHEMA_CASE_MANIFEST_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_CASE_MANIFEST_V1:
            raise ValueError(f"schema_version must be {SCHEMA_CASE_MANIFEST_V1}")
        if self.mode not in AGENCY_MODES:
            raise ValueError("invalid agency mode")
        if self.safety_mode != SAFETY_MODE:
            raise ValueError("agency safety mode is non-overridable")
        validate_timestamp(self.created_at_utc, "created_at_utc")
        validate_timestamp(self.analysis_cutoff_utc, "analysis_cutoff_utc")
        for digest in self.input_artifact_hashes:
            validate_sha256(digest, "input_artifact_hash")
        if self.audit_head_hash is not None:
            validate_sha256(self.audit_head_hash, "audit_head_hash")
        validate_sha256(self.status_projection_hash, "status_projection_hash")

    @classmethod
    def from_events(
        cls,
        *,
        agency_case_id: TypedID,
        created_at_utc: str,
        analysis_cutoff_utc: str,
        mode: str,
        rows: list[dict[str, Any]],
        input_artifact_hashes: tuple[str, ...],
        next_actions: tuple[NextAction, ...] = (),
        artifact_refs: Mapping[str, tuple[ArtifactRef, ...]] | None = None,
        legacy_bytes: bytes | None = None,
    ) -> "AgencyCaseManifest":
        replay = replay_status(rows, agency_case_id, legacy_bytes=legacy_bytes)
        projection = {
            "agency_case_id": agency_case_id.to_dict(),
            "status": replay.status,
            "sequence_number": replay.sequence_number,
            "audit_head_hash": replay.audit_head_hash,
            "blockers": list(replay.blockers),
            "next_action_types": [action.action_type for action in next_actions],
        }
        return cls(
            agency_case_id=agency_case_id,
            created_at_utc=created_at_utc,
            analysis_cutoff_utc=analysis_cutoff_utc,
            mode=mode,
            status=replay.status,
            input_artifact_hashes=input_artifact_hashes,
            audit_head_hash=replay.audit_head_hash,
            status_projection_hash=sha256_hex(canonical_bytes(projection)),
            blockers=replay.blockers,
            next_actions=next_actions,
            artifact_refs=artifact_refs or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "agency_case_id": self.agency_case_id.to_dict(),
            "supersedes_agency_case_id": self.supersedes_agency_case_id.to_dict() if self.supersedes_agency_case_id else None,
            "created_at_utc": self.created_at_utc,
            "analysis_cutoff_utc": self.analysis_cutoff_utc,
            "mode": self.mode,
            "safety_mode": self.safety_mode,
            "status": self.status,
            "artifact_refs": {
                namespace: [ref.to_dict() for ref in refs]
                for namespace, refs in sorted(self.artifact_refs.items())
            },
            "input_artifact_hashes": list(self.input_artifact_hashes),
            "audit_head_hash": self.audit_head_hash,
            "status_projection_hash": self.status_projection_hash,
            "blockers": list(self.blockers),
            "next_actions": [action.to_dict() for action in self.next_actions],
        }
