from __future__ import annotations

import socket
from pathlib import Path

import pytest

from market_lab.valuation_benchmark import run_valuation_benchmark

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "tests" / "market_lab" / "fixtures" / "valuation" / "benchmark_v1.jsonl"


def test_oz_valuation_bench_v1_runs_all_60_zero_network_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network forbidden")))
    result = run_valuation_benchmark(BENCHMARK, fail_on_gate=True)

    assert result["schema_version"] == "oz-valuation-bench.v1"
    assert result["ok"] is True
    assert result["total"] == 60
    assert result["passed"] == 60
    assert result["failed_case_ids"] == []
    assert result["categories"] == {
        "normalization": {"passed": 12, "total": 12},
        "comparables": {"passed": 10, "total": 10},
        "dcf": {"passed": 10, "total": 10},
        "reverse_dcf": {"passed": 6, "total": 6},
        "scenario_memo": {"passed": 8, "total": 8},
        "temporal": {"passed": 6, "total": 6},
        "memo_safety": {"passed": 8, "total": 8},
    }
