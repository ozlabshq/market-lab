# vt_trend Independent Mock-Tracking Gate — Research Spec

**Status:** Pre-implementation specification (research/paper-only)
**Date:** 2026-06-03
**Author:** Ozzy (ozzy-research)
**Context:** vt_trend merged to main at 62cc754 / PR #16. Next-safe-experiment proposal recommended 30-day mock tracking before any ensemble wiring. This spec defines the gate.
**Posture:** research/mock/paper only. No live broker orders, no secrets, no investment advice.

---

## 1. Why an Independent Gate

vt_trend is the codebase's first volatility-targeted trend signal with variable position sizing and drawdown circuit breakers. It deliberately lives outside the main ensemble pipeline — `generate_strategy_signals()` does not include it, and `market_lab_daily.py` does not feed it into order candidates.

The 30-day mock period must be **fully independent** from the main portfolio for three reasons:

| Reason | Detail |
|--------|--------|
| **Isolation** | Main mock portfolio holds 5 positions from ensemble TSMOM/RSI/baseline signals. Commingling vt_trend's vol-scaled positions would confound attribution — you couldn't tell which strategy caused the P&L. |
| **No lookahead laundering** | The same close→next-open discipline applies, but a separate ledger prevents accidental data cross-contamination in diagnosis (e.g., attributing a main-portfolio SELL to a vt_trend trigger). |
| **Clean go/no-go decision** | After 30 tracking days, the isolated P&L is the sole evidence for promotion. No "well the main portfolio had a bad week so vt_trend looks good by comparison" ambiguity. |

---

## 2. Signal Schedule

vt_trend evaluates at the daily close and produces a target weight (not a binary BUY/SELL). The tracking process mirrors the main pipeline's candidate model:

```
t close:
  fetch_prices(symbol, days=120+)
  sig = generate_vt_trend_signal(symbol, bars)
  if target_weight differs from current position weight by > threshold (0.001):
    queue an OrderCandidate for next-open fill
    signal_date = t

t+1 open:
  if candidate exists and latest_date > signal_date:
    place_mock_order(side, symbol, qty, next_open)
    append to vt_trend ledger
    update vt_trend portfolio state
```

**Cadence:** One evaluation cycle per trading day, triggered by the same cron/scheduler that runs `market_lab_daily.py`. The tracking script is designed to be called daily regardless of whether a candidate is due.

**Symbol scope:** Start with SPY only for the 30-day tracking window. Rationale:
- SPY is the most liquid, lowest-noise symbol — cleanest signal evaluation
- One symbol eliminates cross-sectional complexity during validation
- vt_trend is a single-symbol trend strategy by design (the `target_vol` parameter is per-symbol)
- If SPY tracking is clean, expand to QQQ as a second axis in a follow-up card

**What if the signal stays HOLD for days?** That's expected behavior — vt_trend spends long periods flat (vol spike guard, drawdown level 2, trend break). The tracking script records a daily "no candidate" log entry so the absence of activity is itself evidence.

**What if the signal jumps from HOLD to BUY at 0.3 target weight?** A re-entry after a flat period creates a candidate at next-open fill. The sizing backtest engine handles this correctly — it computes delta between current weight (0.0) and desired weight (0.3) and issues a BUY for the difference.

---

## 3. Isolated Ledger / State Semantics

### 3.1 State Files

All vt_trend state lives under a dedicated subdirectory, completely separate from the main mock portfolio's files.

| File | Path | Purpose |
|------|------|---------|
| State | `data/market-lab/vt_trend/portfolio_state.json` | Current cash, position quantity, avg price. Same `Portfolio` dataclass as main broker. |
| Ledger | `data/market-lab/vt_trend/ledger.jsonl` | Append-only JSONL of every `OrderDecision` — accepts and rejects. Same schema as main `mock_ledger.jsonl`. |
| Candidates | `data/market-lab/vt_trend/pending_candidates.jsonl` | Queued close→next-open candidates. Same `OrderCandidate` schema. |
| Diagnostics | `data/market-lab/evidence/vt_trend_trades.jsonl` | `TradeDiagnosis` records, appended via the evidence council. Stream name `vt_trend_trades`. |
| Health | `data/market-lab/evidence/vt_trend_health.jsonl` | `StrategyHealthReport` records. Stream name `vt_trend_health`. |

### 3.2 Reuse Existing Broker Functions

The mock broker's `load_portfolio`, `save_portfolio`, `place_mock_order`, `append_ledger`, `load_order_candidates`, `save_order_candidates` all accept optional `path` parameters. The vt_trend tracking module passes vt-specific paths:

```python
VT_DATA_DIR = Path(os.environ.get("MARKET_LAB_VT_TREND_DIR", 
    os.environ.get("MARKET_LAB_DATA_DIR", ROOT / "data" / "market-lab")) / "vt_trend")

VT_STATE_PATH = VT_DATA_DIR / "portfolio_state.json"
VT_LEDGER_PATH = VT_DATA_DIR / "ledger.jsonl"
VT_CANDIDATES_PATH = VT_DATA_DIR / "pending_candidates.jsonl"
```

**No new code for broker operations.** It's the same `place_mock_order()`, same `OrderCandidate` → `candidate_to_order_at_open()` flow, same `_portfolio_lock()`, same atomic writes — just different path arguments. The safety gates in `evaluate_order()` remain in effect (no live trading, no shorting, position limits, etc.).

### 3.3 Initial Capital

vt_trend starts with **$25,000 mock cash** — a quarter of the main portfolio's $100k. Rationale:
- vt_trend is the experiment; the main portfolio is the baseline
- With volatility targeting at 15% target vol, position sizes are smaller than full equity deployment
- $25k provides enough headroom for 5+ concurrent positions at the max trade notional ($5k)
- If vt_trend outperforms, the success metric is risk-adjusted return, not dollar P&L — capital size is irrelevant to the Sharpe ratio

### 3.4 Portfolio Lock Integrity

The existing `_portfolio_lock()` uses `fcntl.flock` on a `.lock` file adjacent to the state file. Since vt_trend uses a different state path, its lock file is `vt_trend/portfolio_state.json.lock` — separate from the main `mock_portfolio_state.json.lock`. No contention.

### 3.5 Candidate Queue Semantics

Same as main pipeline:
- Candidates are generated at signal close (`signal_date`)
- Filled at the next available open where `latest_date > signal_date`
- If no such bar exists yet, the candidate stays in the pending file
- `_dedupe_candidates()` collapses duplicate (symbol, signal_date, strategy, side) entries — inherited behavior

---

## 4. Performance / Evidence Metrics

### 4.1 Metrics Collected per Tracking Day

| Metric | Source | Format |
|--------|--------|--------|
| Current equity | vt_trend portfolio state + latest close | `$X,XXX.XX` |
| Cash remaining | vt_trend portfolio state | `$X,XXX.XX` |
| Open position quantity | vt_trend portfolio state | `int` |
| Position weight (% of equity) | Computed | `XX.X%` |
| Target weight from signal | `generate_vt_trend_signal` return | `XX.X%` |
| Vol20 (annualized) | Signal evidence dict | `XX.X%` |
| Exposure (target_vol / vol20) | Signal evidence dict | `X.XX` |
| Drawdown from 90d peak | Signal evidence dict | `-XX.X%` |
| Drawdown level | Signal evidence dict | `0`, `1`, or `2` |
| Trend regime | Signal evidence dict (`trend_up`) | `true` / `false` |
| Re-entry allowed | Signal evidence dict (`reentry_ok`) | `true` / `false` |

### 4.2 Metrics Accumulated over 30 Days

| Metric | Computation | Use |
|--------|-------------|-----|
| Total return | `(final_equity / initial_cash) - 1` | Headline P&L |
| Sharpe ratio | Annualized from daily equity returns | Risk-adjusted comparison |
| Max drawdown | Peak-to-trough from equity curve | Worst-case loss |
| Win rate of fills | Fills with positive P&L / total fills | Signal reliability |
| Average holding bars | Mean bars per position before exit | Turnover proxy |
| Trade frequency | Fills / trading days | Activity level |
| Time in market | Days with non-zero position / total days | Opportunity cost |
| Volatility of strategy returns | Std dev of daily equity returns | Risk consistency |
| Benchmark comparison | SPY buy/hold over same period | Relative performance |

### 4.3 Evidence Council Integration

The existing evidence council (`market_lab_review.py` → `diagnose_new_mock_decisions()`) reads from a single ledger. For vt_trend to get diagnoses, the review script must accept a ledger path parameter, or a new script reads from the vt_trend ledger.

**Recommended approach:** Add a `--ledger-path` flag to `market_lab_review.py`. When omitted, defaults to the main ledger (current behavior). When passed, reads vt_trend's ledger for diagnosis.

Example:
```bash
python3 scripts/market_lab_review.py --ledger-path data/market-lab/vt_trend/ledger.jsonl
```

This keeps one review script with a parameterized entry point rather than forking into two separate scripts.

### 4.4 Go / No-Go Thresholds for Promotion

After 30 tracking days, evaluate against these criteria. All three must pass:

| Criterion | Threshold |
|-----------|-----------|
| Sharpe ratio | `>= 0.5` — strategy adds risk-adjusted value over cash |
| Max drawdown | `<= -25%` — no catastrophic tail worse than buy/hold drawdowns during the period |
| Signal utilization | `>= 40%` of trading days produced a non-zero target weight — strategy wasn't flat the whole period |

If any criterion fails, produce a gap analysis and either:
- Adjust parameters (target_vol, vol_floor) and restart the 30-day clock, OR
- Write off the experiment with a post-mortem

---

## 5. Safety Guardrails

### 5.1 Built into vt_trend Signal (Already Merged)

| Guard | What it does |
|-------|-------------|
| Vol spike guard | vol20 > 100% → go flat |
| Exposure floor | raw exposure < 0.10 → go flat |
| Drawdown level 1 | 15% below 90d peak → reduce to 50% |
| Drawdown level 2 | 20% below 90d peak → go flat |
| Re-entry rule | After level 2, re-entry requires trend up AND close > 90% of peak |
| Trend break | Close below SMA100 → go flat |
| Max leverage cap | `full_target_weight` clamped to `max_leverage` (1.0) |

### 5.2 Built into Mock Broker (Already Merged)

| Guard | What it does |
|-------|-------------|
| `RiskConfig.live_trading_enabled` = False | `evaluate_order` refuses all orders |
| Max position (%) | 10% of equity |
| Max single order (%) | 5% of equity |
| Min trade notional | $500 |
| Max trade notional | $5,000 |
| No shorting | `allow_short` = False |
| No margin | `allow_margin` = False |
| Atomic state writes | Temp file + `os.replace` |
| `fcntl` portfolio lock | Process-level exclusion on concurrent writes |

### 5.3 Additional Mock-Tracking Gates (New for This Spec)

| Gate | Mechanism | Why |
|------|-----------|-----|
| **Portfolio isolation** | Separate state/ledger/candidate paths under `vt_trend/` | Prevents state cross-contamination with main portfolio |
| **Synthetic data detection** | `--require-live-data` flag; abort if any symbol's price source is synthetic | Mock tracking on synthetic prices produces misleading evidence |
| **Capital cap** | Start with $25k, never exceed `RiskConfig.max_trade_notional` per order | Limits experiment scope; main portfolio is the baseline |
| **No ensemble wiring** | `generate_strategy_signals()` and `generate_ensemble_signal()` unchanged | Keeps the gate honest — vt_trend earns promotion on its own evidence |
| **Hard max fill rate** | At most 1 fill per symbol per day | Prevents intraday compounding from accumulated pending candidates |

### 5.4 No Broker / Live Path

vt_trend mock tracking uses only the existing mock broker (`broker.py`). There is:
- No Tradier adapter integration
- No Alpaca adapter integration
- No `live_trading_enabled` path
- No secrets, no API keys, no environment variables beyond `MARKET_LAB_DATA_DIR`

---

## 6. Regression Tests

### 6.1 New Test File: `tests/market_lab/test_vt_trend_tracking.py`

| Test | What it covers |
|------|---------------|
| `test_vt_trend_state_path_isolation` | vt_trend state file paths are distinct from main | 
| `test_vt_trend_load_save_portfolio` | Load/save vt_trend portfolio at vt-specific path. Verify main portfolio is unchanged. |
| `test_vt_trend_ledger_isolation` | Append to vt_trend ledger; verify main ledger has no new records |
| `test_vt_trend_candidate_queue` | Queue a vt_trend candidate at vt-specific path; verify main candidate file unchanged |
| `test_vt_trend_signal_to_fill_cycle` | Full cycle: generate vt_trend signal → queue candidate → fill at next open → portfolio state correct |
| `test_vt_trend_initial_capital` | Starting cash is $25,000, not $100,000 |
| `test_vt_trend_flat_period_logging` | No signal → no candidate → tracking log shows "no candidate" counter |
| `test_vt_trend_reentry_produces_correct_side` | After level 2 flat → re-entry OK → BUY candidate for correct delta weight |
| `test_vt_trend_diagnosis_integration` | vt_trend ledger fed to `market_lab_review` produces correct diagnoses at vt_trend evidence path |
| `test_vt_trend_synthetic_data_refusal` | `--require-live-data` aborts when any symbol is synthetic |

### 6.2 Modified Test Files

| File | Change |
|------|--------|
| `tests/market_lab/test_research_strategies.py` | No change — vt_trend tests already exist here |
| `tests/market_lab/test_broker.py` | Add a test verifying `place_mock_order` with custom `portfolio_path` and `ledger_path` works and doesn't touch default paths |

### 6.3 Test Infrastructure Notes

- All tests use `tempfile.TemporaryDirectory` to avoid polluting real state
- `bars_from_prices()` helper from test_research_strategies.py can be imported directly
- Tests must be hermetic — no dependency on existing vt_trend/ directory on disk

---

## 7. Dashboard / Report Surface

### 7.1 Daily Report Section

Add a new section to the daily markdown report (in `report.py` `render_report()`) when vt_trend tracking data is present:

```markdown
## vt_trend Independent Mock Tracking — Day N/30

**Status:** Research tracking — not wired into ensemble. Evidence collected daily.

| Metric | Value |
|--------|-------|
| Cash | $XX,XXX.XX |
| Position | XXX shares SPY @ $XXX.XX avg |
| Equity | $XX,XXX.XX |
| Position weight | XX.X% |
| Target weight | XX.X% |
| Vol20 (ann.) | XX.X% |
| Drawdown from 90d peak | -XX.X% |
| Drawdown level | 0/1/2 |
| Trend regime | up / break / flat |
| Re-entry allowed | yes / no |
| Cumulative fills | N |
| Days since first fill | N |
| Evidence council last run | 2026-06-03 |
```

Condition: This section renders only when `data/market-lab/vt_trend/` exists and contains a portfolio state file. Absence of vt_trend tracking is not an error — it means tracking hasn't started yet.

### 7.2 Evidence Council Health Report

The strategy health report (via `market_lab_review.py --ledger-path ...`) produces a `StrategyHealthReport` for strategy `"vt_trend"`:

```json
{
  "strategy": "vt_trend",
  "total_trades": 5,
  "win_rate": 0.60,
  "avg_pnl": 0.012,
  "sharpe_of_trades": 0.8,
  "avg_holding_bars": 8.2,
  "regime_breakdown": {"trending_up": {...}},
  "decay_alert": false,
  "recommended_action": "continue",
  "top_failure_modes": ["false_positive"]
}
```

### 7.3 Webapp Surface

Add an HMAC-signed `/api/vt-trend-snapshot` endpoint to the existing web app (same pattern as `/api/snapshot`). Returns JSON:
- Current state: cash, position, equity, latest signal evidence
- Cumulative metrics: fills, win rate, total return (if tracking is active)
- Last evidence council timestamp

The webapp's read-only posture is unchanged (POST/PUT/PATCH/DELETE → 405).

### 7.4 Automated Report Capture

When the tracking script runs, it emits a markdown snapshot to:
```
data/market-lab/vt_trend/reports/vt_trend-YYYYMMDD-HHMMSS.md
```
Plus `data/market-lab/vt_trend/reports/latest.md` (symlink or overwrite). This mirrors the main report pattern and lets the webapp serve it without parsing JSONL.

---

## 8. Dev Follow-Up Card

### 8.1 Implementation Card

```yaml
Title: Implement vt_trend independent mock-tracking gate (30-day)
Assignee: ozzy-research
Skills: [ozlabs-operations]
Body: |
  Wire vt_trend into its own mock portfolio per research/vt-trend-mock-tracking-spec.md.

  Deliverables:
  1. Create scripts/market_lab_vt_trend.py:
     - Daily evaluation: fetch SPY bars → generate_vt_trend_signal() → queue candidate if weight differs
     - Execute due candidates at next-open fill on vt-specific state/ledger
     - Emit markdown report to data/market-lab/vt_trend/reports/
     - Accept --network (prefer yfinance), --require-live-data (abort on synthetic)
     - Track "days since start" counter; after 30 days emit a completion summary

  2. Add vt_trend paths to market_lab/config.py:
     VT_TREND_DIR = DATA_DIR / "vt_trend"
     VT_TREND_STATE = VT_TREND_DIR / "portfolio_state.json"
     VT_TREND_LEDGER = VT_TREND_DIR / "ledger.jsonl"
     VT_TREND_CANDIDATES = VT_TREND_DIR / "pending_candidates.jsonl"
     VT_TREND_REPORT_DIR = VT_TREND_DIR / "reports"
     Initial capital: VT_TREND_STARTING_CASH = 25_000.0

  3. Add --ledger-path flag to scripts/market_lab_review.py:
     - Default: current behavior (reads main ledger)
     - When passed: reads vt_trend ledger, writes to evidence/vt_trend_trades.jsonl
     - Update evidence_stream_path() to use strategy-specific stream names

  4. Add vt_trend section to market_lab/report.py render_report():
     - Conditionally render vt_trend tracking table when vt_trend state exists
     - Include all metrics from spec section 7.1

  5. Add research-only webapp endpoint at webapp.py:
     - /api/vt-trend-snapshot returns JSON of current vt_trend state
     - Same read-only posture (no write verbs)

  6. Write tests at tests/market_lab/test_vt_trend_tracking.py:
     - 10 tests from spec section 6.1

  7. Add test to tests/market_lab/test_broker.py:
     - Verify place_mock_order with custom paths works independently

  8. Wire into .github/workflows/ci.yml or equivalent:
     - New tests run in CI; no new dependencies

  Safety:
  - All mock orders go through existing evaluate_order() (live_trading_enabled = False enforced)
  - Separate paths prevent cross-contamination with main portfolio
  - --require-live-data aborts if synthetic prices are used
  - No ensemble wiring; vt_trend stays independent

  Posture: research/mock/paper only. No live broker orders. No secrets.

  Acceptance criteria:
  - `python3 scripts/market_lab_vt_trend.py --network` runs cleanly and produces vt_trend/state + reports
  - `python3 scripts/market_lab_review.py --ledger-path data/market-lab/vt_trend/ledger.jsonl` diagnoses vt_trend fills
  - Daily report shows vt_trend section when tracking is active
  - 10 new tests pass
  - Main portfolio state is completely unchanged after vt_trend operations
```

### 8.2 Prerequisites (Before Implementation)

None — vt_trend signal, backtest engine, mock broker, evidence council all exist and pass tests. The implementation is wiring-only.

### 8.3 Dependency Chain

```
t_da30e988 (this spec)
  └─→ [implementation card] ──→ scripts/market_lab_vt_trend.py + config + tests + review
       └─→ tests pass on CI
            └─→ first manual run on SPY
                 ├─→ 30 tracking days elapse
                 │    ├─→ evidence council runs weekly
                 │    └─→ daily report includes vt_trend section
                 └─→ day 30 evaluation → go/no-go for ensemble wiring
                      ├─→ go: card to wire vt_trend into ensemble signal
                      └─→ no-go: post-mortem card, parameter tune, restart
```

---

## 9. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| SPY-only scope | Start with 1 symbol | Cleanest signal evaluation; eliminates cross-sectional complexity |
| Separate script vs. flag on daily.py | Separate script (`market_lab_vt_trend.py`) | Zero risk of state cross-contamination; independent scheduling |
| Reuse broker fns with path args vs. new broker | Reuse existing | Same safety gates, same atomicity, same test coverage — just different paths |
| $25k initial capital vs. $100k | $25k | Experiment-scale; outcome metric is Sharpe/return, not dollar P&L |
| Review script parameter vs. fork | `--ledger-path` flag | One script, parameterized entry point; evidence council logic unchanged |
| 30 calendar days vs. 30 trading days | 30 calendar days | Simpler to track; allow some holiday/skip days in the window |
| Go/no-go at 30 days vs. rolling evaluation | Hard stop at 30 days | Prevents "just a few more days" bias; clean binary promotion decision |

---

## 10. Prior Art in This Repo

- **Tradier sandbox spec** (`research/tradier-sandbox-integration-spec.md`): Same research-only posture, independent env gates, evidence-based promotion criteria.
- **Next-safe-experiment proposal** (`research/next-safe-experiment-proposal.md`): This spec is the direct follow-through on Phase 2 step 3 ("If vt_trend passes backtest gates: Create follow-up card to wire vt_trend into mock order candidate queue — separate from ensemble — independent tracking portfolio").
- **Evidence council** (`market_lab/evidence.py`, `market_lab/diagnosis.py`, `scripts/market_lab_review.py`): The diagnostics pipeline this spec extends with a parameterized entry point.

---

*End of spec. Research/paper-only. No live trading, no investment advice.*