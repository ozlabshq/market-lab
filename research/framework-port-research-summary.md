# Framework Research Synthesis — What to Port into Market Lab

**Date:** 2026-05-28  
**Status:** Research only, no file edits  
**Mission:** Aggressive research, conservative execution

---

## 1. Market Lab Today (What Exists)

| Component | State |
|-----------|-------|
| Signal pipeline | `tsmom`, `rsi_pullback`, `baseline_scoring`, `ensemble` |
| Backtest engine | Single-bar loop, next-open fills, basic slippage |
| Broker | Mock broker with `OrderCandidate` -> `candidate_to_order_at_open` |
| Data | Daily OHLCV via yfinance, synthetic fallback |
| Factors | Fundamental overlay (PE, PB, FCF yield, AI score) |
| Tests | Synthetic bars only, signals/backtest/broker covered |

**Strengths:** Clean separation of concerns, no-lookahead semantics already enforced, research docs are rigorous.
**Gaps:** No vectorized backtests, no param sweeps, no risk-management overlay, no scheduled rebalancing, no walk-forward framework.

---

## 2. Frameworks Analyzed

### A. vectorbt (Polakow)
- **Core pattern:** `Portfolio.from_signals(entries, exits, stop_loss, take_profit, fees, slippage)` — vectorized + Numba-compiled
- **Key innovation:** Run entire signal series at once; param sweep thousands of variants in seconds
- **What to port:**
  - Array-based signal backtesting (run full history via numpy, not per-bar loop)
  - Built-in stop/take-profit as signal-layer primitives
  - Parameter grid search with metric collection
  - `Portfolio` metrics object (Sharpe, Calmar, max DD, turnover)
- **What NOT to port:** Full vectorbt dependency (heavy, Numba, pandas internals). Port the *pattern* lightweight.

### B. backtrader (mementum)
- **Core pattern:** `Strategy.next()` event-driven callback; `Cerebro` orchestrates; `Analyzer` computes stats
- **Key innovation:** Clean event-driven architecture, reusable indicators, commission/slippage modeling
- **What to port:**
  - Strategy base class with `next()` / `notify_order()` hooks
  - Analyzer/observer decorators for metrics collection (Sharpe, DrawDown, Returns, TradeAnalyzer)
  - Commission + slippage as first-class simulation inputs
- **What NOT to port:** Full Cerebro engine (over-engineered for small repo). Port the *analyzer pattern*.

### C. freqtrade
- **Core pattern:** Strategy template with `populate_indicators()`, `populate_entry_trend()`, `populate_exit_trend()`; framework-level stoploss and ROI exits
- **Key innovation:** Exit logic is first-class (not ad-hoc), trailing stops are framework params, hyperopt parameters decorate strategy
- **What to port:**
  - Explicit `populate_entry` / `populate_exit` separation
  - Framework stop-loss and ROI time-table exits (e.g., exit after 5 days or at +4%)
  - Trailing stop as config, not strategy code
  - Hyperopt parameter ranges (`IntParameter`, `DecimalParameter`)
- **What NOT to port:** Full bot runtime, exchange integrations, database layer.

### D. QuantConnect Lean
- **Core pattern:** Algorithm Framework = `AlphaModel` -> `PortfolioConstructionModel` -> `ExecutionModel` -> `RiskManagementModel`
- **Key innovation:** Signals, sizing, execution, and risk are *separate* pluggable modules
- **What to port:**
  - Modular pipeline: Alpha (signal) -> Construction (target weights) -> Risk (override)
  - `EqualWeightingPortfolioConstructionModel` pattern for cross-sectional strategies
  - `MaximumDrawdownPercentPerSecurity` risk model
  - Scheduled rebalancing (daily, weekly, monthly)
- **What NOT to port:** Full C# engine, securities database, live brokerage integrations.

---

## 3. Top 5 Strategy Families to Build

| Rank | Family | Evidence Level | Complexity | What to Port |
|------|--------|----------------|------------|--------------|
| **1** | **TSMOM + Vol Targeting** | Strong (Moskowitz/Ooi/Pedersen, Hurst) | Low-Medium | vectorbt array backtest + param sweep |
| **2** | **Risk Overlay / Regime Filter** | Moderate (Fleming/Kirby, Moreira/Muir) | Low | Lean RiskManagementModel pattern |
| **3** | **Cross-Sectional Momentum** | Strong (Jegadeesh/Titman, Asness) | Medium | Lean PortfolioConstructionModel + monthly rebalance |
| **4** | **RSI Pullback (Regime-Filtered)** | Weak-Moderate (Wilder, Chan/Connors) | Medium | freqtrade entry/exit separation + stop framework |
| **5** | **MA Crossover / Breakout Baseline** | Weak Modern (Brock et al.) | Low | backtrader analyzer pattern for benchmarking only |

---

## 4. Recommendation: Implement in This Order

### First — TSMOM with Array-Based Backtesting & Param Sweep
**Why:**
- Skeleton already exists in `generate_tsmom_signal`
- Strongest academic evidence (Moskowitz/Ooi/Pedersen 2012; Hurst/Ooi/Pedersen 2017)
- Works on single assets and universes
- Easiest to make auditable: clear signal, clear sizing, clear costs
- Port vectorbt's `Portfolio.from_signals` pattern *without the dependency*: write a lightweight numpy-based `run_signals_backtest(closes, entries, exits, fees, slippage)` that returns equity curve + metrics

**Concrete deliverables:**
1. `market_lab/backtest.py`: `run_signals_backtest(entries, exits, prices, fees, slippage)` using numpy arrays
2. `market_lab/optimization.py`: `param_sweep(signal_func, param_grid, bars, metric="sharpe")` returning ranked results
3. Walk-forward split: `train_pct=0.7`, lock in-sample best params, report OOS result
4. Add `turnover` metric (annual trades / avg positions)

### Second — Risk Overlay Module (Lean-style)
**Why:**
- Highest risk-adjusted ROI of any feature
- Wraps *any* strategy without changing its logic
- Prevents catastrophic run scenarios

**Concrete deliverables:**
1. `market_lab/risk.py`: `RiskOverlay` class with:
   - `max_drawdown_pct`: reduce/flat when drawdown exceeds threshold
   - `vol_spike_filter`: reduce exposure when 20d vol > 80th percentile of trailing 252d
   - `correlation_spike_prox`: avoid new entries when average pairwise correlation > 0.80
2. Apply as post-processing step: `risked_signal = RiskOverlay.apply(signal, bars)`

### Third — Cross-Sectional Momentum with Scheduled Rebalance
**Why:**
- Natural extension of TSMOM to ETF universes (SPY, QQQ, sector ETFs)
- Already have `cross_sectional_momentum_ranks`; needs portfolio construction

**Concrete deliverables:**
1. `market_lab/portfolio_construction.py`: Equal-weight or inverse-vol weight from ranks
2. `market_lab/scheduler.py`: Rebalance trigger (monthly, on first trading day)
3. Backtest that simulates monthly rebalancing with transaction costs

### Fourth — RSI Pullback with Framework-Level Stops
**Why:**
- Already have `generate_rsi_pullback_signal`; weak as standalone, acceptable as conditional overlay
- Port freqtrade's stop-loss / time-stop primitives to make it testable

**Concrete deliverables:**
1. `market_lab/exits.py`: Framework stop-loss (fixed % trailing), time-stop (N bars), RSI-exit targets
2. Backtest that respects stops inside `run_signals_backtest`
3. Report win rate, avg winner, avg loser, expectancy

### Fifth — MA Crossover / Breakout as Benchmark Only
**Why:**
- Brock et al. evidence is dated; many rules fail after costs in modern eras
- Useful only as a benchmark to prove TSMOM/momentum adds value

**Concrete deliverables:**
1. `market_lab/benchmarks.py`: `ma_cross_benchmark`, `donchian_breakout_benchmark`
2. backtrader-style `Analyzer` that outputs comparison table (strategy vs benchmark)

---

## 5. Anti-Patterns to Avoid (From Framework Research)

| Anti-Pattern | Why It Happens | Market Lab Guard |
|--------------|----------------|------------------|
| Overfitting param grids | Optimizing on full history | Walk-forward split built into `param_sweep` |
| Ignoring transaction costs | Frameworks default to zero | `ExecutionModel` already has 5bps slippage; extend to 10bps for small-caps |
| Same-bar fills | Backtrader/freqtrade default is next-open, but custom `next()` can cheat | Already enforced: `candidate_to_order_at_open` |
| Survivorship bias | Backtests on current S&P 500 only | Document limitation; use ETF universes or note synthetic delisting |
| Annualizing Sharpe from 30 trades | Small-sample overconfidence | Block report if `trades < 30` or `bars < 2 years` |

---

## 6. Summary: One-Sentence Takeaways

- **vectorbt** -> Port array-based backtesting and param sweeps (lightweight, no dependency).
- **backtrader** -> Port analyzer/observer pattern for metrics collection.
- **freqtrade** -> Port explicit entry/exit separation and framework-level stop/ROI logic.
- **Lean** -> Port modular Alpha -> Portfolio Construction -> Risk pipeline.
- **Implement first:** TSMOM with properly vectorized backtests and parameter robustness checks.

---
*Research only. Not investment advice.*
