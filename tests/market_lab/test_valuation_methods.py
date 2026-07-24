from __future__ import annotations

from decimal import Decimal

from market_lab.valuation_methods import calculate_comparable_metric, calculate_dcf, calculate_wacc, solve_reverse_dcf


def _capital_structure() -> dict[str, str]:
    return {
        "short_term_debt": "5",
        "long_term_debt": "15",
        "lease_adjustment": "5",
        "preferred_equity": "0",
        "noncontrolling_interest": "0",
        "cash_and_equivalents": "10",
        "non_operating_investments": "0",
        "diluted_shares": "10",
        "lease_policy_version": "lease_adjusted_debt.v1",
    }


def test_comparable_metric_preserves_distribution_and_lease_consistent_equity_bridge() -> None:
    peers = [
        {"peer_id": f"p{index}", "multiple": str(value), "lease_policy_version": "lease_adjusted_debt.v1"}
        for index, value in enumerate((2, 3, 4, 5, 6), start=1)
    ]

    result = calculate_comparable_metric(
        valuation_id="valuation-1",
        metric_type="ev_revenue",
        candidate_denominator="100",
        peer_observations=peers,
        capital_structure=_capital_structure(),
        method_role="primary",
        role_rationale="same business model and exact TTM definition",
    )

    assert result["status"] == "calculated"
    assert result["distribution"] == {
        "count": 5,
        "minimum": "2",
        "q25": "3",
        "median": "4",
        "q75": "5",
        "maximum": "6",
    }
    assert result["implied_enterprise_value_range"] == ["300", "500"]
    assert result["implied_common_equity_value_range"] == ["285", "485"]
    assert result["implied_per_share_value_range"] == ["28.5", "48.5"]
    assert result["calculation_trace"]["sorted_observations"] == ["2", "3", "4", "5", "6"]
    assert len(result["calculation_trace"]["formula_definition_hash"]) == 64
    assert len(result["calculation_trace"]["formula_registry_hash"]) == 64
    assert Decimal(result["implied_per_share_value_range"][0]) < Decimal(result["implied_per_share_value_range"][1])


def test_comparable_metric_blocks_sparse_or_mixed_lease_policy_without_values() -> None:
    sparse = calculate_comparable_metric(
        valuation_id="valuation-1",
        metric_type="ev_revenue",
        candidate_denominator="100",
        peer_observations=[
            {"peer_id": "p1", "multiple": "2", "lease_policy_version": "lease_adjusted_debt.v1"},
            {"peer_id": "p2", "multiple": "3", "lease_policy_version": "unadjusted"},
        ],
        capital_structure=_capital_structure(),
        method_role="primary",
        role_rationale="fixture",
    )

    assert sparse["status"] == "blocked"
    assert set(sparse["blockers"]) == {"blocked_insufficient_peers", "inconsistent_lease_policy"}
    assert sparse["implied_enterprise_value_range"] is None
    assert sparse["implied_per_share_value_range"] is None


def test_wacc_uses_gross_multi_component_capital_without_netting_cash() -> None:
    result = calculate_wacc(
        common_equity="1000",
        borrowings="100",
        leases="50",
        preferred="20",
        noncontrolling_interest="10",
        cost_of_equity="0.10",
        pre_tax_cost_of_borrowing="0.05",
        pre_tax_cost_of_leases="0.04",
        cost_of_preferred="0.06",
        marginal_tax_rate="0.25",
    )

    assert result["formula_version"] == "wacc.multi_component_gross_capital.v1"
    assert len(result["formula_definition_hash"]) == 64
    assert len(result["formula_registry_hash"]) == 64
    assert result["total_capital"] == "1180"
    assert result["wacc"] == "0.09105932203389830508474576271"
    assert "cash" not in result["weights"]


def test_dcf_matches_hand_calculation_and_blocks_invalid_terminal_structure() -> None:
    calculated = calculate_dcf(
        valuation_id="valuation-1",
        scenario_id="scenario-base",
        forecast_fcff=["100"] * 5,
        wacc="0.10",
        terminal_growth="0.02",
        capital_structure=_capital_structure(),
    )

    assert calculated["status"] == "calculated"
    assert calculated["enterprise_value_range"] == [
        "1170.753363841267672973157571",
        "1170.753363841267672973157571",
    ]
    assert calculated["per_share_value_range"] == [
        "115.5753363841267672973157571",
        "115.5753363841267672973157571",
    ]
    assert calculated["terminal_value_share"] == "0.6762096196784954733732517994"
    assert calculated["sensitivity_rows"]
    assert all(cell["value"] is None for cell in calculated["sensitivity_rows"] if cell["status"] == "invalid")

    blocked = calculate_dcf(
        valuation_id="valuation-1",
        scenario_id="scenario-base",
        forecast_fcff=["100"] * 5,
        wacc="0.03",
        terminal_growth="0.02",
        capital_structure=_capital_structure(),
    )
    assert blocked["status"] == "blocked"
    assert "wacc_terminal_spread_too_narrow" in blocked["blockers"]
    assert blocked["per_share_value_range"] is None


def test_reverse_dcf_solves_one_bounded_market_implied_variable() -> None:
    solved = solve_reverse_dcf(
        valuation_id="valuation-1",
        solve_variable="revenue_cagr",
        lower="0",
        upper="0.30",
        target_common_equity="1600",
        evaluator=lambda growth: Decimal("1000") + Decimal("5000") * growth,
        tolerance="0.000001",
    )

    assert solved["status"] == "calculated"
    assert solved["result_scope"] == "market_implied"
    assert solved["scenario_id"] is None
    assert abs(Decimal(solved["implied_assumption"]) - Decimal("0.12")) <= Decimal("0.000001")
    assert Decimal(solved["residual"]).copy_abs() <= Decimal("0.005")
    assert solved["common_equity_value_range"] is None

    blocked = solve_reverse_dcf(
        valuation_id="valuation-1",
        solve_variable="revenue_cagr",
        lower="0",
        upper="0.10",
        target_common_equity="5000",
        evaluator=lambda growth: Decimal("1000") + growth,
    )
    assert blocked["status"] == "blocked"
    assert blocked["blockers"] == ["not_bracketed"]
    assert blocked["implied_assumption"] is None
