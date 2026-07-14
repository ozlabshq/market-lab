from __future__ import annotations

"""Web-evidence contracts and shared schemas.

This module intentionally stays provider-agnostic. It defines typed request/response
models, provider protocols, and registry helpers used by the web-evidence runner and
CLI.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
import ipaddress
import os
import re
import socket
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

SCHEMA_EVIDENCE_V2 = "mlab-evidence.v2"
SCHEMA_SNAPSHOT_V1 = "web-snapshot.v1"
PROVIDER_FAMILY_WEB_INDEX = "web_index"
PROVIDER_FAMILY_METASEARCH = "metasearch"
PROVIDER_FAMILY_DIRECT_FETCH = "direct_fetch"
PROVIDER_FAMILY_EXTRACTOR = "extractor"
PROVIDER_FAMILY_DOMAIN_API = "domain_api"

EVIDENCE_STANCES = {
    "supports",
    "refutes",
    "qualifies",
    "context",
}

FETCH_STATUSES = {
    "success",
    "not_found",
    "blocked",
    "rate_limited",
    "auth_required",
    "paywall",
    "robots_disallowed",
    "unsafe_url",
    "too_large",
    "unsupported_media",
    "transport_error",
    "extraction_failed",
    "invalid_request",
    "bad_data",
    "unconfigured",
}

PROVIDER_STATUSES = {
    "ready",
    "degraded",
    "rate_limited",
    "unconfigured",
    "unavailable",
    "disabled",
}


def utcnow() -> str:
    """UTC timestamp in RFC3339 compact form used for durable records."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_hex(payload: bytes | str, *, encode: str = "utf-8") -> str:
    if isinstance(payload, str):
        payload = payload.encode(encode)
    return hashlib.sha256(payload).hexdigest()


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(payload: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json(payload))


def audit_hash_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(event)
    payload.pop("event_hash", None)
    payload.pop("event_id", None)
    payload.pop("__raw_line", None)
    return payload


def request_id_for(namespace: str, request_body: Mapping[str, Any] | str) -> str:
    payload = request_body if isinstance(request_body, str) else canonical_json(dict(request_body))
    return f"{namespace}-{sha256_hex(payload.encode('utf-8'))[:16]}"


def _normalize_port(host_port: int | None) -> int | None:
    if host_port is None:
        return None
    return int(host_port)


def validate_fetch_url(url: str, *, enforce_dns: bool = True, allow_private: bool = False) -> str:
    """Validate a URL for outbound raw fetch.

    Returns the normalized URL (without fragments) when safe.
    Raises ValueError for unsafe/malformed inputs.
    """

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("unsupported url scheme")
    if not parsed.netloc:
        raise ValueError("url missing host")
    if parsed.username or parsed.password:
        raise ValueError("url credentials are forbidden")
    if parsed.fragment:
        raise ValueError("url fragment is not allowed")

    port = _normalize_port(parsed.port)
    if port is not None and port not in {80, 443}:
        raise ValueError("non-standard ports are not allowed")

    host = parsed.hostname or ""
    if not host:
        raise ValueError("url missing host")

    # Basic host guardrails.
    lowered = host.lower()
    if lowered in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("private or loopback destination blocked")

    if enforce_dns:
        try:
            infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
        except OSError as exc:
            raise ValueError(f"dns resolution failed: {exc}") from exc

        resolved: list[ipaddress._BaseAddress] = []
        for fam, _, _, _, sockaddr in infos:
            ip_txt = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_txt)
            except ValueError:
                continue
            resolved.append(ip)
            if not allow_private and any(
                (
                    ip.is_private,
                    ip.is_loopback,
                    ip.is_link_local,
                    ip.is_reserved,
                    ip.is_multicast,
                    ip.is_unspecified,
                    ip.is_global is False,
                )
            ):
                raise ValueError("resolved destination is private/restricted")

        if not resolved:
            raise ValueError("dns resolution produced no usable addresses")

    normalized = parsed._replace(fragment="", query=re.sub(r"\s+", " ", parsed.query).strip()).geturl()
    return normalized


def classify_url_safety(url: str, *, enforce_dns: bool = True, allow_private: bool = False) -> tuple[bool, str, str]:
    try:
        return True, validate_fetch_url(url, enforce_dns=enforce_dns, allow_private=allow_private), ""
    except Exception as exc:
        return False, url, str(exc)


def canonicalize_url_for_dedupe(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    scheme = (parsed.scheme or "https").lower()
    port = parsed.port
    netloc = host
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{host}:{port}"
    path = parsed.path or "/"
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    query = urlencode(sorted(query_pairs), doseq=True)
    return urlunparse((scheme, netloc, path, "", query, ""))


def origin_cluster_id_for(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    parts = host.split(".")
    if len(parts) > 2:
        host = ".".join(parts[-2:])
    return f"origin-{sha256_hex(host)[:12]}"


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    provider_family: str
    implementation_version: str
    capabilities: list[str]
    configuration_fields: list[str]
    requires_managed_key: bool
    supports_keyless: bool
    cost_model: str
    retention_note: str
    regions: list[str] = field(default_factory=list)
    self_hosted: bool = False
    rate_policy: str = ""


@dataclass(frozen=True)
class ProviderHealth:
    provider_id: str
    timestamp: str
    status: str
    capabilities_ready: list[str]
    missing_configuration: list[str] = field(default_factory=list)
    reason_code: str = ""
    safe_message: str = ""
    latency_ms: int = 0
    retry_after_utc: str | None = None
    observed_endpoint: str | None = None

    def is_ready(self) -> bool:
        return self.status == "ready"


@dataclass(frozen=True)
class CostEstimate:
    provider_id: str
    currency: str
    micros: int
    requires_hard_budget: bool = False


@dataclass(frozen=True)
class SearchRequest:
    request_id: str
    query_id: str
    run_id: str
    claim_ids: list[str]
    exact_query: str
    lane: str
    as_of: str = ""
    language: str = "en"
    country: str = "US"
    domains_include: list[str] = field(default_factory=list)
    domains_exclude: list[str] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    max_results: int = 8
    timeout_seconds: int = 20
    budget_reservation_id: str | None = None
    query_strategy: str = "exact_claim"
    fallback_for_query_id: str | None = None


@dataclass(frozen=True)
class SearchHit:
    provider_id: str
    provider_result_id: str
    rank: int
    url: str
    title: str
    snippet: str
    published_hint: str | None = None
    raw_response_snapshot_id: str | None = None
    raw_result_hash: str | None = None
    discovered_at: str = ""
    eligible_as_evidence: bool = False

    def __post_init__(self) -> None:
        # Hard invariant for version 1.
        if self.eligible_as_evidence:
            raise ValueError("SearchHit.eligible_as_evidence must be false")


@dataclass(frozen=True)
class SearchResponse:
    request_id: str
    query_id: str
    provider_id: str
    status: str
    hits: list[SearchHit]
    result_count: int
    latency_ms: int
    typed_error: str = ""
    snapshot_id: str | None = None
    raw_payload_hash: str | None = None


@dataclass(frozen=True)
class FetchRequest:
    request_id: str
    run_id: str
    claim_ids: list[str]
    query_ids: list[str]
    url: str
    expected_source_type: str = "web_document"
    as_of: str = ""
    timeout_seconds: int = 45
    max_bytes: int = 20 * 1024 * 1024
    max_redirects: int = 5
    allow_third_party_transform: bool = True
    budget_reservation_id: str | None = None


@dataclass(frozen=True)
class FetchResponse:
    request_id: str
    run_id: str
    claim_ids: list[str]
    query_ids: list[str]
    provider_id: str
    provider_call_id: str
    status: str
    snapshot_id: str | None = None
    canonical_url: str = ""
    redirect_chain: list[str] = field(default_factory=list)
    content_type: str = ""
    byte_length: int = 0
    retry_after_utc: str | None = None
    typed_error: str = ""
    latency_ms: int = 0
    charged_cost: int | None = None
    payload: bytes | None = None
    response_headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DomainLookupRequest:
    request_id: str
    run_id: str
    claim_ids: list[str]
    identifier_type: str
    identifier_value: str
    timeout_seconds: int = 20
    as_of: str = ""


@dataclass(frozen=True)
class DomainLookupResponse:
    request_id: str
    run_id: str
    provider_id: str
    identifier_type: str
    identifier_value: str
    status: str
    canonical_url: str
    payload: dict[str, Any] | None = None
    typed_error: str = ""
    latency_ms: int = 0


@dataclass(frozen=True)
class EvidenceSegment:
    segment_id: str
    snapshot_id: str
    locator_type: str
    locator: str
    verbatim_excerpt_or_value: str
    segment_sha256: str
    units: str = ""
    scope: str = ""
    geography: str = ""


@dataclass(frozen=True)
class EvidenceRecord:
    schema_version: str
    evidence_id: str
    run_id: str
    claim_id: str
    segment_id: str
    snapshot_id: str
    stance: str
    source_type: str = ""
    source_tier: str = ""
    source_quality_reason: str = ""
    publisher: str = ""
    issuing_authority: str = ""
    title: str = ""
    canonical_url: str = ""
    document_identifier: str = ""
    publication_time: str = ""
    effective_time: str = ""
    reference_period: str = ""
    retrieved_at_utc: str = ""
    exact_locator: str = ""
    verbatim_excerpt_or_value: str = ""
    query_ids: list[str] = field(default_factory=list)
    provider_id: str = ""
    provider_call_id: str = ""
    source_lineage: str = ""
    origin_cluster_id: str = ""
    version: str = ""
    amendment: str = ""
    vintage: str = ""
    superseded_by: str = ""
    claim_temporal_fit: str = ""
    is_primary_for_claim: bool = False
    independence_group: str = ""
    license_terms_note: str = ""
    robots_status: str = ""
    paywall_status: str = ""
    edge_evaluator: str = ""
    evaluator_version: str = ""
    confidence: float = 1.0


class Provider(Protocol):
    provider_id: str

    def spec(self) -> ProviderSpec:
        ...

    def health(self, context: Mapping[str, Any] | None = None) -> ProviderHealth:
        ...

    def estimate_cost(self, request: SearchRequest | FetchRequest | DomainLookupRequest) -> CostEstimate:
        ...


class SearchProvider(Protocol):
    def search(self, request: SearchRequest, context: Mapping[str, Any] | None = None) -> SearchResponse:
        ...


class FetchProvider(Protocol):
    def fetch(self, request: FetchRequest, context: Mapping[str, Any] | None = None) -> FetchResponse:
        ...


class DomainProvider(Protocol):
    def lookup(self, request: DomainLookupRequest, context: Mapping[str, Any] | None = None) -> DomainLookupResponse:
        ...


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Any] = {}

    def register(self, provider: Provider) -> None:
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> Provider:
        return self._providers[provider_id]

    def items(self):
        return self._providers.items()

    def providers(self) -> list[Provider]:
        return list(self._providers.values())

    def ids(self) -> list[str]:
        return list(self._providers.keys())

    def by_capability(self, capability: str) -> list[Provider]:
        found: list[Provider] = []
        for provider in self._providers.values():
            has_capability = capability in getattr(provider.spec(), "capabilities", [])
            if has_capability:
                found.append(provider)
        return found


@dataclass(frozen=True)
class BudgetProfile:
    profile: str
    max_paid_provider_cost_usd: float = 0.0
    max_total_paid_cost_usd: float = 0.0
    max_queries_per_claim: int = 3
    max_fetches_per_claim: int = 4
    max_results_per_query: int = 8
    max_provider_retries: int = 2
    search_timeout_seconds: int = 20
    fetch_timeout_seconds: int = 45
    max_redirects: int = 5
    max_bytes_per_fetch: int = 20 * 1024 * 1024
    max_total_fetch_bytes: int = 100 * 1024 * 1024


BUDGET_PROFILES = {
    "keyless_standard": BudgetProfile(
        profile="keyless_standard",
        max_paid_provider_cost_usd=0.0,
        max_total_paid_cost_usd=0.0,
        max_queries_per_claim=3,
        max_fetches_per_claim=4,
        max_results_per_query=8,
    ),
    "frozen_replay": BudgetProfile(
        profile="frozen_replay",
        max_paid_provider_cost_usd=0.0,
        max_total_paid_cost_usd=0.0,
        max_queries_per_claim=2,
        max_fetches_per_claim=2,
        max_results_per_query=5,
    ),
}


def load_budget_profile(profile: str) -> BudgetProfile:
    if profile not in BUDGET_PROFILES:
        raise ValueError(f"Unknown web evidence budget profile: {profile}")
    return BUDGET_PROFILES[profile]


def to_dict_record(record: Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    if hasattr(record, "__dict__"):
        return asdict(record)
    raise TypeError(f"unsupported record type: {type(record)!r}")


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", (query or "").strip())


def make_evidence_id(run_id: str, claim_id: str, segment_id: str, stance: str) -> str:
    return f"ev-{sha256_hex(f'{run_id}:{claim_id}:{segment_id}:{stance}')[:16]}"


__all__ = [
    "SCHEMA_EVIDENCE_V2",
    "SCHEMA_SNAPSHOT_V1",
    "ProviderSpec",
    "ProviderHealth",
    "CostEstimate",
    "SearchRequest",
    "SearchHit",
    "SearchResponse",
    "FetchRequest",
    "FetchResponse",
    "DomainLookupRequest",
    "DomainLookupResponse",
    "EvidenceSegment",
    "EvidenceRecord",
    "BudgetProfile",
    "BUDGET_PROFILES",
    "load_budget_profile",
    "Provider",
    "SearchProvider",
    "FetchProvider",
    "DomainProvider",
    "ProviderRegistry",
    "validate_fetch_url",
    "request_id_for",
    "sha256_hex",
    "canonical_json",
    "canonical_hash",
    "audit_hash_payload",
    "classify_url_safety",
    "canonicalize_url_for_dedupe",
    "origin_cluster_id_for",
    "make_evidence_id",
    "to_dict_record",
    "normalize_query",
    "utcnow",
    "EVIDENCE_STANCES",
    "FETCH_STATUSES",
    "PROVIDER_STATUSES",
    "PROVIDER_FAMILY_WEB_INDEX",
    "PROVIDER_FAMILY_METASEARCH",
    "PROVIDER_FAMILY_DIRECT_FETCH",
    "PROVIDER_FAMILY_EXTRACTOR",
    "PROVIDER_FAMILY_DOMAIN_API",
]
