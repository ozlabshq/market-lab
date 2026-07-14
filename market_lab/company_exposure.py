from __future__ import annotations

"""Minimal deterministic exposure arithmetic core."""

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from enum import Enum
from typing import Any, Mapping


class MaterialityBand(Enum):
    IMMATERIAL = "IMMATERIAL"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    CORE = "CORE"
    UNKNOWN = "UNKNOWN"


class ExposureStatus(Enum):
    VALID = "VALID"
    ESTIMATED_RANGE = "ESTIMATED_RANGE"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class ExposureResult:
    share_low: Decimal | None
    share_high: Decimal | None
    band_low: MaterialityBand
    band_high: MaterialityBand
    status: ExposureStatus
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "share_low": str(self.share_low) if self.share_low is not None else None,
            "share_high": str(self.share_high) if self.share_high is not None else None,
            "band_low": self.band_low.value,
            "band_high": self.band_high.value,
            "status": self.status.value,
            "blockers": list(self.blockers),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExposureResult":
        return cls(
            share_low=_from_decimal(payload.get("share_low"), "share_low"),
            share_high=_from_decimal(payload.get("share_high"), "share_high"),
            band_low=_enum(MaterialityBand, payload.get("band_low"), "band_low"),
            band_high=_enum(MaterialityBand, payload.get("band_high"), "band_high"),
            status=_enum(ExposureStatus, payload.get("status"), "status"),
            blockers=_strings(payload.get("blockers", ()), "blockers"),
        )


def _enum(enum_type: type[Enum], value: Any, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} contains unknown enum value") from exc


def _from_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception as exc:
            raise ValueError(f"{field_name} must be a Decimal-compatible decimal string") from exc
    raise ValueError(f"{field_name} must be None or a Decimal-compatible decimal string")


def _strings(values: tuple[str, ...] | list[Any] | tuple[Any, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    result = tuple(value if isinstance(value, str) else str(value) for value in values)
    return result


def _require_decimal(value: Any, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, (int, float, str)):
        raise ValueError(f"{field_name} must be Decimal or None")
    if not isinstance(value, Decimal):
        raise ValueError(f"{field_name} must be Decimal or None")
    return value


_ZERO = Decimal("0")
_ONE = Decimal("1")
_MATERIALITY_BAND_01 = Decimal("0.01")
_MATERIALITY_BAND_05 = Decimal("0.05")
_MATERIALITY_BAND_20 = Decimal("0.20")
_DECIMAL_CONTEXT = Context(prec=50)


def _materiality_band(value: Decimal) -> MaterialityBand:
    if value < _MATERIALITY_BAND_01:
        return MaterialityBand.IMMATERIAL
    if value < _MATERIALITY_BAND_05:
        return MaterialityBand.MINOR
    if value < _MATERIALITY_BAND_20:
        return MaterialityBand.MATERIAL
    return MaterialityBand.CORE


def _safe_divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext(_DECIMAL_CONTEXT):
        return numerator / denominator


def _unknown() -> ExposureResult:
    return ExposureResult(
        share_low=None,
        share_high=None,
        band_low=MaterialityBand.UNKNOWN,
        band_high=MaterialityBand.UNKNOWN,
        status=ExposureStatus.UNKNOWN,
        blockers=(),
    )


def _blocked(*blockers: str) -> ExposureResult:
    return ExposureResult(
        share_low=None,
        share_high=None,
        band_low=MaterialityBand.UNKNOWN,
        band_high=MaterialityBand.UNKNOWN,
        status=ExposureStatus.BLOCKED,
        blockers=tuple(blockers),
    )


def assess_exposure(
    *,
    numerator_value: Decimal | None = None,
    numerator_low: Decimal | None = None,
    numerator_high: Decimal | None = None,
    denominator_value: Decimal | None = None,
) -> ExposureResult:
    try:
        denominator = _require_decimal(denominator_value, "denominator_value")
        numerator = _require_decimal(numerator_value, "numerator_value")
        low = _require_decimal(numerator_low, "numerator_low")
        high = _require_decimal(numerator_high, "numerator_high")
    except ValueError:
        return _blocked("malformed_decimal")

    supplied = tuple(value for value in (denominator, numerator, low, high) if value is not None)
    if any(not value.is_finite() for value in supplied):
        return _blocked("non_finite")
    if denominator is not None and denominator <= _ZERO:
        return _blocked("non_positive_denominator")
    if any(value < _ZERO for value in (numerator, low, high) if value is not None):
        return _blocked("negative")

    exact_inputs = numerator is not None
    range_inputs = low is not None or high is not None

    if not exact_inputs and not range_inputs:
        return _unknown()
    if exact_inputs and range_inputs:
        return _blocked("mixed_exact_and_range")

    if range_inputs and (low is None or high is None):
        return _blocked("partial_range")

    if numerator is not None:
        if denominator is None:
            return _unknown()
        if numerator > denominator:
            return _blocked("numerator_exceeds_denominator")

        share = _safe_divide(numerator, denominator)
        if share < _ZERO or share > _ONE:
            return _blocked("range_out_of_bounds")
        band = _materiality_band(share)
        return ExposureResult(
            share_low=share,
            share_high=share,
            band_low=band,
            band_high=band,
            status=ExposureStatus.VALID,
            blockers=(),
        )

    # range_inputs is True and low/high are both Decimal due earlier validation.
    assert low is not None and high is not None
    if denominator is None:
        return _unknown()
    if low > high:
        return _blocked("reversed_range")
    if low > denominator:
        return _blocked("numerator_exceeds_denominator")
    if high > denominator:
        return _blocked("range_exceeds_denominator")

    share_low = _safe_divide(low, denominator)
    share_high = _safe_divide(high, denominator)
    if share_low < _ZERO or share_high < _ZERO or share_high > _ONE or share_low > share_high:
        return _blocked("range_out_of_bounds")

    return ExposureResult(
        share_low=share_low,
        share_high=share_high,
        band_low=_materiality_band(share_low),
        band_high=_materiality_band(share_high),
        status=ExposureStatus.ESTIMATED_RANGE,
        blockers=(),
    )
