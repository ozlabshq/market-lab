from __future__ import annotations

"""Deterministic, cross-module contracts for the Market Lab agency control plane."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re
import unicodedata
from typing import Any, Iterable, Mapping

SCHEMA_TYPED_ID_V1 = "mlab-typed-id.v1"
SCHEMA_ARTIFACT_REF_V1 = "mlab-artifact-ref.v1"
SCHEMA_GATE_RESULT_V1 = "mlab-gate-result.v1"
SCHEMA_NEXT_ACTION_V1 = "mlab-next-action.v1"
SCHEMA_REVIEW_ENVELOPE_V1 = "mlab-review-envelope.v1"
SCHEMA_CASE_MANIFEST_V1 = "mlab-agency-case.v1"
SCHEMA_AGENCY_EVENT_V1 = "mlab-agency-event.v1"

_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


def sha256_hex(value: str | bytes) -> str:
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def validate_sha256(value: str, field_name: str = "sha256") -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a full lowercase SHA-256")
    return value


def validate_timestamp(value: str, field_name: str = "timestamp") -> str:
    if not isinstance(value, str) or not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be UTC RFC 3339")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def validate_local_id(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError("local_id must be a non-empty string of at most 512 characters")
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("local_id contains surrounding whitespace or control characters")
    if unicodedata.normalize("NFC", value) != value:
        raise ValueError("local_id must use Unicode NFC")
    return value


def _reject_float(_: str) -> Any:
    raise ValueError("binary floats are forbidden in canonical JSON")


def _reject_constant(_: str) -> Any:
    raise ValueError("non-finite values are forbidden in canonical JSON")


def _pairs_to_dict(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    normalized_keys: set[str] = set()
    for key, value in pairs:
        normalized = unicodedata.normalize("NFC", key)
        if key in result or normalized in normalized_keys:
            raise ValueError(f"duplicate canonical key: {key}")
        normalized_keys.add(normalized)
        result[key] = value
    return result


def strict_json_loads(raw: str) -> Any:
    return json.loads(
        raw,
        object_pairs_hook=_pairs_to_dict,
        parse_float=_reject_float,
        parse_constant=_reject_constant,
    )


def _decimal_string(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("non-finite Decimal is forbidden")
    if value.is_zero() and value.is_signed():
        raise ValueError("negative zero is forbidden")
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ValueError("binary floats are forbidden in canonical JSON")
    if isinstance(value, Decimal):
        return _decimal_string(value)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            canonical_key = unicodedata.normalize("NFC", key)
            if canonical_key in normalized:
                raise ValueError(f"duplicate canonical key: {canonical_key}")
            normalized[canonical_key] = _canonicalize(item)
        return {key: normalized[key] for key in sorted(normalized)}
    if isinstance(value, (set, frozenset)):
        items = [_canonicalize(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    if isinstance(value, (list, tuple)):
        items = [_canonicalize(item) for item in value]
        sequence_items = [item for item in items if isinstance(item, dict) and "sequence_index" in item]
        if sequence_items:
            if len(sequence_items) != len(items):
                raise ValueError("semantic sequence items must all declare sequence_index")
            indices = [item["sequence_index"] for item in sequence_items]
            if any(isinstance(index, bool) or not isinstance(index, int) for index in indices):
                raise ValueError("sequence_index must be an integer")
            if indices != list(range(len(items))):
                raise ValueError("semantic sequence indices must be contiguous and ordered")
        return items
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_value(payload: Any) -> Any:
    return _canonicalize(payload)


def canonical_json(payload: Any) -> str:
    return json.dumps(
        _canonicalize(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def canonical_bytes(payload: Any) -> bytes:
    return canonical_json(payload).encode("utf-8")


@dataclass(frozen=True, eq=False)
class TypedID:
    kind: str
    domain: str
    id_schema_version: str
    local_id: str
    digest_sha256: str = ""
    schema_version: str = SCHEMA_TYPED_ID_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_TYPED_ID_V1:
            raise ValueError(f"schema_version must be {SCHEMA_TYPED_ID_V1}")
        if not _TOKEN_RE.fullmatch(self.kind):
            raise ValueError("invalid typed-id kind")
        if not _TOKEN_RE.fullmatch(self.domain):
            raise ValueError("invalid typed-id domain")
        if not _VERSION_RE.fullmatch(self.id_schema_version):
            raise ValueError("invalid id_schema_version")
        validate_local_id(self.local_id)
        payload = {
            "domain": self.domain,
            "id_schema_version": self.id_schema_version,
            "kind": self.kind,
            "local_id": self.local_id,
            "schema_version": SCHEMA_TYPED_ID_V1,
        }
        expected = sha256_hex(canonical_bytes(payload))
        if self.digest_sha256 and self.digest_sha256 != expected:
            raise ValueError("typed-id digest does not match domain-separated payload")
        object.__setattr__(self, "digest_sha256", expected)

    def identity_key(self) -> tuple[str, str, str]:
        return (self.domain, self.id_schema_version, self.digest_sha256)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, TypedID) and self.identity_key() == other.identity_key()

    def __hash__(self) -> int:
        return hash(self.identity_key())

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "domain": self.domain,
            "id_schema_version": self.id_schema_version,
            "digest_sha256": self.digest_sha256,
            "local_id": self.local_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TypedID":
        return cls(
            kind=str(payload.get("kind", "")),
            domain=str(payload.get("domain", "")),
            id_schema_version=str(payload.get("id_schema_version", "")),
            local_id=str(payload.get("local_id", "")),
            digest_sha256=str(payload.get("digest_sha256", "")),
            schema_version=str(payload.get("schema_version", "")),
        )


@dataclass(frozen=True)
class ArtifactRef:
    artifact_id: TypedID
    schema_version: str
    semantic_sha256: str
    byte_sha256: str
    locator: str
    producer_version: str
    created_at_utc: str
    system_available_at_utc: str
    source_commit: str | None = None
    external_manifest_digest: str | None = None
    analysis_cutoff_utc: str | None = None
    source_available_at_utc: str | None = None
    supersedes_artifact_id: TypedID | None = None
    review_ref: TypedID | None = None
    contract_schema_version: str = SCHEMA_ARTIFACT_REF_V1

    def __post_init__(self) -> None:
        if self.contract_schema_version != SCHEMA_ARTIFACT_REF_V1:
            raise ValueError(f"contract_schema_version must be {SCHEMA_ARTIFACT_REF_V1}")
        validate_sha256(self.semantic_sha256, "semantic_sha256")
        validate_sha256(self.byte_sha256, "byte_sha256")
        if not self.locator or not self.producer_version or not self.schema_version:
            raise ValueError("artifact locator, producer_version, and schema_version are required")
        validate_timestamp(self.created_at_utc, "created_at_utc")
        validate_timestamp(self.system_available_at_utc, "system_available_at_utc")
        for name in ("analysis_cutoff_utc", "source_available_at_utc"):
            value = getattr(self, name)
            if value is not None:
                validate_timestamp(value, name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_schema_version": self.contract_schema_version,
            "artifact_id": self.artifact_id.to_dict(),
            "schema_version": self.schema_version,
            "semantic_sha256": self.semantic_sha256,
            "byte_sha256": self.byte_sha256,
            "locator": self.locator,
            "producer_version": self.producer_version,
            "source_commit": self.source_commit,
            "external_manifest_digest": self.external_manifest_digest,
            "created_at_utc": self.created_at_utc,
            "analysis_cutoff_utc": self.analysis_cutoff_utc,
            "source_available_at_utc": self.source_available_at_utc,
            "system_available_at_utc": self.system_available_at_utc,
            "supersedes_artifact_id": self.supersedes_artifact_id.to_dict() if self.supersedes_artifact_id else None,
            "review_ref": self.review_ref.to_dict() if self.review_ref else None,
        }


@dataclass(frozen=True)
class NextAction:
    next_action_id: TypedID
    owner: str
    action_type: str
    reason_codes: tuple[str, ...]
    dependency_refs: tuple[TypedID, ...]
    due_event_or_time: str
    completion_evidence_schema: str
    retry_budget_remaining: int
    terminal_if_unavailable: bool
    schema_version: str = SCHEMA_NEXT_ACTION_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_NEXT_ACTION_V1:
            raise ValueError(f"schema_version must be {SCHEMA_NEXT_ACTION_V1}")
        if not self.owner or not self.action_type or not self.reason_codes or not self.completion_evidence_schema:
            raise ValueError("next action requires owner, type, reason, and completion evidence")
        if self.retry_budget_remaining < 0:
            raise ValueError("retry_budget_remaining must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "next_action_id": self.next_action_id.to_dict(),
            "owner": self.owner,
            "action_type": self.action_type,
            "reason_codes": list(self.reason_codes),
            "dependency_refs": [ref.to_dict() for ref in self.dependency_refs],
            "due_event_or_time": self.due_event_or_time,
            "completion_evidence_schema": self.completion_evidence_schema,
            "retry_budget_remaining": self.retry_budget_remaining,
            "terminal_if_unavailable": self.terminal_if_unavailable,
        }


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    group: str
    status: str
    reason_codes: tuple[str, ...]
    checked_at_utc: str
    policy_hash: str
    claim_refs: tuple[TypedID, ...] = ()
    evidence_refs: tuple[TypedID, ...] = ()
    artifact_refs: tuple[TypedID, ...] = ()
    override_allowed: bool = False
    override_use_ref: TypedID | None = None
    next_action_ref: TypedID | None = None
    schema_version: str = SCHEMA_GATE_RESULT_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_GATE_RESULT_V1:
            raise ValueError(f"schema_version must be {SCHEMA_GATE_RESULT_V1}")
        if self.status not in {"PASS", "WARN", "FAIL", "BLOCKED", "NOT_APPLICABLE"}:
            raise ValueError("invalid gate status")
        if not self.gate_id or not self.group:
            raise ValueError("gate_id and group are required")
        validate_timestamp(self.checked_at_utc, "checked_at_utc")
        validate_sha256(self.policy_hash, "policy_hash")
        if self.override_use_ref is not None and not self.override_allowed:
            raise ValueError("override_use_ref requires override_allowed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "gate_id": self.gate_id,
            "group": self.group,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "claim_refs": [ref.to_dict() for ref in self.claim_refs],
            "evidence_refs": [ref.to_dict() for ref in self.evidence_refs],
            "artifact_refs": [ref.to_dict() for ref in self.artifact_refs],
            "checked_at_utc": self.checked_at_utc,
            "policy_hash": self.policy_hash,
            "override_allowed": self.override_allowed,
            "override_use_ref": self.override_use_ref.to_dict() if self.override_use_ref else None,
            "next_action_ref": self.next_action_ref.to_dict() if self.next_action_ref else None,
        }


@dataclass(frozen=True)
class ReviewEnvelope:
    review_id: TypedID
    reviewed_artifact_refs: tuple[TypedID, ...]
    reviewed_manifest_hash: str
    builder_actor_id: str
    reviewer_actor_id: str
    reviewer_profile: str
    reviewer_session: str
    model_family: str
    decision: str
    checks: tuple[str, ...]
    findings: tuple[str, ...]
    created_at_utc: str
    content_hash_sha256: str = ""
    signature_scheme: str | None = None
    signer_key_id: str | None = None
    signature: str | None = None
    schema_version: str = SCHEMA_REVIEW_ENVELOPE_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_REVIEW_ENVELOPE_V1:
            raise ValueError(f"schema_version must be {SCHEMA_REVIEW_ENVELOPE_V1}")
        if self.builder_actor_id == self.reviewer_actor_id:
            raise ValueError("builder and reviewer must differ")
        if self.decision not in {"APPROVE", "REQUEST_CHANGES", "REJECT"}:
            raise ValueError("invalid review decision")
        if not self.reviewed_artifact_refs or not self.reviewer_profile or not self.reviewer_session or not self.model_family:
            raise ValueError("digest-bound review identity and scope are required")
        validate_sha256(self.reviewed_manifest_hash, "reviewed_manifest_hash")
        validate_timestamp(self.created_at_utc, "created_at_utc")
        expected = sha256_hex(canonical_bytes(self._content_dict()))
        if self.content_hash_sha256 and self.content_hash_sha256 != expected:
            raise ValueError("review content hash mismatch")
        object.__setattr__(self, "content_hash_sha256", expected)

    def _content_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "review_id": self.review_id.to_dict(),
            "reviewed_artifact_refs": [ref.to_dict() for ref in self.reviewed_artifact_refs],
            "reviewed_manifest_hash": self.reviewed_manifest_hash,
            "builder_actor_id": self.builder_actor_id,
            "reviewer_actor_id": self.reviewer_actor_id,
            "reviewer_profile": self.reviewer_profile,
            "reviewer_session": self.reviewer_session,
            "model_family": self.model_family,
            "decision": self.decision,
            "checks": list(self.checks),
            "findings": list(self.findings),
            "created_at_utc": self.created_at_utc,
            "signature_scheme": self.signature_scheme,
            "signer_key_id": self.signer_key_id,
            "signature": self.signature,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "content_hash_sha256": self.content_hash_sha256}


def typed_ids(values: Iterable[Mapping[str, Any]]) -> tuple[TypedID, ...]:
    return tuple(TypedID.from_dict(value) for value in values)
