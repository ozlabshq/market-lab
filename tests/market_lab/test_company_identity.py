from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from market_lab.agency_contracts import TypedID, canonical_json, strict_json_loads
from market_lab.company_identity import (
    EntityType,
    IdentityResolutionError,
    IdentityStatus,
    InvestabilityStatus,
    IssuerRecord,
    OfficialIdentitySource,
    RegistryIdentifier,
    ResolutionStatus,
    SecurityRecord,
    SecurityType,
    active_during,
    resolve_issuer,
    select_security,
)

NOW = "2026-07-14T08:00:00Z"


def tid(kind: str, local_id: str) -> TypedID:
    return TypedID(kind=kind, domain="agency", id_schema_version="v1", local_id=local_id)


def reg(value: str, scheme: str = "SEC_CIK") -> RegistryIdentifier:
    return RegistryIdentifier(scheme=scheme, value=value, jurisdiction="US")


def issuer(local_id: str = "issuer-alpha", *, status: IdentityStatus = IdentityStatus.RESOLVED, sec_cik: str | None = "0001000001") -> IssuerRecord:
    return IssuerRecord(
        issuer_id=tid("issuer", local_id),
        legal_name="Alpha Grid Holdings Inc.",
        normalized_name="alpha grid holdings inc",
        aliases=("Alpha Grid",),
        parent_issuer_id=None,
        ultimate_parent_issuer_id=None,
        subsidiaries=(),
        jurisdiction="US",
        sec_cik=sec_cik,
        lei=None,
        registry_identifiers=(reg(sec_cik),) if sec_cik else (),
        entity_type=EntityType.OPERATING_COMPANY,
        filer_status="SEC_FILER",
        identity_effective_from="2020-01-01T00:00:00Z",
        identity_effective_to=None,
        source_evidence_ids=(tid("evidence", "issuer-alpha-official"),),
        identity_status=status,
    )


def security(
    local_id: str = "security-alpha",
    *,
    symbol: str = "AGRD",
    share_class: str = "A",
    security_type: SecurityType = SecurityType.COMMON,
    active_from: str = "2024-01-01T00:00:00Z",
    active_to: str | None = None,
    issuer_id: TypedID | None = None,
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
    investability: InvestabilityStatus = InvestabilityStatus.SUPPORTED_EQUITY,
) -> SecurityRecord:
    issuer_id = issuer_id or tid("issuer", "issuer-alpha")
    return SecurityRecord(
        security_id=tid("security", local_id),
        issuer_id=issuer_id,
        security_type=security_type,
        symbol=symbol,
        exchange_mic="XNYS",
        currency="USD",
        share_class=share_class,
        voting_rights_note="one share one vote",
        adr_ratio=None,
        identifiers=(RegistryIdentifier(scheme="EXCHANGE_SYMBOL", value=f"XNYS:{symbol}:{share_class}", jurisdiction="US"),),
        active_from=active_from,
        active_to=active_to,
        primary_listing=True,
        investability_status=investability,
        source_evidence_ids=(tid("evidence", f"{local_id}-official"),),
        resolution_status=status,
    )


def official(local_id: str, *, cik: str = "0001000001", registry_value: str = "0001000001") -> OfficialIdentitySource:
    return OfficialIdentitySource(
        source_id=tid("evidence", local_id),
        legal_name="Alpha Grid Holdings Inc.",
        jurisdiction="US",
        sec_cik=cik,
        lei=None,
        registry_identifiers=(reg(registry_value),),
        official_domain="sec.gov",
    )


def test_issuer_and_security_contract_round_trip_freeze_and_boundary_times() -> None:
    record = issuer()
    sec = security(active_from="2024-01-01T00:00:00Z", active_to="2026-07-14T08:00:00Z")
    assert IssuerRecord.from_dict(strict_json_loads(canonical_json(record.to_dict()))) == record
    assert SecurityRecord.from_dict(strict_json_loads(canonical_json(sec.to_dict()))) == sec
    assert active_during(sec.active_from, sec.active_to, "2023-12-31T23:59:59Z") is False
    assert active_during(sec.active_from, sec.active_to, "2024-01-01T00:00:00Z") is True
    assert active_during(sec.active_from, sec.active_to, "2026-07-14T07:59:59Z") is True
    assert active_during(sec.active_from, sec.active_to, "2026-07-14T08:00:00Z") is False
    with pytest.raises(FrozenInstanceError):
        record.legal_name = "Mutated"  # type: ignore[misc]


def test_schema_enum_parent_and_interval_rejection() -> None:
    payload = issuer().to_dict()
    payload["schema_version"] = "mlab-issuer.v2"
    with pytest.raises(ValueError, match="schema_version"):
        IssuerRecord.from_dict(payload)
    payload = security().to_dict()
    payload["security_type"] = "TOKEN"
    with pytest.raises(ValueError, match="security_type"):
        SecurityRecord.from_dict(payload)
    with pytest.raises(ValueError, match="parent"):
        IssuerRecord.from_dict({**issuer().to_dict(), "parent_issuer_id": issuer().issuer_id.to_dict()})
    with pytest.raises(ValueError, match="effective interval"):
        IssuerRecord.from_dict({**issuer().to_dict(), "identity_effective_to": "2019-01-01T00:00:00Z"})


def test_issuer_resolution_requires_exact_or_two_compatible_official_sources_and_blocks_conflicts() -> None:
    record = issuer()
    resolved = resolve_issuer(
        proposed_name="Alpha Grid",
        official_registry_identifier=reg("0001000001"),
        official_sources=(),
        issuer_records=(record,),
        as_of_utc=NOW,
    )
    assert resolved.issuer == record
    assert resolved.status is IdentityStatus.RESOLVED

    resolved_two_sources = resolve_issuer(
        proposed_name="Alpha Grid fuzzy",
        official_registry_identifier=None,
        official_sources=(official("source-a"), official("source-b")),
        issuer_records=(record,),
        as_of_utc=NOW,
    )
    assert resolved_two_sources.issuer == record

    fuzzy_only = resolve_issuer(
        proposed_name="Alpha Grid Holdings Inc.",
        official_registry_identifier=None,
        official_sources=(),
        issuer_records=(record,),
        as_of_utc=NOW,
    )
    assert fuzzy_only.status is IdentityStatus.PROVISIONAL
    assert fuzzy_only.issuer is None

    conflicted = resolve_issuer(
        proposed_name="Alpha Grid",
        official_registry_identifier=None,
        official_sources=(official("source-a", cik="0001000001"), official("source-b", cik="0002000002", registry_value="0002000002")),
        issuer_records=(record,),
        as_of_utc=NOW,
    )
    assert conflicted.status is IdentityStatus.CONFLICTED
    assert conflicted.issuer is None


def test_future_identity_records_do_not_resolve_historically() -> None:
    future = IssuerRecord.from_dict({**issuer("future-issuer").to_dict(), "identity_effective_from": "2027-01-01T00:00:00Z"})
    result = resolve_issuer(
        proposed_name="Alpha Grid",
        official_registry_identifier=reg("0001000001"),
        official_sources=(),
        issuer_records=(future,),
        as_of_utc=NOW,
    )
    assert result.status is IdentityStatus.PROVISIONAL
    assert result.issuer is None


def test_security_selection_exact_identity_ambiguity_ticker_reuse_and_unsupported_types() -> None:
    record = issuer()
    selected = select_security(record, (security(),), as_of_utc=NOW, symbol="AGRD", exchange_mic="XNYS", share_class="A", currency="USD")
    assert selected.security_id == tid("security", "security-alpha")

    with pytest.raises(IdentityResolutionError, match="ticker alone"):
        select_security(record, (security(),), as_of_utc=NOW, symbol="AGRD")
    with pytest.raises(IdentityResolutionError, match="ambiguous"):
        select_security(
            record,
            (security("a1"), security("a2")),
            as_of_utc=NOW,
            symbol="AGRD",
            exchange_mic="XNYS",
            share_class="A",
            currency="USD",
        )
    with pytest.raises(IdentityResolutionError, match="unsupported"):
        select_security(
            record,
            (security("preferred", security_type=SecurityType.PREFERRED),),
            as_of_utc=NOW,
            symbol="AGRD",
            exchange_mic="XNYS",
            share_class="A",
            currency="USD",
        )
    with pytest.raises(IdentityResolutionError, match="inactive"):
        select_security(
            record,
            (security("old", symbol="OLD", active_to="2025-01-01T00:00:00Z"),),
            as_of_utc=NOW,
            symbol="OLD",
            exchange_mic="XNYS",
            share_class="A",
            currency="USD",
        )


def test_security_selection_blocks_conflicted_issuer_and_resolution_status() -> None:
    with pytest.raises(IdentityResolutionError, match="issuer conflict"):
        select_security(issuer(status=IdentityStatus.CONFLICTED), (security(),), as_of_utc=NOW, symbol="AGRD", exchange_mic="XNYS", share_class="A", currency="USD")
    with pytest.raises(IdentityResolutionError, match="security conflict"):
        select_security(issuer(), (security(status=ResolutionStatus.CONFLICTED),), as_of_utc=NOW, symbol="AGRD", exchange_mic="XNYS", share_class="A", currency="USD")
