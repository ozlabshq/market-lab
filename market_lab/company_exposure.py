from __future__ import annotations

"""Minimal deterministic exposure arithmetic core."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Context, Decimal, localcontext
from enum import Enum
from typing import Any, Mapping

from .agency_contracts import validate_timestamp


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


@dataclass(frozen=True)
class ExposureEvidence:
    evidence_id: str
    numerator_value: Decimal | None
    numerator_low: Decimal | None
    numerator_high: Decimal | None
    denominator_value: Decimal | None
    period_start: str
    period_end: str
    period_type: str
    scope: str
    unit: str
    currency: str
    accounting_basis: str
    entity_id: str
    source_as_of_utc: str
    supersedes_evidence_id: str | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.evidence_id.strip():
            raise ValueError("evidence_id must be a non-empty string")
        for field_name, value in (
            ("numerator_value", self.numerator_value),
            ("numerator_low", self.numerator_low),
            ("numerator_high", self.numerator_high),
            ("denominator_value", self.denominator_value),
        ):
            if value is not None and not isinstance(value, Decimal):
                raise ValueError(f"{field_name} must be Decimal or None")

        for field_name, value in (
            ("period_start", self.period_start),
            ("period_end", self.period_end),
            ("period_type", self.period_type),
            ("scope", self.scope),
            ("unit", self.unit),
            ("currency", self.currency),
            ("accounting_basis", self.accounting_basis),
            ("entity_id", self.entity_id),
        ):
            if not value or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")

        validate_timestamp(self.source_as_of_utc, "source_as_of_utc")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "numerator_value": str(self.numerator_value) if self.numerator_value is not None else None,
            "numerator_low": str(self.numerator_low) if self.numerator_low is not None else None,
            "numerator_high": str(self.numerator_high) if self.numerator_high is not None else None,
            "denominator_value": str(self.denominator_value) if self.denominator_value is not None else None,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "period_type": self.period_type,
            "scope": self.scope,
            "unit": self.unit,
            "currency": self.currency,
            "accounting_basis": self.accounting_basis,
            "entity_id": self.entity_id,
            "source_as_of_utc": self.source_as_of_utc,
            "supersedes_evidence_id": self.supersedes_evidence_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExposureEvidence":
        return cls(
            evidence_id=str(payload.get("evidence_id", "")),
            numerator_value=_from_decimal(payload.get("numerator_value"), "numerator_value"),
            numerator_low=_from_decimal(payload.get("numerator_low"), "numerator_low"),
            numerator_high=_from_decimal(payload.get("numerator_high"), "numerator_high"),
            denominator_value=_from_decimal(payload.get("denominator_value"), "denominator_value"),
            period_start=str(payload.get("period_start", "")),
            period_end=str(payload.get("period_end", "")),
            period_type=str(payload.get("period_type", "")),
            scope=str(payload.get("scope", "")),
            unit=str(payload.get("unit", "")),
            currency=str(payload.get("currency", "")),
            accounting_basis=str(payload.get("accounting_basis", "")),
            entity_id=str(payload.get("entity_id", "")),
            source_as_of_utc=str(payload.get("source_as_of_utc", "")),
            supersedes_evidence_id=payload.get("supersedes_evidence_id"),
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


def _parse_utc_timestamp(value: str, field_name: str) -> datetime:
    validate_timestamp(value, field_name)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _critical_guard(result: ExposureResult, readiness_critical: bool) -> ExposureResult:
    if readiness_critical and result.status is ExposureStatus.UNKNOWN:
        return _blocked("critical_unknown")
    return result


def assess_exposure_from_evidence(
    *,
    evidence_inputs: tuple[ExposureEvidence, ...],
    period_start: str,
    period_end: str,
    period_type: str,
    scope: str,
    currency: str,
    unit: str,
    accounting_basis: str,
    entity_id: str,
    as_of_utc: str,
    denominator_value: Decimal | None = None,
    allow_superseded: bool = False,
    readiness_critical: bool = False,
) -> ExposureResult:
    try:
        as_of_dt = _parse_utc_timestamp(_require_text(as_of_utc, "as_of_utc"), "as_of_utc")
    except (TypeError, ValueError):
        return _blocked("malformed_as_of_utc")

    if not isinstance(evidence_inputs, tuple):
        return _blocked("malformed_evidence_inputs")

    if not evidence_inputs:
        return _critical_guard(_unknown(), readiness_critical)

    try:
        period_start = _require_text(period_start, "period_start")
        period_end = _require_text(period_end, "period_end")
        period_type = _require_text(period_type, "period_type")
        scope = _require_text(scope, "scope")
        currency = _require_text(currency, "currency")
        unit = _require_text(unit, "unit")
        accounting_basis = _require_text(accounting_basis, "accounting_basis")
        entity_id = _require_text(entity_id, "entity_id")
    except ValueError:
        return _blocked("malformed_selection_context")

    seen_ids: set[str] = set()
    for evidence in evidence_inputs:
        if evidence.evidence_id in seen_ids:
            return _blocked("duplicate_evidence_id")
        seen_ids.add(evidence.evidence_id)

    aligned = tuple(
        evidence
        for evidence in evidence_inputs
        if evidence.period_start == period_start
        and evidence.period_end == period_end
        and evidence.period_type == period_type
    )
    if not aligned:
        return _blocked("period_mismatch")

    aligned = tuple(evidence for evidence in aligned if evidence.scope == scope)
    if not aligned:
        return _blocked("scope_mismatch")

    aligned = tuple(
        evidence
        for evidence in aligned
        if evidence.unit == unit
        and evidence.currency == currency
        and evidence.accounting_basis == accounting_basis
    )
    if not aligned:
        return _blocked("unit_currency_accounting_basis_mismatch")

    aligned = tuple(evidence for evidence in aligned if evidence.entity_id == entity_id)
    if not aligned:
        return _blocked("entity_mismatch")

    aligned = tuple(
        evidence
        for evidence in aligned
        if _parse_utc_timestamp(evidence.source_as_of_utc, "source_as_of_utc") <= as_of_dt
    )
    if not aligned:
        return _blocked("source_timestamp_unavailable")

    denominators = tuple(evidence.denominator_value for evidence in aligned if evidence.denominator_value is not None)
    if denominator_value is None:
        if not denominators:
            return _blocked("missing_denominator")
        unique_denominators = tuple({denominator for denominator in denominators})
        if len(unique_denominators) != 1:
            return _blocked("ambiguous_denominator")
        denominator_value = unique_denominators[0]
    else:
        if any(evidence.denominator_value is None for evidence in aligned):
            return _blocked("missing_denominator")
        if any(evidence.denominator_value != denominator_value for evidence in aligned):
            return _blocked("denominator_mismatch")

    aligned = tuple(evidence for evidence in aligned if evidence.denominator_value == denominator_value)
    if not aligned:
        return _blocked("denominator_mismatch")

    if not allow_superseded:
        aligned_ids = {evidence.evidence_id for evidence in aligned}
        if any(
            evidence.supersedes_evidence_id in aligned_ids
            for evidence in aligned
            if evidence.supersedes_evidence_id is not None
        ):
            return _blocked("stale_superseded_evidence")
    else:
        superseded = {
            evidence.supersedes_evidence_id
            for evidence in aligned
            if evidence.supersedes_evidence_id is not None
        }
        aligned = tuple(evidence for evidence in aligned if evidence.evidence_id not in superseded)
        if not aligned:
            return _blocked("stale_superseded_evidence")

    if len(aligned) != 1:
        return _blocked("duplicate_or_double_count")

    selected = aligned[0]
    return _critical_guard(
        assess_exposure(
            numerator_value=selected.numerator_value,
            numerator_low=selected.numerator_low,
            numerator_high=selected.numerator_high,
            denominator_value=denominator_value,
        ),
        readiness_critical,
    )


def assess_exposure_from_evidence_inputs(
    *,
    evidence_inputs: tuple[ExposureEvidence, ...],
    period_start: str,
    period_end: str,
    period_type: str,
    scope: str,
    currency: str,
    unit: str,
    accounting_basis: str,
    entity_id: str,
    as_of_utc: str,
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


def assess_exposure_from_evidence_rows(
    *,
    evidence_rows: tuple[ExposureEvidence, ...],
    period_start: str,
    period_end: str,
    period_type: str,
    scope: str,
    currency: str,
    unit: str,
    accounting_basis: str,
    entity_id: str,
    as_of_utc: str,
    denominator_value: Decimal | None = None,
    allow_superseded: bool = False,
    readiness_critical: bool = False,
) -> ExposureResult:
    return assess_exposure_from_evidence(
        evidence_inputs=evidence_rows,
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
