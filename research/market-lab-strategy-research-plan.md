# Market Lab Strategy Research Plan

Status: created after Ronak challenged the first MVP strategies. The current MVP strategies are baseline heuristics, not researched/proven edges.

## What is implemented today

Current `market_lab/signals.py` combines:
- Trend filter: close > SMA20 > SMA50
- EMA confirmation: EMA12 > EMA26
- RSI regime: constructive if RSI14 is 45-70, overbought penalty above 78, small washed-out credit below 30
- Volatility filter: annualized 20-day vol below 75% preferred

Current `market_lab/backtest.py` only sanity-checks a moving-average cross strategy using next-bar execution. It is not enough to establish edge.

## Immediate correction

Do not describe current output as a researched strategy portfolio. It is an MVP signal/tracking scaffold.

The daily engine should not claim to “trade on close” as if fills are executable. For after-close daily tracking, signals should produce next-session candidate orders, and fills should be modeled at next open or next available bar once available.

## Strategy research tracks to build

1. Time-series momentum / trend following
   - Core idea: assets with positive recent returns/trend continue over intermediate horizons.
   - Candidate sources: Moskowitz, Ooi & Pedersen, “Time Series Momentum”; Hurst/Ooi/Pedersen “A Century of Evidence on Trend-Following Investing.”
   - Tests: 20/60/120-day momentum, SMA/EMA trend filters, volatility targeting.

2. Cross-sectional momentum
   - Core idea: rank universe by trailing returns, long winners / avoid losers.
   - Candidate source: Jegadeesh & Titman, “Returns to Buying Winners and Selling Losers.”
   - Tests: 1/3/6/12-month returns excluding recent reversal window.

3. Value + momentum / multi-factor
   - Core idea: combine complementary factors; momentum alone can crash.
   - Candidate source: Asness, Moskowitz & Pedersen, “Value and Momentum Everywhere.”
   - MVP proxy: ETF/equity trend + relative strength + drawdown/volatility filter.

4. Simple technical rules
   - Core source found live via Semantic Scholar: Brock, Lakonishok & LeBaron (1992), “Simple Technical Trading Rules and the Stochastic Properties of Stock Returns” — 2,361 citations in Semantic Scholar result.
   - Tests: moving average crossovers, channel breakouts, bootstrap/randomization robustness checks.

5. Mean reversion / RSI
   - Core idea: RSI is a heuristic from Welles Wilder, not sufficient edge alone.
   - Use only as context/filter until tested.
   - Tests: RSI2/RSI14 oversold bounce, regime-filtered mean reversion, stop-loss sensitivity.

6. Volatility/risk filters
   - Core idea: reduce size/avoid entries when realized volatility or drawdown risk is extreme.
   - Tests: vol targeting, max drawdown filter, VIX proxy when available.

## Required next implementation upgrade

- Separate `Signal` from `OrderCandidate`.
- Daily after close: generate candidate orders for next session; do not mark fills at close.
- Next session: fill prior candidates at actual open/next available price in mock broker.
- Add strategy metadata: strategy_name, horizon, evidence_level, source_refs.
- Add backtest modules per strategy family before trusting any signal.

## Book/source shelf to use

Books / practitioner references to consult and encode into docs before advancing:
- Welles Wilder, *New Concepts in Technical Trading Systems* — RSI and ATR origins.
- John J. Murphy, *Technical Analysis of the Financial Markets* — classical TA context.
- Perry Kaufman, *Trading Systems and Methods* — systematic strategy design.
- Ernest Chan, *Algorithmic Trading* and *Quantitative Trading* — practical backtesting and pitfalls.
- Andreas Clenow, *Following the Trend* / *Stocks on the Move* — trend and momentum implementation.

Academic papers to consult:
- Brock, Lakonishok & LeBaron (1992), “Simple Technical Trading Rules and the Stochastic Properties of Stock Returns.”
- Jegadeesh & Titman (1993), “Returns to Buying Winners and Selling Losers.”
- Moskowitz, Ooi & Pedersen (2012), “Time Series Momentum.”
- Asness, Moskowitz & Pedersen (2013), “Value and Momentum Everywhere.”

## Standard for claiming a strategy is usable

A strategy is not “usable” until it has:
- no-lookahead backtest
- benchmark comparison
- transaction costs/slippage
- turnover
- max drawdown
- parameter sensitivity
- out-of-sample or walk-forward check
- mock/paper tracking evidence
- clear failure modes
