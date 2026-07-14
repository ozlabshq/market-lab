import json
from pathlib import Path

import pytest

from market_lab.web_evidence_runner import run_benchmark


FIXTURE = Path("tests/market_lab/fixtures/web_evidence/benchmark_v1.jsonl")
CHAOS = Path("tests/market_lab/fixtures/web_evidence/chaos_v1.jsonl")


def test_frozen_benchmark_verifies_fixture_body_hashes(tmp_path: Path) -> None:
    result = run_benchmark(tmp_path / "run", lane="frozen", cases_path=FIXTURE, output_path=tmp_path / "out.json", fail_on_gate=True)

    assert result["passed"] is True
    assert result["checks"]["frozen_replay_reproduces_hashes"] is True
    assert result["metrics"]["network_calls"] == 0


def test_frozen_benchmark_fails_corrupt_hash(tmp_path: Path) -> None:
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    rows[0]["expected_snapshot_sha256"] = "0" * 64
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="benchmark-gates-failed"):
        run_benchmark(tmp_path / "run", lane="frozen", cases_path=corrupt, output_path=tmp_path / "out.json", fail_on_gate=True)


def test_chaos_benchmark_fails_corrupt_expected_status(tmp_path: Path) -> None:
    rows = [json.loads(line) for line in CHAOS.read_text(encoding="utf-8").splitlines()]
    rows[0]["expected_status"] = "success"
    corrupt = tmp_path / "chaos-corrupt.jsonl"
    corrupt.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="benchmark-gates-failed"):
        run_benchmark(tmp_path / "run", lane="chaos", cases_path=corrupt, output_path=tmp_path / "out.json", fail_on_gate=True)


def test_chaos_benchmark_derives_honesty_checks_from_simulated_outcomes(tmp_path: Path) -> None:
    result = run_benchmark(tmp_path / "run", lane="chaos", cases_path=CHAOS, output_path=tmp_path / "out.json", fail_on_gate=True)

    assert result["passed"] is True
    assert result["checks"]["no_failed_fetch_evidence"] is True
    assert result["metrics"]["simulated_failed_fetches"] == 4
    assert result["checks"]["private_destinations_blocked"] is True
    assert result["metrics"]["private_block_status"] == "unsafe_url"
    assert result["checks"]["optional_providers_explicit"] is True
    assert result["metrics"]["optional_health_status"] == "unconfigured"
    assert result["checks"]["resume_idempotent"] is True
    assert result["metrics"]["resume_counts"]["first"] == result["metrics"]["resume_counts"]["second"]
    assert result["checks"]["budget_adherence"] is True
    assert result["metrics"]["network_calls"] == 0
    assert result["metrics"]["charged_cost"] == 0


def test_chaos_benchmark_fails_missing_failure_type(tmp_path: Path) -> None:
    rows = [json.loads(line) for line in CHAOS.read_text(encoding="utf-8").splitlines()]
    corrupt = tmp_path / "chaos-missing.jsonl"
    corrupt.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows[1:]) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="benchmark-gates-failed"):
        run_benchmark(tmp_path / "run", lane="chaos", cases_path=corrupt, output_path=tmp_path / "out.json", fail_on_gate=True)

    written = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert "rate_limited" in written["checks"]["missing_failure_types"]


def test_malformed_corpus_fails_under_gate(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="benchmark-corpus-missing-or-empty"):
        run_benchmark(tmp_path / "run", lane="frozen", cases_path=malformed, output_path=tmp_path / "out.json", fail_on_gate=True)

    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["passed"] is False
