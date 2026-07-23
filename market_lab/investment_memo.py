from __future__ import annotations

"""Canonical investment memo assembly and pure Markdown rendering."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Mapping, Sequence

from .valuation_contracts import decimal_value, stable_id
from .valuation_methods import decimal_string


def validate_catalysts(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for row in rows:
        catalyst_id = str(row.get("catalyst_id", "unknown"))
        required = (
            "title",
            "mechanism",
            "expected_window_start",
            "expected_window_end",
            "evidence_ids",
            "confirmation_source_requirement",
            "monitoring_query_or_identifier",
        )
        if any(not row.get(field) for field in required):
            reasons.append(f"invalid_catalyst:{catalyst_id}")
    return reasons


def validate_invalidations(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    reasons: list[str] = []
    for row in rows:
        invalidation_id = str(row.get("invalidation_id", "unknown"))
        required = (
            "thesis_component",
            "observable_metric_or_event",
            "operator",
            "threshold",
            "units",
            "observation_window",
            "required_source_class",
            "monitoring_identifier",
            "action_on_trigger",
            "rationale",
        )
        if any(row.get(field) is None or row.get(field) == "" or row.get(field) == [] for field in required):
            reasons.append(f"invalid_invalidation:{invalidation_id}")
        if row.get("action_on_trigger") not in {"force_review", "mark_rejected"}:
            reasons.append(f"unsafe_invalidation_action:{invalidation_id}")
    return reasons


def display_per_share_range(value_range: Sequence[str], cutoff_price: str) -> str:
    if len(value_range) != 2:
        raise ValueError("per-share value range must have two endpoints")
    low = decimal_value(value_range[0], "range_low")
    high = decimal_value(value_range[1], "range_high")
    if low > high:
        raise ValueError("range endpoints must be ordered")
    increment = max(Decimal("0.10"), decimal_value(cutoff_price, "cutoff_price") * Decimal("0.01"))
    rounded_low = (low / increment).to_integral_value(rounding=ROUND_FLOOR) * increment
    rounded_high = (high / increment).to_integral_value(rounding=ROUND_CEILING) * increment
    decimals = max(1, -increment.as_tuple().exponent)
    return f"${rounded_low:.{decimals}f}–${rounded_high:.{decimals}f}"


def reconcile_methods(
    comparable_results: Sequence[Mapping[str, Any]],
    scenario_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    units: list[dict[str, Any]] = []
    for result in comparable_results:
        if result.get("status") in {"calculated", "review_required"} and result.get("method_role") == "primary":
            units.append(
                {
                    "unit_id": result["comparable_metric_id"],
                    "unit_type": result["metric_type"],
                    "range": result["implied_per_share_value_range"],
                }
            )
    base_rows = [row for row in scenario_results if row.get("name") == "base"]
    if base_rows:
        method = base_rows[0].get("method_result", {})
        if method.get("status") == "calculated":
            units.append({"unit_id": method["method_id"], "unit_type": "base_dcf", "range": method["per_share_value_range"]})
    if not units:
        return {"status": "NO_VALUATION", "primary_units": [], "primary_method_overlap": None, "disagreements": []}
    if len(units) == 1:
        return {"status": "single_method_high_uncertainty", "primary_units": units, "primary_method_overlap": units[0]["range"], "disagreements": []}
    low = max(decimal_value(row["range"][0]) for row in units)
    high = min(decimal_value(row["range"][1]) for row in units)
    disagreements: list[list[str]] = []
    for index, left in enumerate(units):
        left_low, left_high = (decimal_value(value) for value in left["range"])
        for right in units[index + 1 :]:
            right_low, right_high = (decimal_value(value) for value in right["range"])
            if max(left_low, right_low) > min(left_high, right_high):
                disagreements.append([left["unit_id"], right["unit_id"]])
    if disagreements:
        return {
            "status": "material_method_disagreement",
            "primary_units": units,
            "primary_method_overlap": None,
            "disagreements": disagreements,
            "policy": "ranges remain separate; no averaging, midpointing, weighting, or preferred-target selection",
        }
    return {
        "status": "primary_method_overlap",
        "primary_units": units,
        "primary_method_overlap": [decimal_string(low), decimal_string(high)],
        "disagreements": [],
        "policy": "intersection shown alongside full ranges; it is not a target",
    }


def build_investment_memo(
    *,
    valuation_id: str,
    run_id: str,
    candidate_id: str,
    analysis_cutoff_utc: str,
    company: Mapping[str, Any],
    input_payload: Mapping[str, Any],
    input_validation: Mapping[str, Any],
    comparable_results: Sequence[Mapping[str, Any]],
    scenario_results: Sequence[Mapping[str, Any]],
    reverse_dcf: Mapping[str, Any],
    safety_attestation: Mapping[str, Any],
) -> dict[str, Any]:
    scenario_names = [row.get("name") for row in scenario_results]
    blockers = list(input_validation.get("reason_codes", ()))
    if scenario_names != ["bear", "base", "bull"]:
        blockers.append("bear_base_bull_required_in_canonical_order")
    blockers.extend(validate_catalysts(input_payload.get("catalysts", ())))
    blockers.extend(validate_invalidations(input_payload.get("invalidations", ())))
    thesis = input_payload.get("thesis", {})
    if not thesis.get("contrary_evidence_ids"):
        blockers.append("contrary_evidence_required")
    reconciliation = reconcile_methods(comparable_results, scenario_results)
    if reconciliation["status"] == "material_method_disagreement":
        memo_status = "review_required"
    elif blockers:
        memo_status = "blocked"
    else:
        memo_status = "review_required"
    market_cap = decimal_value(input_payload["capital_structure"]["market_cap"])
    shares = decimal_value(input_payload["capital_structure"]["diluted_shares"])
    cutoff_price = decimal_string(market_cap / shares)
    per_share_ranges: dict[str, str] = {}
    for result in comparable_results:
        value_range = result.get("implied_per_share_value_range")
        if value_range:
            per_share_ranges[result["comparable_metric_id"]] = display_per_share_range(value_range, cutoff_price)
    for scenario in scenario_results:
        value_range = scenario.get("per_share_value_range")
        if value_range:
            per_share_ranges[scenario["scenario_id"]] = display_per_share_range(value_range, cutoff_price)
    memo_id = stable_id(
        "mlab-memo-id.v1",
        {
            "candidate_id": candidate_id,
            "method_ids": sorted(
                [row["comparable_metric_id"] for row in comparable_results]
                + [row["method_result"]["method_id"] for row in scenario_results]
                + [reverse_dcf["method_id"]]
            ),
            "valuation_id": valuation_id,
        },
    )
    uncertainty_reasons = []
    if reconciliation["status"] == "material_method_disagreement":
        uncertainty_reasons.append("primary method ranges do not overlap")
    if any(row.get("quality_flags") for row in comparable_results):
        uncertainty_reasons.append("one or more comparable metrics have quality warnings")
    if any(row.get("method_result", {}).get("quality_flags") for row in scenario_results):
        uncertainty_reasons.append("DCF terminal value or sensitivity warning")
    return {
        "schema_version": "mlab-investment-memo.v1",
        "memo_id": memo_id,
        "valuation_id": valuation_id,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "issuer": company.get("issuer"),
        "security": company.get("security"),
        "analysis_cutoff_utc": analysis_cutoff_utc,
        "research_only": True,
        "memo_status": memo_status,
        "executive_summary": thesis.get("executive_summary", ""),
        "thesis_claim_ids": thesis.get("thesis_claim_ids", []),
        "company_and_security_mapping": {
            "candidate_id": candidate_id,
            "issuer": company.get("issuer"),
            "security": company.get("security"),
            "mapping_rationale": company.get("discovery_rationale"),
        },
        "why_now": thesis.get("why_now", ""),
        "reported_financial_summary": input_validation.get("facts", []),
        "valuation_methods": list(comparable_results) + [row["method_result"] for row in scenario_results],
        "reverse_dcf": dict(reverse_dcf),
        "scenario_valuations": [{key: value for key, value in row.items() if key != "method_result"} for row in scenario_results],
        "method_reconciliation": reconciliation,
        "catalysts": list(input_payload.get("catalysts", ())),
        "invalidations": list(input_payload.get("invalidations", ())),
        "principal_risks": thesis.get("principal_risks", []),
        "contrary_evidence_ids": thesis.get("contrary_evidence_ids", []),
        "unknowns_and_blockers": list(thesis.get("unknowns", ())) + blockers,
        "provenance_summary": input_validation.get("provenance_summary", {}),
        "uncertainty_summary": {"label": "HIGH", "reasons": uncertainty_reasons or ["scenario and model uncertainty remains material"]},
        "staleness_and_next_review": {"status": "current_at_cutoff", "next_review": "next filing, catalyst update, or material invalidation event"},
        "benchmark_and_controls": {"no_blended_target": True, "reverse_dcf_market_implied_only": True},
        "review": {"status": "PENDING", "reviewer": None},
        "safety_attestation": dict(safety_attestation),
        "render_trace": {"cutoff_price": cutoff_price, "per_share_ranges": per_share_ranges, "rounding_policy": "max($0.10, 1% cutoff price), outward"},
    }


def render_investment_memo(memo: Mapping[str, Any]) -> str:
    lines = [
        "# RESEARCH ONLY — Investment Memo",
        f"Status: {memo['memo_status']} | Cutoff: {memo['analysis_cutoff_utc']} | Memo: {memo['memo_id']}",
        "",
        "## Candidate Identity",
        f"{memo.get('issuer')} ({memo.get('security')}) — {memo['candidate_id']}",
        "",
        "## Executive Summary",
        str(memo.get("executive_summary", "")),
        f"Why now: {memo.get('why_now', '')}",
        "",
        "## Evidence-Backed Thesis and Company Economics",
        f"Claims: {', '.join(memo.get('thesis_claim_ids', []))}",
        "",
        "## Reported Financials and Provenance",
        f"Source-resolved facts: {memo.get('provenance_summary', {}).get('source_resolved', 0)}/{memo.get('provenance_summary', {}).get('material_facts', 0)}",
        "",
        "## Valuation Overview",
        f"Reconciliation: {memo['method_reconciliation']['status']} (no blended point target)",
    ]
    rendered = memo["render_trace"]["per_share_ranges"]
    for method in memo.get("valuation_methods", []):
        identifier = method.get("comparable_metric_id") or method.get("method_id")
        if identifier in rendered:
            label = method.get("metric_type") or f"DCF {method.get('scenario_id')}"
            lines.append(f"- {label}: {rendered[identifier]} [{method.get('status')}] ({method.get('method_role')})")
        elif method.get("status") == "blocked":
            lines.append(f"- {method.get('metric_type') or method.get('method_type')}: BLOCKED — {', '.join(method.get('blockers', []))}")
    lines.extend(["", "## Reverse DCF", f"{memo['reverse_dcf'].get('interpretation', '')}: {memo['reverse_dcf'].get('implied_assumption')}"])
    lines.extend(["", "## Bull / Base / Bear"])
    for scenario in memo.get("scenario_valuations", []):
        value = rendered.get(scenario["scenario_id"], "BLOCKED")
        lines.append(f"- {scenario['name'].upper()}: {value} — {scenario['description']}")
    lines.extend(["", "## Catalysts"])
    for row in memo.get("catalysts", []):
        lines.append(f"- {row['title']} ({row['expected_window_start']} to {row['expected_window_end']}): {row['mechanism']}")
    lines.extend(["", "## Invalidation Conditions"])
    for row in memo.get("invalidations", []):
        lines.append(f"- {row['observable_metric_or_event']} {row['operator']} {row['threshold']} over {row['observation_window']} → {row['action_on_trigger']}")
    lines.extend(["", "## Principal Risks and Contrary Evidence"])
    lines.extend(f"- {risk}" for risk in memo.get("principal_risks", []))
    lines.append(f"Contrary evidence: {', '.join(memo.get('contrary_evidence_ids', []))}")
    lines.extend(["", "## Unknowns / Blockers"])
    lines.extend(f"- {item}" for item in memo.get("unknowns_and_blockers", []))
    lines.extend(["", "## Uncertainty / No False Precision", f"{memo['uncertainty_summary']['label']}: {'; '.join(memo['uncertainty_summary']['reasons'])}"])
    lines.extend(["", "## Independent Review", f"{memo['review']['status']}"])
    lines.extend(["", "## Safety Attestation", "No broker, order-candidate, portfolio, options, or independent-track state was changed."])
    return "\n".join(lines) + "\n"
