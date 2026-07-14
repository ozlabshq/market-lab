from __future__ import annotations

from dataclasses import FrozenInstanceError
from decimal import Decimal, getcontext

import pytest

from market_lab.agency_contracts import canonical_json, strict_json_loads
from market_lab.company_exposure import ExposureResult, ExposureStatus, MaterialityBand, assess_exposure


def d(value: str) -> Decimal:
    return Decimal(value)


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
