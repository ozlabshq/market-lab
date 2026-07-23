from __future__ import annotations

"""Exact Decimal valuation methods. No acquisition, ranking, sizing, or execution."""

from decimal import Decimal, ROUND_FLOOR
from typing import Any, Callable, Mapping, Sequence

from .valuation_contracts import FORMULA_REGISTRY_HASH, decimal_value, require_formula, stable_id


def decimal_string(value: Decimal) -> str:
    normalized = value.normalize()
    text = format(normalized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def percentile(values: Sequence[Decimal], probability: Decimal) -> Decimal:
    if not values:
        raise ValueError("percentile requires observations")
    if probability < 0 or probability > 1:
        raise ValueError("percentile probability must be in [0, 1]")
    ordered = sorted(values)
    rank = Decimal(len(ordered) - 1) * probability
    lower_index = int(rank.to_integral_value(rounding=ROUND_FLOOR))
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = rank - Decimal(lower_index)
    return ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction


def _capital_bridge(enterprise_value: Decimal, capital: Mapping[str, Any]) -> Decimal:
    return (
        enterprise_value
        - decimal_value(capital["short_term_debt"], "short_term_debt")
        - decimal_value(capital["long_term_debt"], "long_term_debt")
        - decimal_value(capital["lease_adjustment"], "lease_adjustment")
        - decimal_value(capital["preferred_equity"], "preferred_equity")
        - decimal_value(capital["noncontrolling_interest"], "noncontrolling_interest")
        + decimal_value(capital["cash_and_equivalents"], "cash_and_equivalents")
        + decimal_value(capital["non_operating_investments"], "non_operating_investments")
    )


def calculate_comparable_metric(
    *,
    valuation_id: str,
    metric_type: str,
    candidate_denominator: Decimal | str | int,
    peer_observations: Sequence[Mapping[str, Any]],
    capital_structure: Mapping[str, Any],
    method_role: str,
    role_rationale: str,
) -> dict[str, Any]:
    if metric_type not in {"ev_revenue", "ev_ebitda", "pe", "fcf_yield"}:
        raise ValueError("unsupported comparable metric")
    if method_role not in {"primary", "cross_check"}:
        raise ValueError("comparable role must be fixed before calculation")
    candidate = decimal_value(candidate_denominator, "candidate_denominator")
    if candidate <= 0:
        raise ValueError("candidate denominator must be positive")
    lease_policy = str(capital_structure.get("lease_policy_version", ""))
    blockers: list[str] = []
    included: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []
    multiples: list[Decimal] = []
    seen_peers: set[str] = set()
    for observation in peer_observations:
        peer_id = str(observation.get("peer_id", ""))
        if not peer_id or peer_id in seen_peers:
            excluded.append({"peer_id": peer_id, "reason": "duplicate_or_missing_peer_id"})
            continue
        seen_peers.add(peer_id)
        if str(observation.get("lease_policy_version", "")) != lease_policy:
            excluded.append({"peer_id": peer_id, "reason": "inconsistent_lease_policy"})
            blockers.append("inconsistent_lease_policy")
            continue
        multiple = decimal_value(observation.get("multiple", ""), f"peer[{peer_id}].multiple")
        if multiple <= 0:
            excluded.append({"peer_id": peer_id, "reason": "nonpositive_multiple"})
            continue
        multiples.append(multiple)
        included.append({"peer_id": peer_id, "multiple": decimal_string(multiple)})
    if len(multiples) < 3:
        blockers.append("blocked_insufficient_peers")
    metric_id = stable_id(
        "mlab-comparable-metric-id.v1",
        {
            "formula_version": "comparable_implied_value.v1",
            "metric_type": metric_type,
            "peer_ids": sorted(item["peer_id"] for item in included),
            "valuation_id": valuation_id,
        },
    )
    base: dict[str, Any] = {
        "schema_version": "mlab-comparable-metric-result.v1",
        "comparable_metric_id": metric_id,
        "metric_type": metric_type,
        "method_role": method_role,
        "role_rationale": role_rationale,
        "formula_version": "comparable_implied_value.v1",
        "lease_policy_version": lease_policy,
        "included_peer_observations": included,
        "excluded_peer_observations": excluded,
        "blockers": sorted(set(blockers)),
    }
    if blockers:
        return {
            **base,
            "status": "blocked",
            "distribution": None,
            "implied_enterprise_value_range": None,
            "implied_common_equity_value_range": None,
            "implied_per_share_value_range": None,
            "calculation_trace": {"sorted_observations": [decimal_string(value) for value in sorted(multiples)]},
        }
    q25 = percentile(multiples, Decimal("0.25"))
    median = percentile(multiples, Decimal("0.5"))
    q75 = percentile(multiples, Decimal("0.75"))
    distribution = {
        "count": len(multiples),
        "minimum": decimal_string(min(multiples)),
        "q25": decimal_string(q25),
        "median": decimal_string(median),
        "q75": decimal_string(q75),
        "maximum": decimal_string(max(multiples)),
    }
    ev_range: tuple[Decimal, Decimal] | None
    if metric_type in {"ev_revenue", "ev_ebitda"}:
        ev_range = (candidate * q25, candidate * q75)
        equity_range = tuple(_capital_bridge(value, capital_structure) for value in ev_range)
    elif metric_type == "pe":
        ev_range = None
        equity_range = (candidate * q25, candidate * q75)
    else:
        ev_range = None
        equity_range = (candidate / q75, candidate / q25)
    diluted_shares = decimal_value(capital_structure["diluted_shares"], "diluted_shares")
    if diluted_shares <= 0:
        raise ValueError("diluted shares must be positive")
    per_share = tuple(max(value, Decimal(0)) / diluted_shares for value in equity_range)
    effective_role = method_role if len(multiples) >= 5 else "cross_check"
    status = "calculated" if len(multiples) >= 5 else "review_required"
    return {
        **base,
        "status": status,
        "method_role": effective_role,
        "quality_flags": [] if len(multiples) >= 5 else ["sparse_peer_set"],
        "distribution": distribution,
        "implied_enterprise_value_range": None if ev_range is None else [decimal_string(value) for value in ev_range],
        "implied_common_equity_value_range": [decimal_string(value) for value in equity_range],
        "implied_per_share_value_range": [decimal_string(value) for value in per_share],
        "calculation_trace": {
            "formula_definition_hash": require_formula("comparable_implied_value.v1").definition_hash,
            "formula_registry_hash": FORMULA_REGISTRY_HASH,
            "sorted_observations": [decimal_string(value) for value in sorted(multiples)],
            "q25": decimal_string(q25),
            "q75": decimal_string(q75),
            "candidate_denominator": decimal_string(candidate),
        },
    }


def calculate_wacc(
    *,
    common_equity: Decimal | str | int,
    borrowings: Decimal | str | int,
    leases: Decimal | str | int,
    preferred: Decimal | str | int,
    noncontrolling_interest: Decimal | str | int,
    cost_of_equity: Decimal | str | int,
    pre_tax_cost_of_borrowing: Decimal | str | int,
    pre_tax_cost_of_leases: Decimal | str | int,
    cost_of_preferred: Decimal | str | int,
    marginal_tax_rate: Decimal | str | int,
) -> dict[str, Any]:
    components = {
        "common_equity": decimal_value(common_equity, "common_equity"),
        "borrowings": decimal_value(borrowings, "borrowings"),
        "leases": decimal_value(leases, "leases"),
        "preferred": decimal_value(preferred, "preferred"),
        "noncontrolling_interest": decimal_value(noncontrolling_interest, "noncontrolling_interest"),
    }
    if any(value < 0 for value in components.values()):
        raise ValueError("WACC capital components cannot be negative")
    tax = decimal_value(marginal_tax_rate, "marginal_tax_rate")
    if tax < 0 or tax >= 1:
        raise ValueError("marginal tax rate must be in [0, 1)")
    costs = {
        "common_equity": decimal_value(cost_of_equity, "cost_of_equity"),
        "borrowings": decimal_value(pre_tax_cost_of_borrowing, "pre_tax_cost_of_borrowing") * (1 - tax),
        "leases": decimal_value(pre_tax_cost_of_leases, "pre_tax_cost_of_leases") * (1 - tax),
        "preferred": decimal_value(cost_of_preferred, "cost_of_preferred"),
        "noncontrolling_interest": decimal_value(cost_of_equity, "cost_of_equity"),
    }
    total = sum(components.values(), Decimal(0))
    if total <= 0:
        raise ValueError("gross capital must be positive")
    weights = {name: value / total for name, value in components.items()}
    wacc = sum((weights[name] * costs[name] for name in components), Decimal(0))
    return {
        "formula_version": "wacc.multi_component_gross_capital.v1",
        "formula_definition_hash": require_formula("wacc.multi_component_gross_capital.v1").definition_hash,
        "formula_registry_hash": FORMULA_REGISTRY_HASH,
        "total_capital": decimal_string(total),
        "components": {name: decimal_string(value) for name, value in components.items()},
        "weights": {name: decimal_string(value) for name, value in weights.items()},
        "post_tax_costs": {name: decimal_string(value) for name, value in costs.items()},
        "wacc": decimal_string(wacc),
    }


def _dcf_core(forecast_fcff: Sequence[Decimal], wacc: Decimal, terminal_growth: Decimal) -> dict[str, Decimal]:
    if wacc <= terminal_growth:
        raise ValueError("wacc_not_above_terminal_growth")
    if wacc - terminal_growth < Decimal("0.015"):
        raise ValueError("wacc_terminal_spread_too_narrow")
    if not forecast_fcff:
        raise ValueError("forecast_fcff_required")
    pv_fcff = sum(
        (cash_flow / ((Decimal(1) + wacc) ** period) for period, cash_flow in enumerate(forecast_fcff, start=1)),
        Decimal(0),
    )
    terminal_value = forecast_fcff[-1] * (Decimal(1) + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((Decimal(1) + wacc) ** len(forecast_fcff))
    enterprise_value = pv_fcff + pv_terminal
    denominator_floor = max(
        Decimal(1),
        Decimal("0.000001") * max(abs(pv_fcff), abs(pv_terminal), Decimal(1)),
    )
    if pv_terminal <= 0:
        raise ValueError("nonpositive_terminal_value")
    if enterprise_value <= 0:
        raise ValueError("nonpositive_enterprise_value")
    if enterprise_value < denominator_floor:
        raise ValueError("near_zero_enterprise_value")
    return {
        "pv_fcff": pv_fcff,
        "terminal_value": terminal_value,
        "pv_terminal_value": pv_terminal,
        "enterprise_value": enterprise_value,
        "denominator_floor": denominator_floor,
        "terminal_value_share": pv_terminal / enterprise_value,
    }


def calculate_dcf(
    *,
    valuation_id: str,
    scenario_id: str,
    forecast_fcff: Sequence[Decimal | str | int],
    wacc: Decimal | str | int,
    terminal_growth: Decimal | str | int,
    capital_structure: Mapping[str, Any],
) -> dict[str, Any]:
    cash_flows = tuple(decimal_value(value, "forecast_fcff") for value in forecast_fcff)
    discount_rate = decimal_value(wacc, "wacc")
    growth = decimal_value(terminal_growth, "terminal_growth")
    method_id = stable_id(
        "mlab-method-id.v1",
        {
            "formula_version": "fcff_dcf.gordon.lease_adjusted.v1",
            "scenario_id": scenario_id,
            "valuation_id": valuation_id,
        },
    )
    base = {
        "schema_version": "mlab-valuation-method-result.v1",
        "method_id": method_id,
        "method_type": "dcf_fcff",
        "result_scope": "scenario",
        "scenario_id": scenario_id,
        "method_role": "primary" if scenario_id.endswith("base") else "cross_check",
        "formula_version": "fcff_dcf.gordon.lease_adjusted.v1",
        "formula_definition_hash": require_formula("fcff_dcf.gordon.lease_adjusted.v1").definition_hash,
        "formula_registry_hash": FORMULA_REGISTRY_HASH,
    }
    try:
        core = _dcf_core(cash_flows, discount_rate, growth)
    except ValueError as exc:
        return {
            **base,
            "status": "blocked",
            "blockers": [str(exc)],
            "quality_flags": [],
            "enterprise_value_range": None,
            "common_equity_value_range": None,
            "per_share_value_range": None,
            "terminal_value_share": None,
            "sensitivity_rows": [],
            "calculation_trace": {"forecast_fcff": [decimal_string(value) for value in cash_flows]},
        }
    share = core["terminal_value_share"]
    if share > Decimal("0.85"):
        return {
            **base,
            "status": "blocked",
            "blockers": ["terminal_value_share_above_85_percent"],
            "quality_flags": [],
            "enterprise_value_range": None,
            "common_equity_value_range": None,
            "per_share_value_range": None,
            "terminal_value_share": decimal_string(share),
            "sensitivity_rows": [],
            "calculation_trace": {name: decimal_string(value) for name, value in core.items()},
        }
    equity_value = _capital_bridge(core["enterprise_value"], capital_structure)
    diluted_shares = decimal_value(capital_structure["diluted_shares"], "diluted_shares")
    if diluted_shares <= 0:
        raise ValueError("diluted shares must be positive")
    per_share = max(equity_value, Decimal(0)) / diluted_shares
    sensitivity_rows: list[dict[str, Any]] = []
    for wacc_shift in (Decimal("-0.01"), Decimal(0), Decimal("0.01")):
        for growth_shift in (Decimal("-0.005"), Decimal(0), Decimal("0.005")):
            cell_wacc = discount_rate + wacc_shift
            cell_growth = growth + growth_shift
            try:
                cell_core = _dcf_core(cash_flows, cell_wacc, cell_growth)
                cell_equity = _capital_bridge(cell_core["enterprise_value"], capital_structure)
                cell_value = max(cell_equity, Decimal(0)) / diluted_shares
                sensitivity_rows.append(
                    {
                        "wacc": decimal_string(cell_wacc),
                        "terminal_growth": decimal_string(cell_growth),
                        "status": "calculated",
                        "value": decimal_string(cell_value),
                        "reason": None,
                    }
                )
            except ValueError as exc:
                sensitivity_rows.append(
                    {
                        "wacc": decimal_string(cell_wacc),
                        "terminal_growth": decimal_string(cell_growth),
                        "status": "invalid",
                        "value": None,
                        "reason": str(exc),
                    }
                )
    quality_flags = ["terminal_value_share_above_70_percent"] if share > Decimal("0.70") else []
    return {
        **base,
        "status": "calculated",
        "blockers": [],
        "quality_flags": quality_flags,
        "enterprise_value_range": [decimal_string(core["enterprise_value"])] * 2,
        "common_equity_value_range": [decimal_string(equity_value)] * 2,
        "per_share_value_range": [decimal_string(per_share)] * 2,
        "terminal_value_share": decimal_string(share),
        "sensitivity_rows": sensitivity_rows,
        "calculation_trace": {
            "forecast_fcff": [decimal_string(value) for value in cash_flows],
            **{name: decimal_string(value) for name, value in core.items()},
            "wacc": decimal_string(discount_rate),
            "terminal_growth": decimal_string(growth),
        },
    }


def solve_reverse_dcf(
    *,
    valuation_id: str,
    solve_variable: str,
    lower: Decimal | str | int,
    upper: Decimal | str | int,
    target_common_equity: Decimal | str | int,
    evaluator: Callable[[Decimal], Decimal],
    tolerance: Decimal | str | int = "0.000001",
    max_iterations: int = 100,
) -> dict[str, Any]:
    if solve_variable not in {"revenue_cagr", "terminal_ebit_margin"}:
        raise ValueError("reverse DCF must solve exactly one supported variable")
    low = decimal_value(lower, "lower")
    high = decimal_value(upper, "upper")
    target = decimal_value(target_common_equity, "target_common_equity")
    tol = decimal_value(tolerance, "tolerance")
    if low >= high or tol <= 0 or max_iterations <= 0:
        raise ValueError("invalid reverse DCF bracket or tolerance")
    method_id = stable_id(
        "mlab-method-id.v1",
        {"method_type": "reverse_dcf", "solve_variable": solve_variable, "valuation_id": valuation_id},
    )
    base = {
        "schema_version": "mlab-valuation-method-result.v1",
        "method_id": method_id,
        "method_type": "reverse_dcf",
        "result_scope": "market_implied",
        "scenario_id": None,
        "method_role": "cross_check",
        "formula_version": "fcff_dcf.gordon.lease_adjusted.v1",
        "formula_definition_hash": require_formula("fcff_dcf.gordon.lease_adjusted.v1").definition_hash,
        "formula_registry_hash": FORMULA_REGISTRY_HASH,
        "common_equity_value_range": None,
        "per_share_value_range": None,
        "solve_variable": solve_variable,
        "bracket": [decimal_string(low), decimal_string(high)],
    }

    def evaluate(value: Decimal) -> Decimal:
        result = evaluator(value)
        if not isinstance(result, Decimal):
            raise TypeError("reverse DCF evaluator must return Decimal")
        if not result.is_finite():
            raise ValueError("invalid_model_cell")
        return result

    try:
        sample_x = [low + (high - low) * Decimal(index) / Decimal(4) for index in range(5)]
        sample_y = [evaluate(value) for value in sample_x]
    except (TypeError, ValueError):
        return {**base, "status": "blocked", "blockers": ["invalid_model_cell"], "implied_assumption": None, "residual": None, "iterations": 0}
    increasing = all(left < right for left, right in zip(sample_y, sample_y[1:]))
    decreasing = all(left > right for left, right in zip(sample_y, sample_y[1:]))
    if not increasing and not decreasing:
        return {**base, "status": "blocked", "blockers": ["non_monotonic"], "implied_assumption": None, "residual": None, "iterations": 0}
    minimum, maximum = min(sample_y[0], sample_y[-1]), max(sample_y[0], sample_y[-1])
    if target < minimum or target > maximum:
        return {**base, "status": "blocked", "blockers": ["not_bracketed"], "implied_assumption": None, "residual": None, "iterations": 0}
    midpoint = low
    mid_value = sample_y[0]
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        midpoint = (low + high) / Decimal(2)
        try:
            mid_value = evaluate(midpoint)
        except (TypeError, ValueError):
            return {**base, "status": "blocked", "blockers": ["invalid_model_cell"], "implied_assumption": None, "residual": None, "iterations": iterations}
        if mid_value == target or high - low <= tol:
            break
        if (mid_value < target) == increasing:
            low = midpoint
        else:
            high = midpoint
    else:
        return {**base, "status": "blocked", "blockers": ["iteration_limit"], "implied_assumption": None, "residual": None, "iterations": max_iterations}
    residual = mid_value - target
    return {
        **base,
        "status": "calculated",
        "blockers": [],
        "implied_assumption": decimal_string(midpoint),
        "residual": decimal_string(residual),
        "iterations": iterations,
        "interpretation": "market-implied operating requirement; not a forecast or fair-value target",
        "calculation_trace": {
            "sample_x": [decimal_string(value) for value in sample_x],
            "sample_y": [decimal_string(value) for value in sample_y],
            "target_common_equity": decimal_string(target),
            "tolerance": decimal_string(tol),
            "monotonic_direction": "increasing" if increasing else "decreasing",
        },
    }
