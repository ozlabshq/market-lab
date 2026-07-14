from __future__ import annotations

"""Immutable normalized company document and transcript citation contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from .agency_contracts import TypedID, canonical_bytes, sha256_hex, validate_sha256, validate_timestamp

SCHEMA_COMPANY_DOCUMENT_PROVENANCE_V1 = "mlab-company-document-provenance.v1"
SCHEMA_COMPANY_DOCUMENT_V1 = "mlab-company-document.v1"
SCHEMA_COMPANY_SEGMENT_V1 = "mlab-company-segment.v1"
SCHEMA_COMPANY_CITATION_V1 = "mlab-company-citation.v1"
SCHEMA_COMPANY_DOCUMENT_VALIDATION_V1 = "mlab-company-document-validation.v1"


class DocumentKind(Enum):
    ANNUAL_REPORT = "ANNUAL_REPORT"
    QUARTERLY_REPORT = "QUARTERLY_REPORT"
    EARNINGS_TRANSCRIPT = "EARNINGS_TRANSCRIPT"
    PRESS_RELEASE = "PRESS_RELEASE"
    OTHER_OFFICIAL = "OTHER_OFFICIAL"


class RevisionKind(Enum):
    ORIGINAL = "ORIGINAL"
    AMENDMENT = "AMENDMENT"
    CORRECTION = "CORRECTION"


class RevisionRelation(Enum):
    AMENDS = "AMENDS"
    CORRECTS = "CORRECTS"


def _dt(value: str) -> datetime:
    validate_timestamp(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


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


def _require_kind(value: TypedID | None, expected_kind: str, field_name: str) -> None:
    if not isinstance(value, TypedID):
        raise ValueError(f"{field_name} must be a TypedID")
    if value.kind != expected_kind:
        raise ValueError(f"{field_name} must be a {expected_kind} TypedID")


def _require_kinds(values: tuple[TypedID, ...], expected_kind: str, field_name: str) -> None:
    for value in values:
        _require_kind(value, expected_kind, field_name)


def _require_sequence(value: Any, name: str) -> tuple[Any, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{name} must be a list")
    return tuple(value)


def _id_key(value: TypedID) -> tuple[str, str, str]:
    return value.identity_key()


def _same_period(left: "CompanyDocumentProvenance", right: "CompanyDocumentProvenance") -> bool:
    return left.period_start_utc == right.period_start_utc and left.period_end_utc == right.period_end_utc


@dataclass(frozen=True)
class CompanyDocumentProvenance:
    issuer_id: TypedID
    document_kind: DocumentKind
    source_locator: str
    source_published_at_utc: str
    system_available_at_utc: str
    period_start_utc: str
    period_end_utc: str
    source_byte_sha256: str
    normalized_content_sha256: str
    source_evidence_ids: tuple[TypedID, ...]
    schema_version: str = SCHEMA_COMPANY_DOCUMENT_PROVENANCE_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_COMPANY_DOCUMENT_PROVENANCE_V1:
            raise ValueError(f"schema_version must be {SCHEMA_COMPANY_DOCUMENT_PROVENANCE_V1}")
        _require_kind(self.issuer_id, "issuer", "issuer_id")
        if not isinstance(self.document_kind, DocumentKind):
            object.__setattr__(self, "document_kind", _enum(DocumentKind, self.document_kind, "document_kind"))
        if not self.source_locator or not self.source_evidence_ids:
            raise ValueError("source locator and source evidence are required")
        _require_kinds(self.source_evidence_ids, "evidence", "source_evidence_ids")
        validate_timestamp(self.source_published_at_utc, "source_published_at_utc")
        validate_timestamp(self.system_available_at_utc, "system_available_at_utc")
        validate_timestamp(self.period_start_utc, "period_start_utc")
        validate_timestamp(self.period_end_utc, "period_end_utc")
        if _dt(self.period_end_utc) <= _dt(self.period_start_utc):
            raise ValueError("reporting period must be half-open with end after start")
        if _dt(self.system_available_at_utc) < _dt(self.source_published_at_utc):
            raise ValueError("source published timestamp cannot be after system availability")
        validate_sha256(self.source_byte_sha256, "source_byte_sha256")
        validate_sha256(self.normalized_content_sha256, "normalized_content_sha256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "issuer_id": self.issuer_id.to_dict(),
            "document_kind": self.document_kind.value,
            "source_locator": self.source_locator,
            "source_published_at_utc": self.source_published_at_utc,
            "system_available_at_utc": self.system_available_at_utc,
            "period_start_utc": self.period_start_utc,
            "period_end_utc": self.period_end_utc,
            "source_byte_sha256": self.source_byte_sha256,
            "normalized_content_sha256": self.normalized_content_sha256,
            "source_evidence_ids": [evidence_id.to_dict() for evidence_id in self.source_evidence_ids],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CompanyDocumentProvenance":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            issuer_id=_typed_id(payload.get("issuer_id"), "issuer_id"),  # type: ignore[arg-type]
            document_kind=_enum(DocumentKind, payload.get("document_kind"), "document_kind"),  # type: ignore[arg-type]
            source_locator=str(payload.get("source_locator", "")),
            source_published_at_utc=str(payload.get("source_published_at_utc", "")),
            system_available_at_utc=str(payload.get("system_available_at_utc", "")),
            period_start_utc=str(payload.get("period_start_utc", "")),
            period_end_utc=str(payload.get("period_end_utc", "")),
            source_byte_sha256=str(payload.get("source_byte_sha256", "")),
            normalized_content_sha256=str(payload.get("normalized_content_sha256", "")),
            source_evidence_ids=_typed_ids(payload.get("source_evidence_ids", ()), "source_evidence_ids"),
        )


@dataclass(frozen=True)
class NormalizedCompanyDocument:
    document_id: TypedID
    provenance: CompanyDocumentProvenance
    revision: RevisionKind
    revision_target_document_id: TypedID | None
    revision_relation: RevisionRelation | None
    supersedes_document_id: TypedID | None
    normalized_text: str
    document_digest_sha256: str = ""
    schema_version: str = SCHEMA_COMPANY_DOCUMENT_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_COMPANY_DOCUMENT_V1:
            raise ValueError(f"schema_version must be {SCHEMA_COMPANY_DOCUMENT_V1}")
        _require_kind(self.document_id, "company_document", "document_id")
        if not isinstance(self.provenance, CompanyDocumentProvenance):
            raise ValueError("provenance must be a CompanyDocumentProvenance")
        if self.revision_target_document_id is not None:
            _require_kind(self.revision_target_document_id, "company_document", "revision_target_document_id")
        if self.supersedes_document_id is not None:
            _require_kind(self.supersedes_document_id, "company_document", "supersedes_document_id")
        if not isinstance(self.revision, RevisionKind):
            object.__setattr__(self, "revision", _enum(RevisionKind, self.revision, "revision"))
        if self.revision_relation is not None and not isinstance(self.revision_relation, RevisionRelation):
            object.__setattr__(self, "revision_relation", _enum(RevisionRelation, self.revision_relation, "revision_relation"))
        if not self.normalized_text:
            raise ValueError("normalized_text is required")
        expected_content_hash = sha256_hex(self.normalized_text)
        if self.provenance.normalized_content_sha256 != expected_content_hash:
            raise ValueError("normalized_content_sha256 does not match normalized_text")
        if self.revision is RevisionKind.ORIGINAL and (
            self.revision_target_document_id is not None or self.revision_relation is not None or self.supersedes_document_id is not None
        ):
            raise ValueError("original documents cannot declare revision targets or supersession")
        if self.revision is not RevisionKind.ORIGINAL and (
            self.revision_target_document_id is None or self.revision_relation is None or self.supersedes_document_id is None
        ):
            raise ValueError("non-original revisions require target, relation, and supersession")
        expected = sha256_hex(canonical_bytes(self._content_dict()))
        if self.document_digest_sha256 and self.document_digest_sha256 != expected:
            raise ValueError("document digest mismatch")
        object.__setattr__(self, "document_digest_sha256", expected)

    def _content_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_id": self.document_id.to_dict(),
            "provenance": self.provenance.to_dict(),
            "revision": self.revision.value,
            "revision_target_document_id": self.revision_target_document_id.to_dict() if self.revision_target_document_id else None,
            "revision_relation": self.revision_relation.value if self.revision_relation else None,
            "supersedes_document_id": self.supersedes_document_id.to_dict() if self.supersedes_document_id else None,
            "normalized_text": self.normalized_text,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "document_digest_sha256": self.document_digest_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NormalizedCompanyDocument":
        relation = payload.get("revision_relation")
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            document_id=_typed_id(payload.get("document_id"), "document_id"),  # type: ignore[arg-type]
            provenance=CompanyDocumentProvenance.from_dict(payload.get("provenance", {})),
            revision=_enum(RevisionKind, payload.get("revision"), "revision"),  # type: ignore[arg-type]
            revision_target_document_id=_typed_id(payload.get("revision_target_document_id"), "revision_target_document_id"),
            revision_relation=_enum(RevisionRelation, relation, "revision_relation") if relation is not None else None,  # type: ignore[arg-type]
            supersedes_document_id=_typed_id(payload.get("supersedes_document_id"), "supersedes_document_id"),
            normalized_text=str(payload.get("normalized_text", "")),
            document_digest_sha256=str(payload.get("document_digest_sha256", "")),
        )


@dataclass(frozen=True)
class TranscriptSegment:
    segment_id: TypedID
    document_id: TypedID
    sequence_index: int
    text: str
    text_sha256: str = ""
    segment_digest_sha256: str = ""
    schema_version: str = SCHEMA_COMPANY_SEGMENT_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_COMPANY_SEGMENT_V1:
            raise ValueError(f"schema_version must be {SCHEMA_COMPANY_SEGMENT_V1}")
        _require_kind(self.segment_id, "company_segment", "segment_id")
        _require_kind(self.document_id, "company_document", "document_id")
        if isinstance(self.sequence_index, bool) or not isinstance(self.sequence_index, int) or self.sequence_index < 0:
            raise ValueError("sequence_index must be a non-negative integer")
        if self.text == "":
            raise ValueError("segment text is required")
        expected_text_hash = sha256_hex(self.text)
        if self.text_sha256 and self.text_sha256 != expected_text_hash:
            raise ValueError("text_sha256 mismatch")
        object.__setattr__(self, "text_sha256", expected_text_hash)
        expected = sha256_hex(canonical_bytes(self._content_dict()))
        if self.segment_digest_sha256 and self.segment_digest_sha256 != expected:
            raise ValueError("segment digest mismatch")
        object.__setattr__(self, "segment_digest_sha256", expected)

    def _content_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "segment_id": self.segment_id.to_dict(),
            "document_id": self.document_id.to_dict(),
            "sequence_index": self.sequence_index,
            "text": self.text,
            "text_sha256": self.text_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "segment_digest_sha256": self.segment_digest_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TranscriptSegment":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            segment_id=_typed_id(payload.get("segment_id"), "segment_id"),  # type: ignore[arg-type]
            document_id=_typed_id(payload.get("document_id"), "document_id"),  # type: ignore[arg-type]
            sequence_index=payload.get("sequence_index"),  # type: ignore[arg-type]
            text=str(payload.get("text", "")),
            text_sha256=str(payload.get("text_sha256", "")),
            segment_digest_sha256=str(payload.get("segment_digest_sha256", "")),
        )


@dataclass(frozen=True)
class SegmentCitation:
    citation_id: TypedID
    document_id: TypedID
    segment_id: TypedID
    start_char: int
    end_char: int
    quoted_text: str
    quote_sha256: str
    citation_digest_sha256: str = ""
    schema_version: str = SCHEMA_COMPANY_CITATION_V1

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_COMPANY_CITATION_V1:
            raise ValueError(f"schema_version must be {SCHEMA_COMPANY_CITATION_V1}")
        _require_kind(self.citation_id, "company_citation", "citation_id")
        _require_kind(self.document_id, "company_document", "document_id")
        _require_kind(self.segment_id, "company_segment", "segment_id")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (self.start_char, self.end_char)):
            raise ValueError("citation ranges must be integers")
        if self.start_char < 0 or self.end_char <= self.start_char:
            raise ValueError("citation range must be a non-empty half-open span")
        if self.quoted_text == "":
            raise ValueError("quoted_text is required")
        validate_sha256(self.quote_sha256, "quote_sha256")
        expected = sha256_hex(canonical_bytes(self._content_dict()))
        if self.citation_digest_sha256 and self.citation_digest_sha256 != expected:
            raise ValueError("citation digest mismatch")
        object.__setattr__(self, "citation_digest_sha256", expected)

    def _content_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "citation_id": self.citation_id.to_dict(),
            "document_id": self.document_id.to_dict(),
            "segment_id": self.segment_id.to_dict(),
            "start_char": self.start_char,
            "end_char": self.end_char,
            "quoted_text": self.quoted_text,
            "quote_sha256": self.quote_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._content_dict(), "citation_digest_sha256": self.citation_digest_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SegmentCitation":
        return cls(
            schema_version=str(payload.get("schema_version", "")),
            citation_id=_typed_id(payload.get("citation_id"), "citation_id"),  # type: ignore[arg-type]
            document_id=_typed_id(payload.get("document_id"), "document_id"),  # type: ignore[arg-type]
            segment_id=_typed_id(payload.get("segment_id"), "segment_id"),  # type: ignore[arg-type]
            start_char=payload.get("start_char"),  # type: ignore[arg-type]
            end_char=payload.get("end_char"),  # type: ignore[arg-type]
            quoted_text=str(payload.get("quoted_text", "")),
            quote_sha256=str(payload.get("quote_sha256", "")),
            citation_digest_sha256=str(payload.get("citation_digest_sha256", "")),
        )


@dataclass(frozen=True)
class CompanyDocumentValidationResult:
    ok: bool
    reason_codes: tuple[str, ...]
    active_document_ids: tuple[TypedID, ...]
    accepted_citation_ids: tuple[TypedID, ...]
    schema_version: str = SCHEMA_COMPANY_DOCUMENT_VALIDATION_V1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "ok": self.ok,
            "reason_codes": list(self.reason_codes),
            "active_document_ids": [document_id.to_dict() for document_id in self.active_document_ids],
            "accepted_citation_ids": [citation_id.to_dict() for citation_id in self.accepted_citation_ids],
        }


def validate_company_document_bundle(
    documents: Any,
    segments: Any,
    citations: Any,
    accepted_evidence_ids: Any,
    expected_issuer_id: TypedID,
    as_of_utc: str,
) -> CompanyDocumentValidationResult:
    reasons: set[str] = set()
    docs: tuple[NormalizedCompanyDocument, ...] = ()
    segs: tuple[TranscriptSegment, ...] = ()
    cites: tuple[SegmentCitation, ...] = ()
    evidence_ids: set[TypedID] = set()
    try:
        validate_timestamp(as_of_utc, "as_of_utc")
    except Exception:
        reasons.add("malformed_as_of")
    if not isinstance(expected_issuer_id, TypedID):
        reasons.add("malformed_expected_issuer")
    try:
        docs = tuple(item if isinstance(item, NormalizedCompanyDocument) else NormalizedCompanyDocument.from_dict(item) for item in _require_sequence(documents, "documents"))
    except Exception:
        reasons.add("malformed_documents")
    try:
        segs = tuple(item if isinstance(item, TranscriptSegment) else TranscriptSegment.from_dict(item) for item in _require_sequence(segments, "segments"))
    except Exception:
        reasons.add("malformed_segments")
    try:
        cites = tuple(item if isinstance(item, SegmentCitation) else SegmentCitation.from_dict(item) for item in _require_sequence(citations, "citations"))
    except Exception:
        reasons.add("malformed_citations")
    try:
        if not isinstance(accepted_evidence_ids, (set, frozenset, list, tuple)):
            raise ValueError("accepted_evidence_ids must be a collection")
        evidence_ids = {item if isinstance(item, TypedID) else TypedID.from_dict(item) for item in accepted_evidence_ids}
        if not evidence_ids:
            reasons.add("empty_evidence_index")
    except Exception:
        reasons.add("malformed_evidence_index")
    if isinstance(expected_issuer_id, TypedID) and expected_issuer_id.kind != "issuer":
        reasons.add("malformed_expected_issuer")
    if not docs:
        reasons.add("empty_documents")
    if any(evidence_id.kind != "evidence" for evidence_id in evidence_ids):
        reasons.add("malformed_evidence_index")
    if reasons:
        return _blocked(reasons)

    document_by_id: dict[TypedID, NormalizedCompanyDocument] = {}
    segment_by_id: dict[TypedID, TranscriptSegment] = {}
    citation_by_id: dict[TypedID, SegmentCitation] = {}
    seen_ids: set[tuple[str, str, str]] = set()
    for typed_id in [doc.document_id for doc in docs] + [seg.segment_id for seg in segs] + [cite.citation_id for cite in cites]:
        key = _id_key(typed_id)
        if key in seen_ids:
            reasons.add("duplicate_id")
        seen_ids.add(key)
    for doc in docs:
        if doc.document_id in document_by_id:
            reasons.add("duplicate_id")
        document_by_id[doc.document_id] = doc
    for seg in segs:
        if seg.segment_id in segment_by_id:
            reasons.add("duplicate_id")
        segment_by_id[seg.segment_id] = seg
    for cite in cites:
        if cite.citation_id in citation_by_id:
            reasons.add("duplicate_id")
        citation_by_id[cite.citation_id] = cite

    _validate_documents(docs, evidence_ids, expected_issuer_id, as_of_utc, reasons)
    superseded_ids = _validate_revisions(docs, document_by_id, reasons)
    _validate_segments(segs, document_by_id, reasons)
    accepted = _validate_citations(cites, segment_by_id, document_by_id, superseded_ids, reasons)
    if reasons:
        return _blocked(reasons)
    active_ids = tuple(doc.document_id for doc in docs if doc.document_id not in superseded_ids)
    return CompanyDocumentValidationResult(True, (), active_ids, accepted)


def _blocked(reasons: set[str]) -> CompanyDocumentValidationResult:
    return CompanyDocumentValidationResult(False, tuple(sorted(reasons)), (), ())


def _validate_documents(
    docs: tuple[NormalizedCompanyDocument, ...],
    evidence_ids: set[TypedID],
    expected_issuer_id: TypedID,
    as_of_utc: str,
    reasons: set[str],
) -> None:
    seen_content: set[tuple[TypedID, DocumentKind, str, str, str]] = set()
    for doc in docs:
        if doc.provenance.issuer_id != expected_issuer_id:
            reasons.add("cross_issuer_document")
        if _dt(doc.provenance.system_available_at_utc) > _dt(as_of_utc):
            reasons.add("document_unavailable_as_of")
        if not doc.provenance.source_evidence_ids:
            reasons.add("empty_document_evidence")
        for evidence_id in doc.provenance.source_evidence_ids:
            if evidence_id not in evidence_ids:
                reasons.add("missing_evidence")
        key = (
            doc.provenance.issuer_id,
            doc.provenance.document_kind,
            doc.provenance.period_start_utc,
            doc.provenance.period_end_utc,
            doc.provenance.normalized_content_sha256,
        )
        if key in seen_content:
            reasons.add("duplicate_normalized_content")
        seen_content.add(key)


def _validate_revisions(
    docs: tuple[NormalizedCompanyDocument, ...],
    document_by_id: Mapping[TypedID, NormalizedCompanyDocument],
    reasons: set[str],
) -> set[TypedID]:
    successors: dict[TypedID, list[TypedID]] = {}
    for doc in docs:
        if doc.revision is RevisionKind.ORIGINAL:
            continue
        target_id = doc.revision_target_document_id
        supersedes_id = doc.supersedes_document_id
        if target_id == doc.document_id or supersedes_id == doc.document_id:
            reasons.add("revision_self_link")
        if doc.revision is RevisionKind.CORRECTION and doc.revision_relation is not RevisionRelation.CORRECTS:
            reasons.add("wrong_revision_relation")
        if doc.revision is RevisionKind.AMENDMENT and doc.revision_relation is not RevisionRelation.AMENDS:
            reasons.add("wrong_revision_relation")
        if target_id is None or supersedes_id is None or target_id != supersedes_id:
            reasons.add("missing_revision_target")
            continue
        target = document_by_id.get(target_id)
        if target is None:
            reasons.add("missing_revision_target")
            continue
        if (
            target.provenance.issuer_id != doc.provenance.issuer_id
            or target.provenance.document_kind is not doc.provenance.document_kind
            or not _same_period(target.provenance, doc.provenance)
        ):
            reasons.add("incompatible_revision_target")
        if _dt(doc.provenance.source_published_at_utc) < _dt(target.provenance.source_published_at_utc):
            reasons.add("revision_non_monotonic_publication")
        if _dt(doc.provenance.system_available_at_utc) <= _dt(target.provenance.system_available_at_utc):
            reasons.add("revision_non_monotonic_availability")
        successors.setdefault(target_id, []).append(doc.document_id)
    for ids in successors.values():
        if len(ids) > 1:
            reasons.add("ambiguous_successors")
    for doc in docs:
        seen: set[TypedID] = set()
        current = doc
        while current.revision_target_document_id is not None:
            if current.document_id in seen:
                reasons.add("revision_cycle")
                break
            seen.add(current.document_id)
            target = document_by_id.get(current.revision_target_document_id)
            if target is None:
                break
            current = target
    return set(successors)


def _validate_segments(segs: tuple[TranscriptSegment, ...], document_by_id: Mapping[TypedID, NormalizedCompanyDocument], reasons: set[str]) -> None:
    by_doc: dict[TypedID, list[TranscriptSegment]] = {}
    for seg in segs:
        if seg.document_id not in document_by_id:
            reasons.add("missing_segment_document")
            continue
        by_doc.setdefault(seg.document_id, []).append(seg)
    for doc_id, doc_segments in by_doc.items():
        indices = [seg.sequence_index for seg in doc_segments]
        if len(indices) != len(set(indices)):
            reasons.add("duplicate_segment_index")
        if sorted(indices) != list(range(len(doc_segments))):
            reasons.add("noncontiguous_segment_indices")
        joined = "\n".join(seg.text for seg in sorted(doc_segments, key=lambda item: item.sequence_index))
        if joined != document_by_id[doc_id].normalized_text:
            reasons.add("segment_text_mismatch")


def _validate_citations(
    cites: tuple[SegmentCitation, ...],
    segment_by_id: Mapping[TypedID, TranscriptSegment],
    document_by_id: Mapping[TypedID, NormalizedCompanyDocument],
    superseded_ids: set[TypedID],
    reasons: set[str],
) -> tuple[TypedID, ...]:
    accepted: list[TypedID] = []
    for cite in cites:
        doc = document_by_id.get(cite.document_id)
        seg = segment_by_id.get(cite.segment_id)
        if doc is None:
            reasons.add("missing_citation_document")
            continue
        if seg is None:
            reasons.add("missing_citation_segment")
            continue
        if seg.document_id != cite.document_id:
            reasons.add("cross_document_segment_reference")
            continue
        if cite.document_id in superseded_ids:
            reasons.add("citation_to_superseded_document")
            continue
        if cite.end_char > len(seg.text):
            reasons.add("citation_range_out_of_bounds")
            continue
        quote = seg.text[cite.start_char : cite.end_char]
        if quote != cite.quoted_text:
            reasons.add("citation_quote_mismatch")
            continue
        if sha256_hex(quote) != cite.quote_sha256:
            reasons.add("citation_hash_mismatch")
            continue
        accepted.append(cite.citation_id)
    return tuple(accepted)
