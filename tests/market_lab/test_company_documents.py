from __future__ import annotations

import socket
from dataclasses import FrozenInstanceError

import pytest

from market_lab.agency_contracts import TypedID, canonical_json, sha256_hex, strict_json_loads
from market_lab.company_documents import (
    CompanyDocumentProvenance,
    DocumentKind,
    NormalizedCompanyDocument,
    RevisionKind,
    RevisionRelation,
    SegmentCitation,
    TranscriptSegment,
    validate_company_document_bundle,
)

NOW = "2026-07-14T08:00:00Z"
Q1_START = "2026-01-01T00:00:00Z"
Q1_END = "2026-04-01T00:00:00Z"


def tid(kind: str, local_id: str) -> TypedID:
    return TypedID(kind=kind, domain="agency", id_schema_version="v1", local_id=local_id)


def provenance(
    *,
    issuer_id: TypedID | None = None,
    kind: DocumentKind = DocumentKind.EARNINGS_TRANSCRIPT,
    period_start: str = Q1_START,
    period_end: str = Q1_END,
    normalized_text: str = "Revenue rose 10%.\nMargins expanded.",
    evidence_ids: tuple[TypedID, ...] | None = None,
    source_published_at_utc: str = "2026-04-20T12:00:00Z",
    system_available_at_utc: str = "2026-04-20T12:05:00Z",
) -> CompanyDocumentProvenance:
    return CompanyDocumentProvenance(
        issuer_id=issuer_id or tid("issuer", "alpha"),
        document_kind=kind,
        source_locator="sec://alpha/q1-transcript",
        source_published_at_utc=source_published_at_utc,
        system_available_at_utc=system_available_at_utc,
        period_start_utc=period_start,
        period_end_utc=period_end,
        source_byte_sha256=sha256_hex(b"source bytes"),
        normalized_content_sha256=sha256_hex(normalized_text),
        source_evidence_ids=evidence_ids or (tid("evidence", "alpha-q1-source"),),
    )


def document(
    local_id: str = "alpha-q1-original",
    *,
    text: str = "Revenue rose 10%.\nMargins expanded.",
    issuer_id: TypedID | None = None,
    kind: DocumentKind = DocumentKind.EARNINGS_TRANSCRIPT,
    period_start: str = Q1_START,
    period_end: str = Q1_END,
    revision: RevisionKind = RevisionKind.ORIGINAL,
    target: TypedID | None = None,
    relation: RevisionRelation | None = None,
    supersedes: TypedID | None = None,
    available: str = "2026-04-20T12:05:00Z",
) -> NormalizedCompanyDocument:
    return NormalizedCompanyDocument(
        document_id=tid("company_document", local_id),
        provenance=provenance(
            issuer_id=issuer_id,
            kind=kind,
            period_start=period_start,
            period_end=period_end,
            normalized_text=text,
            system_available_at_utc=available,
        ),
        revision=revision,
        revision_target_document_id=target,
        revision_relation=relation,
        supersedes_document_id=supersedes,
        normalized_text=text,
    )


def segments(doc: NormalizedCompanyDocument) -> tuple[TranscriptSegment, TranscriptSegment]:
    first, second = doc.normalized_text.split("\n")
    return (
        TranscriptSegment(segment_id=tid("company_segment", f"{doc.document_id.local_id}-s0"), document_id=doc.document_id, sequence_index=0, text=first),
        TranscriptSegment(segment_id=tid("company_segment", f"{doc.document_id.local_id}-s1"), document_id=doc.document_id, sequence_index=1, text=second),
    )


def citation(doc: NormalizedCompanyDocument, segment: TranscriptSegment, start: int = 0, end: int = 7) -> SegmentCitation:
    quote = segment.text[start:end]
    return SegmentCitation(
        citation_id=tid("company_citation", f"{segment.segment_id.local_id}-{start}-{end}"),
        document_id=doc.document_id,
        segment_id=segment.segment_id,
        start_char=start,
        end_char=end,
        quoted_text=quote,
        quote_sha256=sha256_hex(quote),
    )


def test_document_segment_and_citation_round_trip_digest_and_freeze() -> None:
    doc = document()
    seg = segments(doc)[0]
    cite = citation(doc, seg)

    assert NormalizedCompanyDocument.from_dict(strict_json_loads(canonical_json(doc.to_dict()))) == doc
    assert TranscriptSegment.from_dict(strict_json_loads(canonical_json(seg.to_dict()))) == seg
    assert SegmentCitation.from_dict(strict_json_loads(canonical_json(cite.to_dict()))) == cite
    assert len(doc.document_digest_sha256) == 64
    assert len(seg.segment_digest_sha256) == 64
    assert len(cite.citation_digest_sha256) == 64
    with pytest.raises(FrozenInstanceError):
        doc.normalized_text = "mutated"  # type: ignore[misc]


def test_strict_schema_enum_timestamp_hash_and_tampered_digest_validation() -> None:
    doc = document()
    payload = doc.to_dict()
    payload["schema_version"] = "mlab-company-document.v2"
    with pytest.raises(ValueError, match="schema_version"):
        NormalizedCompanyDocument.from_dict(payload)
    payload = doc.to_dict()
    payload["revision"] = "RESTATED"
    with pytest.raises(ValueError, match="revision"):
        NormalizedCompanyDocument.from_dict(payload)
    payload = doc.to_dict()
    payload["document_digest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="digest"):
        NormalizedCompanyDocument.from_dict(payload)
    payload = doc.to_dict()
    payload["provenance"]["normalized_content_sha256"] = sha256_hex("different")
    with pytest.raises(ValueError, match="normalized_content_sha256"):
        NormalizedCompanyDocument.from_dict(payload)
    payload = doc.to_dict()
    payload["provenance"]["source_published_at_utc"] = "2026-04-20T12:10:00Z"
    with pytest.raises(ValueError, match="published"):
        NormalizedCompanyDocument.from_dict(payload)


def test_valid_bundle_returns_unambiguous_active_leaf_and_exact_citation() -> None:
    original = document()
    corrected = document(
        "alpha-q1-correction",
        text="Revenue rose 11%.\nMargins expanded.",
        revision=RevisionKind.CORRECTION,
        target=original.document_id,
        relation=RevisionRelation.CORRECTS,
        supersedes=original.document_id,
        available="2026-04-21T09:00:00Z",
    )
    segs = segments(original) + segments(corrected)
    cite = citation(corrected, segs[2], 8, 12)

    result = validate_company_document_bundle(
        documents=(original, corrected),
        segments=segs,
        citations=(cite,),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )

    assert result.ok is True
    assert result.reason_codes == ()
    assert result.active_document_ids == (corrected.document_id,)
    assert result.accepted_citation_ids == (cite.citation_id,)


def test_valid_bundle_makes_no_network_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_socket(*args: object, **kwargs: object) -> socket.socket:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "socket", blocked_socket)
    doc = document()
    result = validate_company_document_bundle(
        documents=(doc,),
        segments=segments(doc),
        citations=(),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )

    assert result.ok is True
    assert result.reason_codes == ()


def test_evidence_index_must_include_document_source_evidence() -> None:
    doc = document()
    result = validate_company_document_bundle(
        documents=(doc,),
        segments=segments(doc),
        citations=(),
        accepted_evidence_ids={tid("evidence", "other-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )

    assert result.ok is False
    assert result.reason_codes == ("missing_evidence",)


def test_citation_to_missing_document_is_deterministic() -> None:
    doc = document()
    seg = segments(doc)[0]
    cite = SegmentCitation(
        citation_id=tid("company_citation", "missing-doc-cite"),
        document_id=tid("company_document", "missing-doc"),
        segment_id=seg.segment_id,
        start_char=0,
        end_char=7,
        quoted_text=seg.text[0:7],
        quote_sha256=sha256_hex(seg.text[0:7]),
    )

    result = validate_company_document_bundle(
        documents=(doc,),
        segments=segments(doc),
        citations=(cite,),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )

    assert result.ok is False
    assert result.reason_codes == ("missing_citation_document",)


def test_revision_safety_rejects_bad_links_ambiguous_branches_cycles_and_stale_citations() -> None:
    original = document()
    with pytest.raises(ValueError, match="original"):
        NormalizedCompanyDocument.from_dict({**original.to_dict(), "revision_target_document_id": original.document_id.to_dict()})

    correction = document(
        "alpha-q1-correction",
        text="Revenue rose 11%.\nMargins expanded.",
        revision=RevisionKind.CORRECTION,
        target=original.document_id,
        relation=RevisionRelation.CORRECTS,
        supersedes=original.document_id,
        available="2026-04-21T09:00:00Z",
    )
    branch = document(
        "alpha-q1-amendment",
        text="Revenue rose 12%.\nMargins expanded.",
        revision=RevisionKind.AMENDMENT,
        target=original.document_id,
        relation=RevisionRelation.AMENDS,
        supersedes=original.document_id,
        available="2026-04-22T09:00:00Z",
    )
    stale_cite = citation(original, segments(original)[0])
    result = validate_company_document_bundle(
        documents=(original, correction, branch),
        segments=segments(original) + segments(correction) + segments(branch),
        citations=(stale_cite,),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert result.ok is False
    assert result.reason_codes == ("ambiguous_successors", "citation_to_superseded_document")

    self_link = document(
        "self-link",
        revision=RevisionKind.CORRECTION,
        target=tid("company_document", "self-link"),
        relation=RevisionRelation.CORRECTS,
        supersedes=tid("company_document", "self-link"),
    )
    result = validate_company_document_bundle(
        documents=(self_link,),
        segments=segments(self_link),
        citations=(),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert "revision_self_link" in result.reason_codes

    older = document("older-correction", revision=RevisionKind.CORRECTION, target=original.document_id, relation=RevisionRelation.CORRECTS, supersedes=original.document_id, available="2026-04-20T12:03:00Z")
    result = validate_company_document_bundle((original, older), segments(original) + segments(older), (), {tid("evidence", "alpha-q1-source")}, tid("issuer", "alpha"), NOW)
    assert "revision_non_monotonic_availability" in result.reason_codes

    cycle_a = document("cycle-a", revision=RevisionKind.CORRECTION, target=tid("company_document", "cycle-b"), relation=RevisionRelation.CORRECTS, supersedes=tid("company_document", "cycle-b"))
    cycle_b = document("cycle-b", revision=RevisionKind.CORRECTION, target=cycle_a.document_id, relation=RevisionRelation.CORRECTS, supersedes=cycle_a.document_id)
    result = validate_company_document_bundle((cycle_a, cycle_b), segments(cycle_a) + segments(cycle_b), (), {tid("evidence", "alpha-q1-source")}, tid("issuer", "alpha"), NOW)
    assert "revision_cycle" in result.reason_codes

    missing_target = document("missing-target", revision=RevisionKind.CORRECTION, target=tid("company_document", "missing"), relation=RevisionRelation.CORRECTS, supersedes=tid("company_document", "missing"))
    wrong_relation = document("wrong-relation", revision=RevisionKind.CORRECTION, target=original.document_id, relation=RevisionRelation.AMENDS, supersedes=original.document_id, available="2026-04-21T00:00:00Z")
    other_kind = document("other-kind", kind=DocumentKind.QUARTERLY_REPORT)
    incompatible = document("incompatible", revision=RevisionKind.AMENDMENT, target=other_kind.document_id, relation=RevisionRelation.AMENDS, supersedes=other_kind.document_id, available="2026-04-21T00:00:00Z")
    result = validate_company_document_bundle(
        (original, missing_target, wrong_relation, other_kind, incompatible),
        segments(original) + segments(missing_target) + segments(wrong_relation) + segments(other_kind) + segments(incompatible),
        (),
        {tid("evidence", "alpha-q1-source")},
        tid("issuer", "alpha"),
        NOW,
    )
    assert "missing_revision_target" in result.reason_codes
    assert "wrong_revision_relation" in result.reason_codes
    assert "incompatible_revision_target" in result.reason_codes


def test_revision_target_rejects_cross_issuer_and_cross_period() -> None:
    original = document()
    cross_issuer = document(
        "beta-correction",
        issuer_id=tid("issuer", "beta"),
        revision=RevisionKind.CORRECTION,
        target=original.document_id,
        relation=RevisionRelation.CORRECTS,
        supersedes=original.document_id,
        available="2026-04-21T00:00:00Z",
    )
    cross_period_target = document("q2-original", period_start="2026-04-01T00:00:00Z", period_end="2026-07-01T00:00:00Z")
    cross_period = document(
        "q1-to-q2-correction",
        revision=RevisionKind.CORRECTION,
        target=cross_period_target.document_id,
        relation=RevisionRelation.CORRECTS,
        supersedes=cross_period_target.document_id,
        available="2026-04-21T00:00:00Z",
    )

    result = validate_company_document_bundle(
        (original, cross_issuer),
        segments(original) + segments(cross_issuer),
        (),
        {tid("evidence", "alpha-q1-source")},
        tid("issuer", "alpha"),
        NOW,
    )
    assert "incompatible_revision_target" in result.reason_codes

    result = validate_company_document_bundle(
        (cross_period_target, cross_period),
        segments(cross_period_target) + segments(cross_period),
        (),
        {tid("evidence", "alpha-q1-source")},
        tid("issuer", "alpha"),
        NOW,
    )
    assert "incompatible_revision_target" in result.reason_codes


def test_entity_temporal_dedupe_and_malformed_inputs_fail_closed() -> None:
    original = document()
    cross_issuer = document("beta-q1", issuer_id=tid("issuer", "beta"))
    future = document("future", available="2026-08-01T00:00:00Z")
    duplicate_content = document("alpha-q1-copy")
    different_period_same_text = document("alpha-q2-same-text", period_start="2026-04-01T00:00:00Z", period_end="2026-07-01T00:00:00Z")

    result = validate_company_document_bundle(
        documents=(original, cross_issuer, future, duplicate_content, different_period_same_text),
        segments=segments(original) + segments(cross_issuer) + segments(future) + segments(duplicate_content) + segments(different_period_same_text),
        citations=(),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert result.ok is False
    assert "cross_issuer_document" in result.reason_codes
    assert "document_unavailable_as_of" in result.reason_codes
    assert "duplicate_normalized_content" in result.reason_codes

    duplicate_id = document()
    result = validate_company_document_bundle(
        documents=(original, duplicate_id),
        segments=segments(original),
        citations=(),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert "duplicate_id" in result.reason_codes

    result = validate_company_document_bundle(
        documents=(original, different_period_same_text),
        segments=segments(original) + segments(different_period_same_text),
        citations=(),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert result.ok is True
    assert result.active_document_ids == (original.document_id, different_period_same_text.document_id)

    result = validate_company_document_bundle(
        documents=(original, cross_issuer),
        segments=segments(original) + segments(cross_issuer),
        citations=(),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert "cross_issuer_document" in result.reason_codes
    assert "duplicate_normalized_content" not in result.reason_codes

    malformed = validate_company_document_bundle(
        documents={"not": "a sequence"},
        segments=(),
        citations=(),
        accepted_evidence_ids=set(),
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert malformed.ok is False
    assert malformed.reason_codes == ("empty_documents", "empty_evidence_index", "malformed_documents")

    empty = validate_company_document_bundle(
        documents=(),
        segments=(),
        citations=(),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert empty.ok is False
    assert empty.reason_codes == ("empty_documents",)

    with pytest.raises(ValueError, match="half-open"):
        provenance(period_start=Q1_START, period_end=Q1_START)
    with pytest.raises(ValueError, match="half-open"):
        provenance(period_start=Q1_END, period_end=Q1_START)


def test_segment_and_citation_fidelity_blocks_exact_reference_span_quote_and_hash_defects() -> None:
    doc = document()
    seg0, seg1 = segments(doc)
    other = document("other-doc", period_start="2026-04-01T00:00:00Z", period_end="2026-07-01T00:00:00Z")
    other_seg = segments(other)[0]
    duplicate_index = TranscriptSegment(segment_id=tid("company_segment", "duplicate-index"), document_id=doc.document_id, sequence_index=1, text="duplicate")
    bad_citation = SegmentCitation(
        citation_id=tid("company_citation", "bad-quote"),
        document_id=doc.document_id,
        segment_id=seg0.segment_id,
        start_char=0,
        end_char=7,
        quoted_text="Revenue",
        quote_sha256=sha256_hex("wrong"),
    )
    cross_doc_citation = SegmentCitation(
        citation_id=tid("company_citation", "cross-doc"),
        document_id=doc.document_id,
        segment_id=other_seg.segment_id,
        start_char=0,
        end_char=7,
        quoted_text=other_seg.text[0:7],
        quote_sha256=sha256_hex(other_seg.text[0:7]),
    )
    out_of_range = SegmentCitation(
        citation_id=tid("company_citation", "out-of-range"),
        document_id=doc.document_id,
        segment_id=seg0.segment_id,
        start_char=0,
        end_char=len(seg0.text) + 1,
        quoted_text=seg0.text,
        quote_sha256=sha256_hex(seg0.text),
    )
    wrong_quote = SegmentCitation(
        citation_id=tid("company_citation", "wrong-quote"),
        document_id=doc.document_id,
        segment_id=seg0.segment_id,
        start_char=0,
        end_char=7,
        quoted_text="Margins",
        quote_sha256=sha256_hex("Margins"),
    )
    missing_segment = SegmentCitation(
        citation_id=tid("company_citation", "missing-segment"),
        document_id=doc.document_id,
        segment_id=tid("company_segment", "missing"),
        start_char=0,
        end_char=7,
        quoted_text="Revenue",
        quote_sha256=sha256_hex("Revenue"),
    )

    result = validate_company_document_bundle(
        documents=(doc, other),
        segments=(seg0, seg1, duplicate_index, other_seg),
        citations=(bad_citation, cross_doc_citation, out_of_range, wrong_quote, missing_segment),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert result.ok is False
    assert "duplicate_segment_index" in result.reason_codes
    assert "citation_hash_mismatch" in result.reason_codes
    assert "cross_document_segment_reference" in result.reason_codes
    assert "citation_range_out_of_bounds" in result.reason_codes
    assert "citation_quote_mismatch" in result.reason_codes
    assert "missing_citation_segment" in result.reason_codes

    duplicate_id_seg = TranscriptSegment(segment_id=seg0.segment_id, document_id=doc.document_id, sequence_index=1, text=seg1.text)
    result = validate_company_document_bundle(
        documents=(doc,),
        segments=(seg0, duplicate_id_seg),
        citations=(),
        accepted_evidence_ids={tid("evidence", "alpha-q1-source")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert result.reason_codes == ("duplicate_id",)

    with pytest.raises(ValueError, match="half-open"):
        SegmentCitation(
            citation_id=tid("company_citation", "empty-span"),
            document_id=doc.document_id,
            segment_id=seg0.segment_id,
            start_char=3,
            end_char=3,
            quoted_text="",
            quote_sha256=sha256_hex(""),
        )


def test_typed_id_kind_boundaries_fail_closed() -> None:
    with pytest.raises(ValueError, match="document_id must be a company_document"):
        NormalizedCompanyDocument(
            document_id=tid("evidence", "wrong-document-kind"),
            provenance=provenance(),
            revision=RevisionKind.ORIGINAL,
            revision_target_document_id=None,
            revision_relation=None,
            supersedes_document_id=None,
            normalized_text="Revenue rose 10%.\nMargins expanded.",
        )

    with pytest.raises(ValueError, match="source_evidence_ids must be a evidence"):
        provenance(evidence_ids=(tid("company_document", "wrong-evidence-kind"),))

    result = validate_company_document_bundle(
        documents=(document(),),
        segments=segments(document()),
        citations=(),
        accepted_evidence_ids={tid("company_document", "wrong-evidence-kind")},
        expected_issuer_id=tid("issuer", "alpha"),
        as_of_utc=NOW,
    )
    assert "malformed_evidence_index" in result.reason_codes
