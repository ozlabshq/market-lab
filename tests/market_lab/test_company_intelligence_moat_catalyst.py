from __future__ import annotations

import pytest

from market_lab.agency_contracts import TypedID, canonical_json, strict_json_loads
from market_lab.company_intelligence import (
    CatalystAssessment,
    CatalystStatus,
    ClaimStatus,
    ContractValidationResult,
    CompetitiveMoatAssessment,
    CompetitiveRelationship,
    EvidenceKind,
    EvidencePolarity,
    SourceBackedEvidenceRef,
    ValidationOutcome,
    ValueChainRelation,
    validate_catalyst_assessment,
    validate_competitive_moat,
)

CUTOFF = "2026-07-14T08:00:00Z"


def tid(kind: str, local_id: str) -> TypedID:
    return TypedID(kind=kind, domain="agency", id_schema_version="v1", local_id=local_id)


def evidence(
    local_id: str,
    *,
    claim_id: TypedID | None = None,
    claim_status: ClaimStatus = ClaimStatus.VERIFIED,
    evidence_kind: EvidenceKind = EvidenceKind.OFFICIAL_FILING,
    polarity: EvidencePolarity = EvidencePolarity.SUPPORTS,
    source_published_at_utc: str = "2026-07-01T00:00:00Z",
    source_available_at_utc: str = "2026-07-01T02:00:00Z",
    system_available_at_utc: str = "2026-07-01T03:00:00Z",
) -> SourceBackedEvidenceRef:
    return SourceBackedEvidenceRef(
        evidence_id=tid("evidence", local_id),
        claim_id=claim_id or tid("claim", f"{local_id}-claim"),
        claim_status=claim_status,
        evidence_kind=evidence_kind,
        polarity=polarity,
        source_published_at_utc=source_published_at_utc,
        source_available_at_utc=source_available_at_utc,
        system_available_at_utc=system_available_at_utc,
    )


def moat_assessment(
    *,
    moat_evidence_ids: tuple[TypedID, ...],
    counterevidence_ids: tuple[TypedID, ...] = (),
    relationships: tuple[CompetitiveRelationship, ...] = (),
) -> CompetitiveMoatAssessment:
    return CompetitiveMoatAssessment(
        issuer_id=tid("issuer", "acme"),
        analysis_cutoff_utc=CUTOFF,
        moat_claim_ids=(tid("claim", "moat"),),
        moat_evidence_ids=moat_evidence_ids,
        counterevidence_ids=counterevidence_ids,
        competitor_relationships=relationships,
        analyst_rationale="Assess durable pricing power against identified competitors.",
    )


def catalyst_assessment(
    *,
    status: CatalystStatus,
    claim_ids: tuple[TypedID, ...] = (tid("claim", "capacity-expansion"),),
    evidence_ids: tuple[TypedID, ...] = (),
    counterevidence_ids: tuple[TypedID, ...] = (),
) -> CatalystAssessment:
    return CatalystAssessment(
        catalyst_id=tid("catalyst", "capacity-expansion"),
        issuer_id=tid("issuer", "acme"),
        description="New capacity enters service.",
        analysis_cutoff_utc=CUTOFF,
        expected_event_at_utc="2026-10-01T00:00:00Z",
        claim_ids=claim_ids,
        evidence_ids=evidence_ids,
        counterevidence_ids=counterevidence_ids,
        status=status,
    )


def test_source_backed_evidence_round_trip_and_malformed_timestamps_fail_closed() -> None:
    item = evidence("filing")

    assert SourceBackedEvidenceRef.from_dict(strict_json_loads(canonical_json(item.to_dict()))) == item

    with pytest.raises(ValueError, match="source_published_at_utc"):
        evidence("bad", source_published_at_utc="2026-07-01")
    with pytest.raises(ValueError, match="source_available_at_utc"):
        evidence("bad", source_available_at_utc="2026-07-01T02:00:00-05:00")
    with pytest.raises(ValueError, match="system_available_at_utc"):
        evidence("bad", system_available_at_utc="")


def test_management_only_moat_support_without_eligible_evidence_is_non_promotable() -> None:
    management = evidence("company-pr", claim_id=tid("claim", "moat"), evidence_kind=EvidenceKind.OFFICIAL_COMPANY)
    assessment = moat_assessment(moat_evidence_ids=(management.evidence_id,))

    result = validate_competitive_moat(assessment, {management.evidence_id: management})

    assert CompetitiveMoatAssessment.from_dict(strict_json_loads(canonical_json(assessment.to_dict()))) == assessment
    assert ContractValidationResult.from_dict(strict_json_loads(canonical_json(result.to_dict()))) == result
    assert result.ok is False
    assert result.outcome is ValidationOutcome.NON_PROMOTABLE
    assert "management_only_moat_support" in result.reason_codes
    assert "missing_eligible_moat_evidence" in result.reason_codes


def test_competitor_relationship_effective_after_analysis_cutoff_is_rejected() -> None:
    support = evidence("filing", claim_id=tid("claim", "moat"))
    relationship = CompetitiveRelationship(
        relationship_id=tid("competitive_relationship", "late-entrant"),
        competitor_issuer_id=tid("issuer", "lateco"),
        relation=ValueChainRelation.COMPETES_WITH,
        valid_from="2026-08-01T00:00:00Z",
        valid_to=None,
        evidence_ids=(support.evidence_id,),
    )
    assessment = moat_assessment(moat_evidence_ids=(support.evidence_id,), relationships=(relationship,))

    result = validate_competitive_moat(assessment, {support.evidence_id: support})

    assert result.ok is False
    assert result.outcome is ValidationOutcome.NON_PROMOTABLE
    assert "relationship_after_analysis_cutoff" in result.reason_codes


def test_competitor_relationship_without_evidence_fails_closed() -> None:
    support = evidence("filing", claim_id=tid("claim", "moat"))
    relationship = CompetitiveRelationship(
        relationship_id=tid("competitive_relationship", "unsupported-competitor"),
        competitor_issuer_id=tid("issuer", "rivalco"),
        relation=ValueChainRelation.COMPETES_WITH,
        valid_from="2026-07-01T00:00:00Z",
        valid_to=None,
        evidence_ids=(),
    )
    assessment = moat_assessment(moat_evidence_ids=(support.evidence_id,), relationships=(relationship,))

    result = validate_competitive_moat(assessment, {support.evidence_id: support})

    assert result.ok is False
    assert result.outcome is ValidationOutcome.NON_PROMOTABLE
    assert result.reason_codes == ("missing_relationship_evidence",)


def test_confirmed_catalyst_with_only_unverified_claim_id_has_no_unsupported_confirmed_result() -> None:
    assessment = catalyst_assessment(status=CatalystStatus.CONFIRMED, claim_ids=(tid("claim", "rumor"),), evidence_ids=())

    result = validate_catalyst_assessment(assessment, {})

    assert result.ok is False
    assert result.outcome is ValidationOutcome.NON_PROMOTABLE
    assert result.promoted_status is CatalystStatus.BLOCKED
    assert "confirmed_catalyst_missing_eligible_evidence" in result.reason_codes


def test_missing_counterevidence_reference_fails_closed() -> None:
    support = evidence("filing", claim_id=tid("claim", "moat"))
    assessment = moat_assessment(
        moat_evidence_ids=(support.evidence_id,),
        counterevidence_ids=(tid("evidence", "missing-counterevidence"),),
    )

    result = validate_competitive_moat(assessment, {support.evidence_id: support})

    assert result.ok is False
    assert result.outcome is ValidationOutcome.NON_PROMOTABLE
    assert "missing_counterevidence" in result.reason_codes


def test_stale_confirmation_beyond_freshness_sla_fails_closed() -> None:
    stale = evidence(
        "stale-filing",
        source_published_at_utc="2025-12-01T00:00:00Z",
        source_available_at_utc="2025-12-01T01:00:00Z",
        system_available_at_utc="2025-12-01T02:00:00Z",
    )
    assessment = catalyst_assessment(status=CatalystStatus.CONFIRMED, evidence_ids=(stale.evidence_id,))

    result = validate_catalyst_assessment(assessment, {stale.evidence_id: stale}, freshness_sla_days=30)

    assert result.ok is False
    assert result.outcome is ValidationOutcome.NON_PROMOTABLE
    assert result.promoted_status is CatalystStatus.BLOCKED
    assert "stale_confirmation_evidence" in result.reason_codes


def test_evidence_timestamps_after_cutoff_and_refuting_evidence_are_non_promotable() -> None:
    future_support = evidence("future", claim_id=tid("claim", "moat"), system_available_at_utc="2026-07-15T00:00:00Z")
    refuting = evidence("refuting", polarity=EvidencePolarity.REFUTES)
    assessment = moat_assessment(
        moat_evidence_ids=(future_support.evidence_id,),
        counterevidence_ids=(refuting.evidence_id,),
    )

    result = validate_competitive_moat(
        assessment,
        {future_support.evidence_id: future_support, refuting.evidence_id: refuting},
    )

    assert result.ok is False
    assert result.outcome is ValidationOutcome.DISPUTED
    assert "evidence_after_analysis_cutoff" in result.reason_codes
    assert "refuting_counterevidence" in result.reason_codes


def test_confirmed_catalyst_round_trip_and_typed_promotable_outcome() -> None:
    support = evidence("fresh-filing", claim_id=tid("claim", "capacity-expansion"))
    assessment = catalyst_assessment(status=CatalystStatus.CONFIRMED, evidence_ids=(support.evidence_id,))

    result = validate_catalyst_assessment(assessment, {support.evidence_id: support}, freshness_sla_days=30)

    assert CatalystAssessment.from_dict(strict_json_loads(canonical_json(assessment.to_dict()))) == assessment
    assert result.ok is True
    assert result.outcome is ValidationOutcome.PROMOTABLE
    assert result.promoted_status is CatalystStatus.CONFIRMED
    assert result.reason_codes == ()


def test_unrelated_or_late_evidence_cannot_promote_claims_or_relationships() -> None:
    unrelated = evidence("unrelated")
    catalyst = catalyst_assessment(status=CatalystStatus.CONFIRMED, evidence_ids=(unrelated.evidence_id,))
    catalyst_result = validate_catalyst_assessment(catalyst, {unrelated.evidence_id: unrelated})
    assert catalyst_result.outcome is ValidationOutcome.NON_PROMOTABLE
    assert catalyst_result.promoted_status is CatalystStatus.BLOCKED
    assert "catalyst_evidence_claim_mismatch" in catalyst_result.reason_codes

    moat_support = evidence("moat-support", claim_id=tid("claim", "moat"))
    late_relationship = evidence("late-relationship", system_available_at_utc="2026-07-15T00:00:00Z")
    relationship = CompetitiveRelationship(
        relationship_id=tid("competitive_relationship", "late-evidence"),
        competitor_issuer_id=tid("issuer", "lateco"),
        relation=ValueChainRelation.COMPETES_WITH,
        valid_from="2026-07-01T00:00:00Z",
        valid_to=None,
        evidence_ids=(late_relationship.evidence_id,),
    )
    moat = moat_assessment(moat_evidence_ids=(moat_support.evidence_id,), relationships=(relationship,))
    moat_result = validate_competitive_moat(
        moat,
        {moat_support.evidence_id: moat_support, late_relationship.evidence_id: late_relationship},
    )
    assert moat_result.outcome is ValidationOutcome.NON_PROMOTABLE
    assert "evidence_after_analysis_cutoff" in moat_result.reason_codes


def test_old_source_cannot_be_freshened_by_late_system_ingestion_and_refutation_disputes_catalyst() -> None:
    old_source = evidence(
        "old-source-new-ingest",
        claim_id=tid("claim", "capacity-expansion"),
        source_published_at_utc="2025-12-01T00:00:00Z",
        source_available_at_utc="2025-12-01T01:00:00Z",
        system_available_at_utc="2026-07-14T07:00:00Z",
    )
    refuting = evidence("catalyst-refuting", polarity=EvidencePolarity.REFUTES)
    assessment = catalyst_assessment(
        status=CatalystStatus.CONFIRMED,
        evidence_ids=(old_source.evidence_id,),
        counterevidence_ids=(refuting.evidence_id,),
    )
    result = validate_catalyst_assessment(
        assessment,
        {old_source.evidence_id: old_source, refuting.evidence_id: refuting},
        freshness_sla_days=30,
    )
    assert result.outcome is ValidationOutcome.DISPUTED
    assert result.promoted_status is CatalystStatus.REFUTED
    assert "stale_confirmation_evidence" in result.reason_codes
    assert "refuting_counterevidence" in result.reason_codes
