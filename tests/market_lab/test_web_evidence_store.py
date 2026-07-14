import json
from pathlib import Path

from market_lab.web_evidence import sha256_hex
from market_lab.web_evidence_store import append_audit_chain, load_audit_chain, verify_audit_chain


def test_legacy_audit_anchor_preserves_no_trailing_newline(tmp_path: Path) -> None:
    legacy = b'{"event":"legacy"}'
    (tmp_path / "audit_log.jsonl").write_bytes(legacy)

    append_audit_chain(tmp_path, {"event_type": "first", "run_id": "run"})
    rows = load_audit_chain(tmp_path)

    assert rows[1]["previous_event_hash"] == sha256_hex(legacy)
    assert verify_audit_chain(rows) == (True, "")


def test_audit_chain_rejects_missing_v2_envelope_field(tmp_path: Path) -> None:
    append_audit_chain(tmp_path, {"event_type": "first", "run_id": "run"})
    rows = load_audit_chain(tmp_path)
    rows[0].pop("actor_type")

    assert verify_audit_chain(rows) == (False, "invalid v2 envelope: actor_type")


def test_audit_hash_excludes_loader_metadata(tmp_path: Path) -> None:
    append_audit_chain(tmp_path, {"event_type": "first", "run_id": "run"})
    row = load_audit_chain(tmp_path)[0]
    raw = json.loads(row["__raw_line"])

    assert raw["event_hash"] == row["event_hash"]
    assert verify_audit_chain([row]) == (True, "")
