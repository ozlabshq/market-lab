from __future__ import annotations

"""Deterministic company-intelligence contracts for Slice 1 theme/value-chain work."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from .agency_contracts import TypedID, canonical_bytes, canonical_json, sha256_hex, strict_json_loads, validate_timestamp
from .company_identity import IdentityStatus, IssuerRecord, SecurityRecord

SCHEMA_THEME_V1 = "mlab-theme.v1"
SCHEMA_VALUE_CHAIN_V1 = "mlab-value-chain.v1"
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
