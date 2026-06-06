# Market Lab: Ensemble Evidence Assessment — 2026-06-05

**Status:** Research/mock only. No live broker orders. No investment advice.
**Date:** 2026-06-05 (post-close, SPY $737.55, -2.43% day)
**Author:** Ozzy (ozzy-research)
**Files checked:**
  - `/Users/ozlabs/market-lab/data/market-lab/reports/latest.md` — daily ensemble report
  - `/Users/ozlabs/market-lab/data/market-lab/vt_trend/reports/latest.md` — vt_trend track report
  - `/Users/ozlabs/market-lab/data/market-lab/tsmom/reports/latest.md` — TSMOM track report
  - `/Users/ozlabs/market-lab/data/market-lab/evidence/strategy_health.jsonl` — evidence council output (4 reports)
  - `/Users/ozlabs/market-lab/data/market-lab/evidence/trades.jsonl` — 43 trade diagnosis records
  - `/Users/ozlabs/market-lab/data/market-lab/mock_ledger.jsonl` — 18 mock fills
  - `/Users/ozlabs/market-lab/data/market-lab/mock_portfolio_state.json` — 7 open positions
  - `/Users/ozlabs/market-lab/data/market-lab/vt_trend/portfolio_state.json` — vt_trend isolated portfolio
  - `/Users/ozlabs/market-lab/data/market-lab/vt_trend/ledger.jsonl` — vt_trend 1 fill
  - `/Users/ozlabs/market-lab/data/market-lab/vt_trend/pending_candidates.jsonl` — vt_trend pending
  - `/Users/ozlabs/market-lab/data/market-lab/tsmom/portfolio_state.json` — TSMOM isolated portfolio
  - `/Users/ozlabs/market-lab/data/market-lab/tsmom/pending_candidates.jsonl` — TSMOM pending
  - `/Users/ozlabs/market-lab/data/market-lab/prices/SPY.csv` — cached OHLCV
  - `/Users/ozlabs/market-lab/scripts/market_lab_independent_tracks.py` — track runner
  - `/Users/ozlabs/market-lab/scripts/market_lab_review.py` — evidence council (ran with --network)
  - `/Users/ozlabs/market-lab/scripts/market_lab_vt_trend.py` — vt_trend implementation
  - `/Users/ozlabs/market-lab/scripts/market_lab_tsmom.py` — TSMOM implementation (not shown)
  - `/Users/ozlabs/market-lab/research/independent-track-evidence-20260605.md` — prior day's evidence
  - `/Users/ozlabs/market-lab/research/track-evidence-comparison-20260604.md` — prior day's comparison
  - `/Users/ozlabs/market-lab/research/next-safe-experiment-proposal.md` — prior experiment proposal

---

## 1. Baseline Ensemble Portfolio Evidence

| Metric | 2026-06-04 | 2026-06-05 | Change |
|--------|-----------|-----------|--------|
| Cash | $46,812 | $37,801 | -19.2% |
| Equity | ~$97,946 | ~$97,705 | -0.2% |
| Open positions | 6 | 7 | Added AMD + SPY |
| Trade diagnoses | 19 | 43 | +24 new diagnoses |
| Win rate | 9% | 0% | -9pp |
| Avg P&L per trade | -3.9% | -6.5% | -2.6pp |
| Trade Sharpe | -4.6 | -6.15 | Worsened |
| Dominant failure mode | whipsaw | whipsaw | Unchanged |

**Regime breakdown (NEW — first time with --network):**
- `high_vol_chop`: 4 trades, 0% win rate, avg P&L -5.0%
- `trending_up`: 9 trades, 0% win rate, avg P&L -7.2%

**Verdict: The ensemble signal is losing money in ALL regime environments.** The strategy buys into strength (trending_up) and fails to exit before reversals (whipsaw). It also buys into volatility (high_vol_chop) and gets chopped. There is no regime where this signal works.

**Key mock fills today:**
- BUY 9 AMD @ $499.37 (closed flat, but now underwater)
- BUY 6 SPY @ $752.48 (closed $737.55, -1.98% unrealized)
- REJECTED BUY 16 AAPL (risk gate — correct call in retrospect, AAPL held up but 2.6% of equity in one AAPL order was too large)

---

## 2. vt_trend Independent Track Evidence

| Metric | Value |
|--------|-------|
| Starting capital | $25,000 |
| Cash | $24,246.52 |
| Position | 1 SPY @ $752.48 avg |
| Equity | $24,984.07 |
| Unrealized P&L | -1.98% |
| Fills | 1 (first fill executed 2026-06-05) |
| Tracking | Day 1/30 |
| Trend regime | up |
| Pending | 1 BUY SPY (wants to accumulate toward 100% weight) |

**Key change today:** vt_trend got its first fill. The strategy bought 1 SPY at $752.48 per the pending candidate from 2026-06-03. SPY dropped -2.43% today → position is -1.98% unrealized. A new BUY candidate is queued for the next open (wants to keep accumulating).

**Evidence quality: VERY LOW.** Only 1 fill. Too early to draw any conclusions about the strategy. The entry was at the high end of the week (SPY $752, now $737.55) — this is normal for trend-following (buy strength, ride pullbacks). The drawdown guards (15% → reduce, 20% → flat) are nowhere near triggered.

---

## 3. TSMOM Independent Track Evidence

| Metric | Value |
|--------|-------|
| Starting capital | $25,000 |
| Cash | $25,000 |
| Position | 0 |
| Equity | $25,000 |
| Fills | 0 |
| Tracking | Day 0/30 |
| Raw momentum | 6.6% |
| Pending | 1 BUY SPY @ $752.28 ref (0.536 confidence) |

**Key change today:** FIRST CANDIDATE GENERATED. TSMOM ran with --network and produced a BUY SPY signal at 0.536 confidence. The candidate references $752.28 close. Since TSMOM uses next-open fills, this will execute at Monday's open (next trading session).

**Evidence quality: NONE.** No fills yet. The pipeline is flowing. First fill expected next trading day (Monday 2026-06-08 open).

---

## 4. Cross-Track Evidence Comparison

| Dimension | Main Ensemble | vt_trend | TSMOM |
|-----------|--------------|----------|-------|
| **Track history** | 8 trading days | 2 days | 1 day |
| **Fills** | 18 accepted | 1 | 0 |
| **Win rate** | 0% | — | — |
| **Trade Sharpe** | -6.15 | — | — |
| **Regime labels** | NOW REAL (with --network) | — | — |
| **Data freshness** | cache (after-hours) | cache (after-hours) | cache (after-hours) |
| **Pending candidates** | 0 | 1 BUY SPY | 1 BUY SPY |

**The independent tracks are producing data but have essentially zero statistical power.** Combined: 1 fill, 0 closed trades, ~1 day of tracking each.

---

## 5. Data/Reporting Gaps Identified

1. **After-hours data staleness.** It's Friday 23:10 UTC. yfinance cache has today's close, but `--require-live-data` fails because the data source label is "cache" not "yfinance". The scripts treat cached yfinance data as non-live. This means independent tracks can't run with --require-live-data after market close.

2. **yfinance network is flaky/slow.** The daily script (`market_lab_daily.py`) timed out at 120s with --network. The review script succeeded with --network and produced real regime labels, but only on retry.

3. **Regime labels work only with --network.** The evidence council produces "unknown" for all regime labels when using cached data (not enough history). Regime labeling requires fetching data beyond the 120-day lookback for SMA100 computation.

4. **Daily ensemble report does NOT show regime breakdowns.** The evidence council is run separately. The daily report still shows "Strategy family diagnostics" with crude HOLD/0.00 readings but no regime context for the buyer's remorse.

5. **No SPY buy/hold benchmark in reports.** The ensemble is losing -2.3% from $100k start, but SPY has also dropped ~2.5% this week. Is the strategy simply beta? Is it doing worse than buy/hold? The reports don't answer this.

6. **Independent track reports not directly comparable.** vt_trend and TSMOM have different starting capitals ($25k each), different reporting formats, and no shared benchmark. No cross-track P&L chart or correlation surface.

---

## 6. Next Safe Experiment Recommendation

### Primary: Add SPY buy/hold benchmark to all three portfolios

**Hypothesis:** The ensemble strategy underperforms simple SPY buy/hold over the same period. If true, the ensemble signal is destroying value and should be paused/replaced.

**Implementation:** Add a `benchmark_close` field to the daily report that tracks what $100k in SPY would be worth from the same start date (2026-05-28 close = $754 SPY). This is zero-code — just add a formulaic line to the report template.

**Why this:** Before drawing ANY conclusions about vt_trend vs TSMOM vs ensemble, we need to establish whether any of them beats SPY. The ensemble is -2.3%; SPY may be -2.2% over the same period — they could be equivalent. Or SPY might be -0.5% and the strategy is making it worse. We can't tell without the benchmark.

### Secondary (requires code change): Wire regime breakdown into daily report

The evidence council now generates real regime labels when run with --network. The daily report should surface a "Regime breakdown" section showing how the strategy performs in each detected regime. This would guide the tuning decision.

### Deferred (not yet):

- **Wire TSMOM candidate** — First fill not until Monday. Let it execute.
- **vt_trend second fill** — Pending candidate will fill Monday. Let it accumulate.
- **Change ensemble signal thresholds** — Premature without benchmark comparison.
- **Add cron/scheduling** — Manual cadence remains correct.
- **Options scaling** — Single CSP on NVDA is fine. Let it expire.
- **Cross-track comparison dashboard** — Premature. Need at least 5-10 fills per track.

### Cadence recommendation:

1. **Monday 2026-06-08 after close:** Run all tracks with --network. TSMOM first fill expected. vt_trend second fill expected.
2. **Add SPY benchmark to reports** (zero-code — report template update).
3. **Wednesday 2026-06-10:** Re-run evidence council with --network. By then vt_trend may have 2-3 fills, TSMOM 1-2 fills.
4. **Friday 2026-06-12:** First cross-track evidence comparison with 5 trading days of independent track data.

### Safety guardrail compliance:
- No live trading
- No broker orders
- No secrets in output
- No cron changes
- Mock-only execution
- Ronak remains final decision maker

---

*Written: 2026-06-05 23:30 UTC, post-close assessment. Research/mock-only.*