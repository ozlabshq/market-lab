from pathlib import Path
import json

import pytest

from market_lab.prediction_markets.errors import ConflictError, PathEscapeError
from market_lab.prediction_markets.models import canonical_json_bytes, parse_json_bytes, sha256_hex
from market_lab.prediction_markets.report import write_report
from market_lab.prediction_markets.store import import_descriptor, load_records, verify


FIXTURES = Path(__file__).parent / "fixtures" / "prediction_markets"


def test_import_writes_raw_and_normalized_idempotently(tmp_path):
    root = tmp_path / "prediction_markets"
    result = import_descriptor(root, FIXTURES / "binary_open_valid.json")
    record = load_records(root)[0]
    path = root / "normalized" / "sha256" / record.normalized_record_hash[:2] / record.normalized_record_hash / "market.json"
    before = path.stat().st_mtime_ns
    again = import_descriptor(root, FIXTURES / "binary_open_valid.json")
    assert result["quarantined"] is False
    assert again["normalized_record_hash"] == result["normalized_record_hash"]
    assert path.stat().st_mtime_ns == before


def test_malformed_fixture_quarantines_without_normalized_record(tmp_path):
    root = tmp_path / "prediction_markets"
    result = import_descriptor(root, FIXTURES / "binary_malformed_prices.json")
    assert result["quarantined"] is True
    assert load_records(root) == []
    check = verify(root)
    assert check["ok"] is True
    assert check["quarantine_count"] == 1
    assert verify(root, strict=True)["ok"] is False


def test_verify_strict_rejects_quote_admissible_and_quarantine(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_missing_rules.json")
    assert verify(root, strict=True)["ok"] is False
    import_descriptor(root, FIXTURES / "binary_malformed_prices.json")
    assert verify(root, strict=True)["quarantine_count"] == 1


def test_verify_detects_normalized_tamper(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    record = load_records(root)[0]
    path = root / "normalized" / "sha256" / record.normalized_record_hash[:2] / record.normalized_record_hash / "market.json"
    path.write_text(path.read_text().replace("Synthetic rainfall", "Synthetic changed"), encoding="utf-8")
    result = verify(root)
    assert result["ok"] is False
    assert result["errors"]


def test_import_all_valid_non_quarantine_fixtures(tmp_path):
    root = tmp_path / "prediction_markets"
    for name in ("binary_open_valid.json", "binary_missing_rules.json", "binary_rule_revision.json", "binary_closed_not_final.json", "binary_void_or_nonstandard.json"):
        assert import_descriptor(root, FIXTURES / name)["quarantined"] is False
    assert len(load_records(root)) == 5


def test_verify_fails_closed_for_missing_manifest_and_orphans(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    (next((root / "raw" / "sha256").glob("*/*")) / "manifest.json").unlink()
    assert verify(root)["ok"] is False
    import_descriptor(tmp_path / "other", FIXTURES / "binary_open_valid.json")
    orphan = root / "normalized" / "sha256" / "aa" / ("a" * 64) / "extra.json"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("{}", encoding="utf-8")
    result = verify(root)
    assert result["ok"] is False
    assert result["errors"]


def test_verify_rejects_rehashed_invalid_normalized_record(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    record_path = next((root / "normalized" / "sha256").glob("*/*/market.json"))
    data = json.loads(record_path.read_text(encoding="utf-8"))
    data["status"] = "BOGUS"
    digestable = dict(data)
    digestable["normalized_record_hash"] = None
    data["normalized_record_hash"] = sha256_hex(canonical_json_bytes(digestable))
    new_path = root / "normalized" / "sha256" / data["normalized_record_hash"][:2] / data["normalized_record_hash"] / "market.json"
    record_path.unlink()
    new_path.parent.mkdir(parents=True)
    new_path.write_bytes(canonical_json_bytes(data) + b"\n")
    result = verify(root)
    assert result["ok"] is False
    assert any(e["error_code"] == "PM0_SCHEMA" for e in result["errors"])


def test_verify_rejects_corrupt_quarantine_metadata(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_malformed_prices.json")
    next((root / "quarantine" / "sha256").glob("*/*/error.json")).write_text("{not-json", encoding="utf-8")
    result = verify(root)
    assert result["ok"] is False
    assert result["errors"]


def test_verify_replays_quarantine_and_rejects_fabricated_metadata(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_malformed_prices.json")
    error_path = next((root / "quarantine" / "sha256").glob("*/*/error.json"))
    error = parse_json_bytes(error_path.read_bytes())
    error["message"] = "fabricated"
    error_path.write_bytes(canonical_json_bytes(error) + b"\n")
    result = verify(root)
    assert result["ok"] is False
    assert any(e["error_code"] == "PM0_INTEGRITY" for e in result["errors"])


def test_verify_rejects_valid_descriptor_stored_only_in_quarantine(tmp_path):
    root = tmp_path / "prediction_markets"
    raw = (FIXTURES / "binary_open_valid.json").read_bytes()
    digest = sha256_hex(raw)
    qdir = root / "quarantine" / "sha256" / digest[:2] / digest
    qdir.mkdir(parents=True)
    (qdir / "input.bin").write_bytes(raw)
    error = {"schema_version": "mlab-pm-quarantine-error.v1", "descriptor_sha256": digest, "error_code": "PM0_SCHEMA", "message": "fabricated"}
    (qdir / "error.json").write_bytes(canonical_json_bytes(error) + b"\n")
    result = verify(root)
    assert result["ok"] is False
    assert any("not rejected" in e["message"] for e in result["errors"])


def test_contextual_conflict_quarantine_verifies_nonstrict_but_not_strict(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    data = parse_json_bytes((FIXTURES / "binary_open_valid.json").read_bytes())
    data["market"]["rules_text"] = data["market"]["rules_text"] + " Same raw identity conflicting revision."
    conflict = tmp_path / "conflict.json"
    conflict.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    result = import_descriptor(root, conflict)
    assert result["quarantined"] is True
    assert result["error_code"] == "PM0_CONFLICT"
    check = verify(root)
    assert check["ok"] is True
    assert check["quarantine_count"] == 1
    strict = verify(root, strict=True)
    assert strict["ok"] is False
    assert strict["quarantine_count"] == 1
    assert strict["strict_failures"]


def test_verify_rejects_fabricated_contextual_conflict_metadata(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    data = parse_json_bytes((FIXTURES / "binary_open_valid.json").read_bytes())
    data["market"]["rules_text"] = data["market"]["rules_text"] + " Same raw identity conflicting revision."
    conflict = tmp_path / "conflict.json"
    conflict.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    import_descriptor(root, conflict)
    error_path = next((root / "quarantine" / "sha256").glob("*/*/error.json"))
    error = parse_json_bytes(error_path.read_bytes())
    error["conflict_context"]["candidate_record"]["rules_hash"] = "0" * 64
    error_path.write_bytes(canonical_json_bytes(error) + b"\n")
    result = verify(root)
    assert result["ok"] is False
    assert any("candidate reference" in e["message"] for e in result["errors"])


def test_verify_rejects_contextual_conflict_when_canonical_record_missing_or_changed(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    data = parse_json_bytes((FIXTURES / "binary_open_valid.json").read_bytes())
    data["market"]["rules_text"] = data["market"]["rules_text"] + " Same raw identity conflicting revision."
    conflict = tmp_path / "conflict.json"
    conflict.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    import_descriptor(root, conflict)
    next((root / "normalized" / "sha256").glob("*/*/market.json")).unlink()
    result = verify(root)
    assert result["ok"] is False
    assert any("missing" in e["message"] or "reference" in e["message"] for e in result["errors"])


def test_verify_rejects_descriptor_manifest_provenance_drift(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    descriptor = next((root / "raw" / "sha256").glob("*/*/descriptor.json"))
    data = parse_json_bytes(descriptor.read_bytes())
    data["capture_adapter_version"] = "changed"
    descriptor.write_bytes(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    result = verify(root)
    assert result["ok"] is False
    assert result["errors"]


def test_descriptor_required_field_types_fail_closed(tmp_path):
    root = tmp_path / "prediction_markets"
    data = parse_json_bytes((FIXTURES / "binary_open_valid.json").read_bytes())
    data["capture_adapter_version"] = 7
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    assert import_descriptor(root, bad)["quarantined"] is True
    assert verify(root, strict=True)["ok"] is False


def test_no_terminal_newline_descriptor_keeps_manifest_provenance(tmp_path):
    root = tmp_path / "prediction_markets"
    raw = (FIXTURES / "binary_open_valid.json").read_bytes().rstrip(b"\n")
    descriptor = tmp_path / "descriptor.json"
    descriptor.write_bytes(raw)
    result = import_descriptor(root, descriptor)
    assert result["quarantined"] is False
    manifest = parse_json_bytes(next((root / "raw" / "sha256").glob("*/*/manifest.json")).read_bytes())
    assert manifest["descriptor_sha256"] == sha256_hex(raw)
    assert verify(root, strict=True)["ok"] is True


def test_report_and_store_reject_symlink_write_dirs(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "reports").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathEscapeError):
        write_report(root)
    root2 = tmp_path / "prediction_markets2"
    raw_hash = parse_json_bytes((FIXTURES / "binary_open_valid.json").read_bytes())["raw_sha256"]
    (root2 / "raw" / "sha256").mkdir(parents=True)
    (root2 / "raw" / "sha256" / raw_hash[:2]).symlink_to(outside, target_is_directory=True)
    result = import_descriptor(root2, FIXTURES / "binary_open_valid.json")
    assert result["quarantined"] is True
    assert result["error_code"] == "PM0_PATH_ESCAPE"
    assert list(outside.iterdir()) == []


def test_explicit_prediction_root_symlink_cannot_write_to_target(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    lane = tmp_path / "lane"
    lane.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathEscapeError):
        import_descriptor(lane, FIXTURES / "binary_open_valid.json")
    assert list(outside.iterdir()) == []


def test_verify_rejects_closed_inventory_orphan_report(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    (root / "reports").mkdir()
    (root / "reports" / "orphan.bin").write_bytes(b"orphan")
    result = verify(root)
    assert result["ok"] is False
    assert any(e["error_code"] == "PM0_INTEGRITY" for e in result["errors"])


def test_identical_report_write_preserves_mtime(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    write_report(root)
    latest = root / "reports" / "latest.md"
    before = latest.stat().st_mtime_ns
    write_report(root)
    assert latest.stat().st_mtime_ns == before


def test_digest_addressed_report_conflicts_when_quarantine_changes_same_dataset(tmp_path):
    root = tmp_path / "prediction_markets"
    import_descriptor(root, FIXTURES / "binary_open_valid.json")
    first = write_report(root)
    digest_path = root / "reports" / f"{first['dataset_sha256']}.md"
    before = digest_path.stat().st_mtime_ns
    import_descriptor(root, FIXTURES / "binary_malformed_prices.json")
    with pytest.raises(ConflictError):
        write_report(root)
    assert digest_path.stat().st_mtime_ns == before
