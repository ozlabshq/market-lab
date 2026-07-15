from __future__ import annotations

"""Frozen, zero-network company-intelligence benchmark fixture contracts."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from .agency_contracts import TypedID, canonical_bytes, canonical_json, sha256_hex, strict_json_loads, validate_sha256, validate_timestamp

SCHEMA_OZ_COMPANY_INTEL_BENCH_V1 = "oz-company-intel-bench.v1"
SCHEMA_OZ_COMPANY_INTEL_SOURCE_V1 = "oz-company-intel-source.v1"
OZ_COMPANY_INTEL_BENCH_V1_BYTE_SHA256 = "5dc70527198a81433dbb485b0eedd365fbe6910e39f2091580f4139dddc50313"
SAFETY_MODE_RESEARCH_MOCK_ONLY = "research_mock_only"


class BenchmarkCategory(Enum):
    EXPOSURE = "EXPOSURE"
    DOCUMENT_TRANSCRIPT = "DOCUMENT_TRANSCRIPT"
    MOAT_COMPETITION = "MOAT_COMPETITION"
    CATALYST = "CATALYST"
    AMENDMENT = "AMENDMENT"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    COUNTEREVIDENCE = "COUNTEREVIDENCE"
    DEDUPE_SYNDICATION = "DEDUPE_SYNDICATION"
    POINT_IN_TIME = "POINT_IN_TIME"


class FrozenSourceKind(Enum):
    SEC_FILING = "SEC_FILING"
    SEC_COMPANYFACTS = "SEC_COMPANYFACTS"
    OFFICIAL_TRANSCRIPT = "OFFICIAL_TRANSCRIPT"
    OFFICIAL_PRESS_RELEASE = "OFFICIAL_PRESS_RELEASE"
    SECONDARY_SYNDICATION = "SECONDARY_SYNDICATION"


_ALLOWED_EXPECTED_STATUSES = frozenset({"PROMOTABLE", "VALID", "ACTIVE_AMENDMENT", "NON_PROMOTABLE", "UNKNOWN", "DISPUTED"})
_FORMULAIC_ID_RE = re.compile(r"^(?:case|row|source|evidence)[-_]?\d+$", re.IGNORECASE)
_PLACEHOLDER_REFERENCE_RE = re.compile(r"(?:\*|<[^>]+>|\{[^}]+}|\b(?:n/?a|placeholder|tbd|todo|unknown)\b)", re.IGNORECASE)
_SOURCE_KEYS = frozenset(
    {
        "schema_version",
        "evidence_id",
        "source_kind",
        "publisher",
        "source_locator",
        "source_reference",
        "source_published_at_utc",
        "source_available_at_utc",
        "system_available_at_utc",
        "content_scope",
        "frozen_content",
        "frozen_content_sha256",
        "excerpt",
        "excerpt_sha256",
        "syndication_group",
    }
)
_CASE_KEYS = frozenset(
    {
        "schema_version",
        "case_id",
        "category",
        "title",
        "analysis_cutoff_utc",
        "input_payload",
        "sources",
        "expected_status",
        "expected_reason_codes",
        "expected_selected_evidence_ids",
        "tags",
        "safety_mode",
        "case_digest_sha256",
    }
)


def _dt(value: str, field_name: str) -> datetime:
    validate_timestamp(value, field_name)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_exact_keys(payload: Mapping[str, Any], expected: frozenset[str], name: str) -> None:
    actual = frozenset(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"{name} keys mismatch; missing={missing}, extra={extra}")


def _enum(enum_type: type[Enum], value: Any, field_name: str) -> Enum:
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} contains unknown enum value") from exc


def _strings(value: Any, field_name: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result = tuple(value)
    if any(not isinstance(item, str) or not item for item in result):
        raise ValueError(f"{field_name} must contain non-empty strings")
    if nonempty and not result:
        raise ValueError(f"{field_name} must be non-empty")
    return result


def _require_concrete_reference(value: str, field_name: str) -> None:
    if _PLACEHOLDER_REFERENCE_RE.search(value):
        raise ValueError(f"{field_name} contains placeholder provenance")


def _require_exposure_value(value: Any, field_name: str) -> Decimal:
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError("exposure requires complete numerator and denominator semantics")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name} must be a finite numeric value") from None
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be a finite numeric value")
    return parsed


@dataclass(frozen=True)
class FrozenSourceRecord:
    evidence_id: TypedID
    source_kind: FrozenSourceKind
    publisher: str
    source_locator: str
    source_reference: str
    source_published_at_utc: str
    source_available_at_utc: str
    system_available_at_utc: str
    content_scope: str
    frozen_content: str
    frozen_content_sha256: str
    excerpt: str
    excerpt_sha256: str
    syndication_group: str | None
    schema_version: str = SCHEMA_OZ_COMPANY_INTEL_SOURCE_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_OZ_COMPANY_INTEL_SOURCE_V1:
            raise ValueError(f"schema_version must be {SCHEMA_OZ_COMPANY_INTEL_SOURCE_V1}")
        if not isinstance(self.source_kind, FrozenSourceKind):
            object.__setattr__(self, "source_kind", _enum(FrozenSourceKind, self.source_kind, "source_kind"))
        if self.evidence_id.kind != "evidence" or self.evidence_id.domain != "company_intel" or self.evidence_id.id_schema_version != "v1":
            raise ValueError("evidence_id must be a company_intel evidence TypedID")
        for field_name in ("publisher", "source_locator", "source_reference", "content_scope", "frozen_content", "excerpt"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} is required")
        if _FORMULAIC_ID_RE.fullmatch(self.source_reference):
            raise ValueError("formulaic source_reference is forbidden")
        _require_concrete_reference(self.source_reference, "source_reference")
        _require_concrete_reference(self.source_locator, "source_locator")
        parsed = urlparse(self.source_locator)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("source_locator must be an absolute HTTPS URL")
        if self.source_kind in (FrozenSourceKind.SEC_FILING, FrozenSourceKind.SEC_COMPANYFACTS) and not parsed.hostname.endswith("sec.gov"):  # type: ignore[union-attr]
            raise ValueError("SEC sources must use an sec.gov locator")
        published = _dt(self.source_published_at_utc, "source_published_at_utc")
        available = _dt(self.source_available_at_utc, "source_available_at_utc")
        system = _dt(self.system_available_at_utc, "system_available_at_utc")
        if available < published or system < available:
            raise ValueError("source timestamps must be monotonic")
        if self.content_scope != "frozen_extract":
            raise ValueError("content_scope must be frozen_extract")
        if len(self.frozen_content) < 80:
            raise ValueError("frozen_content is too short to be realistic evidence")
        validate_sha256(self.frozen_content_sha256, "frozen_content_sha256")
        validate_sha256(self.excerpt_sha256, "excerpt_sha256")
        if sha256_hex(self.frozen_content) != self.frozen_content_sha256:
            raise ValueError("frozen_content_sha256 mismatch")
        if self.excerpt not in self.frozen_content or sha256_hex(self.excerpt) != self.excerpt_sha256:
            raise ValueError("excerpt integrity mismatch")
        expected_local_id = f"frozen-content-sha256:{self.frozen_content_sha256}"
        if self.evidence_id.local_id != expected_local_id:
            raise ValueError("evidence_id is not content-addressed to frozen_content")
        if self.source_kind is FrozenSourceKind.SECONDARY_SYNDICATION:
            if not self.syndication_group:
                raise ValueError("secondary syndication requires syndication_group")
        elif self.syndication_group is not None:
            raise ValueError("only secondary syndication may declare syndication_group")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_id": self.evidence_id.to_dict(),
            "source_kind": self.source_kind.value,
            "publisher": self.publisher,
            "source_locator": self.source_locator,
            "source_reference": self.source_reference,
            "source_published_at_utc": self.source_published_at_utc,
            "source_available_at_utc": self.source_available_at_utc,
            "system_available_at_utc": self.system_available_at_utc,
            "content_scope": self.content_scope,
            "frozen_content": self.frozen_content,
            "frozen_content_sha256": self.frozen_content_sha256,
            "excerpt": self.excerpt,
            "excerpt_sha256": self.excerpt_sha256,
            "syndication_group": self.syndication_group,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FrozenSourceRecord":
        _require_exact_keys(payload, _SOURCE_KEYS, "source")
        return cls(
            schema_version=str(payload["schema_version"]),
            evidence_id=TypedID.from_dict(payload["evidence_id"]),
            source_kind=_enum(FrozenSourceKind, payload["source_kind"], "source_kind"),  # type: ignore[arg-type]
            publisher=str(payload["publisher"]),
            source_locator=str(payload["source_locator"]),
            source_reference=str(payload["source_reference"]),
            source_published_at_utc=str(payload["source_published_at_utc"]),
            source_available_at_utc=str(payload["source_available_at_utc"]),
            system_available_at_utc=str(payload["system_available_at_utc"]),
            content_scope=str(payload["content_scope"]),
            frozen_content=str(payload["frozen_content"]),
            frozen_content_sha256=str(payload["frozen_content_sha256"]),
            excerpt=str(payload["excerpt"]),
            excerpt_sha256=str(payload["excerpt_sha256"]),
            syndication_group=payload["syndication_group"],
        )


@dataclass(frozen=True)
class CompanyIntelBenchmarkCase:
    case_id: str
    category: BenchmarkCategory
    title: str
    analysis_cutoff_utc: str
    input_payload_json: str
    sources: tuple[FrozenSourceRecord, ...]
    expected_status: str
    expected_reason_codes: tuple[str, ...]
    expected_selected_evidence_ids: tuple[TypedID, ...]
    tags: tuple[str, ...]
    safety_mode: str = SAFETY_MODE_RESEARCH_MOCK_ONLY
    schema_version: str = SCHEMA_OZ_COMPANY_INTEL_BENCH_V1
    case_digest_sha256: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_OZ_COMPANY_INTEL_BENCH_V1:
            raise ValueError(f"schema_version must be {SCHEMA_OZ_COMPANY_INTEL_BENCH_V1}")
        if not isinstance(self.category, BenchmarkCategory):
            object.__setattr__(self, "category", _enum(BenchmarkCategory, self.category, "category"))
        if not self.case_id or _FORMULAIC_ID_RE.fullmatch(self.case_id):
            raise ValueError("case_id must be descriptive, not formulaic")
        if not self.title or not self.sources or not self.tags:
            raise ValueError("benchmark case requires title, sources, and tags")
        _dt(self.analysis_cutoff_utc, "analysis_cutoff_utc")
        input_payload = strict_json_loads(self.input_payload_json)
        if not isinstance(input_payload, dict) or not input_payload:
            raise ValueError("input_payload must be a non-empty object")
        if canonical_json(input_payload) != self.input_payload_json:
            raise ValueError("input_payload must use canonical JSON")
        if self.expected_status not in _ALLOWED_EXPECTED_STATUSES:
            raise ValueError("unknown expected_status")
        if self.safety_mode != SAFETY_MODE_RESEARCH_MOCK_ONLY:
            raise ValueError("safety_mode must remain research_mock_only")
        expected = sha256_hex(canonical_bytes(self.to_dict(include_digest=False)))
        if self.case_digest_sha256 and self.case_digest_sha256 != expected:
            raise ValueError("case digest mismatch")
        object.__setattr__(self, "case_digest_sha256", expected)

    @property
    def input_payload(self) -> Mapping[str, Any]:
        return strict_json_loads(self.input_payload_json)

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "category": self.category.value,
            "title": self.title,
            "analysis_cutoff_utc": self.analysis_cutoff_utc,
            "input_payload": strict_json_loads(self.input_payload_json),
            "sources": [source.to_dict() for source in self.sources],
            "expected_status": self.expected_status,
            "expected_reason_codes": list(self.expected_reason_codes),
            "expected_selected_evidence_ids": [evidence_id.to_dict() for evidence_id in self.expected_selected_evidence_ids],
            "tags": list(self.tags),
            "safety_mode": self.safety_mode,
        }
        if include_digest:
            payload["case_digest_sha256"] = self.case_digest_sha256
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CompanyIntelBenchmarkCase":
        _require_exact_keys(payload, _CASE_KEYS, "case")
        sources = payload["sources"]
        selected = payload["expected_selected_evidence_ids"]
        if not isinstance(sources, list) or not isinstance(selected, list):
            raise ValueError("sources and expected_selected_evidence_ids must be lists")
        return cls(
            schema_version=str(payload["schema_version"]),
            case_id=str(payload["case_id"]),
            category=_enum(BenchmarkCategory, payload["category"], "category"),  # type: ignore[arg-type]
            title=str(payload["title"]),
            analysis_cutoff_utc=str(payload["analysis_cutoff_utc"]),
            input_payload_json=canonical_json(payload["input_payload"]),
            sources=tuple(FrozenSourceRecord.from_dict(item) for item in sources),
            expected_status=str(payload["expected_status"]),
            expected_reason_codes=_strings(payload["expected_reason_codes"], "expected_reason_codes"),
            expected_selected_evidence_ids=tuple(TypedID.from_dict(item) for item in selected),
            tags=_strings(payload["tags"], "tags", nonempty=True),
            safety_mode=str(payload["safety_mode"]),
            case_digest_sha256=str(payload["case_digest_sha256"]),
        )


def _validate_corpus(cases: tuple[CompanyIntelBenchmarkCase, ...]) -> None:
    if not cases:
        raise ValueError("OzCompanyIntelBench-v1 corpus is empty")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate benchmark case_id")
    categories = {case.category for case in cases}
    if categories != set(BenchmarkCategory):
        missing = sorted(category.value for category in set(BenchmarkCategory) - categories)
        raise ValueError(f"benchmark category coverage is incomplete: {missing}")

    for case in cases:
        if case.category.value.lower() not in case.tags:
            raise ValueError(f"{case.case_id} is missing its category tag")
        source_ids = tuple(source.evidence_id for source in case.sources)
        selected_ids = case.expected_selected_evidence_ids
        if len(set(selected_ids)) != len(selected_ids) or any(item not in source_ids for item in selected_ids):
            raise ValueError(f"{case.case_id} selected evidence is not a unique source subset")
        duplicates = len(set(source_ids)) != len(source_ids)
        if duplicates:
            if case.category is not BenchmarkCategory.DEDUPE_SYNDICATION:
                raise ValueError(f"{case.case_id} duplicates evidence outside the dedupe case")
            if case.expected_status != "NON_PROMOTABLE" or "duplicate_or_syndicated_evidence" not in case.expected_reason_codes or selected_ids:
                raise ValueError("duplicate or syndicated evidence cannot promote")
        elif case.category is BenchmarkCategory.DEDUPE_SYNDICATION:
            raise ValueError("dedupe case must contain content-identical evidence")

        cutoff = _dt(case.analysis_cutoff_utc, "analysis_cutoff_utc")
        late_sources = tuple(source for source in case.sources if _dt(source.system_available_at_utc, "system_available_at_utc") > cutoff)
        if case.category is BenchmarkCategory.POINT_IN_TIME:
            if not late_sources or case.expected_status != "NON_PROMOTABLE" or "evidence_after_analysis_cutoff" not in case.expected_reason_codes:
                raise ValueError("point-in-time case must fail closed on late evidence")
        elif late_sources:
            raise ValueError(f"{case.case_id} contains unexpected post-cutoff evidence")

        if case.expected_status in {"PROMOTABLE", "VALID", "ACTIVE_AMENDMENT"} and not selected_ids:
            raise ValueError(f"{case.case_id} promotable outcome requires selected evidence")
        if case.category is BenchmarkCategory.EXPOSURE:
            if "numerator_value" not in case.input_payload or "denominator_value" not in case.input_payload:
                raise ValueError("exposure requires complete numerator and denominator semantics")
            numerator = _require_exposure_value(case.input_payload["numerator_value"], "numerator_value")
            denominator = _require_exposure_value(case.input_payload["denominator_value"], "denominator_value")
            if numerator < 0 or denominator <= 0 or numerator > denominator:
                raise ValueError("exposure numerator and denominator have invalid bounds")
        if case.category is BenchmarkCategory.UNKNOWN and (
            case.expected_status != "UNKNOWN" or "missing_quantified_exposure" not in case.expected_reason_codes
        ):
            raise ValueError("UNKNOWN case must preserve missing quantified exposure")
        if case.category is BenchmarkCategory.MISMATCH:
            if case.expected_status != "NON_PROMOTABLE" or selected_ids:
                raise ValueError("mismatch case must be non-promotable and select no evidence")
            if not any(reason.endswith("_mismatch") for reason in case.expected_reason_codes):
                raise ValueError("mismatch case must declare an explicit mismatch reason")
        if case.category is BenchmarkCategory.COUNTEREVIDENCE and (
            case.expected_status != "DISPUTED" or "refuting_counterevidence" not in case.expected_reason_codes
        ):
            raise ValueError("counterevidence case must be disputed")
        if case.category is BenchmarkCategory.COUNTEREVIDENCE and selected_ids:
            raise ValueError("disputed counterevidence cannot select refuting evidence")
        if case.category is BenchmarkCategory.AMENDMENT:
            if len(case.sources) != 2 or case.expected_status != "ACTIVE_AMENDMENT":
                raise ValueError("amendment case must identify one original and one active amendment source")
            payload = case.input_payload
            original_reference = payload.get("original_reference")
            revision_reference = payload.get("revision_reference")
            if not isinstance(original_reference, str) or not isinstance(revision_reference, str):
                raise ValueError("amendment references must be non-empty strings")
            if payload.get("revision") not in {"AMENDMENT", "CORRECTION"} or payload.get("revision_relation") not in {"AMENDS", "CORRECTS"}:
                raise ValueError("amendment input must declare amendment or correction source-chain semantics")
            _require_concrete_reference(original_reference, "original_reference")
            _require_concrete_reference(revision_reference, "revision_reference")
            original_sources = tuple(source for source in case.sources if source.source_reference == original_reference)
            revision_sources = tuple(source for source in case.sources if source.source_reference == revision_reference)
            if original_reference == revision_reference or len(original_sources) != 1 or len(revision_sources) != 1:
                raise ValueError("amendment input references must match source records exactly once")
            original_source = original_sources[0]
            revision_source = revision_sources[0]
            if (
                _dt(revision_source.source_published_at_utc, "source_published_at_utc")
                <= _dt(original_source.source_published_at_utc, "source_published_at_utc")
                or _dt(revision_source.system_available_at_utc, "system_available_at_utc")
                <= _dt(original_source.system_available_at_utc, "system_available_at_utc")
                or selected_ids != (revision_source.evidence_id,)
            ):
                raise ValueError("amendment must select only the later amendment source")
            if "superseded_original" not in case.expected_reason_codes:
                raise ValueError("amendment must declare superseded_original semantics")


def load_oz_company_intel_bench(path: Path, *, enforce_frozen_digest: bool = True) -> tuple[CompanyIntelBenchmarkCase, ...]:
    raw = Path(path).read_bytes()
    if enforce_frozen_digest and sha256_hex(raw) != OZ_COMPANY_INTEL_BENCH_V1_BYTE_SHA256:
        raise ValueError("OzCompanyIntelBench-v1 frozen byte digest mismatch")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("OzCompanyIntelBench-v1 must be UTF-8") from exc
    rows: list[CompanyIntelBenchmarkCase] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        payload = strict_json_loads(line)
        if not isinstance(payload, dict):
            raise ValueError(f"benchmark line {line_number} must be an object")
        if canonical_json(payload) != line:
            raise ValueError(f"benchmark line {line_number} is not canonical JSON")
        rows.append(CompanyIntelBenchmarkCase.from_dict(payload))
    cases = tuple(rows)
    _validate_corpus(cases)
    return cases
