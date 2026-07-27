from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Any

from market_lab.prediction_markets.errors import SchemaError

DECIMAL_QUANT = Decimal("0.000001")
FROZEN_SCHEMA = "mlab-pm-frozen.v1"
MARKET_SCHEMA = "mlab-pm-market.v1"
NORMALIZER_VERSION = "binary-normalizer@1"
ADMISSIBILITY = ("DISCOVERY_ONLY", "QUOTE_ADMISSIBLE", "RESEARCH_ADMISSIBLE", "QUARANTINED")
STATUSES = ("DRAFT", "OPEN", "HALTED", "CLOSED", "PENDING", "DISPUTED", "RESOLVED", "VOID", "CANCELLED")
IDENTITY_RE = re.compile(r"^[A-Za-z0-9._-]+$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
RFC3339Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass(frozen=True, slots=True)
class OutcomeSnapshot:
    provider_outcome_id: str
    label: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    last: Decimal | None
    bid_size: Decimal | None
    ask_size: Decimal | None


@dataclass(frozen=True, slots=True)
class MarketSnapshotV1:
    schema_version: str
    snapshot_id: str
    market_key: str
    normalized_record_hash: str
    normalizer_version: str
    source_class: str
    capture_adapter_version: str
    provider_id: str
    legal_entity_id: str
    venue_id: str
    api_surface_id: str
    jurisdiction_eligibility_status: str
    terms_version: str
    terms_sha256: str
    provider_market_id: str
    request_method: str
    request_url: str
    retrieved_at_utc: str
    observed_at_utc: str
    provider_updated_at_utc: str | None
    raw_content_type: str
    raw_sha256: str
    retention_note: str
    title: str
    description: str | None
    market_type: str
    status: str
    currency: str
    payout_unit: Decimal
    tick_size: Decimal
    opens_at_utc: str | None
    closes_at_utc: str
    scheduled_resolution_at_utc: str | None
    rules_version: str
    rules_text: str | None
    rules_url: str | None
    resolution_source_description: str | None
    resolution_source_url: str | None
    void_policy: str | None
    fee_schedule_id: str | None
    fee_schedule_version: str | None
    fee_schedule_url: str | None
    outcomes: tuple[OutcomeSnapshot, OutcomeSnapshot]
    rules_hash: str | None
    admissibility: str
    inadmissibility_reasons: tuple[str, ...]


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_json_bytes(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchemaError("descriptor must be UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SchemaError("descriptor must be a JSON object")
    return value


def strict_raw_body(descriptor: dict[str, Any]) -> bytes:
    raw64 = _require_str(descriptor, "raw_body_base64")
    try:
        raw = base64.b64decode(raw64.encode("ascii"), validate=True)
    except Exception as exc:
        raise SchemaError("raw_body_base64 must be strict RFC4648 base64") from exc
    if sha256_hex(raw) != descriptor.get("raw_sha256"):
        raise SchemaError("raw_sha256 does not match raw_body_base64")
    return raw


def normalize_descriptor(descriptor: dict[str, Any]) -> MarketSnapshotV1:
    _closed(descriptor, {
        "schema_version", "source_class", "capture_adapter_version", "provider_id", "legal_entity_id",
        "venue_id", "api_surface_id", "jurisdiction_eligibility_status", "terms_version", "terms_sha256",
        "provider_market_id", "request_method", "request_url", "retrieved_at_utc", "observed_at_utc",
        "provider_updated_at_utc", "raw_content_type", "raw_sha256", "raw_body_base64", "retention_note", "market",
    })
    if descriptor.get("schema_version") != FROZEN_SCHEMA or descriptor.get("source_class") != "frozen_fixture":
        raise SchemaError("descriptor schema_version/source_class is not supported")
    for field in (
        "capture_adapter_version", "jurisdiction_eligibility_status", "request_url",
        "raw_content_type", "retention_note",
    ):
        _nonblank_str(descriptor, field)
    for field in ("provider_id", "legal_entity_id", "venue_id", "api_surface_id", "provider_market_id", "terms_version"):
        _identity(_require_str(descriptor, field), field)
    for field in ("terms_sha256", "raw_sha256"):
        if not HASH_RE.match(_require_str(descriptor, field)):
            raise SchemaError(f"{field} must be lowercase sha256 hex")
    if descriptor.get("request_method") != "GET":
        raise SchemaError("request_method must be GET")
    for field in ("retrieved_at_utc", "observed_at_utc"):
        _time(_require_str(descriptor, field), field)
    updated = descriptor.get("provider_updated_at_utc")
    if updated is not None:
        _time(_require_str(descriptor, "provider_updated_at_utc"), "provider_updated_at_utc")
    raw = strict_raw_body(descriptor)
    market = _market(_require_map(descriptor, "market"))
    reasons = _admissibility_reasons(descriptor, market)
    admissibility = "RESEARCH_ADMISSIBLE" if not reasons else ("QUOTE_ADMISSIBLE" if _has_quote(market) else "DISCOVERY_ONLY")
    rules_hash = sha256_hex(market["rules_text"].encode("utf-8")) if market["rules_text"] is not None else None
    outcomes = tuple(_outcome_obj(out) for out in market["outcomes"])
    base = {
        "schema_version": MARKET_SCHEMA,
        "snapshot_id": "sha256:" + sha256_hex(raw),
        "market_key": f"{descriptor['provider_id']}:{descriptor['provider_market_id']}:{market['rules_version']}",
        "normalizer_version": NORMALIZER_VERSION,
        "source_class": descriptor["source_class"],
        **{k: descriptor[k] for k in (
            "capture_adapter_version", "provider_id", "legal_entity_id", "venue_id", "api_surface_id",
            "jurisdiction_eligibility_status", "terms_version", "terms_sha256", "provider_market_id",
            "request_method", "request_url", "retrieved_at_utc", "observed_at_utc", "provider_updated_at_utc",
            "raw_content_type", "raw_sha256", "retention_note",
        )},
        **{k: market[k] for k in (
            "title", "description", "market_type", "status", "currency", "payout_unit", "tick_size",
            "opens_at_utc", "closes_at_utc", "scheduled_resolution_at_utc", "rules_version", "rules_text",
            "rules_url", "resolution_source_description", "resolution_source_url", "void_policy",
            "fee_schedule_id", "fee_schedule_version", "fee_schedule_url",
        )},
        "outcomes": [_outcome_dict(o) for o in outcomes],
        "rules_hash": rules_hash,
        "admissibility": admissibility,
        "inadmissibility_reasons": sorted(set(reasons)),
    }
    digestable = _json_ready({**base, "normalized_record_hash": None})
    record_hash = sha256_hex(canonical_json_bytes(digestable))
    return MarketSnapshotV1(normalized_record_hash=record_hash, outcomes=outcomes, inadmissibility_reasons=tuple(base["inadmissibility_reasons"]), **{k: v for k, v in base.items() if k not in ("outcomes", "inadmissibility_reasons")})


def record_to_dict(record: MarketSnapshotV1) -> dict[str, Any]:
    value = {field: getattr(record, field) for field in record.__dataclass_fields__}
    value["outcomes"] = [_outcome_dict(out) for out in record.outcomes]
    value["inadmissibility_reasons"] = list(record.inadmissibility_reasons)
    return _json_ready(value)


def record_from_dict(value: dict[str, Any]) -> MarketSnapshotV1:
    _closed(value, set(MarketSnapshotV1.__dataclass_fields__))
    if value.get("schema_version") != MARKET_SCHEMA:
        raise SchemaError("unknown normalized record schema")
    if value.get("normalizer_version") != NORMALIZER_VERSION:
        raise SchemaError("unknown normalizer_version")
    for field in (
        "snapshot_id", "market_key", "normalized_record_hash", "source_class", "capture_adapter_version",
        "provider_id", "legal_entity_id", "venue_id", "api_surface_id", "jurisdiction_eligibility_status",
        "terms_version", "provider_market_id", "request_method", "request_url", "retrieved_at_utc",
        "observed_at_utc", "raw_content_type", "raw_sha256", "retention_note", "title", "market_type",
        "status", "currency", "rules_version", "admissibility",
    ):
        _require_str(value, field)
    for field in ("description", "provider_updated_at_utc", "opens_at_utc", "scheduled_resolution_at_utc", "rules_text", "rules_url", "resolution_source_description", "resolution_source_url", "void_policy", "fee_schedule_id", "fee_schedule_version", "fee_schedule_url", "rules_hash"):
        _require_optional_str(value, field)
    if not value["snapshot_id"].startswith("sha256:") or not HASH_RE.match(value["snapshot_id"][7:]):
        raise SchemaError("snapshot_id must be sha256 hash identity")
    if not HASH_RE.match(value["normalized_record_hash"]) or not HASH_RE.match(value["raw_sha256"]) or not HASH_RE.match(value["terms_sha256"]):
        raise SchemaError("record hashes must be lowercase sha256 hex")
    if value["request_method"] != "GET" or value["source_class"] != "frozen_fixture":
        raise SchemaError("record source/request fields are invalid")
    for field in ("provider_id", "legal_entity_id", "venue_id", "api_surface_id", "provider_market_id", "terms_version", "rules_version"):
        _identity(value[field], field)
    for field in ("retrieved_at_utc", "observed_at_utc", "closes_at_utc"):
        _time(_require_str(value, field), field)
    for field in ("provider_updated_at_utc", "opens_at_utc", "scheduled_resolution_at_utc"):
        if value[field] is not None:
            _time(value[field], field)
    if value["status"] not in STATUSES or value["market_type"] != "binary" or value["admissibility"] not in ADMISSIBILITY:
        raise SchemaError("record enum field is invalid")
    if not isinstance(value.get("inadmissibility_reasons"), list) or any(not isinstance(x, str) or not x for x in value["inadmissibility_reasons"]):
        raise SchemaError("inadmissibility_reasons must be strings")
    if sorted(set(value["inadmissibility_reasons"])) != value["inadmissibility_reasons"]:
        raise SchemaError("inadmissibility_reasons must be sorted unique")
    outcomes = tuple(_outcome_obj(out) for out in value["outcomes"])
    if len(outcomes) != 2:
        raise SchemaError("record must have two outcomes")
    data = dict(value)
    data["outcomes"] = outcomes
    data["inadmissibility_reasons"] = tuple(value.get("inadmissibility_reasons", []))
    for field in ("payout_unit", "tick_size"):
        data[field] = parse_decimal(value[field], field)
    return MarketSnapshotV1(**data)


def validate_record_hash(record: MarketSnapshotV1) -> None:
    data = record_to_dict(record)
    expected = data["normalized_record_hash"]
    data["normalized_record_hash"] = None
    if sha256_hex(canonical_json_bytes(data)) != expected:
        raise SchemaError("normalized_record_hash mismatch")


def parse_decimal(value: Any, field: str, *, positive: bool = False, nonnegative: bool = True) -> Decimal:
    if not isinstance(value, str) or not re.match(r"^-?\d+\.\d{6}$", value):
        raise SchemaError(f"{field} must be canonical six-place decimal string")
    try:
        dec = Decimal(value)
    except InvalidOperation as exc:
        raise SchemaError(f"{field} must be decimal") from exc
    if not dec.is_finite():
        raise SchemaError(f"{field} must be finite")
    if positive and dec <= 0:
        raise SchemaError(f"{field} must be positive")
    if nonnegative and dec < 0:
        raise SchemaError(f"{field} must be nonnegative")
    if dec.quantize(DECIMAL_QUANT) != dec:
        raise SchemaError(f"{field} must have six decimal places")
    return dec


def decimal_str(value: Decimal) -> str:
    return format(value.quantize(DECIMAL_QUANT), "f")


def validate_rfc3339z(value: str, field: str) -> None:
    _time(value, field)


def _market(value: dict[str, Any]) -> dict[str, Any]:
    _closed(value, {
        "title", "description", "market_type", "status", "currency", "payout_unit", "tick_size",
        "opens_at_utc", "closes_at_utc", "scheduled_resolution_at_utc", "rules_version", "rules_text",
        "rules_url", "resolution_source_description", "resolution_source_url", "void_policy",
        "fee_schedule_id", "fee_schedule_version", "fee_schedule_url", "outcomes",
    })
    title = _require_str(value, "title")
    if not title.strip() or value.get("market_type") != "binary" or value.get("status") not in STATUSES:
        raise SchemaError("invalid market identity/type/status")
    for field in ("currency",):
        _identity(_require_str(value, field), field)
    for field in ("description", "rules_text", "rules_url", "resolution_source_description", "resolution_source_url", "void_policy", "fee_schedule_id", "fee_schedule_version", "fee_schedule_url"):
        _require_optional_str(value, field)
    payout = parse_decimal(value.get("payout_unit"), "payout_unit", positive=True)
    tick = parse_decimal(value.get("tick_size"), "tick_size", positive=True)
    for field in ("closes_at_utc",):
        _time(_require_str(value, field), field)
    for field in ("opens_at_utc", "scheduled_resolution_at_utc"):
        if value.get(field) is not None:
            _time(_require_str(value, field), field)
    if value.get("opens_at_utc") and value["opens_at_utc"] > value["closes_at_utc"]:
        raise SchemaError("opens_at_utc must not be after closes_at_utc")
    _identity(_require_str(value, "rules_version"), "rules_version")
    outcomes = value.get("outcomes")
    if not isinstance(outcomes, list) or len(outcomes) != 2:
        raise SchemaError("binary markets require exactly two outcomes")
    parsed = [_outcome(o, payout, tick) for o in outcomes]
    if sorted(o["label"] for o in parsed) != ["NO", "YES"]:
        raise SchemaError("outcomes must be exactly YES and NO")
    if len({o["provider_outcome_id"] for o in parsed}) != 2:
        raise SchemaError("outcome ids must be distinct")
    yes = [o for o in parsed if o["label"] == "YES"][0]
    no = [o for o in parsed if o["label"] == "NO"][0]
    if yes["best_bid"] is not None and yes["best_ask"] is not None and yes["best_bid"] > yes["best_ask"]:
        raise SchemaError("YES book is crossed")
    if no["best_bid"] is not None and no["best_ask"] is not None and no["best_bid"] > no["best_ask"]:
        raise SchemaError("NO book is crossed")
    out = dict(value)
    out["payout_unit"] = payout
    out["tick_size"] = tick
    out["outcomes"] = parsed
    return out


def _outcome(value: dict[str, Any], payout: Decimal, tick: Decimal) -> dict[str, Any]:
    _closed(value, {"provider_outcome_id", "label", "best_bid", "best_ask", "last", "bid_size", "ask_size"})
    _identity(_require_str(value, "provider_outcome_id"), "provider_outcome_id")
    if value.get("label") not in ("YES", "NO"):
        raise SchemaError("outcome label must be YES or NO")
    out = {"provider_outcome_id": value["provider_outcome_id"], "label": value["label"]}
    for field in ("best_bid", "best_ask", "last", "bid_size", "ask_size"):
        item = value.get(field)
        out[field] = None if item is None else parse_decimal(item, field)
        if out[field] is not None and field in ("best_bid", "best_ask", "last"):
            if out[field] > payout or (out[field] / tick) != (out[field] / tick).to_integral_value():
                raise SchemaError(f"{field} violates payout or tick")
    return out


def _outcome_obj(value: dict[str, Any]) -> OutcomeSnapshot:
    _closed(value, {"provider_outcome_id", "label", "best_bid", "best_ask", "last", "bid_size", "ask_size"})
    def dec(field: str) -> Decimal | None:
        item = value.get(field)
        if item is None or isinstance(item, Decimal):
            return item
        return parse_decimal(item, field)
    return OutcomeSnapshot(
        provider_outcome_id=_require_str(value, "provider_outcome_id"),
        label=_require_str(value, "label"),
        best_bid=dec("best_bid"),
        best_ask=dec("best_ask"),
        last=dec("last"),
        bid_size=dec("bid_size"),
        ask_size=dec("ask_size"),
    )


def _outcome_dict(value: OutcomeSnapshot | dict[str, Any]) -> dict[str, Any]:
    src = value if isinstance(value, dict) else {field: getattr(value, field) for field in value.__dataclass_fields__}
    return {k: (None if src[k] is None else decimal_str(src[k]) if isinstance(src[k], Decimal) else src[k]) for k in ("provider_outcome_id", "label", "best_bid", "best_ask", "last", "bid_size", "ask_size")}


def _admissibility_reasons(descriptor: dict[str, Any], market: dict[str, Any]) -> list[str]:
    reasons = []
    for field, code in (
        ("terms_version", "MISSING_TERMS_VERSION"), ("terms_sha256", "MISSING_TERMS_HASH"),
        ("jurisdiction_eligibility_status", "MISSING_JURISDICTION_STATUS"),
    ):
        if not descriptor.get(field):
            reasons.append(code)
    for field, code in (
        ("rules_text", "MISSING_RULES"), ("fee_schedule_id", "MISSING_FEE_ID"),
        ("fee_schedule_version", "MISSING_FEE_VERSION"), ("resolution_source_description", "MISSING_RESOLUTION_SOURCE"),
        ("opens_at_utc", "MISSING_OPENS_AT"), ("closes_at_utc", "MISSING_CLOSES_AT"),
    ):
        if not market.get(field):
            reasons.append(code)
    if not _has_quote(market):
        reasons.append("MISSING_COMPLETE_QUOTE")
    return reasons


def _has_quote(market: dict[str, Any]) -> bool:
    return all(o["best_bid"] is not None and o["best_ask"] is not None and o["bid_size"] is not None and o["ask_size"] is not None for o in market["outcomes"])


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_str(value)
    if isinstance(value, tuple):
        return [_json_ready(v) for v in value]
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    return value


def _closed(value: dict[str, Any], allowed: set[str]) -> None:
    if not isinstance(value, dict):
        raise SchemaError("expected object")
    extra = sorted(set(value) - allowed)
    missing = sorted(k for k in allowed if k not in value)
    if extra:
        raise SchemaError("unknown field: " + extra[0])
    if missing:
        raise SchemaError("missing field: " + missing[0])


def _require_str(value: dict[str, Any], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str):
        raise SchemaError(f"{field} must be a string")
    return item


def _nonblank_str(value: dict[str, Any], field: str) -> str:
    item = _require_str(value, field)
    if not item.strip():
        raise SchemaError(f"{field} must be nonblank")
    return item


def _require_optional_str(value: dict[str, Any], field: str) -> str | None:
    item = value.get(field)
    if item is not None and not isinstance(item, str):
        raise SchemaError(f"{field} must be a string or null")
    return item


def _require_map(value: dict[str, Any], field: str) -> dict[str, Any]:
    item = value.get(field)
    if not isinstance(item, dict):
        raise SchemaError(f"{field} must be an object")
    return item


def _identity(value: str, field: str) -> None:
    if not value or ":" in value or not IDENTITY_RE.match(value) or value in ("polymarket", "unknown"):
        raise SchemaError(f"{field} has invalid identity string")


def _time(value: str, field: str) -> None:
    if not RFC3339Z_RE.match(value):
        raise SchemaError(f"{field} must be RFC3339Z")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise SchemaError(f"{field} must be valid UTC timestamp") from exc
