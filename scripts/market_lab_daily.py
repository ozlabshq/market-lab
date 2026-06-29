#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
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
from market_lab.config import DEFAULT_UNIVERSE, RISK, OPTIONS_CHAIN_DIR, OPTIONS_RISK, ensure_dirs
from market_lab.data import fetch_prices, compute_spy_benchmark
from market_lab.factors import fetch_factors
from market_lab.options_data import fetch_option_chain_snapshot, load_available_option_chains, save_option_chain_snapshot
from market_lab.options_paper import (
    OptionPaperCandidate,
    append_option_paper_ledger,
    execute_option_paper_candidate,
    load_option_paper_candidates,
    load_option_paper_portfolio,
    save_option_paper_candidates,
    save_option_paper_portfolio,
)
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
from market_lab.verifier import apply_verifier_guard


def _source_is_synthetic(source: str) -> bool:
    return source.strip().lower() in {"synthetic", "cache", "cache_synthetic"}


def _dedupe_candidates(candidates: list[OrderCandidate]) -> list[OrderCandidate]:
    by_key = {}
    for candidate in candidates:
        key = (candidate.symbol, candidate.signal_date, candidate.strategy, candidate.side)
        by_key[key] = candidate
    return list(by_key.values())


def _candidate_from_signal(sig, signal_date: str, portfolio_equity: float, portfolio=None) -> OrderCandidate | None:
    if sig.close <= 0:
        return None
    if sig.action == "BUY":
        target_notional = min(RISK.max_trade_notional, max(RISK.min_trade_notional, portfolio_equity * max(sig.target_weight, 0.02)))
        qty = max(1, int(target_notional // sig.close))
        if qty * sig.close < RISK.min_trade_notional:
            return None
        return OrderCandidate("BUY", sig.symbol, qty, sig.strategy, sig.confidence, sig.reason, signal_date, sig.close)
    if sig.action == "SELL" and portfolio is not None:
        pos = portfolio.positions.get(sig.symbol.upper())
        if not pos or pos.quantity <= 0:
            return None
        max_qty = max(1, int(RISK.max_trade_notional // sig.close))
        qty = min(pos.quantity, max_qty)
        if qty * sig.close < RISK.min_trade_notional:
            return None
        return OrderCandidate("SELL", sig.symbol, qty, sig.strategy, sig.confidence, sig.reason, signal_date, sig.close)
    return None


def _spy_guarded_tsmom(spy_bars):
    def _signal(symbol, hist):
        spy_history = [bar for bar in spy_bars if hist and bar.date <= hist[-1].date] if spy_bars else None
        return generate_tsmom_signal(symbol, hist, spy_bars=spy_history)
    _signal.__name__ = "generate_tsmom_spy_guarded_signal"
    return _signal


def _ensemble_signal_for_verifier(spy_bars):
    def _signal(symbol, hist):
        spy_history = [bar for bar in spy_bars if hist and bar.date <= hist[-1].date] if spy_bars else None
        return generate_ensemble_signal(symbol, hist, spy_bars=spy_history)
    _signal.__name__ = "generate_ensemble_signal_for_verifier"
    return _signal


def _dedupe_option_candidates(candidates: list[OptionPaperCandidate]) -> list[OptionPaperCandidate]:
    by_key = {}
    for candidate in candidates:
        key = (candidate.action, candidate.contract.contract_id, candidate.strategy)
        by_key[key] = candidate
    return list(by_key.values())


def _option_candidate_from_csp(candidate) -> OptionPaperCandidate:
    return OptionPaperCandidate(
        "SELL_TO_OPEN",
        candidate.contract,
        candidate.contracts,
        "cash_secured_put",
        candidate.contract.quote.mid,
        date.today().isoformat(),
    )


def _option_candidate_from_cc(candidate) -> OptionPaperCandidate:
    return OptionPaperCandidate(
        "SELL_TO_OPEN",
        candidate.contract,
        candidate.contracts,
        "covered_call",
        candidate.contract.quote.mid,
        date.today().isoformat(),
    )


def _execute_due_option_candidates(portfolio):
    pending = load_option_paper_candidates()
    if not pending:
        return [], []
    paper = load_option_paper_portfolio()
    decisions = []
    remaining = []
    for candidate in pending:
        decision = execute_option_paper_candidate(candidate, paper, portfolio, OPTIONS_RISK)
        decisions.append(decision)
        append_option_paper_ledger(decision)
        if not decision.accepted:
            remaining.append(candidate)
    save_option_paper_portfolio(paper)
    save_option_paper_candidates(remaining)
    return decisions, remaining


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


def _earliest_ledger_date(ledger_path: Path) -> date | None:
    """Return the earliest execution_date or signal_date from the ledger."""
    if not ledger_path.exists():
        return None
    earliest = None
    try:
        with ledger_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                ts = data.get("execution_date") or data.get("signal_date") or data.get("timestamp", "")[:10]
                if ts:
                    d = date.fromisoformat(ts)
                    if earliest is None or d < earliest:
                        earliest = d
    except Exception:
        pass
    return earliest


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OzLabs Market Lab daily research/report tracker")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_UNIVERSE)
    parser.add_argument("--days", type=int, default=260)
    parser.add_argument("--network", action="store_true", help="Attempt yfinance before cache/synthetic fallback")
    parser.add_argument("--queue-order-candidates", action="store_true", help="Queue next-session mock candidates instead of same-close fills")
    parser.add_argument("--execute-pending-candidates", action="store_true", help="Fill previously queued candidates at the latest bar open when a later bar is available")
    parser.add_argument("--require-live-data", action="store_true", help="Abort candidate execution/queueing if any symbol falls back to synthetic data")
    parser.add_argument("--fetch-options", action="store_true", help="Fetch and cache yfinance option chains before screening paper options")
    parser.add_argument("--queue-option-candidates", action="store_true", help="Queue top guarded paper option candidates; no fill until --execute-paper-option-candidates")
    parser.add_argument("--execute-paper-option-candidates", action="store_true", help="Execute queued paper option candidates into the paper-only options ledger")
    parser.add_argument("--max-option-symbols", type=int, default=8, help="Maximum symbols to refresh option chains for when --fetch-options is enabled")
    parser.add_argument("--max-option-orders", type=int, default=1, help="Maximum paper option candidates to queue per run")
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
    option_decisions = []
    queued_candidates = []
    queued_option_candidates = []

    for symbol in args.symbols:
        bars, source = fetch_prices(symbol, days=args.days, prefer_network=args.network)
        bars_by_symbol[symbol] = bars
        sources[symbol] = source
        factor, factor_source = fetch_factors(symbol, prefer_network=args.network)
        factors_by_symbol[symbol] = factor
        sources[f"{symbol}:factors"] = factor_source
        prices[symbol] = bars[-1].close

    spy_bars = bars_by_symbol.get("SPY")
    if spy_bars is None:
        spy_bars, spy_source = fetch_prices("SPY", days=args.days, prefer_network=args.network)
        sources["SPY:benchmark_guard"] = spy_source

    for symbol, bars in bars_by_symbol.items():
        factor = factors_by_symbol[symbol]
        ensemble_signals.append(apply_factor_overlay(generate_ensemble_signal(symbol, bars, spy_bars=spy_bars), factor))
        family_signals[symbol] = generate_strategy_signals(symbol, bars, spy_bars=spy_bars)
        backtests.append(run_signal_backtest(symbol, bars, _spy_guarded_tsmom(spy_bars), min_history=140))
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
        ranked_for_orders = rank_signals(ensemble_signals)
        for sig in [s for s in ranked_for_orders if s.action == "SELL"]:
            candidate = _candidate_from_signal(sig, today, equity, portfolio=portfolio)
            if candidate:
                queued_candidates.append(candidate)
        buy_slots = max(args.max_orders - len(queued_candidates), 0)
        verifier_func = _ensemble_signal_for_verifier(spy_bars)
        for sig in [s for s in ranked_for_orders if s.action == "BUY"][:buy_slots]:
            candidate = _candidate_from_signal(sig, today, equity, portfolio=portfolio)
            if candidate:
                allowed, _ = apply_verifier_guard(candidate, bars_by_symbol.get(sig.symbol), verifier_func, spy_bars=spy_bars)
                if allowed:
                    queued_candidates.append(candidate)
        if queued_candidates:
            save_order_candidates(_dedupe_candidates(load_order_candidates() + queued_candidates))

    cross_sectional = cross_sectional_momentum_ranks(bars_by_symbol, spy_bars=spy_bars)
    portfolio = load_portfolio()
    if args.fetch_options and OPTIONS_RISK.allow_options and OPTIONS_RISK.paper_options_enabled and not OPTIONS_RISK.live_options_enabled:
        option_symbols = [sig.symbol for sig in rank_signals(ensemble_signals) if sig.action in {"BUY", "HOLD"}]
        for symbol in option_symbols[: args.max_option_symbols]:
            try:
                save_option_chain_snapshot(fetch_option_chain_snapshot(symbol, OPTIONS_RISK.min_dte, OPTIONS_RISK.max_dte), OPTIONS_CHAIN_DIR)
            except Exception as exc:  # network/vendor failures should not block the equity report
                sources[f"{symbol}:options"] = f"options_unavailable:{type(exc).__name__}"
    option_chains = load_available_option_chains(OPTIONS_CHAIN_DIR)
    if args.execute_paper_option_candidates:
        executed_options, _remaining_options = _execute_due_option_candidates(portfolio)
        option_decisions.extend(executed_options)
    paper_options = load_option_paper_portfolio()
    covered_calls = []
    cash_secured_puts = []
    option_warnings = []
    for chain in option_chains:
        covered_calls.extend(screen_covered_calls(chain, portfolio, OPTIONS_RISK, paper=paper_options))
        cash_secured_puts.extend(screen_cash_secured_puts(chain, portfolio, OPTIONS_RISK, paper=paper_options))
        if "synthetic" in chain.source.lower() or "fixture" in chain.source.lower():
            option_warnings.append(f"{chain.underlying}: option chain source is {chain.source}; paper research only")
    if args.queue_option_candidates:
        selected_options = []
        selected_options.extend(_option_candidate_from_csp(candidate) for candidate in cash_secured_puts[: args.max_option_orders])
        remaining_slots = max(args.max_option_orders - len(selected_options), 0)
        if remaining_slots:
            selected_options.extend(_option_candidate_from_cc(candidate) for candidate in covered_calls[:remaining_slots])
        if selected_options:
            queued_option_candidates = selected_options
            save_option_paper_candidates(_dedupe_option_candidates(load_option_paper_candidates() + queued_option_candidates))
    options_research = {"covered_calls": covered_calls, "cash_secured_puts": cash_secured_puts, "warnings": option_warnings, "option_decisions": option_decisions, "queued_option_candidates": queued_option_candidates}
    # SPY buy/hold benchmark aligned to first ensemble ledger fill date
    from market_lab.config import LEDGER_PATH
    bm_start = _earliest_ledger_date(LEDGER_PATH)
    spy_benchmark = compute_spy_benchmark(
        starting_cash=RISK.starting_cash,
        start_date=bm_start,
        days=args.days,
        prefer_network=args.network,
    )
    text = render_report(ensemble_signals, backtests, decisions, portfolio, prices, sources, queued_candidates, family_signals, cross_sectional, factors_by_symbol, options_research, paper=paper_options, spy_benchmark=spy_benchmark)
    path = save_report(text)
    print(path)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
