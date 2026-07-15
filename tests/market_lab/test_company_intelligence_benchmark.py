from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import socket

import pytest

from market_lab.agency_contracts import TypedID, canonical_bytes, canonical_json, sha256_hex, strict_json_loads
from market_lab.agency_policy import protected_state_paths, snapshot_protected_state
from market_lab.company_intelligence_benchmark import (
    BenchmarkCategory,
    CompanyIntelBenchmarkCase,
    FrozenSourceRecord,
    OZ_COMPANY_INTEL_BENCH_V1_BYTE_SHA256,
    load_oz_company_intel_bench,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "market_lab" / "fixtures" / "company_intelligence" / "oz_company_intel_bench_v1.jsonl"
PRODUCT = ROOT / "market_lab" / "company_intelligence_benchmark.py"


def fixture_rows() -> list[dict[str, object]]:
    return [strict_json_loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


def redigest(row: dict[str, object]) -> None:
    content = {key: value for key, value in row.items() if key != "case_digest_sha256"}
    row["case_digest_sha256"] = sha256_hex(canonical_bytes(content))


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(canonical_json(row) for row in rows) + "\n", encoding="utf-8")


def test_frozen_corpus_has_realistic_complete_deterministic_zero_network_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    def network_forbidden(*args: object, **kwargs: object) -> socket.socket:
        raise AssertionError("OzCompanyIntelBench-v1 attempted network access")

    monkeypatch.setattr(socket, "socket", network_forbidden)
    cases = load_oz_company_intel_bench(FIXTURE)

    assert len(cases) == 36
    assert {case.category for case in cases} == set(BenchmarkCategory)
    assert sha256_hex(FIXTURE.read_bytes()) == OZ_COMPANY_INTEL_BENCH_V1_BYTE_SHA256
    assert len({case.case_id for case in cases}) == len(cases)
    assert len({case.case_digest_sha256 for case in cases}) == len(cases)
    assert all(case.safety_mode == "research_mock_only" for case in cases)
    assert all(case.title and case.input_payload and case.sources for case in cases)
    assert all(source.source_locator.startswith("https://") for case in cases for source in case.sources)
    assert all(source.publisher and source.source_reference for case in cases for source in case.sources)
    assert all(len(source.frozen_content) >= 80 for case in cases for source in case.sources)
    assert all(source.evidence_id.local_id == f"frozen-content-sha256:{source.frozen_content_sha256}" for case in cases for source in case.sources)
    assert [case.case_id for case in cases[:10]] == [
        "nvidia-fy2025-compute-networking-exposure",
        "microsoft-fy2024-intelligent-cloud-exposure",
        "apple-fy2023-services-revenue-exposure",
        "tesla-fy2024-energy-generation-storage-exposure",
        "amd-fy2024-data-center-segment-exposure",
        "broadcom-fy2024-semiconductor-solutions-exposure",
        "amazon-fy2024-aws-segment-exposure",
        "meta-fy2024-reality-labs-exposure",
        "alphabet-fy2024-google-cloud-exposure",
        "oracle-fy2024-cloud-services-license-support-exposure",
    ]
    assert {"post-cutoff-results-cannot-promote", "post-cutoff-amazon-aws-results-block"}.issubset({case.case_id for case in cases})


def test_case_and_source_round_trip_are_frozen_and_digest_bound() -> None:
    case = load_oz_company_intel_bench(FIXTURE)[0]
    recovered = CompanyIntelBenchmarkCase.from_dict(strict_json_loads(canonical_json(case.to_dict())))
    source = FrozenSourceRecord.from_dict(strict_json_loads(canonical_json(case.sources[0].to_dict())))

    assert recovered == case
    assert source == case.sources[0]
    assert case.case_digest_sha256 == sha256_hex(canonical_bytes(case.to_dict(include_digest=False)))
    with pytest.raises(FrozenInstanceError):
        case.title = "mutated"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        source.publisher = "mutated"  # type: ignore[misc]


def test_default_loader_rejects_any_frozen_byte_change(tmp_path: Path) -> None:
    tampered = tmp_path / "tampered.jsonl"
    tampered.write_bytes(FIXTURE.read_bytes().replace(b"Exact same-period", b"Exact same period", 1))

    with pytest.raises(ValueError, match="frozen byte digest mismatch"):
        load_oz_company_intel_bench(tampered)


def test_integrity_rejects_content_hash_excerpt_and_content_address_tampering(tmp_path: Path) -> None:
    rows = fixture_rows()
    source = rows[0]["sources"][0]  # type: ignore[index]
    source["frozen_content"] = f"{source['frozen_content']} tampered"  # type: ignore[index]
    redigest(rows[0])
    corrupt_content = tmp_path / "corrupt-content.jsonl"
    write_rows(corrupt_content, rows)
    with pytest.raises(ValueError, match="frozen_content_sha256 mismatch"):
        load_oz_company_intel_bench(corrupt_content, enforce_frozen_digest=False)

    rows = fixture_rows()
    source = rows[0]["sources"][0]  # type: ignore[index]
    source["excerpt"] = "not present in frozen content"  # type: ignore[index]
    source["excerpt_sha256"] = sha256_hex("not present in frozen content")  # type: ignore[index]
    redigest(rows[0])
    corrupt_excerpt = tmp_path / "corrupt-excerpt.jsonl"
    write_rows(corrupt_excerpt, rows)
    with pytest.raises(ValueError, match="excerpt integrity mismatch"):
        load_oz_company_intel_bench(corrupt_excerpt, enforce_frozen_digest=False)

    rows = fixture_rows()
    source = rows[0]["sources"][0]  # type: ignore[index]
    source["evidence_id"] = TypedID("evidence", "company_intel", "v1", "frozen-content-sha256:" + "0" * 64).to_dict()  # type: ignore[index]
    redigest(rows[0])
    fabricated_id = tmp_path / "fabricated-id.jsonl"
    write_rows(fabricated_id, rows)
    with pytest.raises(ValueError, match="not content-addressed"):
        load_oz_company_intel_bench(fabricated_id, enforce_frozen_digest=False)


def test_integrity_rejects_formulaic_ids_unknown_keys_and_noncanonical_rows(tmp_path: Path) -> None:
    rows = fixture_rows()
    rows[0]["case_id"] = "case-1"
    redigest(rows[0])
    formulaic = tmp_path / "formulaic.jsonl"
    write_rows(formulaic, rows)
    with pytest.raises(ValueError, match="descriptive, not formulaic"):
        load_oz_company_intel_bench(formulaic, enforce_frozen_digest=False)

    rows = fixture_rows()
    rows[0]["unexpected"] = "schema drift"
    extra = tmp_path / "extra.jsonl"
    write_rows(extra, rows)
    with pytest.raises(ValueError, match="keys mismatch"):
        load_oz_company_intel_bench(extra, enforce_frozen_digest=False)

    noncanonical = tmp_path / "noncanonical.jsonl"
    noncanonical.write_text("\n".join(json.dumps(row) for row in fixture_rows()) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not canonical JSON"):
        load_oz_company_intel_bench(noncanonical, enforce_frozen_digest=False)


def test_corpus_rules_reject_missing_coverage_and_syndication_promotion(tmp_path: Path) -> None:
    rows = fixture_rows()
    missing = tmp_path / "missing-category.jsonl"
    write_rows(missing, rows[:-1])
    with pytest.raises(ValueError, match="requires at least 36 cases|category coverage is incomplete"):
        load_oz_company_intel_bench(missing, enforce_frozen_digest=False)

    rows = fixture_rows()
    dedupe = next(row for row in rows if row["category"] == "DEDUPE_SYNDICATION")
    dedupe["expected_status"] = "PROMOTABLE"
    dedupe["expected_reason_codes"] = []
    dedupe["expected_selected_evidence_ids"] = [dedupe["sources"][0]["evidence_id"]]  # type: ignore[index]
    redigest(dedupe)
    promoted = tmp_path / "promoted-syndication.jsonl"
    write_rows(promoted, rows)
    with pytest.raises(ValueError, match="cannot promote"):
        load_oz_company_intel_bench(promoted, enforce_frozen_digest=False)


def test_corpus_rules_reject_late_evidence_shortcuts_and_unknown_coercion(tmp_path: Path) -> None:
    rows = fixture_rows()
    point_in_time = next(row for row in rows if row["category"] == "POINT_IN_TIME")
    point_in_time["expected_status"] = "PROMOTABLE"
    point_in_time["expected_reason_codes"] = []
    point_in_time["expected_selected_evidence_ids"] = [point_in_time["sources"][0]["evidence_id"]]  # type: ignore[index]
    redigest(point_in_time)
    late = tmp_path / "late-promoted.jsonl"
    write_rows(late, rows)
    with pytest.raises(ValueError, match="fail closed on late evidence"):
        load_oz_company_intel_bench(late, enforce_frozen_digest=False)

    rows = fixture_rows()
    unknown = next(row for row in rows if row["category"] == "UNKNOWN")
    unknown["expected_status"] = "VALID"
    unknown["expected_reason_codes"] = []
    unknown["expected_selected_evidence_ids"] = [unknown["sources"][0]["evidence_id"]]  # type: ignore[index]
    redigest(unknown)
    coerced = tmp_path / "unknown-coerced.jsonl"
    write_rows(coerced, rows)
    with pytest.raises(ValueError, match="preserve missing quantified exposure"):
        load_oz_company_intel_bench(coerced, enforce_frozen_digest=False)


def test_amendment_rejects_original_selection_and_missing_supersession(tmp_path: Path) -> None:
    rows = fixture_rows()
    amendment = next(row for row in rows if row["category"] == "AMENDMENT")
    amendment["expected_selected_evidence_ids"] = [amendment["sources"][0]["evidence_id"]]  # type: ignore[index]
    redigest(amendment)
    selects_original = tmp_path / "amendment-selects-original.jsonl"
    write_rows(selects_original, rows)
    with pytest.raises(ValueError, match="later amendment source"):
        load_oz_company_intel_bench(selects_original, enforce_frozen_digest=False)

    rows = fixture_rows()
    amendment = next(row for row in rows if row["category"] == "AMENDMENT")
    amendment["expected_reason_codes"] = []
    redigest(amendment)
    missing_supersession = tmp_path / "amendment-missing-supersession.jsonl"
    write_rows(missing_supersession, rows)
    with pytest.raises(ValueError, match="superseded_original"):
        load_oz_company_intel_bench(missing_supersession, enforce_frozen_digest=False)

    rows = fixture_rows()
    amendment = next(row for row in rows if row["category"] == "AMENDMENT")
    original = amendment["sources"][0]  # type: ignore[index]
    amendment["sources"][1].update(  # type: ignore[index]
        source_published_at_utc=original["source_published_at_utc"],
        source_available_at_utc=original["source_available_at_utc"],
        system_available_at_utc=original["system_available_at_utc"],
    )
    redigest(amendment)
    not_later = tmp_path / "amendment-not-later.jsonl"
    write_rows(not_later, rows)
    with pytest.raises(ValueError, match="later amendment source"):
        load_oz_company_intel_bench(not_later, enforce_frozen_digest=False)


def test_amendment_rejects_source_chain_reference_mismatch_and_placeholder(tmp_path: Path) -> None:
    rows = fixture_rows()
    amendment = next(row for row in rows if row["category"] == "AMENDMENT")
    amendment["input_payload"]["revision_reference"] = "SEC:UNRELATED:REFERENCE"  # type: ignore[index]
    redigest(amendment)
    mismatched = tmp_path / "amendment-reference-mismatch.jsonl"
    write_rows(mismatched, rows)
    with pytest.raises(ValueError, match="references must match source records"):
        load_oz_company_intel_bench(mismatched, enforce_frozen_digest=False)

    rows = fixture_rows()
    amendment = next(row for row in rows if row["category"] == "AMENDMENT")
    amendment["input_payload"]["original_reference"] = "SEC:UNRELATED:ORIGINAL"  # type: ignore[index]
    redigest(amendment)
    mismatched_original = tmp_path / "amendment-original-reference-mismatch.jsonl"
    write_rows(mismatched_original, rows)
    with pytest.raises(ValueError, match="references must match source records"):
        load_oz_company_intel_bench(mismatched_original, enforce_frozen_digest=False)

    rows = fixture_rows()
    amendment = next(row for row in rows if row["category"] == "AMENDMENT")
    amendment["input_payload"]["revision_relation"] = "SUPERSEDES_WITHOUT_SOURCE_CHAIN"  # type: ignore[index]
    redigest(amendment)
    invalid_relation = tmp_path / "amendment-invalid-relation.jsonl"
    write_rows(invalid_relation, rows)
    with pytest.raises(ValueError, match="source-chain semantics"):
        load_oz_company_intel_bench(invalid_relation, enforce_frozen_digest=False)

    rows = fixture_rows()
    amendment = next(row for row in rows if row["category"] == "AMENDMENT")
    amendment["input_payload"]["revision_reference"] = "SEC-SUBMISSIONS:CIK0000789019:***"  # type: ignore[index]
    amendment["sources"][1]["source_reference"] = "SEC-SUBMISSIONS:CIK0000789019:***"  # type: ignore[index]
    redigest(amendment)
    placeholder = tmp_path / "amendment-placeholder-reference.jsonl"
    write_rows(placeholder, rows)
    with pytest.raises(ValueError, match="placeholder"):
        load_oz_company_intel_bench(placeholder, enforce_frozen_digest=False)

    rows = fixture_rows()
    amendment = next(row for row in rows if row["category"] == "AMENDMENT")
    amendment["sources"][1]["source_locator"] = "https://www.sec.gov/***"  # type: ignore[index]
    redigest(amendment)
    placeholder_locator = tmp_path / "amendment-placeholder-locator.jsonl"
    write_rows(placeholder_locator, rows)
    with pytest.raises(ValueError, match="placeholder"):
        load_oz_company_intel_bench(placeholder_locator, enforce_frozen_digest=False)


def test_mismatch_exposure_and_counterevidence_mutations_fail_closed(tmp_path: Path) -> None:
    rows = fixture_rows()
    mismatch = next(row for row in rows if row["category"] == "MISMATCH")
    mismatch["expected_status"] = "DISPUTED"
    redigest(mismatch)
    promotable_mismatch = tmp_path / "mismatch-not-fail-closed.jsonl"
    write_rows(promotable_mismatch, rows)
    with pytest.raises(ValueError, match="mismatch case must be non-promotable"):
        load_oz_company_intel_bench(promotable_mismatch, enforce_frozen_digest=False)

    rows = fixture_rows()
    exposure = next(row for row in rows if row["category"] == "EXPOSURE")
    exposure["input_payload"].pop("numerator_value")  # type: ignore[union-attr]
    redigest(exposure)
    incomplete_exposure = tmp_path / "exposure-missing-numerator.jsonl"
    write_rows(incomplete_exposure, rows)
    with pytest.raises(ValueError, match="numerator and denominator"):
        load_oz_company_intel_bench(incomplete_exposure, enforce_frozen_digest=False)

    rows = fixture_rows()
    exposure = next(row for row in rows if row["category"] == "EXPOSURE")
    exposure["input_payload"].pop("denominator_value")  # type: ignore[union-attr]
    redigest(exposure)
    missing_denominator = tmp_path / "exposure-missing-denominator.jsonl"
    write_rows(missing_denominator, rows)
    with pytest.raises(ValueError, match="numerator and denominator"):
        load_oz_company_intel_bench(missing_denominator, enforce_frozen_digest=False)

    rows = fixture_rows()
    counterevidence = next(row for row in rows if row["category"] == "COUNTEREVIDENCE")
    counterevidence["expected_selected_evidence_ids"] = [counterevidence["sources"][0]["evidence_id"]]  # type: ignore[index]
    redigest(counterevidence)
    selected_refutation = tmp_path / "counterevidence-selected.jsonl"
    write_rows(selected_refutation, rows)
    with pytest.raises(ValueError, match="cannot select refuting evidence"):
        load_oz_company_intel_bench(selected_refutation, enforce_frozen_digest=False)


def test_parser_preserves_nonempty_protected_state_and_has_no_execution_imports(tmp_path: Path) -> None:
    protected = protected_state_paths(tmp_path)[0]
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_bytes(b"non-empty protected benchmark sentinel\n")
    before = snapshot_protected_state(tmp_path)

    assert sum(item["bytes"] for item in before.values() if item["exists"]) > 0
    assert load_oz_company_intel_bench(FIXTURE)
    assert snapshot_protected_state(tmp_path) == before

    tree = ast.parse(PRODUCT.read_text(encoding="utf-8"))
    forbidden = {"broker", "options_data", "options_paper", "options_screeners", "portfolio_construction", "alpaca", "requests", "urllib.request"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name not in forbidden for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module not in forbidden
            assert all(alias.name != "*" for alias in node.names)
