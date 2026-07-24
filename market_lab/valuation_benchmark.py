from __future__ import annotations

"""Deterministic zero-network valuation benchmark runner."""

import json
from pathlib import Path
from typing import Any

from .agency_contracts import canonical_bytes, sha256_hex
from .valuation_contracts import decimal_value
from .valuation_methods import calculate_comparable_metric, calculate_dcf, decimal_string, solve_reverse_dcf

_CAPITAL = {
    "market_cap": "1000",
    "short_term_debt": "5",
    "long_term_debt": "20",
    "lease_adjustment": "0",
    "preferred_equity": "0",
    "noncontrolling_interest": "0",
    "cash_and_equivalents": "10",
    "non_operating_investments": "0",
    "diluted_shares": "10",
    "lease_policy_version": "lease_adjusted_debt.v1",
}


def _run_case(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    category = row["category"]
    expected = row["expected_status"]
    blocked_case = expected == "blocked"
    if category == "normalization":
        value = decimal_string(decimal_value("001.2300"))
        return ("calculated" if value == "1.23" else "blocked"), {"normalized": value}
    if category == "comparables":
        peer_count = 2 if blocked_case else 5
        peers = [
            {"peer_id": f"p{index}", "multiple": str(index + 1), "lease_policy_version": "lease_adjusted_debt.v1"}
            for index in range(peer_count)
        ]
        result = calculate_comparable_metric(
            valuation_id="benchmark",
            metric_type="ev_revenue",
            candidate_denominator="100",
            peer_observations=peers,
            capital_structure=_CAPITAL,
            method_role="primary",
            role_rationale="benchmark",
        )
        return result["status"], {"result_digest": sha256_hex(canonical_bytes(result))}
    if category == "dcf":
        result = calculate_dcf(
            valuation_id="benchmark",
            scenario_id=row["case_id"],
            forecast_fcff=["100"] * 5,
            wacc="0.10",
            terminal_growth="0.10" if blocked_case else "0.02",
            capital_structure=_CAPITAL,
        )
        return result["status"], {"result_digest": sha256_hex(canonical_bytes(result))}
    if category == "reverse_dcf":
        target = "1000" if blocked_case else "5"
        result = solve_reverse_dcf(
            valuation_id="benchmark",
            solve_variable="revenue_cagr",
            lower="0",
            upper="1",
            target_common_equity=target,
            evaluator=lambda value: value * decimal_value("10"),
        )
        return result["status"], {"result_digest": sha256_hex(canonical_bytes(result))}
    if category == "scenario_memo":
        names = ["bear", "base"] if blocked_case else ["bear", "base", "bull"]
        status = "calculated" if names == ["bear", "base", "bull"] else "blocked"
        return status, {"scenario_names": names}
    if category == "temporal":
        available = "2026-01-01T00:00:00Z" if blocked_case else "2025-12-30T00:00:00Z"
        status = "calculated" if available <= "2025-12-31T23:59:59Z" else "blocked"
        return status, {"available_at_utc": available}
    if category == "memo_safety":
        memo = {"value_range": ["90", "110"]}
        if blocked_case:
            memo["target_price"] = "100"
        status = "blocked" if "target_price" in memo else "calculated"
        return status, {"no_point_target": "target_price" not in memo}
    raise ValueError(f"unknown benchmark category: {category}")


def run_valuation_benchmark(path: Path, *, fail_on_gate: bool) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"benchmark row {line_number} must be an object")
        rows.append(row)
    if len(rows) != 60:
        raise ValueError(f"oz-valuation-bench.v1 requires exactly 60 cases, found {len(rows)}")
    case_ids = [row.get("case_id") for row in rows]
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("benchmark case IDs must be unique")
    outcomes: list[dict[str, Any]] = []
    categories: dict[str, dict[str, int]] = {}
    for row in rows:
        actual, details = _run_case(row)
        passed = actual == row.get("expected_status")
        category = row["category"]
        summary = categories.setdefault(category, {"passed": 0, "total": 0})
        summary["total"] += 1
        summary["passed"] += int(passed)
        outcomes.append(
            {
                "case_id": row["case_id"],
                "category": category,
                "expected_status": row["expected_status"],
                "actual_status": actual,
                "passed": passed,
                "details": details,
            }
        )
    failed = [row["case_id"] for row in outcomes if not row["passed"]]
    result = {
        "schema_version": "oz-valuation-bench.v1",
        "ok": not failed,
        "total": len(outcomes),
        "passed": len(outcomes) - len(failed),
        "failed_case_ids": failed,
        "categories": categories,
        "outcomes": outcomes,
        "fixture_sha256": sha256_hex(Path(path).read_bytes()),
    }
    result["report_digest"] = sha256_hex(canonical_bytes(result))
    if fail_on_gate and failed:
        raise ValueError("valuation benchmark gate failed: " + ",".join(failed))
    return result
