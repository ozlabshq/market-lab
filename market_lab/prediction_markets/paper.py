from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import os
from pathlib import Path
import json
from typing import Any

from market_lab.prediction_markets.config import assert_below_root, assert_write_path
from market_lab.prediction_markets.errors import PaperError, PaperIntegrityError, PaperNotAdmissibleError, PaperNotSyntheticError, SchemaError
from market_lab.prediction_markets.models import canonical_json_bytes, decimal_str, parse_decimal, sha256_hex, validate_rfc3339z
from market_lab.prediction_markets.store import atomic_replace, find_record, load_records, verify


STATE_SCHEMA = "mlab-pm-paper-state.v1"
EVENT_SCHEMA = "mlab-pm-paper-event.v1"
EVENT_TYPES = {"PAPER_INITIALIZED", "PAPER_BUY_FILLED", "PAPER_SELL_FILLED", "PAPER_MARKET_SETTLED"}


@dataclass(frozen=True, slots=True)
class PaperState:
    initial_cash: Decimal
    cash: Decimal
    positions: dict[str, dict[str, Decimal]]
    realized_pnl: Decimal
    settled_markets: dict[str, str]
    last_event_hash: str | None


def init(root: Path, cash: Decimal, observed_at: str) -> dict[str, Any]:
    _load_verified(root, allow_missing=True)
    if _events_path(root).exists():
        raise PaperError("paper account already initialized")
    event = _event(None, "PAPER_INITIALIZED", observed_at, {"cash": decimal_str(cash)})
    state = _commit(root, event)
    return _state_dict(state)


def buy(root: Path, market_key: str, outcome: str, quantity: Decimal, limit_price: Decimal, fee_per_contract: Decimal, observed_at: str) -> dict[str, Any]:
    state = _load_verified(root)
    record, book = _eligible_record(root, market_key, outcome)
    if market_key in state.settled_markets:
        raise PaperError("market already settled")
    if book.best_ask is None or book.ask_size is None:
        raise PaperError("no synthetic ask available")
    if limit_price < book.best_ask:
        raise PaperError("limit price does not cross synthetic ask")
    if quantity > book.ask_size:
        raise PaperError("quantity exceeds synthetic ask depth")
    gross = quantity * book.best_ask
    fee = quantity * fee_per_contract
    if state.cash < gross + fee:
        raise PaperError("insufficient paper cash")
    event = _event(state.last_event_hash, "PAPER_BUY_FILLED", observed_at, {
        "market_key": market_key, "outcome": outcome, "quantity": decimal_str(quantity),
        "price": decimal_str(book.best_ask), "fee_per_contract": decimal_str(fee_per_contract),
        "gross": decimal_str(gross), "fee": decimal_str(fee), "synthetic_top_of_book": True,
        "snapshot_id": record.snapshot_id,
    })
    new_state = _commit(root, event)
    return {"filled": True, "cash": decimal_str(new_state.cash), "gross": decimal_str(gross), "fee": decimal_str(fee)}


def sell(root: Path, market_key: str, outcome: str, quantity: Decimal, limit_price: Decimal, fee_per_contract: Decimal, observed_at: str) -> dict[str, Any]:
    state = _load_verified(root)
    record, book = _eligible_record(root, market_key, outcome)
    key = market_key + ":" + outcome
    if market_key in state.settled_markets:
        raise PaperError("market already settled")
    if book.best_bid is None or book.bid_size is None:
        raise PaperError("no synthetic bid available")
    if limit_price > book.best_bid:
        raise PaperError("limit price does not cross synthetic bid")
    if quantity > book.bid_size:
        raise PaperError("quantity exceeds synthetic bid depth")
    if state.positions.get(key, {}).get("quantity", Decimal("0.000000")) < quantity:
        raise PaperError("naked sell is not allowed")
    gross = quantity * book.best_bid
    fee = quantity * fee_per_contract
    event = _event(state.last_event_hash, "PAPER_SELL_FILLED", observed_at, {
        "market_key": market_key, "outcome": outcome, "quantity": decimal_str(quantity),
        "price": decimal_str(book.best_bid), "fee_per_contract": decimal_str(fee_per_contract),
        "gross": decimal_str(gross), "fee": decimal_str(fee), "snapshot_id": record.snapshot_id,
    })
    new_state = _commit(root, event)
    return {"filled": True, "cash": decimal_str(new_state.cash)}


def settle(root: Path, market_key: str, winning_outcome: str, observed_at: str) -> dict[str, Any]:
    state = _load_verified(root)
    record, _ = _eligible_record(root, market_key, winning_outcome)
    if record.void_policy is not None or record.status in ("VOID", "CANCELLED"):
        raise PaperNotAdmissibleError("void or nonstandard settlement is out of scope")
    if market_key in state.settled_markets:
        raise PaperError("market already settled")
    payout_unit = record.payout_unit
    payout = Decimal("0.000000")
    for outcome in ("YES", "NO"):
        pos = state.positions.get(market_key + ":" + outcome)
        if pos and outcome == winning_outcome:
            payout += pos["quantity"] * payout_unit
    event = _event(state.last_event_hash, "PAPER_MARKET_SETTLED", observed_at, {
        "market_key": market_key, "winning_outcome": winning_outcome, "payout": decimal_str(payout),
        "settlement_source": "synthetic_operator_settlement",
    })
    new_state = _commit(root, event)
    return {"settled": True, "settlement_source": "synthetic_operator_settlement", "payout": decimal_str(payout), "cash": decimal_str(new_state.cash), "realized_pnl": decimal_str(new_state.realized_pnl)}


def portfolio(root: Path) -> dict[str, Any]:
    return _state_dict(_load_verified(root))


def ledger(root: Path) -> list[dict[str, Any]]:
    _load_verified(root)
    return _read_events(root)


def _eligible_record(root: Path, market_key: str, outcome: str):
    check = verify(root, strict=True)
    if not check["ok"]:
        raise PaperNotAdmissibleError("PM-0 verification failed")
    record = find_record(root, market_key)
    _synthetic_gate(record)
    if record.admissibility != "RESEARCH_ADMISSIBLE":
        raise PaperNotAdmissibleError("market is not RESEARCH_ADMISSIBLE")
    if record.status != "OPEN":
        raise PaperNotAdmissibleError("market is not OPEN")
    for out in record.outcomes:
        if out.label == outcome:
            return record, out
    raise PaperError("requested outcome is not present")


def _synthetic_gate(record) -> None:
    if not (record.source_class == "frozen_fixture" and record.provider_id == "synthetic_fixture" and record.legal_entity_id == "synthetic_fixture" and record.venue_id == "synthetic_binary_lab" and record.api_surface_id == "frozen_descriptor_v1"):
        raise PaperNotSyntheticError("paper trading is limited to synthetic frozen fixtures")


def _event(previous: str | None, event_type: str, observed_at: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_rfc3339z(observed_at, "observed-at")
    except SchemaError as exc:
        raise PaperError("observed-at must be deterministic RFC3339Z") from exc
    if event_type not in EVENT_TYPES:
        raise PaperError("unknown paper event type")
    base = {"schema_version": EVENT_SCHEMA, "event_type": event_type, "observed_at_utc": observed_at, "previous_event_hash": previous, "payload": payload}
    event_id = sha256_hex(canonical_json_bytes(base))
    event = {**base, "event_id": event_id}
    event_hash = sha256_hex(canonical_json_bytes(event))
    return {**event, "event_hash": event_hash}


def _append(root: Path, event: dict[str, Any]) -> None:
    path = assert_write_path(root, _events_path(root))
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(event) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _commit(root: Path, event: dict[str, Any]) -> PaperState:
    events = _read_events(root)
    new_state = _state_from_events(root, [*events, event])
    _append(root, event)
    _write_state(root, new_state)
    return new_state


def _load_verified(root: Path, *, allow_missing: bool = False) -> PaperState:
    events_exists = _events_path(root).exists()
    state_exists = _state_path(root).exists()
    if not events_exists:
        if state_exists:
            raise PaperIntegrityError("paper state exists without ledger")
        if allow_missing:
            return PaperState(Decimal("0.000000"), Decimal("0.000000"), {}, Decimal("0.000000"), {}, None)
        raise PaperError("paper account is not initialized")
    if not state_exists:
        raise PaperIntegrityError("paper ledger exists without state")
    state = _rebuild(root)
    state_path = assert_below_root(root, _state_path(root))
    if state_path.read_bytes().strip() != canonical_json_bytes(_state_dict(state)):
        raise PaperIntegrityError("paper state does not match ledger")
    return state


def _rebuild(root: Path) -> PaperState:
    return _state_from_events(root, _read_events(root))


def _state_from_events(root: Path, events: list[dict[str, Any]]) -> PaperState:
    cash = Decimal("0.000000")
    initial = Decimal("0.000000")
    positions: dict[str, dict[str, Decimal]] = {}
    realized = Decimal("0.000000")
    settled: dict[str, str] = {}
    prev = None
    initialized = False
    last_time = ""
    for event in events:
        _validate_event(event)
        if event["observed_at_utc"] < last_time:
            raise PaperIntegrityError("paper events are not timestamp ordered")
        last_time = event["observed_at_utc"]
        body = dict(event)
        event_hash = body.pop("event_hash")
        event_id = body.pop("event_id")
        if sha256_hex(canonical_json_bytes(body)) != event_id or sha256_hex(canonical_json_bytes({**body, "event_id": event_id})) != event_hash or event.get("previous_event_hash") != prev:
            raise PaperIntegrityError("paper ledger hash chain mismatch")
        payload = event["payload"]
        if event["event_type"] == "PAPER_INITIALIZED":
            if initialized or prev is not None:
                raise PaperIntegrityError("paper initialization must be first and unique")
            initialized = True
            initial = cash = parse_decimal(payload["cash"], "cash")
        elif event["event_type"] == "PAPER_BUY_FILLED":
            if not initialized:
                raise PaperIntegrityError("paper event before initialization")
            record, book = _record_for_event(root, payload["market_key"], payload["outcome"], payload["snapshot_id"])
            if payload["market_key"] in settled:
                raise PaperIntegrityError("paper buy after market settlement")
            key = payload["market_key"] + ":" + payload["outcome"]
            q = parse_decimal(payload["quantity"], "quantity")
            price = parse_decimal(payload["price"], "price")
            fee_per_contract = parse_decimal(payload["fee_per_contract"], "fee_per_contract")
            if record.status != "OPEN" or book.best_ask != price:
                raise PaperIntegrityError("paper buy does not match verified market evidence")
            if book.ask_size is None or q > book.ask_size:
                raise PaperIntegrityError("paper buy exceeds verified ask depth")
            gross = q * price
            fee = q * fee_per_contract
            if payload["gross"] != decimal_str(gross) or payload["fee"] != decimal_str(fee):
                raise PaperIntegrityError("paper buy financial identity mismatch")
            if cash < gross + fee:
                raise PaperIntegrityError("paper buy exceeds cash")
            cash -= gross + fee
            pos = positions.setdefault(key, {"quantity": Decimal("0.000000"), "cost_basis": Decimal("0.000000")})
            pos["quantity"] += q
            pos["cost_basis"] += gross + fee
        elif event["event_type"] == "PAPER_SELL_FILLED":
            if not initialized:
                raise PaperIntegrityError("paper event before initialization")
            record, book = _record_for_event(root, payload["market_key"], payload["outcome"], payload["snapshot_id"])
            if payload["market_key"] in settled:
                raise PaperIntegrityError("paper sell after market settlement")
            key = payload["market_key"] + ":" + payload["outcome"]
            q = parse_decimal(payload["quantity"], "quantity")
            price = parse_decimal(payload["price"], "price")
            fee_per_contract = parse_decimal(payload["fee_per_contract"], "fee_per_contract")
            if record.status != "OPEN" or book.best_bid != price:
                raise PaperIntegrityError("paper sell does not match verified market evidence")
            if book.bid_size is None or q > book.bid_size:
                raise PaperIntegrityError("paper sell exceeds verified bid depth")
            gross = q * price
            fee = q * fee_per_contract
            if payload["gross"] != decimal_str(gross) or payload["fee"] != decimal_str(fee):
                raise PaperIntegrityError("paper sell financial identity mismatch")
            pos = positions.get(key)
            if pos is None or pos["quantity"] < q:
                raise PaperIntegrityError("paper sell exceeds position")
            old_q = pos["quantity"]
            basis = pos["cost_basis"] * (q / old_q)
            pos["quantity"] -= q
            pos["cost_basis"] -= basis
            cash += gross - fee
            realized += gross - fee - basis
        elif event["event_type"] == "PAPER_MARKET_SETTLED":
            if not initialized:
                raise PaperIntegrityError("paper event before initialization")
            market_key = payload["market_key"]
            if market_key in settled:
                raise PaperIntegrityError("paper market settled more than once")
            record = _record_for_market(root, market_key)
            if payload["winning_outcome"] not in ("YES", "NO") or payload.get("settlement_source") != "synthetic_operator_settlement":
                raise PaperIntegrityError("invalid settlement payload")
            if record.void_policy is not None or record.status in ("VOID", "CANCELLED"):
                raise PaperIntegrityError("paper settlement does not match verified market evidence")
            payout = Decimal("0.000000")
            basis = Decimal("0.000000")
            for key in list(positions):
                if key.startswith(market_key + ":"):
                    if key.endswith(":" + payload["winning_outcome"]):
                        payout += positions[key]["quantity"] * record.payout_unit
                    basis += positions[key]["cost_basis"]
                    positions.pop(key)
            if payload["payout"] != decimal_str(payout):
                raise PaperIntegrityError("paper settlement payout mismatch")
            cash += payout
            realized += payout - basis
            settled[market_key] = payload["winning_outcome"]
        prev = event_hash
    if not initialized:
        raise PaperIntegrityError("paper ledger missing initialization")
    positions = {k: v for k, v in sorted(positions.items()) if v["quantity"] != Decimal("0.000000")}
    return PaperState(initial, cash, positions, realized, dict(sorted(settled.items())), prev)


def _record_for_event(root: Path, market_key: str, outcome: str, snapshot_id: str):
    record = _record_for_market(root, market_key, snapshot_id)
    _synthetic_gate(record)
    if record.admissibility != "RESEARCH_ADMISSIBLE":
        raise PaperIntegrityError("paper event references inadmissible market")
    for out in record.outcomes:
        if out.label == outcome:
            return record, out
    raise PaperIntegrityError("paper event references unknown outcome")


def _record_for_market(root: Path, market_key: str, snapshot_id: str | None = None):
    matches = [r for r in load_records(root) if r.market_key == market_key and (snapshot_id is None or r.snapshot_id == snapshot_id)]
    if not matches:
        raise PaperIntegrityError("paper event references missing market record")
    record = matches[-1]
    try:
        _synthetic_gate(record)
    except PaperNotSyntheticError as exc:
        raise PaperIntegrityError("paper event references non-synthetic market") from exc
    return record


def _read_events(root: Path) -> list[dict[str, Any]]:
    path = assert_below_root(root, _events_path(root))
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise PaperIntegrityError("paper ledger is not valid JSONL") from exc
    return events


def _write_state(root: Path, state: PaperState) -> None:
    atomic_replace(_state_path(root), canonical_json_bytes(_state_dict(state)) + b"\n")


def _state_dict(state: PaperState) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA, "initial_cash": decimal_str(state.initial_cash), "cash": decimal_str(state.cash),
        "positions": {k: {"quantity": decimal_str(v["quantity"]), "cost_basis": decimal_str(v["cost_basis"])} for k, v in sorted(state.positions.items())},
        "realized_pnl": decimal_str(state.realized_pnl), "settled_markets": state.settled_markets, "last_event_hash": state.last_event_hash,
    }


def _events_path(root: Path) -> Path:
    return root / "paper" / "events.jsonl"


def _state_path(root: Path) -> Path:
    return root / "paper" / "state.json"


def _validate_event(event: dict[str, Any]) -> None:
    if not isinstance(event, dict) or set(event) != {"schema_version", "event_type", "observed_at_utc", "previous_event_hash", "payload", "event_id", "event_hash"}:
        raise PaperIntegrityError("paper event schema mismatch")
    if event["schema_version"] != EVENT_SCHEMA or event["event_type"] not in EVENT_TYPES:
        raise PaperIntegrityError("paper event schema mismatch")
    try:
        validate_rfc3339z(event["observed_at_utc"], "observed_at_utc")
    except SchemaError as exc:
        raise PaperIntegrityError("paper event timestamp is invalid") from exc
    if event["previous_event_hash"] is not None and (not isinstance(event["previous_event_hash"], str) or len(event["previous_event_hash"]) != 64):
        raise PaperIntegrityError("paper previous hash is invalid")
    if not isinstance(event["event_id"], str) or len(event["event_id"]) != 64 or not isinstance(event["event_hash"], str) or len(event["event_hash"]) != 64:
        raise PaperIntegrityError("paper event hash fields are invalid")
    payload = event["payload"]
    if not isinstance(payload, dict):
        raise PaperIntegrityError("paper event payload must be object")
    required = {
        "PAPER_INITIALIZED": {"cash"},
        "PAPER_BUY_FILLED": {"market_key", "outcome", "quantity", "price", "fee_per_contract", "gross", "fee", "synthetic_top_of_book", "snapshot_id"},
        "PAPER_SELL_FILLED": {"market_key", "outcome", "quantity", "price", "fee_per_contract", "gross", "fee", "snapshot_id"},
        "PAPER_MARKET_SETTLED": {"market_key", "winning_outcome", "payout", "settlement_source"},
    }[event["event_type"]]
    if set(payload) != required:
        raise PaperIntegrityError("paper event payload schema mismatch")
    for field in ("cash", "quantity", "price", "fee_per_contract", "gross", "fee", "payout"):
        if field in payload:
            parse_decimal(payload[field], field, positive=field == "quantity")
    for field in ("market_key", "snapshot_id", "settlement_source"):
        if field in payload and not isinstance(payload[field], str):
            raise PaperIntegrityError("paper event string payload field is invalid")
    if "outcome" in payload and payload["outcome"] not in ("YES", "NO"):
        raise PaperIntegrityError("invalid paper outcome")
    if "winning_outcome" in payload and payload["winning_outcome"] not in ("YES", "NO"):
        raise PaperIntegrityError("invalid winning outcome")
    if "synthetic_top_of_book" in payload and payload["synthetic_top_of_book"] is not True:
        raise PaperIntegrityError("paper buy must identify synthetic top of book")
