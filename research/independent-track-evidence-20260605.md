# Market Lab: Independent Track Live-Data Evidence — Day 2

**Date:** 2026-06-05 (heartbeat run 12:01 PDT / 19:01 UTC)
**Author:** Ozzy (ozzy-research)
**Posture:** Research/mock only. No live broker orders. No investment advice.
**Market context:** SPY closed $738.70, down -2.43% on the day

---

## 1. vt_trend Independent Tracking — Day 1/30

| Metric | Value |
|--------|-------|
| Starting capital | $25,000 |
| Cash | $24,246.52 |
| Position | 1 SPY @ $752.48 avg |
| Equity at close | $24,985.07 |
| Position weight | 3.0% (target 100%) |
| Cumulative fills | 1 |
| Pending candidates | 1 (BUY 1 SPY) |
| Data source | yfinance |
| Trend regime | up |
| Vol20 (ann.) | 12.5% |
| Drawdown from 90d peak | -2.8% |
| Re-entry allowed | yes |

**Change since yesterday:** FIRST FILL EXECUTED. The pending candidate from 2026-06-03 filled today at $752.48. SPY closed at $738.70 → unrealized P&L -1.83%. A new BUY candidate was generated from today's run. The strategy wants to accumulate toward full 100% weight (~33 shares). The circuit breaker (20% drawdown) is nowhere near triggered. **The track is now producing live evidence.**

**Signal quality:** The BUY signal was generated at SPY $754+ levels. Entry at $752.48. The system is buying into a down day — this is fundamentally what trend-following does (buy strength, hold through pullback). Whether this position survives the drawdown guard (15% → reduce, 20% → flat) will be the first real test.

---

## 2. TSMOM Independent Tracking — Day 0/30

| Metric | Value |
|--------|-------|
| Starting capital | $25,000 |
| Cash | $25,000.00 |
| Position | 0 |
| Equity | $25,000.00 |
| Cumulative fills | 0 |
| Pending candidates | 1 (BUY 1 SPY @ $752.28 ref) |
| Data source | yfinance |
| Raw momentum | 6.8% |
| Vol20 (ann.) | 12.4% |
| Drawdown from 120d peak | -2.7% |

**Change since yesterday:** FIRST CANDIDATE GENERATED. TSMOM ran with `--network` today (yfinance, live data) and produced a BUY SPY signal at 0.536 confidence. The candidate references $752.28 close. Since this is a next-open fill, it will execute at tomorrow's open — which could be materially lower after today's -2.43% drop. **First fill imminent.**

**Evidence quality:** Zero fills so far, but the pipeline is now flowing. Within 1-2 trading days TSMOM should have at least one position to track.

---

## 3. Main Ensemble Portfolio

| Metric | Value |
|--------|-------|
| Starting capital | $100,000 |
| Cash | $37,801.41 |
| Estimated equity | ~$97,882 |
| Open positions | 7 (AAPL 31, AMD 9, AMZN 36, AVGO 22, MSFT 22, NVDA 44, SPY 12) |
| Trade diagnoses | 13 open trades tracked |
| Win rate (latest health) | 7.7% (1 win / 13) |
| Avg P&L per trade | -3.76% |
| Sharpe of trade P&Ls | -4.37 |
| Dominant failure mode | whipsaw |
| Strategy health action | "tune" |

**Today's mock fills:**
- ACCEPTED BUY 9 AMD @ $499.37 (close $499.38 — flat)
- ACCEPTED BUY 6 SPY @ $752.48 (close $738.70 — -1.83%)
- REJECTED BUY 16 AAPL @ $312.99 (exceeded risk gate)

**Market context:** SPY -2.43%, AMD -4.55%, AVGO -3.85%, NVDA -2.29%, MSFT -0.09%, AAPL +0.72%, AMZN +0.37%. The ensemble was buying into a weak tape and got caught in today's broad selloff. Cash continues to drain ($37.8k from $46.8k yesterday).

**Evidence quality:** MODERATE. 13 open trade diagnoses exist. However, all regime labels remain "unknown" (see finding below).

---

## 4. Options Paper Loop

| Metric | Value |
|--------|-------|
| Starting capital | $100,000 |
| Cash | $100,193.50 |
| Reserved (CSP collateral) | $20,000 |
| Active positions | 1 (SHORT NVDA $200 PUT exp 2026-06-18) |
| Granted premium | $193.50 |
| NVDA close | $213.65 |

The single CSP (NVDA $200 strike) is safely OTM at $213.65 with ~13 DTE. No new candidates were queued. Unchanged from yesterday.

---

## 5. Structural Finding: Regime Labeler Always Returns "unknown"

**Root cause confirmed.** The `label_regime()` function in `market_lab/diagnosis.py` receives `bars_after_entry` — the bars since the trade was entered. For all 13 open trades, this is only 2-5 bars. The function's first guard:

```python
if len(bars) < 20:
    return "unknown"
```

...triggers on every diagnosis. Trades never survive long enough to accumulate 20 bars.

**The fix requires passing pre-entry bars to `label_regime()`** — not post-entry bars. The regime at trade time determines whether the strategy was buying into a trending/chopping market. The current code would only produce labels for trades held >20 trading days (~1 calendar month), which none of the mock trades ever survive.

**Impact:** Every strategy health report's `regime_breakdown` is useless — all 13 trades crammed into "unknown." The "tune" recommendation fires solely from the -4.37 Sharpe, which is correct but lacks the regime context needed to decide *how* to tune.

---

## 6. Evidence Quality Comparison

| Dimension | Main Portfolio | vt_trend | TSMOM | Options Paper |
|-----------|---------------|----------|-------|---------------|
| **Track history** | 8 days | 2 days | 1 day | 3 days |
| **Fills** | 18 accepted | 1 | 0 | 1 CSP |
| **Trade diagnoses** | 13 (open) | 0 | 0 | 0 |
| **Win rate** | 7.7% | — | — | — |
| **Trade Sharpe** | -4.37 | — | — | — |
| **Data freshness** | yfinance live | yfinance live | yfinance live | yfinance chains |
| **Regime labels** | All "unknown" | — | — | — |
| **Key change** | Bought more into selloff | FIRST FILL | FIRST CANDIDATE | Unchanged |

**The independent tracks are now generating live data for the first time.** vt_trend is in-position. TSMOM will fill next session. The regime labeler bug means we still can't answer "does this strategy work in trending vs. choppy markets."

---

## 7. Next Safe Research-Only Action

### Primary recommendation: Extend manual daily cadence for 3-5 more trading days

The independent tracks are now producing the evidence that was missing. Let them accumulate fills before drawing conclusions. Specifically:

1. **Tomorrow (2026-06-06 after market close):** Run `python3 scripts/market_lab_independent_tracks.py --network --require-live-data`
   - TSMOM's pending candidate should fill → first TSMOM position
   - vt_trend should generate another BUY → ~2 shares SPY
2. **Each subsequent day:** Same command. Track fills and P&L trajectory.
3. **After 5 trading days:** Run evidence council on both vt_trend and TSMOM ledgers for first cross-track comparison.

### Secondary recommendation: Document regime labeler fix for next code-change task

The regime labeler fix is a ~5-line change (swap the bars passed to `label_regime()` from post-entry to pre-entry context). But per task scope, I cannot change code. This should be the first code change in the next implementation card.

### Not recommended right now:
- **Adding symbols to independent tracks** — SPY-only is fine for initial evidence collection
- **Wiring evidence council to vt_trend ledger** — premature with only 1 fill
- **Adding cron/scheduling** — manual cadence is correct until tracks prove stable
- **Changing ensemble signal thresholds** — no regime-labeled evidence to guide the change

---

*Research/paper-only. No live broker orders. No investment advice.*