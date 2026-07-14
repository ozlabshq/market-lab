from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import shutil

import pytest

from market_lab.agency_case import AgencyCaseManifest
from market_lab.agency_contracts import (
    SCHEMA_REVIEW_ENVELOPE_V1,
    ReviewEnvelope,
    TypedID,
    canonical_json,
    strict_json_loads,
)
from market_lab.agency_events import (
    canonical_event_line,
    create_event,
    legacy_ledger_anchor,
    load_events,
    replay_status,
    resolve_idempotency,
    verify_event_chain,
)
from market_lab.agency_policy import (
    foundation_fixture_catalog,
    is_policy_compatible,
    protected_state_paths,
    snapshot_protected_state,
    verify_source_manifest,
)

NOW = "2026-07-14T08:00:00Z"
ZERO = "0" * 64
ONE = "1" * 64
ROOT = Path(__file__).resolve().parents[2]


def tid(kind: str, local_id: str, *, domain: str = "agency") -> TypedID:
    return TypedID(kind=kind, domain=domain, id_schema_version="v1", local_id=local_id)


def event(
    sequence: int,
    event_type: str,
    *,
    previous: str | None = None,
    key: str | None = None,
    input_hashes: tuple[str, ...] = (ZERO,),
    legacy_anchor: str | None = None,
    payload: dict | None = None,
) -> dict:
    return create_event(
        event_id=tid("event", f"event-{sequence}"),
        agency_case_id=tid("agency_case", "case-1"),
        subsystem="agency",
        subsystem_run_id=tid("agency_run", "run-1"),
        sequence_number=sequence,
        idempotency_key=key or f"key-{sequence}",
        event_type=event_type,
        occurred_at_utc=NOW,
        actor_type="agent",
        actor_id="maker",
        mode="frozen_replay",
        state_namespace="agency_case_status",
        state_before=None if sequence == 1 else "CREATED",
        state_after="CREATED",
        policy_hash=ONE,
        input_hashes=input_hashes,
        previous_event_hash=previous,
        legacy_anchor_sha256=legacy_anchor,
        event_payload=payload or {},
    )


def test_canonical_json_sorts_objects_and_set_like_collections_but_preserves_sequences() -> None:
    payload = {
        "z": {"beta", "alpha"},
        "a": [
            {"sequence_index": 0, "value": "first"},
            {"sequence_index": 1, "value": "second"},
        ],
        "decimal": Decimal("12.3400"),
    }
    assert canonical_json(payload) == '{"a":[{"sequence_index":0,"value":"first"},{"sequence_index":1,"value":"second"}],"decimal":"12.34","z":["alpha","beta"]}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 1.25, Decimal("-0")])
def test_canonical_json_rejects_binary_float_nonfinite_and_negative_zero(value: object) -> None:
    with pytest.raises(ValueError):
        canonical_json({"value": value})


def test_canonical_json_rejects_duplicate_keys_and_noncontiguous_semantic_sequence() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        strict_json_loads('{"a":1,"a":2}')
    with pytest.raises(ValueError, match="contiguous"):
        canonical_json([{"sequence_index": 1}, {"sequence_index": 0}])


def test_typed_ids_are_domain_separated_and_validate_local_ids() -> None:
    agency = tid("security", "AAPL", domain="agency")
    web = tid("security", "AAPL", domain="web_evidence")
    assert agency != web
    assert agency.digest_sha256 != web.digest_sha256
    assert agency == TypedID.from_dict(agency.to_dict())
    with pytest.raises(ValueError, match="local_id"):
        tid("security", " bad ")
    with pytest.raises(ValueError, match="digest"):
        TypedID("security", "agency", "v1", "AAPL", ZERO)


def test_review_envelope_is_digest_bound_and_requires_independence() -> None:
    artifact = tid("artifact", "slice-0")
    review = ReviewEnvelope(
        review_id=tid("review", "review-1"),
        reviewed_artifact_refs=(artifact,),
        reviewed_manifest_hash=ONE,
        builder_actor_id="maker",
        reviewer_actor_id="reviewer",
        reviewer_profile="ozzy-review",
        reviewer_session="session-1",
        model_family="gpt-5.5",
        decision="APPROVE",
        checks=("targeted",),
        findings=(),
        created_at_utc=NOW,
        schema_version=SCHEMA_REVIEW_ENVELOPE_V1,
    )
    assert len(review.content_hash_sha256) == 64
    with pytest.raises(ValueError, match="must differ"):
        ReviewEnvelope(
            review_id=tid("review", "review-2"),
            reviewed_artifact_refs=(artifact,),
            reviewed_manifest_hash=ONE,
            builder_actor_id="same",
            reviewer_actor_id="same",
            reviewer_profile="default",
            reviewer_session="session-2",
            model_family="gpt",
            decision="APPROVE",
            checks=(),
            findings=(),
            created_at_utc=NOW,
        )


def test_event_hash_chain_requires_contiguous_sequence_and_detects_tamper() -> None:
    first = event(1, "case.created", payload={"projected_status": "CREATED"})
    second = event(2, "inputs.pinned", previous=first["event_hash"], payload={"projected_status": "INPUTS_PINNED"})
    assert verify_event_chain([first, second]) == (True, "")
    broken = dict(second)
    broken["sequence_number"] = 3
    assert verify_event_chain([first, broken]) == (False, "non-contiguous sequence")
    tampered = json.loads(json.dumps(second))
    tampered["event_payload"]["projected_status"] = "FINALIZED"
    assert verify_event_chain([first, tampered]) == (False, "event hash mismatch")


def test_mixed_ledger_requires_anchor_to_exact_legacy_bytes() -> None:
    legacy_bytes = b'{"event":"legacy"}\n'
    legacy = json.loads(legacy_bytes)
    first = event(1, "case.created", legacy_anchor=legacy_ledger_anchor(legacy_bytes))
    assert verify_event_chain([legacy, first], legacy_bytes=legacy_bytes) == (True, "")
    assert verify_event_chain([legacy, first], legacy_bytes=b'{"event": "legacy"}\n') == (False, "legacy anchor mismatch")
    other_bytes = b'{"event":"other"}\n'
    other_anchor = event(1, "case.created", legacy_anchor=legacy_ledger_anchor(other_bytes))
    assert verify_event_chain([legacy, other_anchor], legacy_bytes=other_bytes) == (False, "legacy bytes do not match legacy rows")


def test_idempotency_returns_prior_result_and_changed_inputs_conflict() -> None:
    first = event(1, "case.created", key="stable", input_hashes=(ZERO,))
    assert resolve_idempotency([first], "stable", (ZERO,)) == first
    with pytest.raises(ValueError, match="idempotency conflict"):
        resolve_idempotency([first], "stable", (ONE,))
    conflicting = event(2, "inputs.pinned", previous=first["event_hash"], key="stable", input_hashes=(ONE,))
    assert verify_event_chain([first, conflicting]) == (False, "idempotency conflict")


def test_only_final_partial_jsonl_line_is_recoverable(tmp_path: Path) -> None:
    first = event(1, "case.created")
    path = tmp_path / "events.jsonl"
    path.write_bytes(canonical_event_line(first) + b'{"schema_version":')
    rows, recovered = load_events(path)
    assert rows == [first]
    assert recovered is True
    path.write_bytes(canonical_event_line(first) + bytes([255]))
    rows, recovered = load_events(path)
    assert rows == [first]
    assert recovered is True
    path.write_bytes(b'{"broken":\n' + canonical_event_line(first))
    with pytest.raises(ValueError):
        load_events(path)


def test_status_replay_and_case_projection_are_deterministic() -> None:
    first = event(1, "case.created")
    second = event(2, "inputs.pinned", previous=first["event_hash"])
    status = replay_status([first, second], tid("agency_case", "case-1"))
    assert status.status == "INPUTS_PINNED"
    manifest = AgencyCaseManifest.from_events(
        agency_case_id=tid("agency_case", "case-1"),
        created_at_utc=NOW,
        analysis_cutoff_utc=NOW,
        mode="frozen_replay",
        rows=[first, second],
        input_artifact_hashes=(ZERO,),
    )
    assert manifest.status == "INPUTS_PINNED"
    assert manifest.safety_mode == "research_mock_only"
    assert manifest.to_dict()["status_projection_hash"] == manifest.status_projection_hash


def test_exact_source_manifest_passes_and_drift_blocks(tmp_path: Path) -> None:
    ok, reasons, digests = verify_source_manifest()
    assert ok, reasons
    assert len(digests) == 13

    research = tmp_path / "research"
    research.mkdir()
    source_manifest = ROOT / "research" / "agency_source_manifest.json"
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    shutil.copy2(source_manifest, research / source_manifest.name)
    for row in manifest["artifacts"]:
        source = ROOT / row["path"]
        destination = tmp_path / row["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    drifted = tmp_path / manifest["artifacts"][0]["path"]
    drifted.write_bytes(drifted.read_bytes() + b"\n")
    ok, reasons, _ = verify_source_manifest(research / "agency_source_manifest.json")
    assert not ok
    assert any(reason.startswith("digest_mismatch:") for reason in reasons)


def test_protected_state_resolver_uses_alternate_data_root_without_mutation(tmp_path: Path) -> None:
    paths = protected_state_paths(tmp_path)
    assert len(paths) == 12
    assert all(tmp_path.resolve() in path.parents for path in paths)
    state = tmp_path / "mock_portfolio_state.json"
    state.write_bytes(b'{"cash":100000}\n')
    before = snapshot_protected_state(tmp_path)
    after = snapshot_protected_state(tmp_path)
    assert before == after
    assert before["mock_portfolio_state.json"]["bytes"] > 0


def test_frozen_and_chaos_catalogs_are_exact_nonempty_and_zero_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def network_forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("foundation validation attempted network access")

    monkeypatch.setattr("socket.socket", network_forbidden)
    catalogs = foundation_fixture_catalog(ROOT)
    assert [(catalog.lane, catalog.count()) for catalog in catalogs] == [("frozen", 2), ("chaos", 8)]
    assert all(catalog.verify() == (True, "") for catalog in catalogs)
    assert is_policy_compatible("agency", "mlab-agency-budget.v1")
    assert not is_policy_compatible("agency", "mlab-live-trading.v1")
    ok, reasons, _ = verify_source_manifest()
    assert ok, reasons
