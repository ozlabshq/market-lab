#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_lab.backtest import moving_average_cross_backtest, run_signal_backtest
from market_lab.broker import (
    OrderCandidate,
    candidate_to_order_at_open,
    load_order_candidates,
    load_portfolio,
    save_order_candidates,
)
from market_lab.config import DEFAULT_UNIVERSE, RISK, OPTIONS_CHAIN_DIR, OPTIONS_PAPER_STATE_PATH, OPTIONS_RISK, ensure_dirs
from market_lab.data import fetch_prices
from market_lab.factors import fetch_factors
from market_lab.options_data import fetch_option_chain_snapshot, load_available_option_chains, save_option_chain_snapshot
from market_lab.options_paper import load_option_paper_portfolio
from market_lab.options_screeners import screen_cash_secured_puts, screen_covered_calls
from market_lab.report import render_report, save_report
from market_lab.signals import (
    apply_factor_overlay,
    cross_sectional_momentum_ranks,
    generate_ensemble_signal,
    generate_strategy_signals,
    generate_tsmom_signal,
    rank_signals,
)


def _source_is_synthetic(source: str) -> bool:
    return "synthetic" in source.lower()


def _dedupe_candidates(candidates: list[OrderCandidate]) -> list[OrderCandidate]:
    by_key = {}
    for candidate in candidates:
        key = (candidate.symbol, candidate.signal_date, candidate.strategy, candidate.side)
        by_key[key] = candidate
    return list(by_key.values())


def _candidate_from_signal(sig, signal_date: str, portfolio_equity: float) -> OrderCandidate | None:
    if sig.action != "BUY" or sig.close <= 0:
        return None
    target_notional = min(RISK.max_trade_notional, max(RISK.min_trade_notional, portfolio_equity * max(sig.target_weight, 0.02)))
    qty = max(1, int(target_notional // sig.close))
    if qty * sig.close < RISK.min_trade_notional:
        return None
    return OrderCandidate("BUY", sig.symbol, qty, sig.strategy, sig.confidence, sig.reason, signal_date, sig.close)


def _execute_due_candidates(bars_by_symbol, prices):
    pending = load_order_candidates()
    if not pending:
        return [], []
    decisions = []
    remaining = []
    latest_dates = {sym: bars[-1].date.isoformat() for sym, bars in bars_by_symbol.items() if bars}
    for candidate in pending:
        bars = bars_by_symbol.get(candidate.symbol)
        if not bars:
            remaining.append(candidate)
            continue
        latest_date = latest_dates.get(candidate.symbol)
        # Candidate generated after signal_date close. Fill only once a later bar exists.
        if latest_date and latest_date > candidate.signal_date:
            decisions.append(candidate_to_order_at_open(candidate, bars[-1].open, prices, execution_date=bars[-1].date.isoformat()))
        else:
            remaining.append(candidate)
    save_order_candidates(remaining)
    return decisions, remaining


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OzLabs Market Lab daily research/report tracker")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_UNIVERSE)
    parser.add_argument("--days", type=int, default=260)
    parser.add_argument("--network", action="store_true", help="Attempt yfinance before cache/synthetic fallback")
    parser.add_argument("--queue-order-candidates", action="store_true", help="Queue next-session mock candidates instead of same-close fills")
    parser.add_argument("--execute-pending-candidates", action="store_true", help="Fill previously queued candidates at the latest bar open when a later bar is available")
    parser.add_argument("--require-live-data", action="store_true", help="Abort candidate execution/queueing if any symbol falls back to synthetic data")
    parser.add_argument("--fetch-options", action="store_true", help="Fetch and cache yfinance option chains before screening paper options")
    parser.add_argument("--max-option-symbols", type=int, default=8, help="Maximum symbols to refresh option chains for when --fetch-options is enabled")
    parser.add_argument("--max-orders", type=int, default=3)
    args = parser.parse_args()

    ensure_dirs()
    ensemble_signals = []
    family_signals = {}
    backtests = []
    prices = {}
    sources = {}
    bars_by_symbol = {}
    factors_by_symbol = {}
    decisions = []
    queued_candidates = []

    for symbol in args.symbols:
        bars, source = fetch_prices(symbol, days=args.days, prefer_network=args.network)
        bars_by_symbol[symbol] = bars
        sources[symbol] = source
        factor, factor_source = fetch_factors(symbol, prefer_network=args.network)
        factors_by_symbol[symbol] = factor
        sources[f"{symbol}:factors"] = factor_source
        prices[symbol] = bars[-1].close
        ensemble_signals.append(apply_factor_overlay(generate_ensemble_signal(symbol, bars), factor))
        family_signals[symbol] = generate_strategy_signals(symbol, bars)
        backtests.append(run_signal_backtest(symbol, bars, generate_tsmom_signal, min_history=140))
        backtests.append(moving_average_cross_backtest(symbol, bars))

    if (args.queue_order_candidates or args.execute_pending_candidates) and args.require_live_data:
        synthetic_symbols = sorted(sym for sym, source in sources.items() if _source_is_synthetic(source))
        if synthetic_symbols:
            raise SystemExit(f"Refusing candidate execution/queueing because synthetic data was used for: {', '.join(synthetic_symbols)}")

    if args.execute_pending_candidates:
        executed, _remaining = _execute_due_candidates(bars_by_symbol, prices)
        decisions.extend(executed)

    portfolio = load_portfolio()
    if args.queue_order_candidates:
        today = max(bars[-1].date.isoformat() for bars in bars_by_symbol.values() if bars)
        equity = portfolio.equity(prices)
        for sig in [s for s in rank_signals(ensemble_signals) if s.action == "BUY"][: args.max_orders]:
            candidate = _candidate_from_signal(sig, today, equity)
            if candidate:
                queued_candidates.append(candidate)
        if queued_candidates:
            save_order_candidates(_dedupe_candidates(load_order_candidates() + queued_candidates))

    cross_sectional = cross_sectional_momentum_ranks(bars_by_symbol)
    portfolio = load_portfolio()
    if args.fetch_options and OPTIONS_RISK.allow_options and OPTIONS_RISK.paper_options_enabled and not OPTIONS_RISK.live_options_enabled:
        option_symbols = [sig.symbol for sig in rank_signals(ensemble_signals) if sig.action in {"BUY", "HOLD"}]
        for symbol in option_symbols[: args.max_option_symbols]:
            try:
                save_option_chain_snapshot(fetch_option_chain_snapshot(symbol, OPTIONS_RISK.min_dte, OPTIONS_RISK.max_dte), OPTIONS_CHAIN_DIR)
            except Exception as exc:  # network/vendor failures should not block the equity report
                sources[f"{symbol}:options"] = f"options_unavailable:{type(exc).__name__}"
    option_chains = load_available_option_chains(OPTIONS_CHAIN_DIR)
    paper_options = load_option_paper_portfolio() if OPTIONS_PAPER_STATE_PATH.exists() else None
    covered_calls = []
    cash_secured_puts = []
    option_warnings = []
    for chain in option_chains:
        covered_calls.extend(screen_covered_calls(chain, portfolio, OPTIONS_RISK, paper=paper_options))
        cash_secured_puts.extend(screen_cash_secured_puts(chain, portfolio, OPTIONS_RISK, paper=paper_options))
        if "synthetic" in chain.source.lower() or "fixture" in chain.source.lower():
            option_warnings.append(f"{chain.underlying}: option chain source is {chain.source}; paper research only")
    options_research = {"covered_calls": covered_calls, "cash_secured_puts": cash_secured_puts, "warnings": option_warnings}
    text = render_report(ensemble_signals, backtests, decisions, portfolio, prices, sources, queued_candidates, family_signals, cross_sectional, factors_by_symbol, options_research)
    path = save_report(text)
    print(path)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
