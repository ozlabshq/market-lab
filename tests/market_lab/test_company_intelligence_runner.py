from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from market_lab.agency_contracts import canonical_json
from market_lab.company_intelligence_runner import (
    build_frozen_company_run,
    publish_run,
    replay_run,
    run_frozen_benchmark,
    validate_run,
    validate_web_evidence_input,
    DEFAULT_POLICY,
)
from market_lab.company_intelligence_store import CompanyIntelligenceRunStore, CompanyStoreError

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "market_lab" / "fixtures" / "company_intelligence" / "oz_company_intel_bench_v1.jsonl"


def test_frozen_build_discovers_real_issuers_and_uses_zero_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def network_forbidden(*args: object, **kwargs: object) -> socket.socket:
        raise AssertionError("company intelligence frozen build attempted network access")

    monkeypatch.setattr(socket, "socket", network_forbidden)
    result = build_frozen_company_run(cases_path=FIXTURE, output_root=tmp_path, run_id="run-frozen", builder_id="builder-a")

    assert result["replay"]["ok"] is True
    assert {lead["security"] for lead in result["discovery"]} >= {"NVDA", "MSFT", "AAPL"}
    assert len(result["drafts"]) == 36
    assert replay_run(tmp_path / "run-frozen") == result["replay"]


def test_publication_requires_independent_approve_and_preserves_deterministic_outcomes(tmp_path: Path) -> None:
    build_frozen_company_run(cases_path=FIXTURE, output_root=tmp_path, run_id="run-review", builder_id="builder-a")

    self_review = publish_run(tmp_path / "run-review", reviewer_id="builder-a", decision="APPROVE")
    assert self_review["review_ok"] is False
    assert any(row["outcome"] == "BLOCKED_REVIEW" for row in self_review["outcomes"] if row["validation_outcome"] == "DRAFT_READY_PENDING_REVIEW")

    approved = publish_run(tmp_path / "run-review", reviewer_id="reviewer-b", decision="APPROVE")
    ready = [row for row in approved["outcomes"] if row["outcome"] == "READY"]
    parked = [row for row in approved["outcomes"] if row["outcome"] == "PARK_RESEARCH"]
    rejected = [row for row in approved["outcomes"] if row["outcome"] == "REJECT_MAPPING"]
    assert ready and parked and rejected
    assert all(row["validation_outcome"] != "DRAFT_READY_PENDING_REVIEW" for row in parked + rejected)


def test_store_rejects_truncated_jsonl_and_frozen_replay_does_not_mutate(tmp_path: Path) -> None:
    build_frozen_company_run(cases_path=FIXTURE, output_root=tmp_path, run_id="run-store")
    store = CompanyIntelligenceRunStore(tmp_path, "run-store")
    before = replay_run(tmp_path / "run-store")
    assert replay_run(tmp_path / "run-store") == before

    audit = tmp_path / "run-store" / "audit_log.jsonl"
    audit.write_bytes(audit.read_bytes() + b'{"truncated":true')
    with pytest.raises(CompanyStoreError, match="truncated JSONL"):
        store.read_jsonl("audit_log.jsonl")


def test_m2_adapter_and_benchmark_metrics_are_strict(tmp_path: Path) -> None:
    compatibility = validate_web_evidence_input(FIXTURE, "frozen", "2025-03-01T00:00:00Z", DEFAULT_POLICY)
    assert compatibility.status == "ACCEPTED"
    assert compatibility.accepted_schema_versions == ("oz-company-intel-bench.v1",)

    metrics = run_frozen_benchmark(FIXTURE, fail_on_gate=False)
    assert metrics["ok"] is True
    assert metrics["metrics"]["selected_security_precision"] == "1"
    assert metrics["metrics"]["numeric_exposure_accuracy"] == "1"
    assert metrics["metrics"]["hard_gate_blocks"] > 0

    fail_metrics = run_frozen_benchmark(FIXTURE, fail_on_gate=True)
    assert fail_metrics["ok"] is False


def test_cli_build_validate_replay_benchmark_smoke(tmp_path: Path) -> None:
    script = ROOT / "scripts" / "market_lab_company_intelligence.py"
    build = subprocess.run(
        [sys.executable, str(script), "build", "--cases", str(FIXTURE), "--run-id", "cli-run", "--output-root", str(tmp_path)],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(build.stdout)
    assert payload["run_id"] == "cli-run"

    validate = subprocess.run(
        [sys.executable, str(script), "validate-run", "--run-dir", str(tmp_path / "cli-run"), "--fail-on-gate"],
        text=True,
        capture_output=True,
    )
    assert validate.returncode == 1
    assert json.loads(validate.stdout)["hard_gate_failures"]

    replay = subprocess.run(
        [sys.executable, str(script), "replay", "--run-dir", str(tmp_path / "cli-run")],
        check=True,
        text=True,
        capture_output=True,
    )
    assert json.loads(replay.stdout)["ok"] is True

    benchmark = subprocess.run(
        [sys.executable, str(script), "benchmark", "--cases", str(FIXTURE)],
        check=True,
        text=True,
        capture_output=True,
    )
    assert json.loads(benchmark.stdout)["metrics"]["selected_security_precision"] == "1"
