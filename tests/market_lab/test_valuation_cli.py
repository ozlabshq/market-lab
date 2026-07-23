from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "market_lab_valuation.py"
FIXTURE = ROOT / "tests" / "market_lab" / "fixtures" / "valuation" / "mature_us_issuer_run"
BENCHMARK = ROOT / "tests" / "market_lab" / "fixtures" / "valuation" / "benchmark_v1.jsonl"
CUTOFF = "2025-12-31T23:59:59Z"


def test_cli_build_verify_review_round_trip(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    review_authority = tmp_path / "review-authority"
    build = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "build",
            "--run-dir",
            str(FIXTURE),
            "--candidate-id",
            "fixture-candidate",
            "--analysis-cutoff",
            CUTOFF,
            "--mode",
            "frozen",
            "--forecast-years",
            "5",
            "--output-dir",
            str(output),
            "--builder-id",
            "cli-builder",
        ],
        text=True,
        capture_output=True,
    )
    assert build.returncode == 0, build.stderr
    assert json.loads(build.stdout)["status"] == "REVIEW_REQUIRED"

    verify = subprocess.run(
        [sys.executable, str(SCRIPT), "verify", "--output-dir", str(output)],
        text=True,
        capture_output=True,
    )
    assert verify.returncode == 0, verify.stderr
    assert json.loads(verify.stdout)["ok"] is True

    review = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "review",
            "--output-dir",
            str(output),
            "--reviewer-id",
            "cli-reviewer",
            "--decision",
            "APPROVE",
            "--review-authority-dir",
            str(review_authority),
        ],
        text=True,
        capture_output=True,
    )
    assert review.returncode == 0, review.stderr
    assert json.loads(review.stdout)["status"] == "APPROVED_RESEARCH"

    approved_verify = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "verify",
            "--output-dir",
            str(output),
            "--require-independent-review",
            "--review-authority-dir",
            str(review_authority),
        ],
        text=True,
        capture_output=True,
    )
    assert approved_verify.returncode == 0, approved_verify.stderr
    assert json.loads(approved_verify.stdout)["checks"]["independent_review"] is True


def test_cli_benchmark_enforces_60_case_gate() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "benchmark",
            "--fixture",
            str(BENCHMARK),
            "--fail-on-gate",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["total"] == 60
    assert payload["passed"] == 60
