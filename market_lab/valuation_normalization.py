from __future__ import annotations

"""Source selection and audited financial normalization for valuation inputs."""

from datetime import datetime
from typing import Any, Mapping, Sequence

from .agency_contracts import validate_timestamp
from .valuation_contracts import FORMULA_REGISTRY_HASH, decimal_value, require_formula
from .valuation_methods import decimal_string

SOURCE_LADDER = (
    "sec_xbrl",
    "sec_filing_table",
    "issuer_ir",
    "exchange_regulator",
    "third_party_structured",
    "licensed_market_data",
    "web_discovery",
)
_SOURCE_RANK = {source_class: index for index, source_class in enumerate(SOURCE_LADDER)}


def _timestamp(value: str) -> datetime:
    validate_timestamp(value, "available_at_utc")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def select_preferred_fact(
    facts: Sequence[Mapping[str, Any]],
    *,
    concept: str,
    period_end: str,
    analysis_cutoff_utc: str,
) -> dict[str, Any]:
    cutoff = _timestamp(analysis_cutoff_utc)
    eligible: list[dict[str, Any]] = []
    for raw in facts:
        if raw.get("concept") != concept or raw.get("period_end") != period_end:
            continue
        source_class = str(raw.get("source_class", ""))
        if source_class not in _SOURCE_RANK:
            continue
        try:
            if _timestamp(str(raw.get("available_at_utc", ""))) > cutoff:
                continue
        except ValueError:
            continue
        if raw.get("source_status") in {"synthetic", "cache_synthetic", "search_snippet", "context_only"}:
            continue
        eligible.append(dict(raw))
    if not eligible:
        raise ValueError(f"no cutoff-valid fact for {concept} at {period_end}")
    best_rank = min(_SOURCE_RANK[str(row["source_class"])] for row in eligible)
    preferred_class = [row for row in eligible if _SOURCE_RANK[str(row["source_class"])] == best_rank]
    superseded = {str(row["amends_accession"]) for row in preferred_class if row.get("amends_accession")}
    current = [row for row in preferred_class if str(row.get("accession", "")) not in superseded]
    if not current:
        raise ValueError(f"all facts superseded without usable amendment for {concept}")
    return max(current, key=lambda row: (_timestamp(str(row["available_at_utc"])), str(row.get("fact_id", ""))))


def _derived_row(
    *,
    value: Any,
    formula_version: str,
    input_names: Sequence[str],
    input_fact_ids: Mapping[str, Sequence[str]],
) -> dict[str, Any]:
    missing = [name for name in input_names if not input_fact_ids.get(name)]
    if missing:
        raise ValueError("derived value missing input fact IDs: " + ",".join(missing))
    formula = require_formula(formula_version)
    return {
        "value": decimal_string(decimal_value(value)),
        "formula_version": formula_version,
        "formula_definition_hash": formula.definition_hash,
        "formula_registry_hash": FORMULA_REGISTRY_HASH,
        "input_fact_ids": [fact_id for name in input_names for fact_id in input_fact_ids[name]],
        "capital_structure_policy_version": formula.capital_structure_policy_version,
    }


def derive_normalized_financials(
    values: Mapping[str, Any],
    *,
    input_fact_ids: Mapping[str, Sequence[str]],
) -> dict[str, dict[str, Any]]:
    ebitda_inputs = ("operating_income", "depreciation_amortization", "operating_lease_expense")
    ebitda = sum((decimal_value(values[name], name) for name in ebitda_inputs), start=decimal_value("0"))
    fcf_inputs = ("net_cash_from_operations", "cash_capital_expenditures")
    levered_fcf = decimal_value(values["net_cash_from_operations"]) - decimal_value(values["cash_capital_expenditures"])
    enterprise_inputs = (
        "market_cap",
        "borrowings",
        "leases",
        "preferred",
        "noncontrolling_interest",
        "cash",
        "non_operating_investments",
    )
    enterprise_value = (
        decimal_value(values["market_cap"])
        + decimal_value(values["borrowings"])
        + decimal_value(values["leases"])
        + decimal_value(values["preferred"])
        + decimal_value(values["noncontrolling_interest"])
        - decimal_value(values["cash"])
        - decimal_value(values["non_operating_investments"])
    )
    return {
        "lease_adjusted_ebitda": _derived_row(
            value=ebitda,
            formula_version="ttm_ebitda.lease_adjusted.v1",
            input_names=ebitda_inputs,
            input_fact_ids=input_fact_ids,
        ),
        "levered_fcf": _derived_row(
            value=levered_fcf,
            formula_version="levered_fcf.cfo_less_capex.v1",
            input_names=fcf_inputs,
            input_fact_ids=input_fact_ids,
        ),
        "enterprise_value": _derived_row(
            value=enterprise_value,
            formula_version="enterprise_value.lease_adjusted.v1",
            input_names=enterprise_inputs,
            input_fact_ids=input_fact_ids,
        ),
    }
