from __future__ import annotations

"""Effective-dated issuer and security identity resolution for company intelligence."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from .agency_contracts import TypedID, validate_timestamp

SCHEMA_ISSUER_V1 = "mlab-issuer.v1"
SCHEMA_SECURITY_V1 = "mlab-security.v1"
SUPPORTED_SECURITY_TYPES = frozenset({"COMMON", "ADR", "ETF"})


class EntityType(Enum):
    OPERATING_COMPANY = "OPERATING_COMPANY"
    HOLDING_COMPANY = "HOLDING_COMPANY"
    FUND = "FUND"
    SPV = "SPV"
    GOVERNMENT = "GOVERNMENT"
    PRIVATE_COMPANY = "PRIVATE_COMPANY"
    OTHER = "OTHER"


class IdentityStatus(Enum):
    RESOLVED = "RESOLVED"
    PROVISIONAL = "PROVISIONAL"
    CONFLICTED = "CONFLICTED"
    RETIRED = "RETIRED"


class SecurityType(Enum):
    COMMON = "COMMON"
    PREFERRED = "PREFERRED"
    ADR = "ADR"
    ETF = "ETF"
    CLOSED_END_FUND = "CLOSED_END_FUND"
    BOND = "BOND"
    OPTION = "OPTION"
    PRIVATE = "PRIVATE"
    OTHER = "OTHER"


class InvestabilityStatus(Enum):
    SUPPORTED_EQUITY = "SUPPORTED_EQUITY"
    RESEARCH_ONLY_UNSUPPORTED = "RESEARCH_ONLY_UNSUPPORTED"
    PRIVATE_NO_SECURITY = "PRIVATE_NO_SECURITY"
    DELISTED = "DELISTED"
    IDENTITY_BLOCKED = "IDENTITY_BLOCKED"


class ResolutionStatus(Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICTED = "CONFLICTED"


class IdentityResolutionError(ValueError):
    pass


def _enum(enum_type: type[Enum], value: Any, field_name: str) -> Enum:
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} contains unknown enum value") from exc


def _typed_id(value: TypedID | Mapping[str, Any] | None, field_name: str) -> TypedID | None:
    if value is None:
        return None
    if isinstance(value, TypedID):
        return value
    if isinstance(value, Mapping):
        return TypedID.from_dict(value)
    raise ValueError(f"{field_name} must be a TypedID")


def _typed_ids(values: tuple[TypedID, ...] | list[Any] | tuple[Any, ...], field_name: str) -> tuple[TypedID, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    result = tuple(_typed_id(value, field_name) for value in values)
    if any(value is None for value in result):
        raise ValueError(f"{field_name} cannot contain null")
    return result  # type: ignore[return-value]


def _strings(values: tuple[str, ...] | list[Any] | tuple[Any, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    result = tuple(str(value) for value in values)
    if any(not value for value in result):
        raise ValueError(f"{field_name} cannot contain empty values")
    return result


def active_during(start: str, end: str | None, as_of_utc: str) -> bool:
    validate_timestamp(start, "effective_from")
    validate_timestamp(as_of_utc, "as_of_utc")
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    as_of_dt = datetime.fromisoformat(as_of_utc.replace("Z", "+00:00"))
    if end is not None:
        validate_timestamp(end, "effective_to")
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if end_dt <= start_dt:
            raise ValueError("effective interval must be half-open with end after start")
        return start_dt <= as_of_dt < end_dt
    return start_dt <= as_of_dt


@dataclass(frozen=True)
class RegistryIdentifier:
    scheme: str
    value: str
    jurisdiction: str

    def __post_init__(self) -> None:
        if not self.scheme or not self.value or not self.jurisdiction:
            raise ValueError("registry identifier requires scheme, value, and jurisdiction")

    def key(self) -> tuple[str, str, str]:
        return (self.scheme, self.jurisdiction, self.value)

    def to_dict(self) -> dict[str, str]:
        return {"scheme": self.scheme, "value": self.value, "jurisdiction": self.jurisdiction}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RegistryIdentifier":
        return cls(scheme=str(payload.get("scheme", "")), value=str(payload.get("value", "")), jurisdiction=str(payload.get("jurisdiction", "")))


def _registry_ids(values: tuple[RegistryIdentifier, ...] | list[Any] | tuple[Any, ...], field_name: str) -> tuple[RegistryIdentifier, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    result = tuple(value if isinstance(value, RegistryIdentifier) else RegistryIdentifier.from_dict(value) for value in values)
    if len({identifier.key() for identifier in result}) != len(result):
        raise ValueError(f"{field_name} contains duplicate identifier")
    return result


@dataclass(frozen=True)
class IssuerRecord:
    issuer_id: TypedID
    legal_name: str
    normalized_name: str
    aliases: tuple[str, ...]
    parent_issuer_id: TypedID | None
    ultimate_parent_issuer_id: TypedID | None
    subsidiaries: tuple[TypedID, ...]
    jurisdiction: str
    sec_cik: str | None
    lei: str | None
    registry_identifiers: tuple[RegistryIdentifier, ...]
    entity_type: EntityType
    filer_status: str
    identity_effective_from: str
    identity_effective_to: str | None
    source_evidence_ids: tuple[TypedID, ...]
    identity_status: IdentityStatus
    schema_version: str = SCHEMA_ISSUER_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_ISSUER_V1:
            raise ValueError(f"schema_version must be {SCHEMA_ISSUER_V1}")
        if not isinstance(self.issuer_id, TypedID):
            raise ValueError("issuer_id must be a TypedID")
        validate_timestamp(self.identity_effective_from, "identity_effective_from")
        if self.identity_effective_to is not None:
            validate_timestamp(self.identity_effective_to, "identity_effective_to")
            start_dt = datetime.fromisoformat(self.identity_effective_from.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(self.identity_effective_to.replace("Z", "+00:00"))
            if end_dt <= start_dt:
                raise ValueError("issuer effective interval must be half-open with end after start")
        if not isinstance(self.entity_type, EntityType):
            object.__setattr__(self, "entity_type", _enum(EntityType, self.entity_type, "entity_type"))
        if not isinstance(self.identity_status, IdentityStatus):
            object.__setattr__(self, "identity_status", _enum(IdentityStatus, self.identity_status, "identity_status"))
        if self.parent_issuer_id == self.issuer_id or self.ultimate_parent_issuer_id == self.issuer_id:
            raise ValueError("issuer parent relationships cannot point to self")
        if not self.legal_name or not self.normalized_name or not self.jurisdiction or not self.filer_status or not self.source_evidence_ids:
            raise ValueError("issuer requires legal identity, jurisdiction, filer_status, and source evidence")

    def active_at(self, as_of_utc: str) -> bool:
        return active_during(self.identity_effective_from, self.identity_effective_to, as_of_utc)

    def identifier_keys(self) -> set[tuple[str, str, str]]:
        keys = {identifier.key() for identifier in self.registry_identifiers}
        if self.sec_cik:
            keys.add(("SEC_CIK", self.jurisdiction, self.sec_cik))
        if self.lei:
            keys.add(("LEI", self.jurisdiction, self.lei))
        return keys

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "issuer_id": self.issuer_id.to_dict(),
            "legal_name": self.legal_name,
            "normalized_name": self.normalized_name,
            "aliases": list(self.aliases),
            "parent_issuer_id": self.parent_issuer_id.to_dict() if self.parent_issuer_id else None,
            "ultimate_parent_issuer_id": self.ultimate_parent_issuer_id.to_dict() if self.ultimate_parent_issuer_id else None,
            "subsidiaries": [issuer_id.to_dict() for issuer_id in self.subsidiaries],
            "jurisdiction": self.jurisdiction,
            "sec_cik": self.sec_cik,
            "lei": self.lei,
            "registry_identifiers": [identifier.to_dict() for identifier in self.registry_identifiers],
            "entity_type": self.entity_type.value,
            "filer_status": self.filer_status,
            "identity_effective_from": self.identity_effective_from,
            "identity_effective_to": self.identity_effective_to,
            "source_evidence_ids": [evidence_id.to_dict() for evidence_id in self.source_evidence_ids],
            "identity_status": self.identity_status.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "IssuerRecord":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            issuer_id=_typed_id(payload.get("issuer_id"), "issuer_id"),  # type: ignore[arg-type]
            legal_name=str(payload.get("legal_name", "")),
            normalized_name=str(payload.get("normalized_name", "")),
            aliases=_strings(payload.get("aliases", ()), "aliases"),
            parent_issuer_id=_typed_id(payload.get("parent_issuer_id"), "parent_issuer_id"),
            ultimate_parent_issuer_id=_typed_id(payload.get("ultimate_parent_issuer_id"), "ultimate_parent_issuer_id"),
            subsidiaries=_typed_ids(payload.get("subsidiaries", ()), "subsidiaries"),
            jurisdiction=str(payload.get("jurisdiction", "")),
            sec_cik=payload.get("sec_cik"),
            lei=payload.get("lei"),
            registry_identifiers=_registry_ids(payload.get("registry_identifiers", ()), "registry_identifiers"),
            entity_type=_enum(EntityType, payload.get("entity_type"), "entity_type"),  # type: ignore[arg-type]
            filer_status=str(payload.get("filer_status", "")),
            identity_effective_from=str(payload.get("identity_effective_from", "")),
            identity_effective_to=payload.get("identity_effective_to"),
            source_evidence_ids=_typed_ids(payload.get("source_evidence_ids", ()), "source_evidence_ids"),
            identity_status=_enum(IdentityStatus, payload.get("identity_status"), "identity_status"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class SecurityRecord:
    security_id: TypedID
    issuer_id: TypedID
    security_type: SecurityType
    symbol: str
    exchange_mic: str
    currency: str
    share_class: str
    voting_rights_note: str
    adr_ratio: str | None
    identifiers: tuple[RegistryIdentifier, ...]
    active_from: str
    active_to: str | None
    primary_listing: bool
    investability_status: InvestabilityStatus
    source_evidence_ids: tuple[TypedID, ...]
    resolution_status: ResolutionStatus
    schema_version: str = SCHEMA_SECURITY_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_SECURITY_V1:
            raise ValueError(f"schema_version must be {SCHEMA_SECURITY_V1}")
        if not isinstance(self.security_id, TypedID) or not isinstance(self.issuer_id, TypedID):
            raise ValueError("security_id and issuer_id must be TypedID values")
        validate_timestamp(self.active_from, "active_from")
        if self.active_to is not None:
            validate_timestamp(self.active_to, "active_to")
            start_dt = datetime.fromisoformat(self.active_from.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(self.active_to.replace("Z", "+00:00"))
            if end_dt <= start_dt:
                raise ValueError("security effective interval must be half-open with end after start")
        for attr, enum_type in (("security_type", SecurityType), ("investability_status", InvestabilityStatus), ("resolution_status", ResolutionStatus)):
            if not isinstance(getattr(self, attr), enum_type):
                object.__setattr__(self, attr, _enum(enum_type, getattr(self, attr), attr))
        if not self.symbol or not self.exchange_mic or not self.currency or not self.share_class or not self.voting_rights_note or not self.source_evidence_ids:
            raise ValueError("security requires symbol, exchange, currency, class, voting note, and source evidence")

    def active_at(self, as_of_utc: str) -> bool:
        return active_during(self.active_from, self.active_to, as_of_utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "security_id": self.security_id.to_dict(),
            "issuer_id": self.issuer_id.to_dict(),
            "security_type": self.security_type.value,
            "symbol": self.symbol,
            "exchange_mic": self.exchange_mic,
            "currency": self.currency,
            "share_class": self.share_class,
            "voting_rights_note": self.voting_rights_note,
            "adr_ratio": self.adr_ratio,
            "identifiers": [identifier.to_dict() for identifier in self.identifiers],
            "active_from": self.active_from,
            "active_to": self.active_to,
            "primary_listing": self.primary_listing,
            "investability_status": self.investability_status.value,
            "source_evidence_ids": [evidence_id.to_dict() for evidence_id in self.source_evidence_ids],
            "resolution_status": self.resolution_status.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SecurityRecord":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            security_id=_typed_id(payload.get("security_id"), "security_id"),  # type: ignore[arg-type]
            issuer_id=_typed_id(payload.get("issuer_id"), "issuer_id"),  # type: ignore[arg-type]
            security_type=_enum(SecurityType, payload.get("security_type"), "security_type"),  # type: ignore[arg-type]
            symbol=str(payload.get("symbol", "")),
            exchange_mic=str(payload.get("exchange_mic", "")),
            currency=str(payload.get("currency", "")),
            share_class=str(payload.get("share_class", "")),
            voting_rights_note=str(payload.get("voting_rights_note", "")),
            adr_ratio=payload.get("adr_ratio"),
            identifiers=_registry_ids(payload.get("identifiers", ()), "identifiers"),
            active_from=str(payload.get("active_from", "")),
            active_to=payload.get("active_to"),
            primary_listing=bool(payload.get("primary_listing")),
            investability_status=_enum(InvestabilityStatus, payload.get("investability_status"), "investability_status"),  # type: ignore[arg-type]
            source_evidence_ids=_typed_ids(payload.get("source_evidence_ids", ()), "source_evidence_ids"),
            resolution_status=_enum(ResolutionStatus, payload.get("resolution_status"), "resolution_status"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class OfficialIdentitySource:
    source_id: TypedID
    legal_name: str
    jurisdiction: str
    sec_cik: str | None
    lei: str | None
    registry_identifiers: tuple[RegistryIdentifier, ...]
    official_domain: str

    def __post_init__(self) -> None:
        if not self.legal_name or not self.jurisdiction or not self.official_domain:
            raise ValueError("official source requires legal_name, jurisdiction, and official_domain")
        if not self.sec_cik and not self.lei and not self.registry_identifiers:
            raise ValueError("official source requires an official identifier")

    def identifier_keys(self) -> set[tuple[str, str, str]]:
        keys = {identifier.key() for identifier in self.registry_identifiers}
        if self.sec_cik:
            keys.add(("SEC_CIK", self.jurisdiction, self.sec_cik))
        if self.lei:
            keys.add(("LEI", self.jurisdiction, self.lei))
        return keys


@dataclass(frozen=True)
class IssuerResolution:
    status: IdentityStatus
    issuer: IssuerRecord | None
    reason_codes: tuple[str, ...]


def _find_active_issuer(records: tuple[IssuerRecord, ...], identifiers: set[tuple[str, str, str]], as_of_utc: str) -> tuple[IssuerRecord, ...]:
    return tuple(
        record
        for record in records
        if record.active_at(as_of_utc)
        and record.identity_status is IdentityStatus.RESOLVED
        and bool(record.identifier_keys() & identifiers)
    )


def resolve_issuer(
    *,
    proposed_name: str,
    official_registry_identifier: RegistryIdentifier | None,
    official_sources: tuple[OfficialIdentitySource, ...],
    issuer_records: tuple[IssuerRecord, ...],
    as_of_utc: str,
) -> IssuerResolution:
    validate_timestamp(as_of_utc, "as_of_utc")
    if not proposed_name:
        return IssuerResolution(IdentityStatus.PROVISIONAL, None, ("missing_name",))
    source_identifiers = set().union(*(source.identifier_keys() for source in official_sources)) if official_sources else set()
    if official_registry_identifier is not None and source_identifiers and official_registry_identifier.key() not in source_identifiers:
        return IssuerResolution(IdentityStatus.CONFLICTED, None, ("conflicting_identifiers",))
    if official_registry_identifier is not None:
        matches = _find_active_issuer(issuer_records, {official_registry_identifier.key()}, as_of_utc)
        if len(matches) == 1:
            return IssuerResolution(IdentityStatus.RESOLVED, matches[0], ("exact_registry_identifier",))
        if len(matches) > 1:
            return IssuerResolution(IdentityStatus.CONFLICTED, None, ("conflicting_identifiers",))
        return IssuerResolution(IdentityStatus.PROVISIONAL, None, ("no_active_registry_match",))

    if len(official_sources) >= 2:
        source_key_sets = [source.identifier_keys() for source in official_sources]
        common = set.intersection(*source_key_sets)
        if not common:
            return IssuerResolution(IdentityStatus.CONFLICTED, None, ("conflicting_identifiers",))
        matches = _find_active_issuer(issuer_records, common, as_of_utc)
        if len(matches) == 1:
            return IssuerResolution(IdentityStatus.RESOLVED, matches[0], ("two_compatible_official_sources",))
        if len(matches) > 1:
            return IssuerResolution(IdentityStatus.CONFLICTED, None, ("conflicting_identifiers",))
        return IssuerResolution(IdentityStatus.PROVISIONAL, None, ("no_active_registry_match",))
    return IssuerResolution(IdentityStatus.PROVISIONAL, None, ("fuzzy_name_not_identity",))


def select_security(
    issuer: IssuerRecord,
    securities: tuple[SecurityRecord, ...],
    *,
    as_of_utc: str,
    symbol: str,
    exchange_mic: str | None = None,
    share_class: str | None = None,
    currency: str | None = None,
) -> SecurityRecord:
    validate_timestamp(as_of_utc, "as_of_utc")
    if issuer.identity_status is not IdentityStatus.RESOLVED:
        raise IdentityResolutionError("issuer conflict blocks security selection")
    if not issuer.active_at(as_of_utc):
        raise IdentityResolutionError("issuer inactive at as_of")
    if not exchange_mic or not share_class or not currency:
        raise IdentityResolutionError("ticker alone is not identity")
    exact = tuple(
        security
        for security in securities
        if security.issuer_id == issuer.issuer_id
        and security.symbol == symbol
        and security.exchange_mic == exchange_mic
        and security.share_class == share_class
        and security.currency == currency
    )
    if not exact:
        raise IdentityResolutionError("no matching security")
    active = tuple(security for security in exact if security.active_at(as_of_utc))
    if not active:
        raise IdentityResolutionError("inactive security at as_of")
    unsupported = tuple(
        security
        for security in active
        if security.security_type.value not in SUPPORTED_SECURITY_TYPES
        or security.investability_status is not InvestabilityStatus.SUPPORTED_EQUITY
    )
    if unsupported:
        raise IdentityResolutionError("unsupported security type or investability")
    conflicted = tuple(security for security in active if security.resolution_status is not ResolutionStatus.RESOLVED)
    if conflicted:
        raise IdentityResolutionError("security conflict blocks selection")
    if len(active) != 1:
        raise IdentityResolutionError("ambiguous security identity")
    return active[0]
