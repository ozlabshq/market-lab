from __future__ import annotations

"""Fail-closed normalization of M3 company packets and valuation evidence facts."""

from datetime import datetime, timezone
from typing import Any, Mapping

from .agency_contracts import canonical_bytes, sha256_hex, validate_timestamp
from .valuation_contracts import decimal_value
from .valuation_methods import decimal_string

_FORBIDDEN_SOURCE_STATUSES = {"synthetic", "cache_synthetic", "search_snippet", "context_only", "generated"}


def _utc(value: str, field_name: str) -> datetime:
    validate_timestamp(value, field_name)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _company_candidate(
    candidate_id: str,
    company_packet: Mapping[str, Any],
    company_publication: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    if company_packet.get("schema_version") != "mlab-company-drafts.v1":
        reasons.append("company_packet_schema_invalid")
    if company_publication.get("schema_version") != "mlab-company-publication.v1":
        reasons.append("company_publication_schema_invalid")
    if company_publication.get("draft_digest") != sha256_hex(canonical_bytes(company_packet)):
        reasons.append("company_packet_digest_mismatch")
    if company_publication.get("review_ok") is not True:
        reasons.append("company_review_not_approved")
    if company_publication.get("replay_ok") is not True:
        reasons.append("company_replay_not_verified")
    drafts = [row for row in company_packet.get("drafts", ()) if isinstance(row, dict) and row.get("candidate_id") == candidate_id]
    if len(drafts) != 1:
        reasons.append("company_candidate_missing_or_ambiguous")
        return None, reasons
    draft = drafts[0]
    case_id = str(draft.get("benchmark_case_id", ""))
    ready = any(
        isinstance(row, dict)
        and row.get("outcome") == "READY"
        and (row.get("candidate_id") == candidate_id or (case_id and row.get("case_id") == case_id))
        for row in company_publication.get("outcomes", ())
    )
    if not ready:
        reasons.append("company_candidate_not_ready")
    return draft, reasons


def validate_valuation_inputs(
    payload: Mapping[str, Any],
    company_packet: Mapping[str, Any],
    company_publication: Mapping[str, Any],
) -> dict[str, Any]:
    reasons: list[str] = []
    if payload.get("schema_version") != "mlab-valuation-input.v1":
        reasons.append("valuation_input_schema_invalid")
    if payload.get("research_only") is not True:
        reasons.append("research_only_required")
    candidate_id = str(payload.get("candidate_id", ""))
    if not candidate_id or not payload.get("issuer_id") or not payload.get("security_id"):
        reasons.append("candidate_identity_incomplete")
    try:
        cutoff = _utc(str(payload.get("analysis_cutoff_utc", "")), "analysis_cutoff_utc")
        if cutoff > datetime.now(timezone.utc):
            reasons.append("future_analysis_cutoff")
    except ValueError:
        cutoff = datetime.min.replace(tzinfo=timezone.utc)
        reasons.append("analysis_cutoff_invalid")
    company, company_reasons = _company_candidate(candidate_id, company_packet, company_publication)
    reasons.extend(company_reasons)
    normalized_facts: list[dict[str, Any]] = []
    seen_fact_ids: set[str] = set()
    source_resolved = 0
    derived = 0
    for raw in payload.get("facts", ()):
        if not isinstance(raw, Mapping):
            reasons.append("fact_not_object")
            continue
        fact = dict(raw)
        fact_id = str(fact.get("fact_id", ""))
        if not fact_id or fact_id in seen_fact_ids:
            reasons.append(f"fact_id_missing_or_duplicate:{fact_id}")
            continue
        seen_fact_ids.add(fact_id)
        try:
            fact["value"] = decimal_string(decimal_value(fact.get("value"), f"fact[{fact_id}].value"))
        except (TypeError, ValueError):
            reasons.append(f"invalid_decimal:{fact_id}")
        if not fact.get("concept") or not fact.get("units"):
            reasons.append(f"missing_concept_or_units:{fact_id}")
        try:
            available = _utc(str(fact.get("available_at_utc", "")), f"fact[{fact_id}].available_at_utc")
            if available > cutoff:
                reasons.append(f"post_cutoff_fact:{fact_id}")
        except ValueError:
            reasons.append(f"invalid_availability_time:{fact_id}")
        source_status = str(fact.get("source_status", "")).lower()
        if source_status in _FORBIDDEN_SOURCE_STATUSES:
            reasons.append(f"synthetic_fact:{fact_id}")
        transformation = fact.get("transformation")
        is_derived = transformation is not None and transformation != "none"
        expected_source_status = "derived" if is_derived else "verified"
        if source_status not in _FORBIDDEN_SOURCE_STATUSES and source_status != expected_source_status:
            reasons.append(f"unverified_source_status:{fact_id}")
        if fact.get("defaulted") is True:
            reasons.append(f"defaulted_fact:{fact_id}")
        if fact.get("stale_after_utc"):
            try:
                if _utc(str(fact["stale_after_utc"]), f"fact[{fact_id}].stale_after_utc") < cutoff:
                    reasons.append(f"stale_fact:{fact_id}")
            except ValueError:
                reasons.append(f"invalid_staleness_time:{fact_id}")
        if is_derived:
            derived += 1
            if not isinstance(transformation, Mapping) or not transformation.get("formula_version") or not transformation.get("input_fact_ids"):
                reasons.append(f"invalid_transformation_lineage:{fact_id}")
        else:
            missing_source = [
                key
                for key in ("source_snapshot_id", "source_segment_id", "evidence_id")
                if not fact.get(key)
            ]
            if missing_source:
                reasons.append(f"missing_source_lineage:{fact_id}")
            if not fact.get("exact_locator"):
                reasons.append(f"missing_exact_locator:{fact_id}")
            if not missing_source and fact.get("exact_locator") and source_status == "verified":
                source_resolved += 1
        normalized_facts.append(fact)
    for fact in normalized_facts:
        transformation = fact.get("transformation")
        if not isinstance(transformation, Mapping):
            continue
        for input_fact_id in transformation.get("input_fact_ids", ()):
            if input_fact_id not in seen_fact_ids:
                reasons.append(f"unknown_derived_input:{fact['fact_id']}:{input_fact_id}")
    if not normalized_facts:
        reasons.append("material_facts_missing")
    return {
        "ok": not reasons,
        "reason_codes": list(dict.fromkeys(reasons)),
        "candidate_id": candidate_id,
        "analysis_cutoff_utc": payload.get("analysis_cutoff_utc"),
        "company": company,
        "facts": normalized_facts,
        "provenance_summary": {
            "material_facts": len(normalized_facts),
            "source_resolved": source_resolved,
            "derived": derived,
        },
    }
