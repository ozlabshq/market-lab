#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_lab.broker import (
    OrderCandidate,
    Portfolio,
    Position,
    candidate_to_order_at_open,
    load_order_candidates,
    load_portfolio,
    save_order_candidates,
    save_portfolio,
)
from market_lab.config import (
    RISK,
    TSMOM_CANDIDATES,
    TSMOM_LEDGER,
    TSMOM_REPORT_DIR,
    TSMOM_STARTING_CASH,
    TSMOM_STATE,
    ensure_dirs,
)
from market_lab.data import fetch_prices
from market_lab.signals import generate_tsmom_signal


def _source_is_synthetic(source: str) -> bool:
    return "synthetic" in source.lower()


def _current_weight(portfolio: Portfolio, symbol: str, price: float) -> float:
    equity = portfolio.equity({symbol: price})
    if equity <= 0:
        return 0.0
    pos = portfolio.positions.get(symbol.upper())
    if not pos:
        return 0.0
    return (pos.quantity * price) / equity


def _candidate_from_tsmom_signal(
    sig, signal_date: str, portfolio: Portfolio, price: float
) -> OrderCandidate | None:
    target_weight = float(sig.target_weight)
    current_weight = _current_weight(portfolio, sig.symbol, price)
    delta = target_weight - current_weight
    threshold = 0.001
    if abs(delta) <= threshold:
        return None
    equity = max(portfolio.equity({sig.symbol: price}), 1.0)
    notional = abs(delta) * equity
    # Respect mock broker risk gates
    notional = min(notional, RISK.max_trade_notional, equity * RISK.max_single_order_pct)
    if notional < RISK.min_trade_notional:
        return None
    qty = max(1, int(notional // price))
    side = "BUY" if delta > 0 else "SELL"
    # Cap SELL qty at current position
    if side == "SELL":
        pos = portfolio.positions.get(sig.symbol.upper())
        max_qty = pos.quantity if pos else 0
        qty = min(qty, max_qty)
        if qty <= 0:
            return None
    return OrderCandidate(
        side=side,
        symbol=sig.symbol,
        quantity=qty,
        strategy="tsmom",
        confidence=sig.confidence,
        reason=sig.reason,
        signal_date=signal_date,
        reference_close=sig.close,
    )


def _dedupe_candidates(candidates: list[OrderCandidate]) -> list[OrderCandidate]:
    by_key = {}
    for candidate in candidates:
        key = (candidate.symbol, candidate.signal_date, candidate.strategy, candidate.side)
        by_key[key] = candidate
    return list(by_key.values())


def _execute_due_candidates(bars, prices, state_path, ledger_path, require_live_data=False, source="synthetic"):
    pending = load_order_candidates(path=state_path.with_name("pending_candidates.jsonl"))
    if not pending:
        return [], []
    if require_live_data and _source_is_synthetic(source):
        return [], pending
    decisions = []
    remaining = []
    latest_date = bars[-1].date.isoformat() if bars else None
    # Hard max fill rate: at most 1 fill per symbol per day
    filled_today: set[str] = set()
    for candidate in pending:
        if latest_date and latest_date > candidate.signal_date:
            if candidate.symbol.upper() in filled_today:
                remaining.append(candidate)
                continue
            decision = candidate_to_order_at_open(
                candidate,
                next_open=bars[-1].open,
                prices=prices,
                portfolio_path=state_path,
                ledger_path=ledger_path,
                execution_date=bars[-1].date.isoformat(),
            )
            decisions.append(decision)
            filled_today.add(candidate.symbol.upper())
        else:
            remaining.append(candidate)
    save_order_candidates(remaining, path=state_path.with_name("pending_candidates.jsonl"))
    return decisions, remaining


def _load_or_init_portfolio(path: Path) -> Portfolio:
    if path.exists():
        return load_portfolio(path)
    portfolio = Portfolio(cash=TSMOM_STARTING_CASH, positions={})
    save_portfolio(portfolio, path)
    return portfolio


def _tracking_start_date(portfolio: Portfolio, ledger_path: Path) -> date | None:
    # Prefer a stored start date in portfolio state metadata; fallback to first ledger entry
    if ledger_path.exists():
        try:
            with ledger_path.open() as f:
                first_line = next((line.strip() for line in f if line.strip()), None)
                if first_line:
                    data = json.loads(first_line)
                    ts = data.get("execution_date") or data.get("timestamp", "")[:10]
                    if ts:
                        return date.fromisoformat(ts)
        except Exception:
            pass
    return None


def _render_tsmom_report(
    portfolio: Portfolio,
    price: float,
    sig,
    decisions: list,
    pending: list,
    days_active: int,
    fills_count: int,
    source: str,
) -> str:
    equity = portfolio.equity({sig.symbol: price})
    pos = portfolio.positions.get(sig.symbol.upper())
    pos_qty = pos.quantity if pos else 0
    pos_avg = pos.avg_price if pos else 0.0
    weight = _current_weight(portfolio, sig.symbol, price)
    target = float(sig.target_weight)
    evidence = dict(sig.evidence) if sig.evidence else {}
    vol20 = evidence.get("vol20", 0.0)
    raw_momentum = evidence.get("raw_momentum", 0.0)
    drawdown_from_peak = evidence.get("drawdown_from_peak", 0.0)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M %Z")
    lines = [
        f"# TSMOM Independent Mock Tracking — {now}",
        "",
        "Status: Research tracking — not wired into ensemble. Evidence collected daily.",
        "",
        f"## Day {days_active}/30",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Cash | ${portfolio.cash:,.2f} |",
        f"| Position | {pos_qty} shares {sig.symbol} @ ${pos_avg:.2f} avg |",
        f"| Equity | ${equity:,.2f} |",
        f"| Position weight | {weight*100:.1f}% |",
        f"| Target weight | {target*100:.1f}% |",
        f"| Vol20 (ann.) | {vol20*100:.1f}% |",
        f"| Raw momentum | {raw_momentum*100:.1f}% |",
        f"| Drawdown from 120d peak | {drawdown_from_peak*100:.1f}% |",
        f"| Cumulative fills | {fills_count} |",
        f"| Pending candidates | {len(pending)} |",
        f"| Data source | {source} |",
        "",
        "## Decisions today",
    ]
    if not decisions:
        lines.append("- No fills")
    for d in decisions:
        status = "ACCEPTED" if d.accepted else "REJECTED"
        fill = f" fill ${d.fill_price:.2f}" if d.fill_price else ""
        lines.append(f"- {status} {d.side} {d.quantity} {d.symbol} @ ${d.requested_price:.2f}{fill}: {d.reason}")
    lines += [
        "",
        "## Safety",
        "- Live trading disabled",
        "- Separate TSMOM ledger/state (isolated from main portfolio and vt_trend)",
        "- No ensemble wiring",
        "",
        "*Research/paper-only. No live broker orders. No investment advice.*",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run TSMOM independent mock tracking")
    parser.add_argument("--network", action="store_true", help="Attempt yfinance before cache/synthetic fallback")
    parser.add_argument("--require-live-data", action="store_true", help="Abort if any symbol falls back to synthetic data")
    parser.add_argument("--days", type=int, default=260)
    parser.add_argument("--symbol", default="SPY")
    args = parser.parse_args()

    ensure_dirs()
    symbol = args.symbol.upper()
    bars, source = fetch_prices(symbol, days=args.days, prefer_network=args.network)
    if not bars:
        print(f"No price data for {symbol}", file=sys.stderr)
        return 1

    if args.require_live_data and _source_is_synthetic(source):
        print(f"Refusing TSMOM tracking because {symbol} data is synthetic ({source})", file=sys.stderr)
        return 1

    price = bars[-1].close
    signal_date = bars[-1].date.isoformat()

    portfolio = _load_or_init_portfolio(TSMOM_STATE)
    sig = generate_tsmom_signal(symbol, bars)

    # Queue candidate if weight differs
    candidate = _candidate_from_tsmom_signal(sig, signal_date, portfolio, price)
    if candidate:
        existing = load_order_candidates(path=TSMOM_CANDIDATES)
        existing.append(candidate)
        save_order_candidates(_dedupe_candidates(existing), path=TSMOM_CANDIDATES)

    # Execute due candidates
    decisions, remaining = _execute_due_candidates(
        bars, {symbol: price}, TSMOM_STATE, TSMOM_LEDGER,
        require_live_data=args.require_live_data, source=source,
    )

    # Re-load portfolio after fills
    portfolio = load_portfolio(TSMOM_STATE)

    # Compute tracking metrics
    start_date = _tracking_start_date(portfolio, TSMOM_LEDGER)
    days_active = (date.today() - start_date).days + 1 if start_date else 0
    fills_count = 0
    if TSMOM_LEDGER.exists():
        try:
            with TSMOM_LEDGER.open() as f:
                fills_count = sum(1 for line in f if line.strip() and json.loads(line).get("accepted"))
        except Exception:
            pass

    report = _render_tsmom_report(
        portfolio, price, sig, decisions, remaining, days_active, fills_count, source,
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = TSMOM_REPORT_DIR / f"tsmom-{stamp}.md"
    report_path.write_text(report)
    latest = TSMOM_REPORT_DIR / "latest.md"
    latest.write_text(report)

    print(report_path)
    print(report)

    if days_active >= 30 and start_date:
        print(f"\n--- 30-day tracking window complete (started {start_date.isoformat()}) ---")
        # TODO: compute go/no-go summary in a follow-up card

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
