# Loop Engineering Implementation — SPY-Relative Market Lab Upgrade

Source: RohOnChain, "How To Use Loop Engineering To Build A Self-Improving Quant Trading System" — https://x.com/rohonchain/status/2069056530960490835

## What was implemented

The article's useful parts were not copied literally into autonomous trading. Market Lab remains research/paper-only. The good parts were translated into objective gates inside the current safe pipeline:

1. **Benchmark-relative signal guard**
   - `generate_tsmom_signal(..., spy_bars=...)` now blocks BUYs when the asset's momentum does not beat SPY.
   - If SPY momentum is non-positive, the TSMOM family emits SELL/reduce instead of adding beta exposure.

2. **Benchmark-relative ensemble overlay**
   - `generate_ensemble_signal(..., spy_bars=...)` now downgrades buy pressure when the asset lags SPY and raises sell pressure when SPY itself is in a negative regime.

3. **Cross-sectional excess momentum**
   - `cross_sectional_momentum_ranks(..., spy_bars=...)` can rank symbols by momentum net of SPY.
   - The daily script now uses SPY-aware cross-sectional ranks.

4. **Dual momentum allocator SPY threshold**
   - `dual_momentum_targets(..., spy_bars=...)` now requires selected assets to clear the stronger of the absolute momentum threshold and SPY momentum.

5. **Execution-loop risk improvement**
   - The daily candidate queue now can queue SELL candidates for existing positions when ensemble signals flip to SELL.
   - It does not short; it only exits owned mock positions in risk-capped chunks.

6. **Live-data hardening found during verification**
   - yfinance can return nonfinite/NaN vendor rows. Market Lab now filters invalid bars at network/cache boundaries and keeps Sharpe/volatility calculations finite-safe.

## Why this improves the system

Market Lab had a core underperformance gap: it could buy positive absolute momentum that still lagged SPY. That is structurally how a strategy trails the S&P 500 in a bull market. The new guard converts the loop's stop condition from "agent/strategy says BUY" to a machine-checkable condition:

> Only add exposure when the candidate is stronger than SPY; otherwise hold/sell/avoid.

## Verification run

- Full test suite: `uv run python -m pytest tests/market_lab -q`
- Result: `215 passed, 6 subtests passed`
- Live-data smoke: `MARKET_LAB_DATA_DIR=/tmp/market-lab-live-smoke uv run python scripts/market_lab_daily.py --symbols SPY AAPL MSFT NVDA --days 420 --network --require-live-data`
- Result: report generated successfully with yfinance data and no NaN benchmark after data hardening.

## Remaining improvement lanes

- Add walk-forward SPY-beat verifier before candidate queueing.
- Add track promotion/demotion based on SPY-relative Sharpe and drawdown.
- Add explicit daily evidence records for rejected candidates, not just report text.
- Optimize strategy families against out-of-sample SPY-relative metrics, not in-sample total return.
