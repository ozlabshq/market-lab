# Next Safe Experiment Proposal — Market Lab v1

**Status:** Proposal (research only, no live trading)
**Date:** 2026-06-03
**Prepared by:** Ozzy (research lane)
**Mode:** mock/paper/research only. No broker orders. No secrets.

---

## Current State Assessment

**What works today:**
- Daily report pipeline generates ensemble signals for 19 symbols (3 strategies: TSMOM, RSI pullback, baseline scoring + factor overlay)
- Mock broker executes buy orders at next-open fills with atomic state, portfolio lock, FIFO lot tracking
- 12 accepted mock fills since 2026-05-29 across 5 symbols (AMZN x2, AVGO x2, MSFT x3, NVDA x2, AAPL x2)
- Mock portfolio: $53.1k cash, ~$100k equity, 5 open positions
- Diagnosis + evidence modules fully built (diagnosis.py, evidence.py, market_lab_review.py, tests pass)
- 3 strategy modules specced (vt_trend, vc_mr, dual_momentum) — not yet implemented
- Factor lens across valuation/quality/growth/AI exposure

**Critical gap found:** The evidence council infrastructure is built and tested but **never actually run**. The data/market-lab/evidence/ directory is empty. The review script (`market_lab_review.py`) exists and `diagnose_new_mock_decisions()` + `write_health_reports()` work, but they produce nothing until invoked. This means:
- No TradeDiagnosis records exist for the 12 mock trades
- No StrategyHealthReport exists for the ensemble strategy
- No baseline wall for comparing future experiments against

---

## Recommended Experiment

### Phase 1 (immediate — 0 code changes): ⚡ Bootstrap the Evidence Council

**Hypothesis:** Running the existing evidence council on the current mock ledger will produce non-zero diagnostic data that either (a) reveals strategy decay/failure modes in the ensemble strategy, or (b) establishes a healthy baseline for future experiments. Either outcome is net-new information worth having, and it costs zero code risk.

**Data required:** Already present on disk:
- `data/market-lab/mock_ledger.jsonl` — 12 accepted buy decisions
- `data/market-lab/mock_portfolio_state.json` — 5 open positions
- yfinance price bars for each symbol (network optional; cached bars work)

**Backtest/mock gate:** No gate needed — this is diagnostic, not a new strategy. The review script (`scripts/market_lab_review.py`) only reads existing mock data and emits JSONL evidence records. It never places orders or changes portfolio state.

**Procedure:**
1. Run `python3 scripts/market_lab_review.py` to produce `evidence/trades.jsonl` + `evidence/strategy_health.jsonl`
2. Read the output: record number of new diagnoses, strategy health report, decay alerts
3. Incorporate findings into the next daily report as an "Evidence Council" section

**Safety guardrails:**
- Review script is read-only on mock ledger; no order creation, no portfolio mutation
- Synthetic data flag propagates through each diagnosis so council never treats synthetic as evidence
- Script only diagnoses open positions with >= 2 bars of price data after entry

**Expected output:** 5 TradeDiagnosis records (one per open position) + 1 StrategyHealthReport for "ensemble" strategy showing: win rate, avg P&L, regime breakdown, and whether decay alert fires.

---

### Phase 2 (next day — ~2h implement): 🧪 Volatility-Targeted Trend (vt_trend) — Backtest-Only

**Hypothesis:** Trend-following with explicit volatility targeting (exposure inversely proportional to realized vol) and a hard drawdown circuit breaker produces better risk-adjusted returns in mock tracking than the current crude TSMOM implementation. Academic basis: Moreira & Muir (2017) — Volatility-Managed Portfolios; Moskowitz, Ooi & Pedersen (2012) vol scaling in TSMOM.

**Data required:**
- Daily OHLCV for current watchlist (19 symbols) — already cached
- Minimum 120 bars per symbol — satisfied for all current symbols
- No new data sources needed

**Implementation (from existing spec at research/market-lab-next-3-equity-strategies-spec.md, Module 3):**

| File | Change |
|------|--------|
| `market_lab/signals.py` | Add `generate_vt_trend_signal(symbol, bars, target_vol=0.15, max_leverage=1.0)` |
| `market_lab/indicators.py` | Add `rolling_peak(values, window)` helper |
| `market_lab/backtest.py` | Add `run_signal_backtest_with_sizing(...)` supporting fractional/variable position sizes |
| `tests/market_lab/test_research_strategies.py` | Add 7 `test_vt_trend_*` tests |

**Backtest gate (before any promotion to mock tracking):**
- Minimum 5-year no-lookahead backtest on SPY
- Benchmark comparison vs buy/hold
- Transaction cost stress at 5/10/25 bps
- Turnover report (annual %)
- Max drawdown + longest underwater period
- Parameter sensitivity: target_vol 15% ± 3%, vol floor 5% ± 2%
- Walk-forward with 30%+ OOS holdout
- Failure-mode writeup (2009 momentum crash, Mar 2020 VIX spike)
- 30-day mock tracking before any trust

**Safety guardrails:**
- Implemented as backtest-only module — no integration with broker, no order candidates
- All fills at next-open (no same-bar execution)
- Vol spike guard (100%+ annualized → go flat)
- Drawdown guard: 15% → reduce to 50%, 20% → flat, re-entry requires trend + recovery
- Max exposure cap at 1.0x because Market Lab has no margin/leverage accounting; floor at 0.10 (slivers below 0.10 go flat)

**Research-only posture:**
- Results live in research/ and data/market-lab/evidence/ only
- No daily report integration until Phase 2 mock tracking promotion passes all 10 gates
- No ensemble signal updates until mock tracking evidence exists

---

## Recommendation Order

1. **Today:** Run `market_lab_review.py` — bootstrap evidence council (Phase 1)
2. **Tomorrow:** Implement vt_trend backtest module + tests (Phase 2)
3. **If vt_trend passes backtest gates:** Create follow-up card to wire vt_trend into mock order candidate queue (separate from ensemble — independent tracking portfolio)
4. **After 30-day mock tracking:** Evaluate whether vt_trend outperforms baseline ensemble; create follow-up for ensemble integration

---

## Follow-Up Implementation Card (ready to create)

If this proposal is approved, the next implementation card should be:

> **Title:** Implement vt_trend backtest module (signals + indicators + backtest + tests)
> **Body:** Implement Module 3 from research/market-lab-next-3-equity-strategies-spec.md. Add generate_vt_trend_signal() to signals.py, rolling_peak() to indicators.py, run_signal_backtest_with_sizing() to backtest.py, and 7 tests to test_research_strategies.py. Backtest-only — no broker integration, no order candidates. Verify all tests pass and run a 5-year backtest on SPY before merging.
> **Assignee:** ozzy-research
> **Safety guard:** Research-only module. No live trading path.