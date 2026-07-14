from __future__ import annotations

"""Canonical agency events, integrity verification, recovery, and status replay."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .agency_contracts import (
    SCHEMA_AGENCY_EVENT_V1,
    TypedID,
    canonical_bytes,
    canonical_json,
    sha256_hex,
    strict_json_loads,
    validate_sha256,
    validate_timestamp,
)

LEGACY_SCHEMA_VERSION = "mlab-audit.legacy"


def legacy_ledger_anchor(raw_legacy_bytes: bytes) -> str:
    if not raw_legacy_bytes:
        raise ValueError("legacy ledger anchor requires non-empty prior bytes")
    return sha256_hex(raw_legacy_bytes)


def compute_event_hash(event: Mapping[str, Any]) -> str:
    payload = dict(event)
    payload.pop("event_hash", None)
    return sha256_hex(canonical_bytes(payload))


def create_event(
    *,
    event_id: TypedID,
    agency_case_id: TypedID,
    subsystem: str,
    subsystem_run_id: TypedID,
    sequence_number: int,
    idempotency_key: str,
    event_type: str,
    occurred_at_utc: str,
    actor_type: str,
    actor_id: str,
    mode: str,
    state_namespace: str,
    state_before: str | None,
    state_after: str | None,
    policy_hash: str,
    event_payload: Mapping[str, Any] | None = None,
    input_refs: Iterable[TypedID] = (),
    input_hashes: Iterable[str] = (),
    output_refs: Iterable[TypedID] = (),
    output_hashes: Iterable[str] = (),
    reason_codes: Iterable[str] = (),
    redactions: Iterable[str] = (),
    previous_event_hash: str | None = None,
    legacy_anchor_sha256: str | None = None,
    source_available_at_utc: str | None = None,
    system_available_at_utc: str | None = None,
    effective_at_utc: str | None = None,
    observed_at_utc: str | None = None,
    budget_reservation_id: str | None = None,
    budget_before: str | None = None,
    budget_charge: str | None = None,
    budget_after: str | None = None,
) -> dict[str, Any]:
    if isinstance(sequence_number, bool) or not isinstance(sequence_number, int) or sequence_number < 1:
        raise ValueError("sequence_number must be a positive integer")
    if not idempotency_key or not event_type or not subsystem or not actor_type or not actor_id or not state_namespace:
        raise ValueError("event identity, actor, subsystem, and state namespace are required")
    validate_timestamp(occurred_at_utc, "occurred_at_utc")
    system_available_at_utc = system_available_at_utc or occurred_at_utc
    validate_timestamp(system_available_at_utc, "system_available_at_utc")
    for name, value in (
        ("source_available_at_utc", source_available_at_utc),
        ("effective_at_utc", effective_at_utc),
        ("observed_at_utc", observed_at_utc),
    ):
        if value is not None:
            validate_timestamp(value, name)
    validate_sha256(policy_hash, "policy_hash")
    input_hash_tuple = tuple(input_hashes)
    output_hash_tuple = tuple(output_hashes)
    for digest in (*input_hash_tuple, *output_hash_tuple):
        validate_sha256(digest, "artifact hash")
    if previous_event_hash is not None:
        validate_sha256(previous_event_hash, "previous_event_hash")
    if legacy_anchor_sha256 is not None:
        validate_sha256(legacy_anchor_sha256, "legacy_anchor_sha256")

    event: dict[str, Any] = {
        "schema_version": SCHEMA_AGENCY_EVENT_V1,
        "event_id": event_id.to_dict(),
        "agency_case_id": agency_case_id.to_dict(),
        "subsystem": subsystem,
        "subsystem_run_id": subsystem_run_id.to_dict(),
        "sequence_number": sequence_number,
        "idempotency_key": idempotency_key,
        "event_type": event_type,
        "occurred_at_utc": occurred_at_utc,
        "source_available_at_utc": source_available_at_utc,
        "system_available_at_utc": system_available_at_utc,
        "effective_at_utc": effective_at_utc,
        "observed_at_utc": observed_at_utc,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "mode": mode,
        "state_namespace": state_namespace,
        "state_before": state_before,
        "state_after": state_after,
        "input_refs": [ref.to_dict() for ref in input_refs],
        "input_hashes": list(input_hash_tuple),
        "output_refs": [ref.to_dict() for ref in output_refs],
        "output_hashes": list(output_hash_tuple),
        "policy_hash": policy_hash,
        "budget_reservation_id": budget_reservation_id,
        "budget_before": budget_before,
        "budget_charge": budget_charge,
        "budget_after": budget_after,
        "reason_codes": list(reason_codes),
        "redactions": list(redactions),
        "previous_event_hash": previous_event_hash,
        "legacy_anchor_sha256": legacy_anchor_sha256,
        "event_payload": dict(event_payload or {}),
    }
    event["event_hash"] = compute_event_hash(event)
    return event


def _validate_typed_event(row: Mapping[str, Any]) -> None:
    TypedID.from_dict(row.get("event_id", {}))
    TypedID.from_dict(row.get("agency_case_id", {}))
    TypedID.from_dict(row.get("subsystem_run_id", {}))
    validate_timestamp(str(row.get("occurred_at_utc", "")), "occurred_at_utc")
    validate_timestamp(str(row.get("system_available_at_utc", "")), "system_available_at_utc")
    validate_sha256(str(row.get("policy_hash", "")), "policy_hash")
    validate_sha256(str(row.get("event_hash", "")), "event_hash")
    if not isinstance(row.get("event_payload"), dict):
        raise ValueError("event_payload must be an object")


def verify_event_chain(
    rows: list[dict[str, Any]],
    *,
    legacy_bytes: bytes | None = None,
) -> tuple[bool, str]:
    typed_started = False
    typed_sequence = 0
    previous_hash: str | None = None
    event_ids: set[tuple[str, str, str]] = set()
    idempotency_inputs: dict[str, tuple[str, ...]] = {}
    legacy_count = 0

    for row in rows:
        if row.get("schema_version") != SCHEMA_AGENCY_EVENT_V1:
            if typed_started:
                return False, "legacy row after typed event"
            legacy_count += 1
            continue

        typed_started = True
        typed_sequence += 1
        try:
            _validate_typed_event(row)
        except (TypeError, ValueError) as exc:
            return False, str(exc)
        if row.get("sequence_number") != typed_sequence:
            return False, "non-contiguous sequence"
        event_id = TypedID.from_dict(row["event_id"]).identity_key()
        if event_id in event_ids:
            return False, "duplicate event_id"
        event_ids.add(event_id)

        actual_previous = row.get("previous_event_hash")
        if typed_sequence == 1:
            if actual_previous is not None:
                return False, "first typed event must not reference a typed predecessor"
            if legacy_count:
                if legacy_bytes is None:
                    return False, "mixed ledger requires exact legacy bytes"
                try:
                    anchored_rows = [
                        strict_json_loads(line)
                        for line in legacy_bytes.decode("utf-8").splitlines()
                        if line.strip()
                    ]
                except (UnicodeDecodeError, ValueError):
                    return False, "legacy bytes are not valid JSONL"
                if anchored_rows != rows[:legacy_count]:
                    return False, "legacy bytes do not match legacy rows"
                expected_anchor = legacy_ledger_anchor(legacy_bytes)
                if row.get("legacy_anchor_sha256") != expected_anchor:
                    return False, "legacy anchor mismatch"
            elif row.get("legacy_anchor_sha256") is not None:
                return False, "legacy anchor without legacy rows"
        elif actual_previous != previous_hash:
            return False, "previous_event_hash mismatch"

        if compute_event_hash(row) != row.get("event_hash"):
            return False, "event hash mismatch"
        key = row.get("idempotency_key")
        if not isinstance(key, str) or not key:
            return False, "idempotency_key required"
        hashes = tuple(row.get("input_hashes", []))
        if key in idempotency_inputs:
            if idempotency_inputs[key] != hashes:
                return False, "idempotency conflict"
            return False, "duplicate idempotency key"
        idempotency_inputs[key] = hashes
        previous_hash = str(row["event_hash"])

    return True, ""


def resolve_idempotency(
    rows: Iterable[Mapping[str, Any]],
    idempotency_key: str,
    input_hashes: Iterable[str],
) -> Mapping[str, Any] | None:
    requested = tuple(input_hashes)
    for row in rows:
        if row.get("schema_version") != SCHEMA_AGENCY_EVENT_V1 or row.get("idempotency_key") != idempotency_key:
            continue
        existing = tuple(row.get("input_hashes", []))
        if existing != requested:
            raise ValueError("idempotency conflict: same key with changed input hashes")
        return row
    return None


def load_events(path_or_run_dir: Path, *, allow_final_partial: bool = True) -> tuple[list[dict[str, Any]], bool]:
    path = Path(path_or_run_dir)
    if path.is_dir() or path.suffix != ".jsonl":
        path = path / "events.jsonl"
    if not path.exists():
        return [], False
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    rows: list[dict[str, Any]] = []
    recovered = False
    for index, raw_line in enumerate(lines):
        try:
            text = raw_line.decode("utf-8").strip()
            if not text:
                continue
            row = strict_json_loads(text)
        except (UnicodeDecodeError, ValueError):
            if allow_final_partial and index == len(lines) - 1 and not raw_line.endswith((b"\n", b"\r")):
                recovered = True
                break
            raise
        if not isinstance(row, dict):
            raise ValueError("event row must be an object")
        rows.append(row)
    return rows, recovered


def canonical_event_line(event: Mapping[str, Any]) -> bytes:
    return canonical_json(event).encode("utf-8") + b"\n"


@dataclass(frozen=True)
class ReplayStatus:
    agency_case_id: TypedID
    status: str
    sequence_number: int
    audit_head_hash: str | None
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]


_EVENT_STATUS = {
    "case.created": "CREATED",
    "inputs.pinned": "INPUTS_PINNED",
    "source.captured": "SOURCE_CAPTURED",
    "evidence.accepted": "EVIDENCE_ACCEPTED",
    "run.finalized": "FINALIZED",
    "run.request_changes": "REQUEST_CHANGES",
    "run.superseded": "SUPERSEDED",
}


def replay_status(
    rows: list[dict[str, Any]],
    agency_case_id: TypedID,
    *,
    legacy_bytes: bytes | None = None,
) -> ReplayStatus:
    ok, reason = verify_event_chain(rows, legacy_bytes=legacy_bytes)
    if not ok:
        raise ValueError(f"invalid agency event chain: {reason}")
    status = "CREATED"
    blockers: list[str] = []
    next_actions: list[str] = []
    sequence = 0
    head: str | None = None
    for row in rows:
        if row.get("schema_version") != SCHEMA_AGENCY_EVENT_V1:
            continue
        if TypedID.from_dict(row["agency_case_id"]) != agency_case_id:
            continue
        sequence = int(row["sequence_number"])
        head = str(row["event_hash"])
        payload = row["event_payload"]
        event_type = str(row["event_type"])
        if event_type in _EVENT_STATUS:
            status = _EVENT_STATUS[event_type]
        if event_type == "run.blocked":
            status = "BLOCKED"
            reason_code = payload.get("reason_code")
            if isinstance(reason_code, str) and reason_code:
                blockers.append(reason_code)
        if event_type == "next_action.created":
            action = payload.get("action_type")
            if isinstance(action, str) and action:
                next_actions.append(action)
        projected = payload.get("projected_status")
        if isinstance(projected, str) and projected:
            status = projected
    return ReplayStatus(agency_case_id, status, sequence, head, tuple(blockers), tuple(next_actions))
