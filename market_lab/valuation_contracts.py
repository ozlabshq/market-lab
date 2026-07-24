from __future__ import annotations

"""Exact, research-only contracts shared by the valuation and memo engine."""

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Mapping

from .agency_contracts import canonical_bytes, sha256_hex

ID_SCHEMA_VERSION = "mlab-stable-id.v1"
SAFETY_MODE = "research_mock_only"


@dataclass(frozen=True)
class FormulaSpec:
    symbolic_formula: str
    required_inputs: tuple[str, ...]
    units: str
    period_rules: str
    capital_structure_policy_version: str
    implementation_function: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def definition_hash(self) -> str:
        return sha256_hex(canonical_bytes(self.as_dict()))


def _formula(
    symbolic_formula: str,
    required_inputs: tuple[str, ...],
    units: str,
    implementation_function: str,
    *,
    period_rules: str = "same_cutoff_and_compatible_period",
    capital_policy: str = "lease_adjusted_debt.v1",
) -> FormulaSpec:
    return FormulaSpec(
        symbolic_formula=symbolic_formula,
        required_inputs=required_inputs,
        units=units,
        period_rules=period_rules,
        capital_structure_policy_version=capital_policy,
        implementation_function=implementation_function,
    )


FORMULA_REGISTRY: Mapping[str, FormulaSpec] = MappingProxyType(
    {
        "enterprise_value.lease_adjusted.v1": _formula(
            "market_cap + borrowings + leases + preferred + nci - cash - non_operating_investments",
            ("market_cap", "borrowings", "leases", "preferred", "nci", "cash", "non_operating_investments"),
            "USD",
            "enterprise_value",
        ),
        "wacc.multi_component_gross_capital.v1": _formula(
            "sum(component_value / gross_capital * component_cost)",
            ("common_equity", "borrowings", "leases", "preferred", "nci", "component_costs"),
            "unit_fraction",
            "calculate_wacc",
        ),
        "ttm_ebitda.lease_adjusted.v1": _formula(
            "operating_income + depreciation_amortization + operating_lease_expense",
            ("operating_income", "depreciation_amortization", "operating_lease_expense"),
            "USD",
            "lease_adjusted_ebitda",
            period_rules="identical_non_overlapping_ttm_period",
        ),
        "levered_fcf.cfo_less_capex.v1": _formula(
            "net_cash_from_operations - cash_capital_expenditures",
            ("net_cash_from_operations", "cash_capital_expenditures"),
            "USD",
            "levered_fcf",
            period_rules="identical_non_overlapping_ttm_period",
        ),
        "comparable_implied_value.v1": _formula(
            "candidate_denominator * peer_percentile_range",
            ("candidate_denominator", "peer_observations", "capital_structure", "diluted_shares"),
            "USD_and_USD_per_share",
            "calculate_comparable_metric",
        ),
        "fcff_dcf.gordon.lease_adjusted.v1": _formula(
            "sum(FCFF_t/(1+WACC)^t) + FCFF_N*(1+g)/(WACC-g)/(1+WACC)^N",
            ("forecast_fcff", "wacc", "terminal_growth", "capital_structure", "diluted_shares"),
            "USD_and_USD_per_share",
            "calculate_dcf",
        ),
        "terminal_value_share.pv_over_ev.v1": _formula(
            "pv_terminal_value / enterprise_value",
            ("pv_terminal_value", "enterprise_value", "pv_fcff"),
            "unit_fraction",
            "terminal_value_share",
        ),
    }
)


def decimal_value(value: Decimal | str | int, field_name: str = "value") -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{field_name}: binary floats are forbidden")
    if not isinstance(value, (Decimal, str, int)):
        raise TypeError(f"{field_name}: expected Decimal, decimal string, or integer")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field_name}: invalid decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name}: non-finite decimal is forbidden")
    if result.is_zero() and result.is_signed():
        raise ValueError(f"{field_name}: negative zero is forbidden")
    return result


def stable_id(domain: str, fields: Mapping[str, Any]) -> str:
    if not isinstance(domain, str) or not domain:
        raise ValueError("stable ID domain is required")
    payload = {
        "domain": domain,
        "id_schema_version": ID_SCHEMA_VERSION,
        "fields": dict(fields),
    }
    return sha256_hex(canonical_bytes(payload))


def require_formula(formula_version: str) -> FormulaSpec:
    try:
        return FORMULA_REGISTRY[formula_version]
    except KeyError as exc:
        raise ValueError(f"unknown formula version: {formula_version}") from exc


def formula_registry_hash() -> str:
    """Hash the exact ordered formula definitions for replay audits."""
    definitions = [FORMULA_REGISTRY[key].as_dict() for key in sorted(FORMULA_REGISTRY)]
    return sha256_hex(canonical_bytes(definitions))


FORMULA_REGISTRY_HASH = formula_registry_hash()
