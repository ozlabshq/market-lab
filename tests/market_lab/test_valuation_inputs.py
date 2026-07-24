from __future__ import annotations

from copy import deepcopy

from market_lab.agency_contracts import canonical_bytes, sha256_hex
from market_lab.valuation_inputs import validate_valuation_inputs


CUTOFF = "2025-12-31T23:59:59Z"


def _company_bridge() -> tuple[dict, dict]:
    packet = {
        "schema_version": "mlab-company-drafts.v1",
        "drafts": [
            {
                "candidate_id": "fixture-candidate",
                "issuer": "Fixture Systems, Inc.",
                "security": "FIX",
                "draft_packet_digest": "d" * 64,
                "evidence_ids": ["evidence-1"],
            }
        ],
    }
    publication = {
        "schema_version": "mlab-company-publication.v1",
        "draft_digest": sha256_hex(canonical_bytes(packet)),
        "review_ok": True,
        "replay_ok": True,
        "outcomes": [{"case_id": "case-1", "candidate_id": "fixture-candidate", "outcome": "READY"}],
    }
    return packet, publication


def _input_payload() -> dict:
    return {
        "schema_version": "mlab-valuation-input.v1",
        "candidate_id": "fixture-candidate",
        "issuer_id": "0000000001",
        "security_id": "FIX:XNAS:COMMON",
        "analysis_cutoff_utc": CUTOFF,
        "research_only": True,
        "facts": [
            {
                "fact_id": "revenue-ttm",
                "concept": "revenue",
                "value": "1000",
                "units": "USD",
                "period_start": "2025-01-01T00:00:00Z",
                "period_end": "2025-12-31T00:00:00Z",
                "available_at_utc": "2025-02-01T00:00:00Z",
                "source_snapshot_id": "snapshot-1",
                "source_segment_id": "segment-1",
                "evidence_id": "evidence-1",
                "exact_locator": "10-K accession 0001, XBRL us-gaap:Revenue, context FY2025",
                "source_status": "verified",
                "transformation": "none",
            }
        ],
    }


def test_input_validation_requires_ready_company_packet_and_exact_provenance() -> None:
    packet, publication = _company_bridge()
    result = validate_valuation_inputs(_input_payload(), packet, publication)

    assert result["ok"] is True
    assert result["reason_codes"] == []
    assert result["company"]["issuer"] == "Fixture Systems, Inc."
    assert result["facts"][0]["value"] == "1000"
    assert result["provenance_summary"] == {"material_facts": 1, "source_resolved": 1, "derived": 0}


def test_input_validation_fails_closed_for_post_cutoff_synthetic_or_missing_locator() -> None:
    packet, publication = _company_bridge()
    payload = _input_payload()
    bad = deepcopy(payload["facts"][0])
    bad.update(
        {
            "fact_id": "bad-fact",
            "available_at_utc": "2026-01-01T00:00:00Z",
            "source_status": "cache_synthetic",
            "exact_locator": "",
        }
    )
    payload["facts"].append(bad)

    result = validate_valuation_inputs(payload, packet, publication)

    assert result["ok"] is False
    assert {"post_cutoff_fact:bad-fact", "synthetic_fact:bad-fact", "missing_exact_locator:bad-fact"} <= set(result["reason_codes"])

    publication["outcomes"][0]["outcome"] = "PARK_RESEARCH"
    not_ready = validate_valuation_inputs(_input_payload(), packet, publication)
    assert "company_candidate_not_ready" in not_ready["reason_codes"]


def test_input_validation_blocks_stale_defaulted_superseded_and_unresolved_derived_facts() -> None:
    packet, publication = _company_bridge()
    payload = _input_payload()
    payload["facts"][0].update(
        {
            "stale_after_utc": "2025-06-30T23:59:59Z",
            "defaulted": True,
            "source_status": "superseded",
        }
    )
    payload["facts"].append(
        {
            "fact_id": "derived-margin",
            "concept": "margin",
            "value": "0.10",
            "units": "unit_fraction",
            "available_at_utc": "2025-12-15T00:00:00Z",
            "source_status": "derived",
            "transformation": {
                "formula_version": "margin.v1",
                "input_fact_ids": ["missing-input"],
            },
        }
    )

    result = validate_valuation_inputs(payload, packet, publication)

    assert {
        "stale_fact:revenue-ttm",
        "defaulted_fact:revenue-ttm",
        "unverified_source_status:revenue-ttm",
        "unknown_derived_input:derived-margin:missing-input",
    } <= set(result["reason_codes"])


def test_input_validation_binds_ready_publication_to_exact_company_packet_digest() -> None:
    packet, publication = _company_bridge()
    packet["drafts"][0]["issuer"] = "Tampered Systems, Inc."

    result = validate_valuation_inputs(_input_payload(), packet, publication)

    assert result["ok"] is False
    assert "company_packet_digest_mismatch" in result["reason_codes"]
