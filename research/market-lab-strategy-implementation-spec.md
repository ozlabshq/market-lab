# Market Lab Strategy Implementation Spec
**Status:** Research-ready implementation guide for MVP backtest engine  
**Scope:** Equities, ETFs, crypto using daily OHLCV only. EOD signals → next-open mock fills. No live trading.  
**Date:** 2026-05-27  
**Constraint:** Broad research, conservative execution. Do not overclaim.

---

## 1. WHAT NOT TO CLAIM (hard rules)

- **Do not claim any strategy is “profitable” or “an edge”** until it passes the Minimum Viable Backtest Checklist (§9).
- **Do not claim fills at close** for after-close signals. Label all post-close output as `OrderCandidate` with intended fill at next open.
- **Do not annualize Sharpe from < 2 years** of daily data or < 30 independent trades.
- **Do not ignore transaction costs.** For equities/ETFs assume 5–10 bps all-in; for crypto 10–25 bps depending on venue.
- **Do not present in-sample optimization as evidence.** Any parameter grid must be followed by an out-of-sample or walk-forward block.
- **Do not hide drawdowns.** Report max drawdown and longest underwater period alongside returns.
- **Do not mix daily and intraday logic.** This spec is EOD-only; no candlestick-pattern-intraday edge is assumed realizable.

---

## 2. DATA & EXECUTION ASSUMPTIONS

**Inputs**
- Daily `OHLCV` bars per symbol.
- Minimum history: 252 days (1 year) for any trend/momentum calculation; 60 days minimum for RSI/vol-only filters.
- Universe: any, but backtest must handle delistings/survivorship bias if equities.

**Signal lifecycle**
1. After market close: compute indicators using that day’s `Close`.
2. Generate `Signal` → `OrderCandidate` (direction, target size, strategy tag).
3. Next session: mock fill at next bar’s `Open` (or VWAP proxy if available).
4. No look-ahead: indicators must use bars `t-1` and earlier to produce candidate for `t+1` open. If using `Close` at `t`, fill must be at `t+1` open.

**Costs model (mock)**
- Slippage: 2–5 bps for equities/ETFs; 5–15 bps for crypto mid-cap.
- Commission: 0 bps (assumed included in slippage for MVP).
- Borrow cost for shorting: ignored unless explicitly modeling (MVP long-only first).

---

## 3. STRATEGY FAMILY: TIME-SERIES MOMENTUM (TREND FOLLOWING)

**Core idea:** Own assets with positive recent trend; avoid/short those with negative trend. Works via slow-moving underreaction and autocorrelation in returns at monthly horizons.

**Academic basis**
- Moskowitz, Ooi & Pedersen (2012), *“Time Series Momentum.”* JFE.  
  → Best predictability at 12-month horizon; 1-month reversal is a short-term noise effect to exclude.
- Hurst, Ooi & Pedersen (2017), *“A Century of Evidence on Trend-Following Investing.”*
- Jegadeesh & Titman (1993), *“Returns to Buying Winners and Selling Losers.”*

**Implementable formulas**

**A. Classic TSMOM signal**
```
lookbacks = [20, 60, 120]  # trading days ≈ 1, 3, 6 months
signal_raw = mean( (Close_t - Close_{t-lookback}) / Close_{t-lookback} for lookback in lookbacks )
# Volatility-scaled position
vol = std( daily_returns_{t-20..t} ) * sqrt(252)
target_vol = 0.15  # 15% annualized
position_score = signal_raw / max(vol, 0.05)  # cap leverage via vol
```
*Implementation rule:* If `position_score > 0`, candidate = BUY at next open. If `< 0`, candidate = SELL/flat (or short if enabled). Scale position inversely to vol.

**B. SMA/EMA trend filter (Brock et al. style)**
```
trend_bull = Close_t > SMA20_t > SMA50_t
# confirmation
momentum = Close_t / SMA120_t - 1
signal = +1 if trend_bull and momentum > 0 else 0  # or -1 for short
```

**C. Breakout filter (Donchian channel proxy)**
```
upper = max(High_{t-20..t-1})   # 20-day high excluding today
lower = min(Low_{t-20..t-1})
signal = +1 if Close_t > upper
         -1 if Close_t < lower
         0  otherwise
```
*Note:* This is a noisy proxy on daily data; best used as a filter, not a standalone system.

**Guardrails**
- Parameter bounds: lookback 20–250 days; SMA pairs 10/30, 20/60, 50/200.
- Avoid trading when realized vol > 100% annualized (regime filter).
- Skip if average dollar volume < $5M/day (liquidity guard).
- **Failure mode:** Trend following suffers deep drawdowns during sharp reversals (Aug 2015, Feb 2018, Mar 2020). Always report max drawdown.

**What NOT to claim**
- Do not claim “trend following works in all markets.” It has decade-long flat periods.
- Do not use 1-month momentum alone; include a 1-month skip or blend with longer horizons.

---

## 4. STRATEGY FAMILY: CROSS-SECTIONAL MOMENTUM

**Core idea:** Rank a universe by trailing returns; go long top decile, short bottom decile (or avoid them). The spread is the edge, not the absolute direction.

**Academic basis**
- Jegadeesh & Titman (1993), *“Returns to Buying Winners and Selling Losers.”* JF.
- Asness, Moskowitz & Pedersen (2013), *“Value and Momentum Everywhere.”* JF.

**Implementable formula**
```
formation_period = 126  # 6 months
skip_period = 21        # 1 month to avoid short-term reversal
for each symbol in universe:
    momentum = Close_t / Close_{t - formation_period - skip_period} - 1
    # skip the most recent month: do not include t-21..t in return calc
rank all symbols by momentum
long_candidates = top 20% (or top N)
short/avoid_candidates = bottom 20%
```
*Execution:* Rebalance monthly (every ~21 trading days) at next open after signal.
*Weighting:* Equal-weight within leg, or inverse-vol weighted if vol data available.

**Guardrails**
- Minimum universe size: 20+ symbols. Ranking with < 10 is noise.
- Sector/neutralize if possible: raw cross-sectional momentum concentrates in high-beta sectors.
- **Failure mode:** Momentum crashes (e.g., 2009, 2021) when sharp rallies in losers reverse the spread. A volatility or drawdown filter can reduce tail risk.
- Avoid rebalancing daily; monthly is standard and reduces turnover.

**What NOT to claim**
- Do not claim cross-sectional momentum is “diversified.” It loads heavily on market beta and can crash.
- Do not present long-only top-decile as “momentum” without comparing to the full universe or benchmark.

---

## 5. STRATEGY FAMILY: MEAN REVERSION / RSI PULLBACK

**Core idea:** Short-term oversold conditions within a medium-term uptrend can produce bounces. This is *not* a standalone edge; it is regime-conditional.

**Academic / practitioner basis**
- Welles Wilder (1978), *New Concepts in Technical Trading Systems.* RSI origin.
- Larry Connors & Cesar Alvarez, *Short-Term Trading Strategies That Work.* RSI2 in uptrends.
- Chan (2009), *Quantitative Trading* — mean-reversion requires short holding periods and stops.

**Implementable formula (Regime-Filtered RSI Pullback)**
```
# Only take long mean-reversion signals in an uptrend
uptrend = Close_t > SMA100_t    # or SMA200
rs = RSI(14)_t                  # standard Wilder smoothing

# Entry: oversold in uptrend
if uptrend and rs < 35:
    candidate = BUY at next open
    target_hold = 5 days          # mean reversion is short-horizon
    stop_loss = Open_fill * 0.97  # hard 3% stop

# Exit: RSI > 55 or hold 5 days or stop triggered
```

**Alternative: Short-term reversal (1-month)**
```
last_month_return = Close_t / Close_{t-21} - 1
if last_month_return < -0.15 and Close_t > SMA100_t:
    candidate = BUY at next open  # oversold bounce play
```

**Guardrails**
- Mean reversion is dangerous in downtrends. Never buy oversold without a trend filter.
- Use a hard stop and a time stop. Mean reversion that doesn’t revert quickly often keeps falling.
- **Failure mode:** “Catching a falling knife” — what looks oversold can keep selling off (growth stocks 2022, crypto drawdowns).
- Parameter bounds: RSI window 2–14; oversold threshold 20–40; never below 15.

**What NOT to claim**
- Do not claim RSI alone is an edge. Wilder designed it as a momentum oscillator, not a predictive model.
- Do not show mean-reversion backtests without stops. The left tail dominates.

---

## 6. STRATEGY FAMILY: VOLATILITY TARGETING & REGIME FILTERS

**Core idea:** Size positions inversely to realized volatility; reduce exposure when vol spikes or correlation regime shifts. This is a *risk-management overlay*, not a return generator by itself.

**Academic basis**
- Fleming, Kirby & Ostdiek (2001), *“The Economic Value of Volatility Timing.”* JF.
- Moreira & Muir (2017), *“Volatility-Managed Portfolios.”* JF.
- Moskowitz, Ooi & Pedersen (2012) — volatility scaling in trend following.

**Implementable formulas**

**A. Volatility targeting (position sizing)**
```
asset_vol = std( daily_returns_{t-20..t} ) * sqrt(252)
target_vol = 0.15  # per-asset or per-portfolio
exposure = target_vol / max(asset_vol, 0.05)
exposure = min(exposure, 2.0)  # max 2x leverage cap
position_size = base_position * exposure
```

**B. Regime filter (volatility vs. trend)**
```
# Define “crisis” regime
vix_proxy = percentile( asset_vol_current, lookback=252 )  # if no VIX, use own vol percentile
if vix_proxy > 0.80:  # top quintile of realized vol
    regime = "CRISIS"
    action = REDUCE by 50% or FLAT
else:
    regime = "NORMAL"
    action = follow underlying strategy signal
```

**C. Drawdown filter (hard guardrail)**
```
peak = max(Close_{0..t})
dd = Close_t / peak - 1
if dd < -0.20:  # asset in 20% drawdown
    allow_new_entries = False   # no new longs
    reduce_existing = True      # scale down to 50%
```

**Guardrails**
- Vol estimates lag. A sudden spike will not be captured until day 2+.
- Correlation spikes in crisis mean “diversification” collapses exactly when needed.
- **Failure mode:** Vol targeting increases leverage during calm periods; a sudden shock can cause larger absolute losses than a fixed-size strategy.
- Cap max exposure at 1.5–2.0x; never let vol targeting imply 5x leverage.

**What NOT to claim**
- Do not claim vol targeting “eliminates drawdowns.” It reduces them, often at the cost of lower long-run returns.
- Do not use future vol (e.g., realized vol of the current day) in the sizing formula for today’s close. Use past vol only.

---

## 7. STRATEGY FAMILY: MOVING AVERAGE CROSSOVER & CHANNEL BREAKOUT

**Core idea:** The simplest systematic rules tested in early academic literature. Useful as baselines and robustness checks, not as high-expectancy standalone systems today.

**Academic basis**
- Brock, Lakonishok & LeBaron (1992), *“Simple Technical Trading Rules and the Stochastic Properties of Stock Returns.”* JF.
- Sullivan, Timmermann & White (1999), *“Data-Snooping, Technical Trading Rule Performance, and the Bootstrap.”* JF.

**Implementable formulas**

**A. Dual moving average crossover**
```
short_ma = SMA(10)_t or EMA(12)_t
long_ma = SMA(50)_t or EMA(26)_t
signal = +1 if short_ma crosses above long_ma
         -1 if short_ma crosses below long_ma
         0  otherwise (hold previous)
```
*Execution:* Trade on the day after the cross at next open.

**B. Channel breakout (Brock et al. style)**
```
buy_trigger  = Close_t > max(High_{t-n..t-1})
sell_trigger = Close_t < min(Low_{t-n..t-1})
n in [50, 150, 200]
```

**Guardrails**
- These rules generate many whipsaws in sideways markets. A filter (e.g., only take signals when ADX > 25 or vol percentile < 90) reduces churn.
- Parameter bounds: short 5–50, long 20–250. Avoid optimizing the exact crossover pair without OOS validation.
- **Failure mode:** After costs, many MA-crossover rules underperform buy-and-hold on broad equity indices in modern eras.

**What NOT to claim**
- Do not claim MA crossovers “beat the market” without including transaction costs and comparing to a benchmark.
- Do not optimize the MA lengths on the full dataset and present that as evidence.

---

## 8. UNIVERSAL GUARDRAILS & ANTI-PATTERNS

**Lookahead bias checklist**
- [ ] Indicators never use `High_t`, `Low_t`, or `Close_t` to decide a fill at `Open_t` on the same bar.
- [ ] `max()`/`min()` channels use `t-1` lookback ending yesterday.
- [ ] Earnings, splits, and dividends are adjusted before indicator computation.

**Survivorship bias**
- Backtests on current S&P 500 constituents are invalid for historical claims.
- Use point-in-time universe or at least include delisted tickers if equities.

**Data snooping / overfitting**
- No more than 3–5 parameter sets tested per strategy family before locking to an OOS period.
- Report the “best” in-sample parameter vs. the OOS result. If they diverge > 50%, the strategy is likely curve-fit.

**Turnover sanity**
- Annual turnover > 500% on a slow strategy is a bug or overtrading.
- Target: TSMOM 100–300%; cross-sectional momentum 100–200%; mean reversion 300–800%.

**Crypto-specific guards**
- Gaps: exchanges close for maintenance; use last known bar, not zero.
- Stablecoin/black-swan: stable depeg events generate fake “momentum.” Exclude stablecoins from momentum signals.
- 24/7 markets: “daily” bars can use any cutoff (00:00 UTC), but be consistent.

---

## 9. MINIMUM VIABLE BACKTEST CHECKLIST

Before any strategy is promoted from `research` to `mock_tracking`:

1. **No-lookahead backtest** on ≥ 5 years of daily data.
2. **Benchmark comparison:** Buy-and-hold of the same universe, or SPY/BTC benchmark.
3. **Transaction costs:** Include 5–10 bps slippage per equity/ETF trade; 10–25 bps for crypto.
4. **Turnover report:** Annual turnover and number of trades per year.
5. **Drawdown metrics:** Max drawdown, longest underwater (days), Calmar ratio (return / max DD).
6. **Parameter sensitivity:** Best parameter vs. ±20% parameter variation. Robust if Sharpe changes < 30%.
7. **Out-of-sample or walk-forward:** At least 30% of data unseen during parameter selection.
8. **Mock/paper tracking:** 30+ days of out-of-sample daily signals vs. next-open fills.
9. **Failure mode writeup:** 2–3 historical periods where the strategy would have failed and why.
10. **Position sizing logic:** Explicit capital-per-trade and max exposure rules.

---

## 10. IMPLEMENTATION PRIORITY FOR MVP

**Phase 1 (now)**
1. Refactor `Signal` → `OrderCandidate` with next-open fill semantics.
2. Implement **TSMOM with vol targeting** (§3A + §6A) as the first researched baseline.
3. Implement **cross-sectional momentum ranker** (§4) for ETF universes (e.g., sector ETFs, top-20 crypto).
4. Add **regime filter** (§6B) as a global overlay to both.

**Phase 2 (next)**
5. Add **regime-filtered RSI pullback** (§5) with hard stops and short holds.
6. Add **MA crossover baseline** (§7A) purely as a benchmark comparison, not a traded strategy.
7. Run walk-forward backtests and produce the checklist outputs (§9).

**Phase 3 (later)**
8. Multi-strategy ensemble: combine TSMOM + mean reversion signals with vol-weighted sizing.
9. Introduce cross-asset correlation filter (requires multi-asset covariance estimation).

---

## 11. BIBLIOGRAPHY & SOURCES

**Academic papers**
- Brock, W., Lakonishok, J., & LeBaron, B. (1992). “Simple Technical Trading Rules and the Stochastic Properties of Stock Returns.” *Journal of Finance*, 47(5), 1731–1764.
- Jegadeesh, N., & Titman, S. (1993). “Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency.” *Journal of Finance*, 48(1), 65–91.
- Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). “Time Series Momentum.” *Journal of Financial Economics*, 104(2), 228–250.
- Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). “Value and Momentum Everywhere.” *Journal of Finance*, 68(3), 929–985.
- Hurst, B., Ooi, Y. H., & Pedersen, L. H. (2017). “A Century of Evidence on Trend-Following Investing.” *AQR Working Paper*.
- Moreira, A., & Muir, T. (2017). “Volatility-Managed Portfolios.” *Journal of Finance*, 72(4), 1611–1644.
- Sullivan, R., Timmermann, A., & White, H. (1999). “Data-Snooping, Technical Trading Rule Performance, and the Bootstrap.” *Journal of Finance*, 54(5), 1647–1691.

**Practitioner books**
- Wilder, J. W. (1978). *New Concepts in Technical Trading Systems.* Trend Research.
- Kaufman, P. J. (2013). *Trading Systems and Methods.* 5th ed. Wiley.
- Chan, E. P. (2009). *Quantitative Trading.* Wiley.
- Chan, E. P. (2013). *Algorithmic Trading.* Wiley.
- Clenow, A. F. (2013). *Following the Trend.* Wiley.
- Clenow, A. F. (2015). *Stocks on the Move.* Wiley.

---

*Document version: 1.0. Research use only. Not investment advice.*
