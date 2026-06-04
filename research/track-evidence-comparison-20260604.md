# Market Lab: Track Evidence Comparison & Next Safe Experiment

**Date:** 2026-06-04
**Author:** Ozzy (ozzy-research)
**Posture:** Research/mock only. No live broker orders. No investment advice.

---

## 1. Baseline Mock Portfolio (main ensemble)

| Metric | Value |
|--------|-------|
| Starting capital | $100,000 |
| Current cash | $46,812 |
| Estimated equity | $97,946 |
| Open positions | 6 (AAPL, AMZN, AVGO, MSFT, NVDA, SPY) |
| Closed trades diagnosed | 19 |
| Win rate | 9% (1 win / 11 losses... but then 19 diagnoses) |
| Avg P&L per trade | -3.9% |
| Sharpe of trade P&Ls | -4.6 |
| Dominant failure mode | whipsaw (9 of 11) |

After re-running the evidence council with today's data, the main portfolio diagnoses tell a clear story: **the ensemble signal has been buying into a weak tape**. Only 1 of 11 closed trades made money (AAPL +1%). AVGO went from +10% to -9% between day 3 and day 4. AMZN, NVDA, MSFT have all been whipsawed repeatedly.

The daily report (06:36 UTC today) still recommends BUY on AMD, AAPL, SPY, QQQ, IWM, DIA. The model has not adapted to the fact that its picks are underperforming — it keeps buying into the same signal set.

**Evidence quality: LOW.** Small sample (1 week), no regime labels (all "unknown"), no SPY benchmark comparison, and the evidence council's 45-day data window is too short for the regime labeler to compute SMA100.

---

## 2. vt_trend Independent Tracking

| Metric | Value |
|--------|-------|
| Starting capital | $25,000 |
| Current cash | $25,000 |
| Positions | 0 |
| Cumulative fills | 0 |
| Data source | yfinance (live) |
| Tracking days | 0/30 |
| Pending candidates | 1 BUY SPY @ ~$754 ref close |

**No fills yet.** The pending candidate from 2026-06-03 (target weight 100%, vol20 9.6%, trend regime UP, drawdown -0.7%) is correctly queued and will fill at the next available bar after market close today (2026-06-04). This is working as designed — no bug.

The signal is clean: SPY at low vol, trending, wants full exposure. The pending candidate awaiting fill means the first real evidence from this track will arrive within 1 trading day.

**Evidence quality: NONE yet** — but about to generate the first datum.

---

## 3. TSMOM Independent Tracking

| Metric | Value |
|--------|-------|
| Starting capital | $25,000 |
| Current cash | $25,000 |
| Positions | 0 |
| Cumulative fills | 0 |
| Data source | cache (no --network) |
| Tracking days | 0/30 |
| Pending candidates | 0 |

**No activity at all.** The TSMOM signal on SPY is flat (neutral raw momentum). No candidates generated. Last ran at 17:02 UTC today with cached data.

**Evidence quality: NONE.** The tracking is running but producing zero signal to test.

---

## 4. Options Paper Loop

| Metric | Value |
|--------|-------|
| Starting capital | $100,000 |
| Cash | $100,193.50 |
| Reserved cash (CSP collateral) | $20,000 |
| Active positions | 1 |
| Granted premium | $193.50 |

**Single active position:** SHORT 1 NVDA $200 PUT exp 2026-06-18, sold 2026-06-03 at $1.935 ($193.50 premium). Cash-secured put on NVDA which closed today at $214.46 — the position is safely OTM (NVDA $214 > strike $200) with ~14 DTE remaining.

USO CSP candidates were screened today with attractive annualized yields (10-70%) but none were queued for execution.

**Evidence quality: VERY LOW.** Only 1 position, not yet expired, no realized P&L.

---

## 5. Evidence Quality Comparison

| Dimension | Main Portfolio | vt_trend | TSMOM | Options Paper |
|---|---|---|---|---|
| **Track history** | 7 days | 1 day | 1 day | 1 day |
| **Fills** | 13 accepted | 0 | 0 | 1 |
| **Trade diagnoses** | 19 | 0 | 0 | 0 (not wired) |
| **Win rate** | 9% | — | — | — |
| **Trade Sharpe** | -4.6 | — | — | — |
| **Data freshness** | yfinance live | yfinance live | cache only | yfinance chains |
| **Regime labels** | All "unknown" | — | — | — |
| **Key finding** | Ensemble buying losers | Vol low, wants SPY | Neutral — flat | Single CSP OTM |

**Critical gap:** The independent tracks (vt_trend, TSMOM) have generated zero evidence so far. Combined, only 1 real observation exists (the options CSP). The main portfolio has 19 diagnoses but they all say "unknown" for regime — the evidence council's 45-day data window is insufficient for the SMA100-based regime labeler.

---

## 6. Bounded Next Safe Experiment Recommendation

**Recommended: Extend the evidence council data window from 45 to 120 days** so trade diagnoses receive proper regime labels (trending_up, trending_down, chop, high_vol_chop).

Rationale:
- The regime labeler needs 100 bars for its SMA100 computation
- Current 45-day window produces only "unknown" labels — this wastes the evidence council's diagnostic power
- Without regime labels, the strategy health report cannot tell us *when* the ensemble works vs. fails
- This is a pure parameter change (one integer), does not change any trading logic, does not touch cron/broker/secrets
- It directly improves the quality of every future diagnosis across all tracks

**Implementation** (single file change in `scripts/market_lab_review.py`):
```
--days default from 45 → 120
```
Plus running the review with `--network` so fresh price data is available for the full window.

**Why not other candidates:**
- *Wire evidence council to vt_trend* — premature, vt_trend has 0 fills yet; wait for the first BUY to fill
- *Change ensemble signal thresholds* — speculative without regime-labeled evidence to guide the change
- *Execute more options* — the single CSP is fine for now; let it mature toward expiration
- *Investigate vt_trend stuck candidate* — not stuck; the delayed fill is by-design (next-open after close)

**Follow-up cadence:**
1. After market close today: run vt_trend with --network → first BUY fill executes
2. Run evidence council for vt_trend and main portfolio with --network and --days 120
3. Review regime-labeled health report in 3-5 trading days
