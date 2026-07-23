from __future__ import annotations

"""Bounded M4 valuation orchestration over accepted M2 evidence and final M3 packets."""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from . import config
from .agency_contracts import canonical_bytes, sha256_hex, strict_json_loads, validate_sha256, validate_timestamp
from .agency_policy import snapshot_protected_state
from .investment_memo import build_investment_memo, render_investment_memo
from .valuation_contracts import SAFETY_MODE, decimal_value, stable_id
from .valuation_inputs import validate_valuation_inputs
from .valuation_methods import calculate_comparable_metric, calculate_dcf, decimal_string, solve_reverse_dcf
from .valuation_store import ValuationStore

GENERATOR_VERSION = "mlab-valuation.v1"
_SOURCE_ARTIFACTS = {
    "valuation_input": "valuation_input.json",
    "company_packet": "company_packets/drafts/all_drafts.json",
    "company_publication": "publication.json",
    "input_refs": "input_refs.json",
}


def _load_object(path: Path) -> dict[str, Any]:
    payload = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON artifact must be an object: {path}")
    return payload


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _evidence_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "evidence_id" and isinstance(child, str) and child:
                found.add(child)
            elif key == "evidence_ids" and isinstance(child, (list, tuple)):
                found.update(str(item) for item in child if item)
            else:
                found.update(_evidence_ids(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.update(_evidence_ids(child))
    return found


def _validate_live_refs(refs: Mapping[str, Any], *inputs: Mapping[str, Any]) -> None:
    accepted = set(refs.get("accepted_schema_versions", ()))
    if refs.get("status") != "ACCEPTED" or "mlab-evidence.v2" not in accepted:
        raise ValueError("live mode requires accepted mlab-evidence.v2 input refs")
    verified = {str(value) for value in refs.get("verified_evidence_ids", ())}
    unresolved = sorted(set().union(*(_evidence_ids(value) for value in inputs)) - verified)
    if unresolved:
        raise ValueError("live mode evidence is not accepted: " + ",".join(unresolved))


def _validate_live_bridge(run_dir: Path, *inputs: Mapping[str, Any]) -> None:
    _validate_live_refs(_load_object(run_dir / "input_refs.json"), *inputs)


def _source_artifact_refs(run_dir: Path, output_dir: Path) -> list[dict[str, str]]:
    resolved_output = output_dir.expanduser().resolve()
    refs: list[dict[str, str]] = []
    for role, relative in _SOURCE_ARTIFACTS.items():
        path = (run_dir / relative).expanduser().resolve()
        if not path.is_file():
            if role == "input_refs":
                continue
            raise ValueError(f"required valuation source artifact missing: {relative}")
        if path == resolved_output or resolved_output in path.parents:
            raise ValueError("valuation source artifacts must be outside output directory")
        refs.append({"role": role, "path": str(path), "sha256": sha256_hex(path.read_bytes())})
    return refs


def _lineage_reasons(payload: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    facts = {str(row.get("fact_id")): row for row in payload.get("facts", ()) if isinstance(row, dict)}
    for fact_id in payload.get("capital_structure", {}).get("input_fact_ids", ()):
        if fact_id not in facts:
            reasons.append(f"capital_structure_unknown_fact:{fact_id}")
    for metric in payload.get("comparables", ()):
        ids = metric.get("candidate_denominator_fact_ids", ())
        if not ids:
            reasons.append(f"comparable_missing_denominator_lineage:{metric.get('metric_type')}")
        if any(fact_id not in facts for fact_id in ids):
            reasons.append(f"comparable_unknown_denominator_fact:{metric.get('metric_type')}")
        if len(ids) == 1 and ids[0] in facts:
            if decimal_value(metric.get("candidate_denominator")) != decimal_value(facts[ids[0]].get("value")):
                reasons.append(f"comparable_denominator_fact_mismatch:{metric.get('metric_type')}")
        for peer in metric.get("peer_observations", ()):
            if not peer.get("evidence_id"):
                reasons.append(f"peer_missing_evidence:{peer.get('peer_id')}")
    for scenario in payload.get("scenarios", ()):
        if not scenario.get("assumption_ids") or not scenario.get("evidence_ids"):
            reasons.append(f"scenario_missing_assumption_lineage:{scenario.get('name')}")
    reverse = payload.get("reverse_dcf", {})
    if not reverse.get("evidence_ids"):
        reasons.append("reverse_dcf_missing_evidence")
    return list(dict.fromkeys(reasons))


def _contains_forbidden_point_value(value: Any, path: tuple[str, ...] = ()) -> bool:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            normalized = "_".join(part for part in "".join(char.lower() if char.isalnum() else " " for char in key_text).split())
            child_path = (*path, key_text)
            allowed_target_path = child_path in {
                ("benchmark_and_controls", "no_blended_target"),
                ("reverse_dcf", "calculation_trace", "target_common_equity"),
            }
            if not allowed_target_path and ("target" in normalized or "fair_value" in normalized or "midpoint" in normalized or normalized == "pt"):
                return True
            if _contains_forbidden_point_value(child, child_path):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_point_value(child, (*path, str(index))) for index, child in enumerate(value))
    return False


def _no_false_precision_ok(memo: Mapping[str, Any]) -> bool:
    if _contains_forbidden_point_value(memo):
        return False
    for method in memo.get("valuation_methods", ()):
        if not isinstance(method, Mapping):
            return False
        status = method.get("status")
        value_range = method.get("per_share_value_range") or method.get("implied_per_share_value_range")
        if status in {"calculated", "review_required", "approved"}:
            if not isinstance(value_range, list) or len(value_range) != 2 or not isinstance(method.get("calculation_trace"), Mapping):
                return False
        elif status in {"blocked", "not_applicable"}:
            if any(method.get(name) is not None for name in ("enterprise_value_range", "implied_enterprise_value_range", "common_equity_value_range", "implied_common_equity_value_range", "per_share_value_range", "implied_per_share_value_range")):
                return False
    reconciliation = memo.get("method_reconciliation", {})
    if not isinstance(reconciliation, Mapping) or reconciliation.get("status") not in {
        "NO_VALUATION",
        "single_method_high_uncertainty",
        "material_method_disagreement",
        "primary_method_overlap",
    }:
        return False
    return True


def _fact_provenance_ok(memo: Mapping[str, Any]) -> bool:
    facts = memo.get("reported_financial_summary")
    summary = memo.get("provenance_summary")
    if not isinstance(facts, list) or not isinstance(summary, Mapping) or not facts:
        return False
    try:
        cutoff = datetime.fromisoformat(str(memo.get("analysis_cutoff_utc", "")).replace("Z", "+00:00"))
    except ValueError:
        return False
    seen: set[str] = set()
    source_resolved = 0
    derived_count = 0
    for fact in facts:
        if not isinstance(fact, Mapping):
            return False
        fact_id = str(fact.get("fact_id", ""))
        if not fact_id or fact_id in seen or not fact.get("concept") or not fact.get("units"):
            return False
        seen.add(fact_id)
        try:
            raw_value = fact.get("value")
            if isinstance(raw_value, bool) or not isinstance(raw_value, (Decimal, str, int)):
                return False
            decimal_value(raw_value, f"fact[{fact_id}].value")
            available = datetime.fromisoformat(str(fact.get("available_at_utc", "")).replace("Z", "+00:00"))
            if available > cutoff:
                return False
            if fact.get("stale_after_utc") and datetime.fromisoformat(str(fact["stale_after_utc"]).replace("Z", "+00:00")) < cutoff:
                return False
        except (TypeError, ValueError):
            return False
        if fact.get("defaulted") is True:
            return False
        transformation = fact.get("transformation")
        is_derived = transformation is not None and transformation != "none"
        if is_derived:
            if fact.get("source_status") != "derived" or not isinstance(transformation, Mapping) or not transformation.get("formula_version") or not transformation.get("input_fact_ids"):
                return False
            derived_count += 1
        else:
            if fact.get("source_status") != "verified" or any(not fact.get(key) for key in ("source_snapshot_id", "source_segment_id", "evidence_id", "exact_locator")):
                return False
            source_resolved += 1
    for fact in facts:
        transformation = fact.get("transformation")
        if isinstance(transformation, Mapping) and any(str(fact_id) not in seen for fact_id in transformation.get("input_fact_ids", ())):
            return False
    return (
        summary.get("material_facts") == len(facts)
        and summary.get("source_resolved") == source_resolved
        and summary.get("derived") == derived_count
    )


def _source_provenance_ok(store: ValuationStore, memo: Mapping[str, Any], request: Mapping[str, Any]) -> bool:
    try:
        input_facts = store.read_json("input_facts.json")
        refs = request.get("source_artifacts")
        if not isinstance(refs, list):
            return False
        loaded: dict[str, dict[str, Any]] = {}
        resolved_output = store.output_dir.expanduser().resolve()
        for ref in refs:
            if not isinstance(ref, Mapping):
                return False
            role = str(ref.get("role", ""))
            path = Path(str(ref.get("path", ""))).expanduser().resolve()
            if role not in _SOURCE_ARTIFACTS or role in loaded or not path.is_file():
                return False
            if path == resolved_output or resolved_output in path.parents or sha256_hex(path.read_bytes()) != ref.get("sha256"):
                return False
            loaded[role] = _load_object(path)
        required = {"valuation_input", "company_packet", "company_publication"}
        if not required.issubset(loaded) or (request.get("mode") == "live" and "input_refs" not in loaded):
            return False
        validation = validate_valuation_inputs(
            loaded["valuation_input"],
            loaded["company_packet"],
            loaded["company_publication"],
        )
        if not validation["ok"]:
            return False
        if request.get("mode") == "live":
            _validate_live_refs(
                loaded["input_refs"],
                loaded["valuation_input"],
                loaded["company_packet"],
                loaded["company_publication"],
            )
    except (OSError, TypeError, ValueError):
        return False
    return (
        input_facts.get("facts") == validation["facts"] == memo.get("reported_financial_summary")
        and input_facts.get("provenance_summary") == validation["provenance_summary"] == memo.get("provenance_summary")
        and loaded["valuation_input"].get("candidate_id") == request.get("candidate_id")
        and loaded["valuation_input"].get("analysis_cutoff_utc") == request.get("analysis_cutoff_utc")
    )


def _derived_outputs_ok(store: ValuationStore, memo: Mapping[str, Any], request: Mapping[str, Any]) -> bool:
    try:
        loaded = {
            str(ref["role"]): _load_object(Path(str(ref["path"])))
            for ref in request.get("source_artifacts", ())
            if isinstance(ref, Mapping) and ref.get("role") in _SOURCE_ARTIFACTS
        }
        payload = loaded["valuation_input"]
        validation = validate_valuation_inputs(payload, loaded["company_packet"], loaded["company_publication"])
        validation["reason_codes"].extend(_lineage_reasons(payload))
        validation["reason_codes"] = list(dict.fromkeys(validation["reason_codes"]))
        validation["ok"] = not validation["reason_codes"]
        if not validation["ok"]:
            return False
        request_hash = sha256_hex(canonical_bytes({
            "candidate_id": request["candidate_id"],
            "analysis_cutoff_utc": request["analysis_cutoff_utc"],
            "mode": request["mode"],
            "forecast_years": request["forecast_years"],
        }))
        valuation_id = stable_id(
            "mlab-valuation-id.v1",
            {
                "analysis_cutoff_utc": request["analysis_cutoff_utc"],
                "candidate_id": request["candidate_id"],
                "request_hash": request_hash,
            },
        )
        if valuation_id != request.get("valuation_id"):
            return False
        capital = payload["capital_structure"]
        comparable_results = [
            calculate_comparable_metric(
                valuation_id=valuation_id,
                metric_type=row["metric_type"],
                candidate_denominator=row["candidate_denominator"],
                peer_observations=row["peer_observations"],
                capital_structure=capital,
                method_role=row["method_role"],
                role_rationale=row["role_rationale"],
            )
            for row in payload.get("comparables", ())
        ]
        scenario_results, scenario_reasons = _scenario_results(valuation_id, payload, capital)
        reverse_dcf = _reverse_dcf(valuation_id, payload, capital)
        validation["reason_codes"].extend(scenario_reasons)
        expected_memo = build_investment_memo(
            valuation_id=valuation_id,
            run_id=str(request["run_id"]),
            candidate_id=str(request["candidate_id"]),
            analysis_cutoff_utc=str(request["analysis_cutoff_utc"]),
            company=validation["company"] or {},
            input_payload=payload,
            input_validation=validation,
            comparable_results=comparable_results,
            scenario_results=scenario_results,
            reverse_dcf=reverse_dcf,
            safety_attestation=memo.get("safety_attestation", {}),
        )
        expected = {
            "input_facts.json": {"schema_version": "mlab-valuation-input-facts.v1", "facts": validation["facts"], "provenance_summary": validation["provenance_summary"]},
            "normalized_financials.json": {"schema_version": "mlab-normalized-financials.v1", "capital_structure": capital},
            "peer_set.json": {"schema_version": "mlab-peer-set.v1", "metrics": payload.get("comparables", [])},
            "method_comparables.json": {"schema_version": "mlab-comparables.v1", "results": comparable_results, "combined_range": None},
            "method_dcf.json": {"schema_version": "mlab-dcf-results.v1", "results": [row["method_result"] for row in scenario_results]},
            "method_reverse_dcf.json": reverse_dcf,
            "scenarios.json": {"schema_version": "mlab-scenarios.v1", "scenarios": [{key: value for key, value in row.items() if key != "method_result"} for row in scenario_results]},
            "catalysts.json": {"schema_version": "mlab-catalysts.v1", "catalysts": payload.get("catalysts", [])},
            "invalidations.json": {"schema_version": "mlab-invalidations.v1", "invalidations": payload.get("invalidations", [])},
            "memo.json": expected_memo,
        }
        return all(store.read_json(name) == artifact for name, artifact in expected.items())
    except (KeyError, OSError, TypeError, ValueError):
        return False


def _review_authority_store(
    review_authority_dir: Path | None,
    *,
    output_dir: Path,
    valuation_id: str,
    manifest_digest: str,
) -> ValuationStore:
    validate_sha256(valuation_id, "valuation_id")
    validate_sha256(manifest_digest, "manifest_digest")
    authority_root = Path(review_authority_dir or (config.DATA_DIR / "valuation_review_authority")).expanduser().resolve()
    resolved_output = Path(output_dir).expanduser().resolve()
    if authority_root == resolved_output or resolved_output in authority_root.parents or authority_root in resolved_output.parents:
        raise ValueError("review authority must be outside valuation output directory")
    return ValuationStore(authority_root / valuation_id / manifest_digest)


def _review_binding_ok(
    store: ValuationStore,
    manifest: Mapping[str, Any],
    request: Mapping[str, Any],
    review_authority_dir: Path | None,
) -> bool:
    try:
        review = store.read_json("independent_review.json")
        approval = store.read_json("approval.json")
        review_manifest = store.read_json("review_manifest.json")
        authority_store = _review_authority_store(
            review_authority_dir,
            output_dir=store.output_dir,
            valuation_id=str(request.get("valuation_id", "")),
            manifest_digest=str(manifest.get("manifest_digest", "")),
        )
        authority_receipt = authority_store.read_json("receipt.json")
    except (OSError, ValueError):
        return False
    unsigned_review = {key: value for key, value in review.items() if key != "review_digest"}
    unsigned_review_manifest = {key: value for key, value in review_manifest.items() if key != "review_manifest_digest"}
    if review.get("review_digest") != sha256_hex(canonical_bytes(unsigned_review)):
        return False
    if review_manifest.get("review_manifest_digest") != sha256_hex(canonical_bytes(unsigned_review_manifest)):
        return False
    unsigned_receipt = {key: value for key, value in authority_receipt.items() if key != "receipt_digest"}
    if authority_receipt.get("receipt_digest") != sha256_hex(canonical_bytes(unsigned_receipt)):
        return False
    expected_artifacts = {
        name: {"sha256": sha256_hex((store.output_dir / name).read_bytes()), "bytes": (store.output_dir / name).stat().st_size}
        for name in ("independent_review.json", "approval.json")
    }
    recorded_artifacts = {
        str(row.get("path")): {"sha256": row.get("sha256"), "bytes": row.get("bytes")}
        for row in review_manifest.get("artifacts", ())
        if isinstance(row, Mapping)
    }
    return (
        review_manifest.get("base_manifest_digest") == manifest.get("manifest_digest")
        and review_manifest.get("valuation_id") == request.get("valuation_id")
        and review_manifest.get("authority_receipt_digest") == authority_receipt.get("receipt_digest")
        and recorded_artifacts == expected_artifacts
        and review.get("builder_id") == request.get("builder_id")
        and review.get("reviewer_id") != review.get("builder_id")
        and review.get("decision") == "APPROVE"
        and review.get("reviewed_manifest_digest") == manifest.get("manifest_digest")
        and approval.get("valuation_id") == request.get("valuation_id")
        and approval.get("status") == "APPROVED_RESEARCH"
        and approval.get("research_only") is True
        and approval.get("review_digest") == review.get("review_digest")
        and authority_receipt.get("schema_version") == "mlab-valuation-review-authority-receipt.v1"
        and authority_receipt.get("valuation_id") == request.get("valuation_id")
        and authority_receipt.get("manifest_digest") == manifest.get("manifest_digest")
        and authority_receipt.get("review_digest") == review.get("review_digest")
        and authority_receipt.get("reviewer_id") == review.get("reviewer_id")
        and authority_receipt.get("review_sha256") == expected_artifacts["independent_review.json"]["sha256"]
        and authority_receipt.get("approval_sha256") == expected_artifacts["approval.json"]["sha256"]
    )


def _scenario_identity_ok(memo: Mapping[str, Any]) -> bool:
    scenarios = memo.get("scenario_valuations", ())
    if not isinstance(scenarios, list) or [row.get("name") for row in scenarios if isinstance(row, Mapping)] != ["bear", "base", "bull"]:
        return False
    scenario_methods = {
        str(method.get("method_id")): method
        for method in memo.get("valuation_methods", ())
        if isinstance(method, Mapping) and method.get("result_scope") == "scenario" and method.get("method_id")
    }
    referenced: list[str] = []
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            return False
        method_ids = scenario.get("method_result_ids")
        if not isinstance(method_ids, list) or len(method_ids) != 1:
            return False
        method_id = str(method_ids[0])
        method = scenario_methods.get(method_id)
        if method is None or method.get("scenario_id") != scenario.get("scenario_id") or method.get("method_type") != "dcf_fcff":
            return False
        referenced.append(method_id)
    return len(referenced) == len(set(referenced)) and set(referenced) == set(scenario_methods)


def _scenario_results(
    valuation_id: str,
    payload: Mapping[str, Any],
    capital_structure: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    scenarios = payload.get("scenarios", ())
    if [row.get("name") for row in scenarios] != ["bear", "base", "bull"]:
        return [], ["bear_base_bull_required_in_canonical_order"]
    results: list[dict[str, Any]] = []
    reasons: list[str] = []
    seen_ids: set[str] = set()
    for row in scenarios:
        assumption_hash = sha256_hex(canonical_bytes({
            "assumption_ids": row.get("assumption_ids", ()),
            "forecast_fcff": row.get("forecast_fcff", ()),
            "terminal_growth": row.get("terminal_growth"),
            "wacc": row.get("wacc"),
        }))
        scenario_id = stable_id(
            "mlab-scenario-id.v1",
            {"assumption_set_hash": assumption_hash, "scenario_name": row["name"], "valuation_id": valuation_id},
        )
        if scenario_id in seen_ids:
            reasons.append("duplicate_scenario_id")
        seen_ids.add(scenario_id)
        method = calculate_dcf(
            valuation_id=valuation_id,
            scenario_id=scenario_id,
            forecast_fcff=row.get("forecast_fcff", ()),
            wacc=row.get("wacc"),
            terminal_growth=row.get("terminal_growth"),
            capital_structure=capital_structure,
        )
        method["method_role"] = "primary" if row["name"] == "base" else "cross_check"
        results.append(
            {
                "schema_version": "mlab-scenario-valuation.v1",
                "scenario_id": scenario_id,
                "name": row["name"],
                "description": row.get("description", ""),
                "assumption_ids": list(row.get("assumption_ids", ())),
                "method_result_ids": [method["method_id"]],
                "per_share_value_range": method.get("per_share_value_range"),
                "common_equity_value_range": method.get("common_equity_value_range"),
                "key_dependencies": list(row.get("key_dependencies", ())),
                "quality_flags": list(method.get("quality_flags", ())),
                "method_result": method,
            }
        )
    calculated = [row for row in results if row["per_share_value_range"]]
    if len(calculated) == 3:
        values = [decimal_value(row["per_share_value_range"][0]) for row in calculated]
        if not values[0] <= values[1] <= values[2]:
            reasons.append("review_required_scenario_crossing")
    if not scenarios[0].get("invalidation_ids"):
        reasons.append("bear_scenario_missing_invalidation_path")
    if not scenarios[2].get("catalyst_ids"):
        reasons.append("bull_scenario_missing_catalyst_dependency")
    return results, reasons


def _reverse_dcf(
    valuation_id: str,
    payload: Mapping[str, Any],
    capital_structure: Mapping[str, Any],
) -> dict[str, Any]:
    request = payload["reverse_dcf"]
    starting_fcff = decimal_value(request["starting_fcff"])
    discount_rate = request["wacc"]
    terminal_growth = request["terminal_growth"]

    def evaluator(growth: Decimal) -> Decimal:
        forecast = [starting_fcff * ((Decimal(1) + growth) ** year) for year in range(1, 6)]
        method = calculate_dcf(
            valuation_id=valuation_id,
            scenario_id="reverse-dcf-evaluator",
            forecast_fcff=forecast,
            wacc=discount_rate,
            terminal_growth=terminal_growth,
            capital_structure=capital_structure,
        )
        value_range = method.get("common_equity_value_range")
        if not value_range:
            raise ValueError("invalid_model_cell")
        return decimal_value(value_range[0])

    return solve_reverse_dcf(
        valuation_id=valuation_id,
        solve_variable=request["solve_variable"],
        lower=request["lower"],
        upper=request["upper"],
        target_common_equity=request["target_common_equity"],
        evaluator=evaluator,
    )


def build_valuation_run(
    *,
    run_dir: Path,
    output_dir: Path,
    candidate_id: str,
    analysis_cutoff_utc: str,
    mode: str,
    forecast_years: int,
    builder_id: str,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    output_dir = Path(output_dir)
    resolved_run = run_dir.expanduser().resolve()
    resolved_output = output_dir.expanduser().resolve()
    if resolved_run == resolved_output or resolved_run in resolved_output.parents or resolved_output in resolved_run.parents:
        raise ValueError("valuation source run and output directories must not overlap")
    if mode not in {"frozen", "live"}:
        raise ValueError("mode must be frozen or live")
    validate_timestamp(analysis_cutoff_utc, "analysis_cutoff_utc")
    if forecast_years != 5:
        raise ValueError("MVP forecast_years must be 5")
    if not builder_id:
        raise ValueError("builder_id is required")
    protected_before = snapshot_protected_state(config.DATA_DIR)
    input_payload = _load_object(run_dir / "valuation_input.json")
    company_packet = _load_object(run_dir / "company_packets" / "drafts" / "all_drafts.json")
    publication = _load_object(run_dir / "publication.json")
    source_artifacts = _source_artifact_refs(run_dir, output_dir)
    if mode == "live":
        _validate_live_bridge(run_dir, input_payload, company_packet, publication)
    if input_payload.get("candidate_id") != candidate_id:
        raise ValueError("candidate ID does not match valuation input")
    if input_payload.get("analysis_cutoff_utc") != analysis_cutoff_utc:
        raise ValueError("analysis cutoff does not match frozen valuation input")
    validation = validate_valuation_inputs(input_payload, company_packet, publication)
    validation["reason_codes"].extend(_lineage_reasons(input_payload))
    validation["reason_codes"] = list(dict.fromkeys(validation["reason_codes"]))
    validation["ok"] = not validation["reason_codes"]
    if not validation["ok"]:
        raise ValueError("valuation inputs blocked: " + ",".join(validation["reason_codes"]))
    request_hash = sha256_hex(canonical_bytes({
        "candidate_id": candidate_id,
        "analysis_cutoff_utc": analysis_cutoff_utc,
        "mode": mode,
        "forecast_years": forecast_years,
    }))
    valuation_id = stable_id(
        "mlab-valuation-id.v1",
        {"analysis_cutoff_utc": analysis_cutoff_utc, "candidate_id": candidate_id, "request_hash": request_hash},
    )
    capital = input_payload["capital_structure"]
    comparable_results = [
        calculate_comparable_metric(
            valuation_id=valuation_id,
            metric_type=row["metric_type"],
            candidate_denominator=row["candidate_denominator"],
            peer_observations=row["peer_observations"],
            capital_structure=capital,
            method_role=row["method_role"],
            role_rationale=row["role_rationale"],
        )
        for row in input_payload.get("comparables", ())
    ]
    scenario_results, scenario_reasons = _scenario_results(valuation_id, input_payload, capital)
    reverse_dcf = _reverse_dcf(valuation_id, input_payload, capital)
    protected_after = snapshot_protected_state(config.DATA_DIR)
    safety_attestation = {
        "mode": SAFETY_MODE,
        "zero_execution_side_effects": protected_before == protected_after,
        "before": protected_before,
        "after": protected_after,
    }
    validation["reason_codes"].extend(scenario_reasons)
    if not safety_attestation["zero_execution_side_effects"]:
        validation["reason_codes"].append("execution_state_changed")
    company = validation["company"] or {}
    memo = build_investment_memo(
        valuation_id=valuation_id,
        run_id=run_dir.name,
        candidate_id=candidate_id,
        analysis_cutoff_utc=analysis_cutoff_utc,
        company=company,
        input_payload=input_payload,
        input_validation=validation,
        comparable_results=comparable_results,
        scenario_results=scenario_results,
        reverse_dcf=reverse_dcf,
        safety_attestation=safety_attestation,
    )
    markdown = render_investment_memo(memo)
    gate_rows = [
        {"gate_id": "identity", "status": "pass" if company else "fail", "reason_codes": [] if company else ["company_candidate_not_ready"]},
        {"gate_id": "provenance", "status": "pass" if validation["ok"] else "fail", "reason_codes": validation["reason_codes"]},
        {"gate_id": "scenario", "status": "warn" if scenario_reasons else "pass", "reason_codes": scenario_reasons},
        {"gate_id": "catalyst_invalidation", "status": "pass" if not memo["unknowns_and_blockers"] else "warn", "reason_codes": memo["unknowns_and_blockers"]},
        {"gate_id": "no_false_precision", "status": "pass" if _no_false_precision_ok(memo) else "fail", "reason_codes": [] if _no_false_precision_ok(memo) else ["no_false_precision_failed"]},
        {"gate_id": "safety", "status": "pass" if safety_attestation["zero_execution_side_effects"] else "fail", "reason_codes": []},
        {"gate_id": "independent_review", "status": "warn", "reason_codes": ["review_pending"]},
    ]
    store = ValuationStore(output_dir)
    created_at_utc = analysis_cutoff_utc if mode == "frozen" else _now_utc()
    request_path = output_dir / "request.json"
    if request_path.is_file():
        existing_request = store.read_json("request.json")
        if existing_request.get("valuation_id") == valuation_id:
            created_at_utc = str(existing_request.get("created_at_utc", created_at_utc))
    request = {
        "schema_version": "mlab-valuation-request.v1",
        "valuation_id": valuation_id,
        "run_id": run_dir.name,
        "candidate_id": candidate_id,
        "analysis_cutoff_utc": analysis_cutoff_utc,
        "mode": mode,
        "forecast_years": forecast_years,
        "builder_id": builder_id,
        "research_only": True,
        "generator_version": GENERATOR_VERSION,
        "created_at_utc": created_at_utc,
        "source_artifacts": source_artifacts,
    }
    artifacts: dict[str, Mapping[str, Any] | str] = {
        "request.json": request,
        "input_facts.json": {"schema_version": "mlab-valuation-input-facts.v1", "facts": validation["facts"], "provenance_summary": validation["provenance_summary"]},
        "normalized_financials.json": {"schema_version": "mlab-normalized-financials.v1", "capital_structure": capital},
        "peer_set.json": {"schema_version": "mlab-peer-set.v1", "metrics": input_payload.get("comparables", [])},
        "method_comparables.json": {"schema_version": "mlab-comparables.v1", "results": comparable_results, "combined_range": None},
        "method_dcf.json": {"schema_version": "mlab-dcf-results.v1", "results": [row["method_result"] for row in scenario_results]},
        "method_reverse_dcf.json": reverse_dcf,
        "scenarios.json": {"schema_version": "mlab-scenarios.v1", "scenarios": [{key: value for key, value in row.items() if key != "method_result"} for row in scenario_results]},
        "catalysts.json": {"schema_version": "mlab-catalysts.v1", "catalysts": input_payload.get("catalysts", [])},
        "invalidations.json": {"schema_version": "mlab-invalidations.v1", "invalidations": input_payload.get("invalidations", [])},
        "gate_report.json": {"schema_version": "mlab-valuation-gates.v1", "gates": gate_rows},
        "memo.json": memo,
        "memo.md": markdown,
    }
    artifact_names: list[str] = []
    for name, artifact in artifacts.items():
        if isinstance(artifact, str):
            store.write_text(name, artifact)
        else:
            store.write_json(name, artifact)
        artifact_names.append(name)
    manifest = store.write_manifest(valuation_id=valuation_id, status="REVIEW_REQUIRED", artifact_names=artifact_names)
    return {
        "valuation_id": valuation_id,
        "status": "REVIEW_REQUIRED",
        "input_mode": mode,
        "output_dir": str(output_dir),
        "artifact_count": len(manifest["artifacts"]) + 1,
        "manifest_digest": manifest["manifest_digest"],
    }


def review_valuation_run(
    output_dir: Path,
    *,
    reviewer_id: str,
    decision: str,
    review_authority_dir: Path | None = None,
) -> dict[str, Any]:
    store = ValuationStore(Path(output_dir))
    request = store.read_json("request.json")
    manifest_check = store.verify_manifest()
    if not manifest_check["ok"] or manifest_check["manifest"] is None:
        raise ValueError("manifest integrity check failed: " + ",".join(manifest_check["reason_codes"]))
    manifest = manifest_check["manifest"]
    if reviewer_id == request["builder_id"]:
        raise ValueError("reviewer must differ from builder")
    if decision not in {"APPROVE", "REJECT"}:
        raise ValueError("review decision must be APPROVE or REJECT")
    authority_store = _review_authority_store(
        review_authority_dir,
        output_dir=Path(output_dir),
        valuation_id=request["valuation_id"],
        manifest_digest=manifest["manifest_digest"],
    )
    if decision == "APPROVE":
        verification = verify_valuation_run(Path(output_dir), require_independent_review=False)
        if not verification["ok"]:
            raise ValueError("valuation hard gates failed: " + ",".join(verification["reason_codes"]))
    review = {
        "schema_version": "mlab-valuation-review.v1",
        "valuation_id": request["valuation_id"],
        "builder_id": request["builder_id"],
        "reviewer_id": reviewer_id,
        "decision": decision,
        "reviewed_manifest_digest": manifest["manifest_digest"],
        "reviewed_at_utc": _now_utc(),
    }
    review["review_digest"] = sha256_hex(canonical_bytes(review))
    store.write_json("independent_review.json", review)
    status = "APPROVED_RESEARCH" if decision == "APPROVE" else "REJECTED"
    approval = {
        "schema_version": "mlab-valuation-approval.v1",
        "valuation_id": request["valuation_id"],
        "status": status,
        "review_digest": review["review_digest"],
        "research_only": True,
    }
    store.write_json("approval.json", approval)
    review_path = Path(output_dir) / "independent_review.json"
    approval_path = Path(output_dir) / "approval.json"
    authority_receipt = {
        "schema_version": "mlab-valuation-review-authority-receipt.v1",
        "valuation_id": request["valuation_id"],
        "manifest_digest": manifest["manifest_digest"],
        "review_digest": review["review_digest"],
        "reviewer_id": reviewer_id,
        "reviewed_at_utc": review["reviewed_at_utc"],
        "review_sha256": sha256_hex(review_path.read_bytes()),
        "approval_sha256": sha256_hex(approval_path.read_bytes()),
    }
    authority_receipt["receipt_digest"] = sha256_hex(canonical_bytes(authority_receipt))
    authority_store.write_json("receipt.json", authority_receipt)
    review_artifacts = []
    for name in ("approval.json", "independent_review.json"):
        path = Path(output_dir) / name
        review_artifacts.append({"path": name, "sha256": sha256_hex(path.read_bytes()), "bytes": path.stat().st_size})
    review_manifest = {
        "schema_version": "mlab-valuation-review-manifest.v1",
        "valuation_id": request["valuation_id"],
        "base_manifest_digest": manifest["manifest_digest"],
        "authority_receipt_digest": authority_receipt["receipt_digest"],
        "artifacts": review_artifacts,
    }
    review_manifest["review_manifest_digest"] = sha256_hex(canonical_bytes(review_manifest))
    store.write_json("review_manifest.json", review_manifest)
    return approval


def verify_valuation_run(
    output_dir: Path,
    *,
    require_independent_review: bool,
    review_authority_dir: Path | None = None,
) -> dict[str, Any]:
    store = ValuationStore(Path(output_dir))
    manifest_check = store.verify_manifest()
    reasons = list(manifest_check["reason_codes"])
    checks = {
        "manifest": bool(manifest_check["ok"]),
        "provenance": False,
        "cutoff_integrity": False,
        "no_false_precision": False,
        "memo_fidelity": False,
        "scenario_identity": False,
        "derived_outputs": False,
        "zero_execution_side_effects": False,
        "independent_review": False,
    }
    request: Mapping[str, Any] = {}
    try:
        memo = store.read_json("memo.json")
        request = store.read_json("request.json")
        markdown = (Path(output_dir) / "memo.md").read_text(encoding="utf-8")
        checks["provenance"] = _fact_provenance_ok(memo) and _source_provenance_ok(store, memo, request)
        checks["cutoff_integrity"] = memo.get("analysis_cutoff_utc") == request.get("analysis_cutoff_utc")
        checks["no_false_precision"] = _no_false_precision_ok(memo)
        checks["memo_fidelity"] = markdown == render_investment_memo(memo)
        checks["scenario_identity"] = _scenario_identity_ok(memo)
        checks["derived_outputs"] = _derived_outputs_ok(store, memo, request)
        safety = memo.get("safety_attestation", {})
        checks["zero_execution_side_effects"] = safety.get("zero_execution_side_effects") is True and safety.get("before") == safety.get("after")
    except (OSError, ValueError, KeyError) as exc:
        reasons.append(f"verification_artifact_invalid:{type(exc).__name__}")
    if manifest_check.get("manifest") is not None:
        checks["independent_review"] = _review_binding_ok(
            store,
            manifest_check["manifest"],
            request,
            review_authority_dir,
        )
    required = ["manifest", "provenance", "cutoff_integrity", "no_false_precision", "memo_fidelity", "scenario_identity", "derived_outputs", "zero_execution_side_effects"]
    if require_independent_review:
        required.append("independent_review")
    for name in required:
        if not checks[name]:
            reasons.append(f"check_failed:{name}")
    return {"ok": not reasons, "checks": checks, "reason_codes": reasons}
