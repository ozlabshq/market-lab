# Market Lab: Next 3 High-Signal Equity/ETF Strategy Modules

**Status:** Implementation-ready spec (research/mock only, no live trading)  
**Scope:** Plain equities and ETFs, daily OHLCV, EOD signals → next-open mock fills  
**Date:** 2026-05-28  
**Constraint:** Every claim is conservative. Nothing here is promoted as a guaranteed edge until it passes the Minimum Viable Backtest Checklist.

---

## Summary of Gaps vs. Current Codebase

| Already Implemented | Missing / Under-Specified |
|---------------------|---------------------------|
| Baseline technical scoring (`generate_signal`) | Cross-sectional ranking wired into a tradeable rotation rule |
| TSMOM (`generate_tsmom_signal`) | Formal vol-targeted position sizing + drawdown circuit breaker |
| RSI pullback (`generate_rsi_pullback_signal`) | Volume confirmation on oversold days (capitulation proxy) |
| Cross-sectional ranker (`cross_sectional_momentum_ranks`) | Absolute + relative momentum combined (Dual Momentum) |
| Simple MA cross backtest (`moving_average_cross_backtest`) | Portfolio-level rebalance backtest with next-open fills |
| Factor overlay (`apply_factor_overlay`) | Strategy-specific anti-lookahead guard tests |

The 3 modules below fill these gaps without duplicating existing logic.

---

## Module 1: Dual Momentum ETF Rotation (`dual_momentum`)

### Hypothesis
Assets with **positive absolute momentum** (trending up) **and** **top-quintile relative momentum** (outpacing peers) produce better risk-adjusted returns than either filter alone. This combines Antonacci’s *Dual Momentum* (2014) with the existing cross-sectional rank infrastructure.

- **Academic basis:** Antonacci (2014), *Dual Momentum Investing*; Asness, Moskowitz & Pedersen (2013), *Value and Momentum Everywhere*.
- **Why it fits:** The codebase already has `cross_sectional_momentum_ranks` and `generate_tsmom_signal`. This module wires them into a single rotation rule.

### Required Data
- Daily OHLCV for a universe of 10–30 ETFs (e.g., sector SPDRs, equity-region ETFs, factor ETFs).
- Minimum history: 252 trading days per symbol.

### Signal Rules
1. **Absolute momentum filter** (must pass to be a candidate):  
   `abs_mom = Close_t / Close_{t-252} - 1`  
   Pass if `abs_mom > 0`.
2. **Relative momentum rank** (must pass to be selected):  
   Compute 12-month return with 1-month skip (formation=252, skip=21).  
   Rank universe. Select top 20% (or top N, minimum 3 symbols).
3. **Combined signal:** BUY at next open if symbol passes **both** filters.  
   Otherwise: SELL / avoid at next open.
4. **Rebalance cadence:** Monthly (every 21 trading days). Daily signals are fine, but the backtest should only act on the rebalance day to reduce turnover.

### Exit Rules
- **Rank drop:** If a held symbol falls out of the top 20%, close at next open after the rebalance check.
- **Absolute break:** If `abs_mom` turns negative (Close_t / Close_{t-252} - 1 < 0), close at next open regardless of rank.
- **Emergency exit:** If 20-day vol exceeds 100%, go flat at next open (regime too noisy).

### Risk Gates
- Max allocation per symbol: 20% of portfolio.
- Minimum selected symbols: 3. If fewer than 3 pass both filters, the remaining cash stays in a risk-free proxy (mock: flat).
- Single-leg concentration: never > 25%.

### Position Sizing
Within selected symbols, two options:
1. **Equal-weight** (default for MVP): `weight = 1 / n_selected`, capped at 0.20.
2. **Inverse-vol** (optional): weight inversely proportional to each symbol’s 20-day realized vol, rescaled to sum to 1.0 and capped at 0.20.

### Backtest Tests (`test_dual_momentum`)
1. **Two-asset rotation:** Create a universe of 2 ETFs where one has strong 12m return + positive abs mom, the other has negative abs mom. Verify only the winner is selected.
2. **Absolute filter blocks losers:** Create a symbol with top relative rank but negative absolute momentum (recent sharp rebound, still < 0 vs 12m ago). Verify it is **not** selected.
3. **Monthly turnover:** Run on a 3-symbol universe with stable ranks. Verify exactly 1 rebalancing trade per month per symbol that drops out.
4. **Rebalance at next open:** Set rebalance day price to 100, next open to 110. Verify fill is at 110 (proves no same-bar execution).

### Anti-Lookahead Checklist
- [ ] Absolute momentum uses `Close_{t-252}`; relative momentum uses `Close_{t-273}` to `Close_{t-21}`. Neither uses today’s close for the formation return.
- [ ] Rebalance decision at close of day `t` uses data through `t-21` max.
- [ ] Fill is at next bar’s `Open`, never at `Close_t`.

### Files to Modify
| File | Change |
|------|--------|
| `market_lab/signals.py` | Add `generate_dual_momentum_signal(symbol, bars, universe_bars)` or a new `DualMomentumSelector` class. Add `CrossSectionalMomentumPortfolio` dataclass. |
| `market_lab/backtest.py` | Add `run_portfolio_backtest(universe, signal_func, rebalance_days=21)`. This is a portfolio-level backtest that tracks weights, not a single-asset backtest. |
| `tests/market_lab/test_research_strategies.py` | Add `test_dual_momentum_*` tests (see above). |

---

## Module 2: Volume-Confirmed Mean Reversion (`vc_mr`)

### Hypothesis
Oversold bounces within uptrends have higher probability when accompanied by an **elevated volume spike**. The volume spike proxies forced liquidation / capitulation, which exhausts near-term selling pressure (Connors/Alvarez RSI pullback literature + volume-profile practitioner work).

- **Academic/practitioner basis:** Connors & Alvarez, *Short-Term Trading Strategies That Work*; Wilder (1978) RSI; practitioner volume-at-price analysis.
- **Why it fits:** The codebase already has `generate_rsi_pullback_signal`. This adds a volume filter and explicit stop infrastructure.

### Required Data
- Daily OHLCV (uses volume column, not currently used by existing signals).
- Minimum history: 120 bars.

### Signal Rules
All four conditions must be true simultaneously:
1. **Uptrend regime:** `Close_t > SMA100_t`.
2. **Oversold:** `RSI(14)_t < 30`.
3. **Volume capitulation:** `Volume_t > 1.5 * SMA(Volume, 20)_t`.
4. **Pullback depth:** `Close_t / SMA20_t - 1 < -0.04` (at least 4% below 20-day average, confirming meaningful dip, not just noise).

Confidence scoring:  
`confidence = clamp( (30 - rsi) / 30 + (vol_ratio - 1.5) / 2 + abs(pullback_depth) * 5, 0.25, 0.85 )`

### Exit Rules
1. **Time stop:** Close at next open on the 6th trading day after entry (max 5 days held).
2. **RSI recovery:** Close at next open if `RSI(14)_t >= 60`.
3. **Hard stop:** If price falls to `fill_price * 0.97` at any close, close at next open. Track stop as a `hard_stop_price` field in the backtest state.
4. **Breakeven lock:** If price rises to `fill_price * 1.03`, move the hard stop to `fill_price` (breakeven) for the remainder of the hold.

### Risk Gates
- Skip if 20d annualized vol > 80% (oversold in high vol is more likely to keep falling).
- Skip if `ADR(20) < 1.0%` (average daily range too small; insufficient bounce potential). ADR = mean(High - Low over 20 days) / Close_t.
- Max one position per symbol at a time.

### Backtest Tests (`test_vc_mr`)
1. **Volume spike triggers buy:** Create uptrend bars where RSI drops to 25, volume is 2.0x average, and close is 5% below SMA20. Verify BUY.
2. **No volume spike = no signal:** Same setup but volume at 1.0x average. Verify HOLD.
3. **Downtrend blocks signal:** RSI 25, volume spike, pullback depth, but close < SMA100. Verify HOLD.
4. **Hard stop at -3%:** Entry at 100. Next bar close = 96. Verify exit triggered with final equity reflecting the loss.
5. **Time stop at day 6:** Enter on bar 120. Hold through bar 125. Verify exit on bar 126 open.
6. **Breakeven lock:** Entry at 100. Bar+1 close = 103 (triggers lock). Bar+2 close = 99. Verify exit at next open with 0% loss (breakeven), not -1%.

### Anti-Lookahead Checklist
- [ ] Volume confirmation uses `Volume_t` known after close. Fill is at `Open_{t+1}`.
- [ ] RSI uses close through `t`, but the decision only affects `t+1` open.
- [ ] Stop-loss checks use the **close** of the current bar to decide if a stop is triggered, and the exit executes at the **next open**. This is realistic for EOD-only systems.
- [ ] Breakeven lock uses the close of the bar where the 3% gain is achieved; the stop is updated for future bars, never applying retroactively.

### Files to Modify
| File | Change |
|------|--------|
| `market_lab/signals.py` | Add `generate_vc_mr_signal(symbol, bars)` using the 4-condition rule. |
| `market_lab/indicators.py` | Add `average_daily_range(bars, window=20)` helper. Ensure it returns a list aligned to closes. |
| `market_lab/backtest.py` | Add `run_signal_backtest_with_stops(...)` that accepts stop rules (hard stop %, time stop days, trailing/breakeven rules). This is a richer backtest than the current `run_signal_backtest`. |
| `tests/market_lab/test_research_strategies.py` | Add `test_vc_mr_*` tests (see above). |

---

## Module 3: Volatility-Targeted Trend with Drawdown Guard (`vt_trend`)

### Hypothesis
Scaling trend-following exposure inversely to recent realized volatility improves risk-adjusted returns (Moreira & Muir 2017). Adding a **hard drawdown circuit breaker** prevents the strategy from holding through deep, prolonged drawdowns that trend models typically suffer.

- **Academic basis:** Moreira & Muir (2017), *Volatility-Managed Portfolios*; Moskowitz, Ooi & Pedersen (2012) vol scaling in TSMOM; standard CTA risk management.
- **Why it fits:** The current `generate_tsmom_signal` has crude vol scaling (`target_vol / max(vol, 0.05)`). This module makes it explicit, adds position-sizing precision, and layers a drawdown guard that does not exist today.

### Required Data
- Daily OHLCV.
- Minimum history: 120 bars.

### Signal Rules
1. **Trend filter:** `Close_t > SMA100_t`.
2. **Vol estimate:** `vol20 = std(daily_returns_{t-19..t}) * sqrt(252)`.
3. **Target vol:** `target_vol = 0.15` (15% annualized).
4. **Raw exposure:** `exposure = target_vol / max(vol20, 0.05)`.
5. **Exposure caps:**
   - Max `1.5x` (no > 1.5× leverage).
   - Min `0.10` — if exposure < 0.10, go flat (no token 5% slivers).
6. **Action:**
   - If trend up → BUY with `target_weight = clamp(exposure, 0.10, 1.5)`.
   - If trend down → SELL (flat).

### Exit / Drawdown Rules
1. **Trend break:** `Close_t < SMA100_t` → SELL at next open (same as entry rule).
2. **Drawdown guard — level 1 (reduce):** If `Close_t < 0.85 * peak_90d` (i.e., > 15% drawdown from 90-day peak), reduce position to 50% of current weight at next open.
3. **Drawdown guard — level 2 (flat):** If `Close_t < 0.80 * peak_90d` (i.e., > 20% drawdown), go fully flat at next open.
4. **Vol spike guard:** If `vol20 > 1.00` (100% annualized), go flat at next open regardless of trend.
5. **Re-entry rule:** After a level-2 flat, require `Close_t > SMA100_t` AND `Close_t > 0.90 * peak_90d` before any new entry.

### Risk Gates
- Max per-asset weight: 1.5× (the cap above). In a portfolio context, cap at 25% of NAV.
- No new entries if 90-day rolling max drawdown > 10% for the asset.

### Backtest Tests (`test_vt_trend`)
1. **Vol scaling reduces size in spikes:** Create a trend-up series where vol20 = 60%. Verify target_weight ≈ 0.25. Then vol20 = 10%, verify target_weight ≈ 1.5 (capped).
2. **Floor at 0.10:** Vol20 = 200% → exposure = 0.075 → should go flat (exposure < 0.10).
3. **Drawdown level 1 triggers:** Create a series: peak at 100 on bar 50, then decline to 84 on bar 60 (16% drawdown). Verify position reduced to 50% of original weight at next open.
4. **Drawdown level 2 triggers:** Continue decline to 79 on bar 61 (21% drawdown). Verify fully flat at next open.
5. **Re-entry after level 2:** Stay flat until price recovers above SMA100 AND > 0.90 * peak_90d. Verify no premature re-entry.
6. **Trend break exit:** Trend up with full position. Price drops below SMA100. Verify SELL at next open.
7. **No lookahead in vol:** Vol20 must be computed from `t-19` through `t` (most recent return uses `Close_t / Close_{t-1}`). Decision at `t` uses this vol. The position size for `t+1` open is based on `t` data. This is correct because `Close_t` and `Close_{t-1}` are both known at `t`.

### Anti-Lookahead Checklist
- [ ] `vol20` uses returns `Close_{t-19..t} / Close_{t-20..t-1} - 1`. These are all known at end of day `t`.
- [ ] `peak_90d` uses `max(Close_{t-89..t})`. This is known at `t`.
- [ ] Position size decided at `t` is applied at `Open_{t+1}`.
- [ ] Drawdown check uses close `t`; action is at `Open_{t+1}`.

### Files to Modify
| File | Change |
|------|--------|
| `market_lab/signals.py` | Add `generate_vt_trend_signal(symbol, bars, target_vol=0.15, max_leverage=1.5)`. Include peak_90d tracking and drawdown guard logic in `evidence` dict. |
| `market_lab/indicators.py` | Add `rolling_peak(values, window)` helper (returns rolling max aligned to input). |
| `market_lab/backtest.py` | Extend `run_signal_backtest` or add `run_signal_backtest_with_sizing(...)` that supports fractional/variable position sizes (qty changes based on target_weight). The current backtest is all-in or flat. |
| `tests/market_lab/test_research_strategies.py` | Add `test_vt_trend_*` tests (see above). |

---

## Integration Notes

### Where Each Strategy Sits in the Existing Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Existing: baseline_scoring ( heuristics, no edge claim )   │
├─────────────────────────────────────────────────────────────┤
│  Existing: tsmom ( crude vol scaling )                      │
│  Existing: rsi_pullback ( regime-filtered )                 │
├─────────────────────────────────────────────────────────────┤
│  NEW: dual_momentum  ──► portfolio rotation, next-open      │
│  NEW: vc_mr          ──► volume + stops, next-open          │
│  NEW: vt_trend       ──► vol sizing + drawdown guard        │
└─────────────────────────────────────────────────────────────┘
```

### Ensemble Integration
The existing `generate_ensemble_signal` should be updated to include the 3 new strategies once they exist:

```python
def generate_strategy_signals(symbol, bars) -> list[Signal]:
    return [
        generate_tsmom_signal(symbol, bars),
        generate_rsi_pullback_signal(symbol, bars),
        generate_signal(symbol, bars),
        generate_dual_momentum_signal(symbol, bars, universe_bars),  # new
        generate_vc_mr_signal(symbol, bars),                        # new
        generate_vt_trend_signal(symbol, bars),                     # new
    ]
```

*Note:* `dual_momentum` requires universe data; the ensemble caller must pass a `bars_by_symbol` dict and iterate per symbol.

### Backtest Infrastructure Needed
The current `run_signal_backtest` is single-asset, long-only, all-in/flat. Two new backtest primitives are needed:

1. **`run_portfolio_backtest`** — rebalances a basket monthly at next-open, tracks per-symbol weights, handles partial exits, reports turnover and concentration metrics.
2. **`run_signal_backtest_with_stops`** — single-asset backtest with configurable hard stops, time stops, trailing/breakeven rules, and variable position sizing.

These are architecturally simple additions (add new functions, do not break existing `run_signal_backtest`).

---

## Minimum Viable Backtest Checklist (per strategy)

Before any of these modules is promoted from `research` to `mock_tracking`:

| Check | dual_momentum | vc_mr | vt_trend |
|-------|--------------|-------|----------|
| 1. No-lookahead backtest ≥ 5 years | ✅ Required | ✅ Required | ✅ Required |
| 2. Benchmark comparison (buy-hold or SPY) | ✅ Required | ✅ Required | ✅ Required |
| 3. Transaction costs: 5–10 bps slippage | ✅ Required | ✅ Required | ✅ Required |
| 4. Turnover report (annual %) | ✅ Required | ✅ Required (expect 300–800%) | ✅ Required |
| 5. Max drawdown + longest underwater | ✅ Required | ✅ Required | ✅ Required |
| 6. Parameter sensitivity (±20% shift) | Formation 252±50, skip 21±5 | RSI 30±5, vol 1.5x±0.3 | target_vol 15%±3%, vol floor 5%±2% |
| 7. Out-of-sample / walk-forward ≥ 30% | ✅ Required | ✅ Required | ✅ Required |
| 8. Mock tracking ≥ 30 days | ✅ Required | ✅ Required | ✅ Required |
| 9. Failure mode writeup (2–3 periods) | 2009 momentum crash; 2022 bear market | Growth selloff 2022; flash crashes | Mar 2020 VIX spike; Aug 2015 reversal |
| 10. Position sizing explicit | Equal-weight or inverse-vol | Fixed 5% risk/unit | Vol-targeted 0.10–1.5× |

---

## Anti-Patterns to Avoid

- **Do not optimize parameters on the full history and present that as evidence.** Any grid search must reserve a holdout period.
- **Do not cherry-pick ETF universes.** If testing sector rotation, use the full set of sector SPDRs (XLY, XLP, etc.), not just the ones that backtest well.
- **Do not ignore delisting/survivorship bias** if running on individual equities. This spec is ETF-first to sidestep that problem.
- **Do not fill at `Close_t` for a signal computed using `Close_t`.** All fills are at `Open_{t+1}`.

---

## Implementation Order (Recommended)

1. **Week 1:** Implement `vt_trend` first — it is the simplest (extends existing TSMOM with explicit sizing and drawdown guard). Requires only `signals.py` + `indicators.py` additions.
2. **Week 2:** Implement `vc_mr` — adds volume dependency and stop infrastructure. Requires `signals.py`, `indicators.py`, and a richer backtest primitive.
3. **Week 3:** Implement `dual_momentum` — requires portfolio-level backtest and universe handling. Most complex but highest expected diversification benefit.

---

*Document version: 1.0. Research use only. Not investment advice.*
