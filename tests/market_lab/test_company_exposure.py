from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal, getcontext

import pytest

from market_lab.agency_contracts import canonical_json, strict_json_loads
from market_lab.company_exposure import (
    ExposureEvidence,
    ExposureResult,
    ExposureStatus,
    MaterialityBand,
    assess_exposure,
    assess_exposure_from_evidence,
)


def d(value: str) -> Decimal:
    return Decimal(value)


def evidence(
    *,
    evidence_id: str = "evidence-1",
    numerator_value: Decimal | None = d("10"),
    numerator_low: Decimal | None = None,
    numerator_high: Decimal | None = None,
    denominator_value: Decimal | None = d("100"),
    period_start: str = "2026-01-01",
    period_end: str = "2026-12-31",
    period_type: str = "FY",
    scope: str = "global",
    unit: str = "USD",
    currency: str = "USD",
    accounting_basis: str = "GAAP",
    entity_id: str = "ent-1",
    source_as_of_utc: str = "2026-07-14T00:00:00Z",
    supersedes_evidence_id: str | None = None,
) -> ExposureEvidence:
    return ExposureEvidence(
        evidence_id=evidence_id,
        numerator_value=numerator_value,
        numerator_low=numerator_low,
        numerator_high=numerator_high,
        denominator_value=denominator_value,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        scope=scope,
        unit=unit,
        currency=currency,
        accounting_basis=accounting_basis,
        entity_id=entity_id,
        source_as_of_utc=source_as_of_utc,
        supersedes_evidence_id=supersedes_evidence_id,
    )


def test_assess_exposure_is_zero_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def network_forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("exposure arithmetic attempted network access")

    monkeypatch.setattr("socket.socket", network_forbidden)
    assert assess_exposure(numerator_value=d("1"), denominator_value=d("8")).share_low == d("0.125")


def test_assess_exposure_exact_ratio_is_deterministic_with_hostile_context() -> None:
    previous_precision = getcontext().prec
    try:
        getcontext().prec = 4
        result = assess_exposure(numerator_value=d("1"), denominator_value=d("8"))
    finally:
        getcontext().prec = previous_precision

    assert result.status is ExposureStatus.VALID
    assert result.share_low == d("0.125")
    assert result.share_high == d("0.125")
    assert result.band_low is MaterialityBand.MATERIAL
    assert result.band_high is MaterialityBand.MATERIAL


def test_assess_exposure_exact_case_and_zero_numerator() -> None:
    result = assess_exposure(numerator_value=d("1"), denominator_value=d("4"))
    assert result.status is ExposureStatus.VALID
    assert result.share_low == d("0.25")
    assert result.share_high == d("0.25")
    assert result.band_low is MaterialityBand.CORE
    assert result.band_high is MaterialityBand.CORE

    zero = assess_exposure(numerator_value=d("0"), denominator_value=d("4"))
    assert zero.status is ExposureStatus.VALID
    assert zero.share_low == d("0")
    assert zero.share_high == d("0")
    assert zero.band_low is MaterialityBand.IMMATERIAL
    assert zero.band_high is MaterialityBand.IMMATERIAL


def test_assess_exposure_range_case_preserves_bounds_and_blocks() -> None:
    result = assess_exposure(numerator_low=d("1"), numerator_high=d("9"), denominator_value=d("10"))
    assert result.status is ExposureStatus.ESTIMATED_RANGE
    assert result.share_low == d("0.1")
    assert result.share_high == d("0.9")
    assert result.band_low is MaterialityBand.MATERIAL
    assert result.band_high is MaterialityBand.CORE


def test_assess_exposure_missing_denominator_or_quantified_numerator_is_unknown() -> None:
    missing_denominator = assess_exposure(numerator_value=d("5"))
    assert missing_denominator.status is ExposureStatus.UNKNOWN
    assert missing_denominator.share_low is None
    assert missing_denominator.share_high is None
    assert missing_denominator.band_low is MaterialityBand.UNKNOWN
    assert missing_denominator.band_high is MaterialityBand.UNKNOWN

    missing_numerators = assess_exposure(denominator_value=d("10"))
    assert missing_numerators.status is ExposureStatus.UNKNOWN
    assert missing_numerators.share_low is None
    assert missing_numerators.share_high is None
    assert missing_numerators.band_low is MaterialityBand.UNKNOWN
    assert missing_numerators.band_high is MaterialityBand.UNKNOWN

    neither = assess_exposure()
    assert neither.status is ExposureStatus.UNKNOWN
    assert neither.share_low is None
    assert neither.share_high is None
    assert neither.band_low is MaterialityBand.UNKNOWN
    assert neither.band_high is MaterialityBand.UNKNOWN


@pytest.mark.parametrize("value", [True, 1, 1.0, "1"])
def test_assess_exposure_blocks_non_decimal_inputs_as_malformed(value: object) -> None:
    result = assess_exposure(numerator_value=value)  # type: ignore[arg-type]
    assert result.status is ExposureStatus.BLOCKED
    assert result.blockers == ("malformed_decimal",)

    denominator = assess_exposure(numerator_value=d("1"), denominator_value=value)  # type: ignore[arg-type]
    assert denominator.status is ExposureStatus.BLOCKED
    assert denominator.blockers == ("malformed_decimal",)


def test_assess_exposure_rejects_negative_non_finite_and_invalid_ranges() -> None:
    blocked_negative = assess_exposure(numerator_value=d("-1"), denominator_value=d("10"))
    assert blocked_negative.status is ExposureStatus.BLOCKED
    assert blocked_negative.share_low is None
    assert blocked_negative.blockers == ("negative",)

    blocked_nonfinite = assess_exposure(numerator_value=Decimal("Infinity"), denominator_value=d("10"))
    assert blocked_nonfinite.status is ExposureStatus.BLOCKED
    assert blocked_nonfinite.share_high is None
    assert blocked_nonfinite.blockers == ("non_finite",)

    blocked_partial_range = assess_exposure(numerator_low=d("1"))
    assert blocked_partial_range.status is ExposureStatus.BLOCKED
    assert blocked_partial_range.blockers == ("partial_range",)

    blocked_mixed_range = assess_exposure(numerator_value=d("1"), numerator_high=d("2"))
    assert blocked_mixed_range.status is ExposureStatus.BLOCKED
    assert blocked_mixed_range.blockers == ("mixed_exact_and_range",)

    blocked_denominator = assess_exposure(numerator_value=d("1"), denominator_value=d("0"))
    assert blocked_denominator.status is ExposureStatus.BLOCKED
    assert blocked_denominator.blockers == ("non_positive_denominator",)

    blocked_denominator_without_numerator = assess_exposure(denominator_value=d("-1"))
    assert blocked_denominator_without_numerator.status is ExposureStatus.BLOCKED
    assert blocked_denominator_without_numerator.blockers == ("non_positive_denominator",)

    blocked_nonfinite_without_denominator = assess_exposure(numerator_value=Decimal("NaN"))
    assert blocked_nonfinite_without_denominator.status is ExposureStatus.BLOCKED
    assert blocked_nonfinite_without_denominator.blockers == ("non_finite",)

    blocked_reverse = assess_exposure(numerator_low=d("5"), numerator_high=d("1"), denominator_value=d("10"))
    assert blocked_reverse.status is ExposureStatus.BLOCKED
    assert blocked_reverse.blockers == ("reversed_range",)

    blocked_large = assess_exposure(numerator_low=d("1"), numerator_high=d("11"), denominator_value=d("10"))
    assert blocked_large.status is ExposureStatus.BLOCKED
    assert blocked_large.blockers == ("range_exceeds_denominator",)

    blocked_nonfinite_range = assess_exposure(numerator_low=Decimal("NaN"), numerator_high=Decimal("1"), denominator_value=d("10"))
    assert blocked_nonfinite_range.status is ExposureStatus.BLOCKED
    assert blocked_nonfinite_range.blockers == ("non_finite",)


def test_materiality_boundaries_and_cross_band_classification() -> None:
    assert assess_exposure(numerator_value=d("1"), denominator_value=d("200")).band_low is MaterialityBand.IMMATERIAL
    assert assess_exposure(numerator_value=d("1"), denominator_value=d("100")).band_low is MaterialityBand.MINOR
    assert assess_exposure(numerator_value=d("5"), denominator_value=d("100")).band_low is MaterialityBand.MATERIAL
    assert assess_exposure(numerator_value=d("1"), denominator_value=d("5")).band_low is MaterialityBand.CORE

    range_bands = assess_exposure(numerator_low=d("1"), numerator_high=d("20"), denominator_value=d("100"))
    assert range_bands.band_low is MaterialityBand.MINOR
    assert range_bands.band_high is MaterialityBand.CORE


def test_exposure_result_is_frozen_and_round_trips_stably() -> None:
    result = assess_exposure(numerator_value=d("1"), denominator_value=d("8"))
    with pytest.raises(FrozenInstanceError):
        result.share_low = d("0")  # type: ignore[assignment]

    payload = result.to_dict()
    assert payload["share_low"] == "0.125"
    assert payload["status"] == "VALID"
    recovered = ExposureResult.from_dict(strict_json_loads(canonical_json(payload)))
    assert recovered == result


def test_exact_case_uses_equal_bounds() -> None:
    exact = assess_exposure(numerator_value=d("2"), denominator_value=d("8"))
    assert exact.share_low == exact.share_high


def _selection_context(
    *,
    evidence_inputs: tuple[ExposureEvidence, ...] = (evidence(),),
    period_start: str = "2026-01-01",
    period_end: str = "2026-12-31",
    period_type: str = "FY",
    scope: str = "global",
    unit: str = "USD",
    currency: str = "USD",
    accounting_basis: str = "GAAP",
    entity_id: str = "ent-1",
    as_of_utc: str = "2026-07-14T00:00:00Z",
    denominator_value: Decimal | None = None,
    allow_superseded: bool = False,
    readiness_critical: bool = False,
) -> ExposureResult:
    return assess_exposure_from_evidence(
        evidence_inputs=evidence_inputs,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        scope=scope,
        currency=currency,
        unit=unit,
        accounting_basis=accounting_basis,
        entity_id=entity_id,
        as_of_utc=as_of_utc,
        denominator_value=denominator_value,
        allow_superseded=allow_superseded,
        readiness_critical=readiness_critical,
    )


def test_assess_exposure_from_evidence_selects_compatible_input() -> None:
    result = _selection_context(evidence_inputs=(
        evidence(evidence_id="matching", numerator_value=d("10"), denominator_value=d("100")),
        evidence(evidence_id="misaligned", period_start="2025-01-01"),
    ))

    assert result.status is ExposureStatus.VALID
    assert result.share_low == d("0.1")
    assert result.share_high == d("0.1")
    assert result.blockers == ()


def test_assess_exposure_from_evidence_enforces_exact_period_and_scope_denominator_alignment() -> None:
    period = _selection_context(evidence_inputs=(evidence(evidence_id="p1", period_end="2025-12-31"),))
    assert period.status is ExposureStatus.BLOCKED
    assert period.blockers == ("period_mismatch",)

    scope = _selection_context(
        evidence_inputs=(evidence(evidence_id="s1", scope="local"),),
        scope="global",
    )
    assert scope.status is ExposureStatus.BLOCKED
    assert scope.blockers == ("scope_mismatch",)

    unit = _selection_context(
        evidence_inputs=(evidence(evidence_id="u1", unit="EUR"),),
        unit="USD",
    )
    assert unit.status is ExposureStatus.BLOCKED
    assert unit.blockers == ("unit_currency_accounting_basis_mismatch",)


def test_assess_exposure_from_evidence_blocks_stale_superseded_and_allows_explicit_choice() -> None:
    stale = _selection_context(
        evidence_inputs=(
            evidence(evidence_id="old", numerator_value=d("10")),
            evidence(evidence_id="new", numerator_value=d("20"), supersedes_evidence_id="old"),
        )
    )

    assert stale.status is ExposureStatus.BLOCKED
    assert stale.blockers == ("stale_superseded_evidence",)

    explicit = _selection_context(
        evidence_inputs=(
            evidence(evidence_id="old", numerator_value=d("10")),
            evidence(evidence_id="new", numerator_value=d("20"), supersedes_evidence_id="old"),
        ),
        allow_superseded=True,
    )
    assert explicit.status is ExposureStatus.VALID
    assert explicit.share_low == d("0.2")


def test_assess_exposure_from_evidence_blocks_ambiguous_denominator_and_double_count() -> None:
    ambiguous = _selection_context(
        evidence_inputs=(
            evidence(evidence_id="a1", denominator_value=d("100")),
            evidence(evidence_id="a2", denominator_value=d("200")),
        )
    )
    assert ambiguous.status is ExposureStatus.BLOCKED
    assert ambiguous.blockers == ("ambiguous_denominator",)

    duplicate = _selection_context(
        evidence_inputs=(
            evidence(evidence_id="d1", numerator_value=d("10")),
            evidence(evidence_id="d2", numerator_value=d("10")),
        ),
        denominator_value=d("100"),
    )
    assert duplicate.status is ExposureStatus.BLOCKED
    assert duplicate.blockers == ("duplicate_or_double_count",)


def test_assess_exposure_from_evidence_blocks_source_timestamp_and_entity_fit() -> None:
    future = _selection_context(
        evidence_inputs=(
            evidence(
                evidence_id="future",
                source_as_of_utc="2026-12-31T00:00:00Z",
                numerator_value=d("1"),
            ),
        ),
        as_of_utc="2026-07-14T00:00:00Z",
    )
    assert future.status is ExposureStatus.BLOCKED
    assert future.blockers == ("source_timestamp_unavailable",)

    bad_entity = _selection_context(
        evidence_inputs=(
            evidence(evidence_id="entity", entity_id="wrong", numerator_value=d("1")),
        ),
        entity_id="ent-1",
    )
    assert bad_entity.status is ExposureStatus.BLOCKED
    assert bad_entity.blockers == ("entity_mismatch",)


def test_assess_exposure_from_evidence_blocks_critical_unknown() -> None:
    critical = _selection_context(
        evidence_inputs=(
            evidence(evidence_id="critical", numerator_value=None, denominator_value=d("100")),
        ),
        readiness_critical=True,
    )
    assert critical.status is ExposureStatus.BLOCKED
    assert critical.blockers == ("critical_unknown",)

    non_critical = _selection_context(
        evidence_inputs=(
            evidence(evidence_id="non-critical", numerator_value=None, denominator_value=d("100")),
        ),
        readiness_critical=False,
    )
    assert non_critical.status is ExposureStatus.UNKNOWN
    assert non_critical.share_low is None
