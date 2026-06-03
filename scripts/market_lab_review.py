#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_lab.broker import LEDGER_PATH, OrderDecision
from market_lab.config import EVIDENCE_DIR, ensure_dirs
from market_lab.data import fetch_prices
from market_lab.diagnosis import TradeDiagnosis, decision_id, diagnose_trade, generate_strategy_health_report
from market_lab.evidence import append_atomic_jsonl_batch, evidence_stream_path, load_evidence_records


def _load_accepted_decisions(path: Path = LEDGER_PATH) -> list[OrderDecision]:
    if not path.exists():
        return []
    decisions: list[OrderDecision] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            decision = OrderDecision(**data)
            if decision.accepted and decision.fill_price is not None:
                decisions.append(decision)
    return decisions


def _existing_ids(path: Path) -> set[str]:
    return {str(record.get("decision_id")) for record in load_evidence_records(path) if record.get("decision_id")}


def _latest_trade_records_by_decision(path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for record in load_evidence_records(path):
        record_id = record.get("decision_id")
        if not record_id:
            continue
        current = latest.get(str(record_id))
        if current is None or int(record.get("holding_bars", 0)) >= int(current.get("holding_bars", 0)):
            latest[str(record_id)] = record
    return latest


def _canonical_record(record: dict) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def _decision_date(decision: OrderDecision) -> date:
    if decision.execution_date:
        return date.fromisoformat(decision.execution_date)
    return datetime.fromisoformat(decision.timestamp.replace("Z", "+00:00")).date()


def _bars_from_decision_date(bars, decision: OrderDecision):
    entry_date = _decision_date(decision)
    return [bar for bar in bars if bar.date >= entry_date]


def _has_later_sell(decision: OrderDecision, decisions: list[OrderDecision]) -> bool:
    entry_date = _decision_date(decision)
    return any(
        other.accepted
        and other.side == "SELL"
        and other.symbol == decision.symbol
        and _decision_date(other) > entry_date
        for other in decisions
    )


def _latest_trade_diagnoses() -> list[TradeDiagnosis]:
    latest: dict[str, TradeDiagnosis] = {}
    for record in load_evidence_records(evidence_stream_path("trades", EVIDENCE_DIR)):
        diagnosis = TradeDiagnosis(**record)
        current = latest.get(diagnosis.decision_id)
        if current is None or diagnosis.holding_bars >= current.holding_bars:
            latest[diagnosis.decision_id] = diagnosis
    return list(latest.values())


def _open_buy_decision_ids(decisions: list[OrderDecision]) -> set[str]:
    lots_by_symbol: dict[str, list[tuple[str, int]]] = {}
    for decision in decisions:
        if not decision.accepted or decision.fill_price is None:
            continue
        symbol = decision.symbol.upper()
        if decision.side == "BUY":
            lots_by_symbol.setdefault(symbol, []).append((decision_id(decision), decision.quantity))
            continue
        if decision.side == "SELL":
            remaining_sell = decision.quantity
            updated_lots: list[tuple[str, int]] = []
            for lot_id, open_qty in lots_by_symbol.get(symbol, []):
                if remaining_sell <= 0:
                    updated_lots.append((lot_id, open_qty))
                    continue
                reduction = min(open_qty, remaining_sell)
                updated_lots.append((lot_id, open_qty - reduction))
                remaining_sell -= reduction
            lots_by_symbol[symbol] = updated_lots
    return {lot_id for lots in lots_by_symbol.values() for lot_id, qty in lots if qty > 0}


def diagnose_new_mock_decisions(days: int = 45, prefer_network: bool = False) -> list[TradeDiagnosis]:
    ensure_dirs()
    trades_path = evidence_stream_path("trades", EVIDENCE_DIR)
    decisions = _load_accepted_decisions()
    latest_existing = _latest_trade_records_by_decision(trades_path)
    open_buy_ids = _open_buy_decision_ids(decisions)
    diagnoses: list[TradeDiagnosis] = []
    for decision in decisions:
        if decision.side != "BUY":
            # Accepted SELL decisions close/reduce long positions in the current mock
            # broker. They are accounted for by FIFO lot reduction in _open_buy_decision_ids.
            continue
        if decision_id(decision) not in open_buy_ids:
            # Fully closed lots wait for a future round-trip reconstruction gate.
            continue
        # Use only bars on/after the fill date. If there is no post-entry bar yet,
        # wait instead of fabricating a diagnosis from pre-entry prices.
        bars, source = fetch_prices(decision.symbol, days=days, prefer_network=prefer_network)
        entry_date = _decision_date(decision)
        if not bars or bars[0].date > entry_date:
            continue
        bars = _bars_from_decision_date(bars, decision)
        if len(bars) < 2:
            continue
        diagnosis = diagnose_trade(
            decision,
            bars,
            strategy=decision.strategy,
            evidence_snapshot={"ledger_reason": decision.reason},
            benchmark_return=0.0,
            data_quality="synthetic" if "synthetic" in source.lower() else "live_or_cache",
        )
        existing = latest_existing.get(diagnosis.decision_id)
        if existing is not None:
            existing_holding_bars = int(existing.get("holding_bars", 0))
            if diagnosis.holding_bars < existing_holding_bars:
                continue
            if diagnosis.holding_bars == existing_holding_bars and _canonical_record(diagnosis.as_record()) == _canonical_record(existing):
                continue
        diagnoses.append(diagnosis)
    if diagnoses:
        append_atomic_jsonl_batch([d.as_record() for d in diagnoses], trades_path)
    return diagnoses


def write_health_reports() -> list[dict]:
    trades = _latest_trade_diagnoses()
    health_path = evidence_stream_path("strategy_health", EVIDENCE_DIR)
    existing_by_strategy: dict[str, dict] = {}
    for record in load_evidence_records(health_path):
        strategy = record.get("strategy")
        if strategy:
            existing_by_strategy[str(strategy)] = record
    reports = []
    for strategy in sorted({trade.strategy for trade in trades}):
        report = generate_strategy_health_report(strategy, trades).as_record()
        existing = existing_by_strategy.get(strategy)
        if existing is not None and _canonical_record(existing) == _canonical_record(report):
            continue
        reports.append(report)
    if reports:
        append_atomic_jsonl_batch(reports, health_path)
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description="Review Market Lab mock trades and append council evidence artifacts")
    parser.add_argument("--days", type=int, default=45)
    parser.add_argument("--network", action="store_true")
    args = parser.parse_args()

    diagnoses = diagnose_new_mock_decisions(days=args.days, prefer_network=args.network)
    health_reports = write_health_reports()
    print(f"new_diagnoses={len(diagnoses)}")
    print(f"health_reports={len(health_reports)}")
    if health_reports:
        print(json.dumps(health_reports[-1], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
