from __future__ import annotations

"""Deterministic company-intelligence contracts for Slice 1 theme/value-chain work."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .agency_contracts import TypedID, canonical_bytes, canonical_json, sha256_hex, strict_json_loads, validate_timestamp
from .company_identity import IdentityStatus, IssuerRecord, SecurityRecord

SCHEMA_THEME_V1 = "mlab-theme.v1"
SCHEMA_VALUE_CHAIN_V1 = "mlab-value-chain.v1"
SCHEMA_SOURCE_BACKED_EVIDENCE_V1 = "mlab-source-backed-evidence.v1"
SCHEMA_COMPETITIVE_MOAT_V1 = "mlab-competitive-moat.v1"
SCHEMA_COMPETITIVE_RELATIONSHIP_V1 = "mlab-competitive-relationship.v1"
SCHEMA_CATALYST_ASSESSMENT_V1 = "mlab-catalyst-assessment.v1"
SAFETY_MODE_RESEARCH_MOCK_ONLY = "research_mock_only"


class ThemeStatus(Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"


class ClaimStatus(Enum):
    VERIFIED = "VERIFIED"
    MIXED = "MIXED"
    UNRESOLVED = "UNRESOLVED"
    REFUTED = "REFUTED"


class EvidenceKind(Enum):
    OFFICIAL_FILING = "OFFICIAL_FILING"
    OFFICIAL_REGISTRY = "OFFICIAL_REGISTRY"
    OFFICIAL_COMPANY = "OFFICIAL_COMPANY"
    SYNTHETIC = "SYNTHETIC"
    SECONDARY = "SECONDARY"


class NodeRole(Enum):
    INPUT = "INPUT"
    COMPONENT = "COMPONENT"
    EQUIPMENT = "EQUIPMENT"
    MANUFACTURER = "MANUFACTURER"
    PLATFORM = "PLATFORM"
    DISTRIBUTOR = "DISTRIBUTOR"
    SERVICE = "SERVICE"
    CUSTOMER = "CUSTOMER"
    COMPLEMENT = "COMPLEMENT"
    SUBSTITUTE = "SUBSTITUTE"
    REGULATOR = "REGULATOR"
    CAPITAL_PROVIDER = "CAPITAL_PROVIDER"


class BottleneckType(Enum):
    NONE = "NONE"
    CAPACITY = "CAPACITY"
    IP = "IP"
    REGULATORY = "REGULATORY"
    DATA = "DATA"
    DISTRIBUTION = "DISTRIBUTION"
    SWITCHING = "SWITCHING"
    CAPITAL = "CAPITAL"
    LABOR = "LABOR"
    OTHER = "OTHER"


class Confidence(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EvidencePolarity(Enum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    CONTEXT = "CONTEXT"


class ValidationOutcome(Enum):
    PROMOTABLE = "PROMOTABLE"
    NON_PROMOTABLE = "NON_PROMOTABLE"
    DISPUTED = "DISPUTED"


class CatalystStatus(Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REFUTED = "REFUTED"
    BLOCKED = "BLOCKED"


class ValueChainStatus(Enum):
    PROPOSED = "PROPOSED"
    EVIDENCED = "EVIDENCED"
    DISPUTED = "DISPUTED"
    BLOCKED = "BLOCKED"


class ValueChainRelation(Enum):
    SUPPLIES = "SUPPLIES"
    BUYS_FROM = "BUYS_FROM"
    ENABLES = "ENABLES"
    DISTRIBUTES = "DISTRIBUTES"
    COMPETES_WITH = "COMPETES_WITH"
    SUBSTITUTES = "SUBSTITUTES"
    COMPLEMENTS = "COMPLEMENTS"
    REGULATES = "REGULATES"
    FINANCES = "FINANCES"


class GraphValidationError(ValueError):
    pass


def _enum(enum_type: type[Enum], value: Any, field_name: str) -> Enum:
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} contains unknown enum value") from exc


def _typed_id(value: TypedID | Mapping[str, Any], field_name: str) -> TypedID:
    if isinstance(value, TypedID):
        return value
    if isinstance(value, Mapping):
        return TypedID.from_dict(value)
    raise ValueError(f"{field_name} must be a TypedID")


def _typed_ids(values: tuple[TypedID, ...] | list[Any] | tuple[Any, ...], field_name: str) -> tuple[TypedID, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    return tuple(_typed_id(value, field_name) for value in values)


def _strings(values: tuple[str, ...] | list[Any] | tuple[Any, ...], field_name: str, *, require_nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    result = tuple(str(value) for value in values)
    if require_nonempty and not result:
        raise ValueError(f"{field_name} must be non-empty")
    if any(not value for value in result):
        raise ValueError(f"{field_name} cannot contain empty values")
    return result


def _utc_datetime(value: str, field_name: str) -> datetime:
    validate_timestamp(value, field_name)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: TypedID
    claim_id: TypedID
    claim_status: ClaimStatus
    evidence_kind: EvidenceKind

    def __post_init__(self) -> None:
        if not isinstance(self.claim_status, ClaimStatus):
            object.__setattr__(self, "claim_status", _enum(ClaimStatus, self.claim_status, "claim_status"))
        if not isinstance(self.evidence_kind, EvidenceKind):
            object.__setattr__(self, "evidence_kind", _enum(EvidenceKind, self.evidence_kind, "evidence_kind"))


@dataclass(frozen=True)
class SourceBackedEvidenceRef:
    evidence_id: TypedID
    claim_id: TypedID
    claim_status: ClaimStatus
    evidence_kind: EvidenceKind
    polarity: EvidencePolarity
    source_published_at_utc: str
    source_available_at_utc: str
    system_available_at_utc: str
    schema_version: str = SCHEMA_SOURCE_BACKED_EVIDENCE_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_SOURCE_BACKED_EVIDENCE_V1:
            raise ValueError(f"schema_version must be {SCHEMA_SOURCE_BACKED_EVIDENCE_V1}")
        if not isinstance(self.claim_status, ClaimStatus):
            object.__setattr__(self, "claim_status", _enum(ClaimStatus, self.claim_status, "claim_status"))
        if not isinstance(self.evidence_kind, EvidenceKind):
            object.__setattr__(self, "evidence_kind", _enum(EvidenceKind, self.evidence_kind, "evidence_kind"))
        if not isinstance(self.polarity, EvidencePolarity):
            object.__setattr__(self, "polarity", _enum(EvidencePolarity, self.polarity, "polarity"))
        published = _utc_datetime(self.source_published_at_utc, "source_published_at_utc")
        source_available = _utc_datetime(self.source_available_at_utc, "source_available_at_utc")
        system_available = _utc_datetime(self.system_available_at_utc, "system_available_at_utc")
        if source_available < published:
            raise ValueError("source_available_at_utc cannot precede source_published_at_utc")
        if system_available < source_available:
            raise ValueError("system_available_at_utc cannot precede source_available_at_utc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id.to_dict(),
            "claim_id": self.claim_id.to_dict(),
            "claim_status": self.claim_status.value,
            "evidence_kind": self.evidence_kind.value,
            "polarity": self.polarity.value,
            "source_published_at_utc": self.source_published_at_utc,
            "source_available_at_utc": self.source_available_at_utc,
            "system_available_at_utc": self.system_available_at_utc,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SourceBackedEvidenceRef":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            evidence_id=_typed_id(payload.get("evidence_id", {}), "evidence_id"),
            claim_id=_typed_id(payload.get("claim_id", {}), "claim_id"),
            claim_status=_enum(ClaimStatus, payload.get("claim_status"), "claim_status"),  # type: ignore[arg-type]
            evidence_kind=_enum(EvidenceKind, payload.get("evidence_kind"), "evidence_kind"),  # type: ignore[arg-type]
            polarity=_enum(EvidencePolarity, payload.get("polarity"), "polarity"),  # type: ignore[arg-type]
            source_published_at_utc=str(payload.get("source_published_at_utc", "")),
            source_available_at_utc=str(payload.get("source_available_at_utc", "")),
            system_available_at_utc=str(payload.get("system_available_at_utc", "")),
        )


@dataclass(frozen=True)
class ContractValidationResult:
    ok: bool
    reason_codes: tuple[str, ...]
    outcome: ValidationOutcome
    promoted_status: CatalystStatus | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ValidationOutcome):
            object.__setattr__(self, "outcome", _enum(ValidationOutcome, self.outcome, "outcome"))
        if self.promoted_status is not None and not isinstance(self.promoted_status, CatalystStatus):
            object.__setattr__(self, "promoted_status", _enum(CatalystStatus, self.promoted_status, "promoted_status"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason_codes": list(self.reason_codes),
            "outcome": self.outcome.value,
            "promoted_status": self.promoted_status.value if self.promoted_status is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContractValidationResult":
        promoted = payload.get("promoted_status")
        return cls(
            ok=bool(payload.get("ok", False)),
            reason_codes=_strings(payload.get("reason_codes", ()), "reason_codes"),
            outcome=_enum(ValidationOutcome, payload.get("outcome"), "outcome"),  # type: ignore[arg-type]
            promoted_status=None if promoted is None else _enum(CatalystStatus, promoted, "promoted_status"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class CompetitiveRelationship:
    relationship_id: TypedID
    competitor_issuer_id: TypedID
    relation: ValueChainRelation
    valid_from: str
    valid_to: str | None
    evidence_ids: tuple[TypedID, ...]
    schema_version: str = SCHEMA_COMPETITIVE_RELATIONSHIP_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_COMPETITIVE_RELATIONSHIP_V1:
            raise ValueError(f"schema_version must be {SCHEMA_COMPETITIVE_RELATIONSHIP_V1}")
        start_dt = _utc_datetime(self.valid_from, "valid_from")
        if self.valid_to is not None:
            end_dt = _utc_datetime(self.valid_to, "valid_to")
            if end_dt <= start_dt:
                raise ValueError("competitive relationship interval must end after start")
        if not isinstance(self.relation, ValueChainRelation):
            object.__setattr__(self, "relation", _enum(ValueChainRelation, self.relation, "relation"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "relationship_id": self.relationship_id.to_dict(),
            "competitor_issuer_id": self.competitor_issuer_id.to_dict(),
            "relation": self.relation.value,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "evidence_ids": [evidence_id.to_dict() for evidence_id in self.evidence_ids],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CompetitiveRelationship":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            relationship_id=_typed_id(payload.get("relationship_id", {}), "relationship_id"),
            competitor_issuer_id=_typed_id(payload.get("competitor_issuer_id", {}), "competitor_issuer_id"),
            relation=_enum(ValueChainRelation, payload.get("relation"), "relation"),  # type: ignore[arg-type]
            valid_from=str(payload.get("valid_from", "")),
            valid_to=payload.get("valid_to"),
            evidence_ids=_typed_ids(payload.get("evidence_ids", ()), "evidence_ids"),
        )


@dataclass(frozen=True)
class CompetitiveMoatAssessment:
    issuer_id: TypedID
    analysis_cutoff_utc: str
    moat_claim_ids: tuple[TypedID, ...]
    moat_evidence_ids: tuple[TypedID, ...]
    counterevidence_ids: tuple[TypedID, ...]
    competitor_relationships: tuple[CompetitiveRelationship, ...]
    analyst_rationale: str
    schema_version: str = SCHEMA_COMPETITIVE_MOAT_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_COMPETITIVE_MOAT_V1:
            raise ValueError(f"schema_version must be {SCHEMA_COMPETITIVE_MOAT_V1}")
        validate_timestamp(self.analysis_cutoff_utc, "analysis_cutoff_utc")
        if not self.moat_claim_ids or not self.analyst_rationale:
            raise ValueError("competitive moat assessment requires claims and rationale")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "issuer_id": self.issuer_id.to_dict(),
            "analysis_cutoff_utc": self.analysis_cutoff_utc,
            "moat_claim_ids": [claim_id.to_dict() for claim_id in self.moat_claim_ids],
            "moat_evidence_ids": [evidence_id.to_dict() for evidence_id in self.moat_evidence_ids],
            "counterevidence_ids": [evidence_id.to_dict() for evidence_id in self.counterevidence_ids],
            "competitor_relationships": [relationship.to_dict() for relationship in self.competitor_relationships],
            "analyst_rationale": self.analyst_rationale,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CompetitiveMoatAssessment":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            issuer_id=_typed_id(payload.get("issuer_id", {}), "issuer_id"),
            analysis_cutoff_utc=str(payload.get("analysis_cutoff_utc", "")),
            moat_claim_ids=_typed_ids(payload.get("moat_claim_ids", ()), "moat_claim_ids"),
            moat_evidence_ids=_typed_ids(payload.get("moat_evidence_ids", ()), "moat_evidence_ids"),
            counterevidence_ids=_typed_ids(payload.get("counterevidence_ids", ()), "counterevidence_ids"),
            competitor_relationships=tuple(CompetitiveRelationship.from_dict(item) for item in payload.get("competitor_relationships", ())),
            analyst_rationale=str(payload.get("analyst_rationale", "")),
        )


@dataclass(frozen=True)
class CatalystAssessment:
    catalyst_id: TypedID
    issuer_id: TypedID
    description: str
    analysis_cutoff_utc: str
    expected_event_at_utc: str
    claim_ids: tuple[TypedID, ...]
    evidence_ids: tuple[TypedID, ...]
    counterevidence_ids: tuple[TypedID, ...]
    status: CatalystStatus
    schema_version: str = SCHEMA_CATALYST_ASSESSMENT_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_CATALYST_ASSESSMENT_V1:
            raise ValueError(f"schema_version must be {SCHEMA_CATALYST_ASSESSMENT_V1}")
        validate_timestamp(self.analysis_cutoff_utc, "analysis_cutoff_utc")
        validate_timestamp(self.expected_event_at_utc, "expected_event_at_utc")
        if not isinstance(self.status, CatalystStatus):
            object.__setattr__(self, "status", _enum(CatalystStatus, self.status, "status"))
        if not self.description or not self.claim_ids:
            raise ValueError("catalyst assessment requires description and claim_ids")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "catalyst_id": self.catalyst_id.to_dict(),
            "issuer_id": self.issuer_id.to_dict(),
            "description": self.description,
            "analysis_cutoff_utc": self.analysis_cutoff_utc,
            "expected_event_at_utc": self.expected_event_at_utc,
            "claim_ids": [claim_id.to_dict() for claim_id in self.claim_ids],
            "evidence_ids": [evidence_id.to_dict() for evidence_id in self.evidence_ids],
            "counterevidence_ids": [evidence_id.to_dict() for evidence_id in self.counterevidence_ids],
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CatalystAssessment":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            catalyst_id=_typed_id(payload.get("catalyst_id", {}), "catalyst_id"),
            issuer_id=_typed_id(payload.get("issuer_id", {}), "issuer_id"),
            description=str(payload.get("description", "")),
            analysis_cutoff_utc=str(payload.get("analysis_cutoff_utc", "")),
            expected_event_at_utc=str(payload.get("expected_event_at_utc", "")),
            claim_ids=_typed_ids(payload.get("claim_ids", ()), "claim_ids"),
            evidence_ids=_typed_ids(payload.get("evidence_ids", ()), "evidence_ids"),
            counterevidence_ids=_typed_ids(payload.get("counterevidence_ids", ()), "counterevidence_ids"),
            status=_enum(CatalystStatus, payload.get("status"), "status"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class MechanismClaim:
    mechanism: str
    claim_ids: tuple[TypedID, ...]
    evidence_ids: tuple[TypedID, ...]

    def __post_init__(self) -> None:
        if not self.mechanism or not self.claim_ids or not self.evidence_ids:
            raise ValueError("material mechanism requires mechanism, claim_ids, and evidence_ids")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mechanism": self.mechanism,
            "claim_ids": [claim_id.to_dict() for claim_id in self.claim_ids],
            "evidence_ids": [evidence_id.to_dict() for evidence_id in self.evidence_ids],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MechanismClaim":
        return cls(
            mechanism=str(payload.get("mechanism", "")),
            claim_ids=_typed_ids(payload.get("claim_ids", ()), "claim_ids"),
            evidence_ids=_typed_ids(payload.get("evidence_ids", ()), "evidence_ids"),
        )


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ThemeDefinition:
    theme_id: TypedID
    name: str
    canonical_definition: str
    included_mechanisms: tuple[str, ...]
    excluded_mechanisms: tuple[str, ...]
    geographies: tuple[str, ...]
    horizon: str
    as_of_utc: str
    origin_claim_ids: tuple[TypedID, ...]
    material_claim_ids: tuple[TypedID, ...]
    counterclaim_ids: tuple[TypedID, ...]
    keywords: tuple[str, ...]
    synonyms: tuple[str, ...]
    ambiguous_terms: tuple[str, ...]
    analyst_rationale: str
    rationale_claim_ids: tuple[TypedID, ...]
    rationale_evidence_ids: tuple[TypedID, ...]
    falsifiers: tuple[str, ...]
    status: ThemeStatus
    material_mechanisms: tuple[MechanismClaim, ...] = ()
    disconfirmation_questions: tuple[str, ...] = ()
    schema_version: str = SCHEMA_THEME_V1
    theme_digest_sha256: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_THEME_V1:
            raise ValueError(f"schema_version must be {SCHEMA_THEME_V1}")
        validate_timestamp(self.as_of_utc, "as_of_utc")
        if not isinstance(self.status, ThemeStatus):
            object.__setattr__(self, "status", _enum(ThemeStatus, self.status, "status"))
        digest_payload = self.to_dict(include_digest=False)
        object.__setattr__(self, "theme_digest_sha256", sha256_hex(canonical_bytes(digest_payload)))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "theme_id": self.theme_id.to_dict(),
            "name": self.name,
            "canonical_definition": self.canonical_definition,
            "included_mechanisms": list(self.included_mechanisms),
            "excluded_mechanisms": list(self.excluded_mechanisms),
            "geographies": list(self.geographies),
            "horizon": self.horizon,
            "as_of_utc": self.as_of_utc,
            "origin_claim_ids": [claim_id.to_dict() for claim_id in self.origin_claim_ids],
            "material_claim_ids": [claim_id.to_dict() for claim_id in self.material_claim_ids],
            "counterclaim_ids": [claim_id.to_dict() for claim_id in self.counterclaim_ids],
            "keywords": list(self.keywords),
            "synonyms": list(self.synonyms),
            "ambiguous_terms": list(self.ambiguous_terms),
            "analyst_rationale": self.analyst_rationale,
            "rationale_claim_ids": [claim_id.to_dict() for claim_id in self.rationale_claim_ids],
            "rationale_evidence_ids": [evidence_id.to_dict() for evidence_id in self.rationale_evidence_ids],
            "material_mechanisms": [mechanism.to_dict() for mechanism in self.material_mechanisms],
            "disconfirmation_questions": list(self.disconfirmation_questions),
            "falsifiers": list(self.falsifiers),
            "status": self.status.value,
        }
        if include_digest:
            payload["theme_digest_sha256"] = self.theme_digest_sha256
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ThemeDefinition":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            theme_id=_typed_id(payload.get("theme_id", {}), "theme_id"),
            name=str(payload.get("name", "")),
            canonical_definition=str(payload.get("canonical_definition", "")),
            included_mechanisms=_strings(payload.get("included_mechanisms", ()), "included_mechanisms"),
            excluded_mechanisms=_strings(payload.get("excluded_mechanisms", ()), "excluded_mechanisms"),
            geographies=_strings(payload.get("geographies", ()), "geographies"),
            horizon=str(payload.get("horizon", "")),
            as_of_utc=str(payload.get("as_of_utc", "")),
            origin_claim_ids=_typed_ids(payload.get("origin_claim_ids", ()), "origin_claim_ids"),
            material_claim_ids=_typed_ids(payload.get("material_claim_ids", ()), "material_claim_ids"),
            counterclaim_ids=_typed_ids(payload.get("counterclaim_ids", ()), "counterclaim_ids"),
            keywords=_strings(payload.get("keywords", ()), "keywords"),
            synonyms=_strings(payload.get("synonyms", ()), "synonyms"),
            ambiguous_terms=_strings(payload.get("ambiguous_terms", ()), "ambiguous_terms"),
            analyst_rationale=str(payload.get("analyst_rationale", "")),
            rationale_claim_ids=_typed_ids(payload.get("rationale_claim_ids", ()), "rationale_claim_ids"),
            rationale_evidence_ids=_typed_ids(payload.get("rationale_evidence_ids", ()), "rationale_evidence_ids"),
            material_mechanisms=tuple(MechanismClaim.from_dict(item) for item in payload.get("material_mechanisms", ())),
            disconfirmation_questions=_strings(payload.get("disconfirmation_questions", ()), "disconfirmation_questions"),
            falsifiers=_strings(payload.get("falsifiers", ()), "falsifiers"),
            status=_enum(ThemeStatus, payload.get("status"), "status"),  # type: ignore[arg-type]
        )


def validate_theme(theme: ThemeDefinition, evidence_index: Mapping[TypedID, EvidenceRef]) -> ValidationResult:
    reasons: list[str] = []
    required_strings = (theme.name, theme.canonical_definition, theme.horizon, theme.analyst_rationale)
    if any(not value for value in required_strings):
        reasons.append("missing_definition")
    if not theme.included_mechanisms or not theme.excluded_mechanisms or not theme.geographies:
        reasons.append("missing_scope")
    if not theme.material_claim_ids or not theme.material_mechanisms:
        reasons.append("missing_material_claims")
    if not theme.counterclaim_ids or not theme.disconfirmation_questions or not theme.falsifiers:
        reasons.append("missing_counterclaim_or_falsifier")
    for mechanism in theme.material_mechanisms:
        if not mechanism.claim_ids or not mechanism.evidence_ids:
            reasons.append("mechanism_missing_links")
        for evidence_id in mechanism.evidence_ids:
            evidence = evidence_index.get(evidence_id)
            if evidence is None:
                reasons.append("missing_evidence")
                continue
            if evidence.evidence_kind is EvidenceKind.SYNTHETIC:
                reasons.append("synthetic_evidence")
            if evidence.claim_status not in (ClaimStatus.VERIFIED, ClaimStatus.MIXED):
                reasons.append("unsupported_claim_status")
    return ValidationResult(ok=not reasons, reason_codes=tuple(dict.fromkeys(reasons)))


def _ordered_reasons(reasons: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(reasons))


def _evidence_time_reasons(
    evidence: SourceBackedEvidenceRef,
    analysis_cutoff_utc: str,
    *,
    freshness_sla_days: int | None = None,
    stale_reason: str = "stale_evidence",
) -> list[str]:
    cutoff = _utc_datetime(analysis_cutoff_utc, "analysis_cutoff_utc")
    timestamps = (
        evidence.source_published_at_utc,
        evidence.source_available_at_utc,
        evidence.system_available_at_utc,
    )
    if any(_utc_datetime(value, "evidence_timestamp") > cutoff for value in timestamps):
        return ["evidence_after_analysis_cutoff"]
    if freshness_sla_days is not None:
        if freshness_sla_days < 0:
            raise ValueError("freshness_sla_days must be non-negative")
        source_published = _utc_datetime(evidence.source_published_at_utc, "source_published_at_utc")
        if cutoff - source_published > timedelta(days=freshness_sla_days):
            return [stale_reason]
    return []


def _is_supporting_evidence(evidence: SourceBackedEvidenceRef, *, verified_only: bool) -> bool:
    allowed_statuses = (ClaimStatus.VERIFIED,) if verified_only else (ClaimStatus.VERIFIED, ClaimStatus.MIXED)
    return (
        evidence.evidence_kind is not EvidenceKind.SYNTHETIC
        and evidence.polarity is EvidencePolarity.SUPPORTS
        and evidence.claim_status in allowed_statuses
    )


def _is_external_moat_evidence(evidence: SourceBackedEvidenceRef) -> bool:
    return evidence.evidence_kind not in (EvidenceKind.SYNTHETIC, EvidenceKind.OFFICIAL_COMPANY)


def validate_competitive_moat(
    assessment: CompetitiveMoatAssessment,
    evidence_index: Mapping[TypedID, SourceBackedEvidenceRef],
    *,
    freshness_sla_days: int | None = None,
) -> ContractValidationResult:
    reasons: list[str] = []
    eligible_support_count = 0
    management_support_count = 0
    refuting_counterevidence = False

    for evidence_id in assessment.moat_evidence_ids:
        evidence = evidence_index.get(evidence_id)
        if evidence is None:
            reasons.append("missing_moat_evidence")
            continue
        time_reasons = _evidence_time_reasons(evidence, assessment.analysis_cutoff_utc, freshness_sla_days=freshness_sla_days)
        reasons.extend(time_reasons)
        if time_reasons or not _is_supporting_evidence(evidence, verified_only=False):
            continue
        if evidence.claim_id not in assessment.moat_claim_ids:
            reasons.append("moat_evidence_claim_mismatch")
            continue
        if evidence.evidence_kind is EvidenceKind.OFFICIAL_COMPANY:
            management_support_count += 1
            continue
        if _is_external_moat_evidence(evidence):
            eligible_support_count += 1

    if eligible_support_count == 0:
        reasons.append("missing_eligible_moat_evidence")
        if management_support_count > 0:
            reasons.append("management_only_moat_support")

    cutoff = _utc_datetime(assessment.analysis_cutoff_utc, "analysis_cutoff_utc")
    for relationship in assessment.competitor_relationships:
        if _utc_datetime(relationship.valid_from, "valid_from") > cutoff:
            reasons.append("relationship_after_analysis_cutoff")
        for evidence_id in relationship.evidence_ids:
            evidence = evidence_index.get(evidence_id)
            if evidence is None:
                reasons.append("missing_relationship_evidence")
                continue
            reasons.extend(
                _evidence_time_reasons(
                    evidence,
                    assessment.analysis_cutoff_utc,
                    freshness_sla_days=freshness_sla_days,
                )
            )

    for evidence_id in assessment.counterevidence_ids:
        evidence = evidence_index.get(evidence_id)
        if evidence is None:
            reasons.append("missing_counterevidence")
            continue
        time_reasons = _evidence_time_reasons(evidence, assessment.analysis_cutoff_utc, freshness_sla_days=freshness_sla_days)
        reasons.extend(time_reasons)
        if not time_reasons and evidence.polarity is EvidencePolarity.REFUTES and evidence.claim_status in (ClaimStatus.VERIFIED, ClaimStatus.MIXED):
            reasons.append("refuting_counterevidence")
            refuting_counterevidence = True

    reason_codes = _ordered_reasons(reasons)
    if refuting_counterevidence:
        outcome = ValidationOutcome.DISPUTED
    elif reason_codes:
        outcome = ValidationOutcome.NON_PROMOTABLE
    else:
        outcome = ValidationOutcome.PROMOTABLE
    return ContractValidationResult(ok=not reason_codes, reason_codes=reason_codes, outcome=outcome)


def validate_catalyst_assessment(
    assessment: CatalystAssessment,
    evidence_index: Mapping[TypedID, SourceBackedEvidenceRef],
    *,
    freshness_sla_days: int | None = None,
) -> ContractValidationResult:
    reasons: list[str] = []
    eligible_support_count = 0
    refuting_counterevidence = False

    for evidence_id in assessment.evidence_ids:
        evidence = evidence_index.get(evidence_id)
        if evidence is None:
            reasons.append("missing_catalyst_evidence")
            continue
        time_reasons = _evidence_time_reasons(
            evidence,
            assessment.analysis_cutoff_utc,
            freshness_sla_days=freshness_sla_days,
            stale_reason="stale_confirmation_evidence",
        )
        reasons.extend(time_reasons)
        if not time_reasons and _is_supporting_evidence(evidence, verified_only=True):
            if evidence.claim_id in assessment.claim_ids:
                eligible_support_count += 1
            else:
                reasons.append("catalyst_evidence_claim_mismatch")

    for evidence_id in assessment.counterevidence_ids:
        evidence = evidence_index.get(evidence_id)
        if evidence is None:
            reasons.append("missing_counterevidence")
            continue
        time_reasons = _evidence_time_reasons(evidence, assessment.analysis_cutoff_utc, freshness_sla_days=freshness_sla_days)
        reasons.extend(time_reasons)
        if not time_reasons and evidence.polarity is EvidencePolarity.REFUTES and evidence.claim_status in (ClaimStatus.VERIFIED, ClaimStatus.MIXED):
            reasons.append("refuting_counterevidence")
            refuting_counterevidence = True

    if assessment.status is CatalystStatus.CONFIRMED and eligible_support_count == 0:
        reasons.append("confirmed_catalyst_missing_eligible_evidence")

    reason_codes = _ordered_reasons(reasons)
    if refuting_counterevidence:
        outcome = ValidationOutcome.DISPUTED
        promoted_status = CatalystStatus.REFUTED
    elif reason_codes:
        outcome = ValidationOutcome.NON_PROMOTABLE
        promoted_status = CatalystStatus.BLOCKED
    else:
        outcome = ValidationOutcome.PROMOTABLE
        promoted_status = assessment.status
    return ContractValidationResult(ok=not reason_codes, reason_codes=reason_codes, outcome=outcome, promoted_status=promoted_status)


@dataclass(frozen=True)
class ValueChainNode:
    node_id: TypedID
    label: str
    role: NodeRole
    description: str
    geography: str
    economic_driver: str
    bottleneck_type: BottleneckType
    material_claim_ids: tuple[TypedID, ...]
    evidence_ids: tuple[TypedID, ...]
    counterevidence_ids: tuple[TypedID, ...]
    confidence: Confidence
    status: ValueChainStatus

    def __post_init__(self) -> None:
        for attr, enum_type in (("role", NodeRole), ("bottleneck_type", BottleneckType), ("confidence", Confidence), ("status", ValueChainStatus)):
            if not isinstance(getattr(self, attr), enum_type):
                object.__setattr__(self, attr, _enum(enum_type, getattr(self, attr), attr))
        if not self.label or not self.description or not self.geography or not self.economic_driver:
            raise ValueError("value-chain node requires label, description, geography, and economic_driver")

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id.to_dict(),
            "label": self.label,
            "role": self.role.value,
            "description": self.description,
            "geography": self.geography,
            "economic_driver": self.economic_driver,
            "bottleneck_type": self.bottleneck_type.value,
            "material_claim_ids": [claim_id.to_dict() for claim_id in self.material_claim_ids],
            "evidence_ids": [evidence_id.to_dict() for evidence_id in self.evidence_ids],
            "counterevidence_ids": [evidence_id.to_dict() for evidence_id in self.counterevidence_ids],
            "confidence": self.confidence.value,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValueChainNode":
        return cls(
            node_id=_typed_id(payload.get("node_id", {}), "node_id"),
            label=str(payload.get("label", "")),
            role=_enum(NodeRole, payload.get("role"), "role"),  # type: ignore[arg-type]
            description=str(payload.get("description", "")),
            geography=str(payload.get("geography", "")),
            economic_driver=str(payload.get("economic_driver", "")),
            bottleneck_type=_enum(BottleneckType, payload.get("bottleneck_type"), "bottleneck_type"),  # type: ignore[arg-type]
            material_claim_ids=_typed_ids(payload.get("material_claim_ids", ()), "material_claim_ids"),
            evidence_ids=_typed_ids(payload.get("evidence_ids", ()), "evidence_ids"),
            counterevidence_ids=_typed_ids(payload.get("counterevidence_ids", ()), "counterevidence_ids"),
            confidence=_enum(Confidence, payload.get("confidence"), "confidence"),  # type: ignore[arg-type]
            status=_enum(ValueChainStatus, payload.get("status"), "status"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ValueChainEdge:
    edge_id: TypedID
    from_node_id: TypedID
    to_node_id: TypedID
    relation: ValueChainRelation
    economic_transmission: str
    units_or_basis: str
    valid_from: str
    valid_to: str | None
    claim_ids: tuple[TypedID, ...]
    evidence_ids: tuple[TypedID, ...]
    status: ValueChainStatus

    def __post_init__(self) -> None:
        validate_timestamp(self.valid_from, "valid_from")
        if self.valid_to is not None:
            validate_timestamp(self.valid_to, "valid_to")
            start_dt = datetime.fromisoformat(self.valid_from.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(self.valid_to.replace("Z", "+00:00"))
            if end_dt <= start_dt:
                raise ValueError("edge effective interval must be half-open with end after start")
        for attr, enum_type in (("relation", ValueChainRelation), ("status", ValueChainStatus)):
            if not isinstance(getattr(self, attr), enum_type):
                object.__setattr__(self, attr, _enum(enum_type, getattr(self, attr), attr))
        if not self.economic_transmission or not self.units_or_basis:
            raise ValueError("value-chain edge requires transmission and basis")

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id.to_dict(),
            "from_node_id": self.from_node_id.to_dict(),
            "to_node_id": self.to_node_id.to_dict(),
            "relation": self.relation.value,
            "economic_transmission": self.economic_transmission,
            "units_or_basis": self.units_or_basis,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "claim_ids": [claim_id.to_dict() for claim_id in self.claim_ids],
            "evidence_ids": [evidence_id.to_dict() for evidence_id in self.evidence_ids],
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValueChainEdge":
        return cls(
            edge_id=_typed_id(payload.get("edge_id", {}), "edge_id"),
            from_node_id=_typed_id(payload.get("from_node_id", {}), "from_node_id"),
            to_node_id=_typed_id(payload.get("to_node_id", {}), "to_node_id"),
            relation=_enum(ValueChainRelation, payload.get("relation"), "relation"),  # type: ignore[arg-type]
            economic_transmission=str(payload.get("economic_transmission", "")),
            units_or_basis=str(payload.get("units_or_basis", "")),
            valid_from=str(payload.get("valid_from", "")),
            valid_to=payload.get("valid_to"),
            claim_ids=_typed_ids(payload.get("claim_ids", ()), "claim_ids"),
            evidence_ids=_typed_ids(payload.get("evidence_ids", ()), "evidence_ids"),
            status=_enum(ValueChainStatus, payload.get("status"), "status"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ValueChainGraph:
    theme_id: TypedID
    as_of_utc: str
    nodes: tuple[ValueChainNode, ...]
    edges: tuple[ValueChainEdge, ...]
    coverage_gaps: tuple[str, ...]
    schema_version: str = SCHEMA_VALUE_CHAIN_V1
    graph_digest: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VALUE_CHAIN_V1:
            raise ValueError(f"schema_version must be {SCHEMA_VALUE_CHAIN_V1}")
        validate_timestamp(self.as_of_utc, "as_of_utc")
        object.__setattr__(self, "graph_digest", sha256_hex(canonical_bytes(self.to_dict(include_digest=False))))

    def validate(self) -> None:
        node_ids = [node.node_id for node in self.nodes]
        edge_ids = [edge.edge_id for edge in self.edges]
        if len(set(node_ids)) != len(node_ids):
            raise GraphValidationError("duplicate node id")
        if len(set(edge_ids)) != len(edge_ids):
            raise GraphValidationError("duplicate edge id")
        node_set = set(node_ids)
        for edge in self.edges:
            if edge.from_node_id not in node_set or edge.to_node_id not in node_set:
                raise GraphValidationError("edge references unknown node")

    def has_evidenced_path(self, driver_node_ids: tuple[TypedID, ...], candidate_node_id: TypedID) -> bool:
        self.validate()
        evidenced_nodes = {node.node_id for node in self.nodes if node.status is ValueChainStatus.EVIDENCED}
        if candidate_node_id not in evidenced_nodes:
            return False
        frontier = [node_id for node_id in driver_node_ids if node_id in evidenced_nodes]
        if not frontier:
            return False
        adjacency: dict[TypedID, list[TypedID]] = {}
        for edge in self.edges:
            if edge.status is ValueChainStatus.EVIDENCED and edge.from_node_id in evidenced_nodes and edge.to_node_id in evidenced_nodes:
                adjacency.setdefault(edge.from_node_id, []).append(edge.to_node_id)
        seen: set[TypedID] = set()
        while frontier:
            current = frontier.pop(0)
            if current == candidate_node_id:
                return True
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(node_id for node_id in adjacency.get(current, ()) if node_id not in seen)
        return False

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "theme_id": self.theme_id.to_dict(),
            "as_of_utc": self.as_of_utc,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "coverage_gaps": list(self.coverage_gaps),
        }
        if include_digest:
            payload["graph_digest"] = self.graph_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ValueChainGraph":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            theme_id=_typed_id(payload.get("theme_id", {}), "theme_id"),
            as_of_utc=str(payload.get("as_of_utc", "")),
            nodes=tuple(ValueChainNode.from_dict(item) for item in payload.get("nodes", ())),
            edges=tuple(ValueChainEdge.from_dict(item) for item in payload.get("edges", ())),
            coverage_gaps=_strings(payload.get("coverage_gaps", ()), "coverage_gaps"),
        )


@dataclass(frozen=True)
class CompanyIntelligenceFixtureRow:
    case_id: str
    issuer: IssuerRecord
    security: SecurityRecord | None
    expected_identity_status: IdentityStatus
    safety_mode: str = SAFETY_MODE_RESEARCH_MOCK_ONLY

    def __post_init__(self) -> None:
        if not self.case_id:
            raise ValueError("case_id is required")
        if self.safety_mode != SAFETY_MODE_RESEARCH_MOCK_ONLY:
            raise ValueError("safety_mode must remain research_mock_only")
        if not isinstance(self.expected_identity_status, IdentityStatus):
            object.__setattr__(self, "expected_identity_status", _enum(IdentityStatus, self.expected_identity_status, "expected_identity_status"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "issuer": self.issuer.to_dict(),
            "security": self.security.to_dict() if self.security else None,
            "expected_identity_status": self.expected_identity_status.value,
            "safety_mode": self.safety_mode,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CompanyIntelligenceFixtureRow":
        return cls(
            case_id=str(payload.get("case_id", "")),
            issuer=IssuerRecord.from_dict(payload.get("issuer", {})),
            security=None if payload.get("security") is None else SecurityRecord.from_dict(payload.get("security", {})),
            expected_identity_status=_enum(IdentityStatus, payload.get("expected_identity_status"), "expected_identity_status"),  # type: ignore[arg-type]
            safety_mode=str(payload.get("safety_mode", "")),
        )


def load_company_intelligence_fixture(path: Path) -> tuple[CompanyIntelligenceFixtureRow, ...]:
    rows: list[CompanyIntelligenceFixtureRow] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(CompanyIntelligenceFixtureRow.from_dict(strict_json_loads(line)))
    if not rows:
        raise ValueError("company intelligence fixture is empty")
    return tuple(rows)
