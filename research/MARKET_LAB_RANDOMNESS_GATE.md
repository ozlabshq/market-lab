# Market Lab Randomness Gate

**Status:** Implementation-ready methodology contract  
**Scope:** Research and paper/mock trading only  
**Captured:** 2026-08-30T22:12:13Z  
**Visual companion:** `docs/market-lab-randomness-gate.html`

## Decision

Market Lab should adopt the image's central principle:

> A raw signal is not an edge. An edge is the part that survives known-exposure removal, out-of-sample tests, costs, time, and regime change.

Market Lab must not copy the image's chart values, author identities, or affiliations as facts. The supplied image has no visible DOI, publication date, journal, bibliography, or source URL. Its `qmlab.edu` addresses and generic institution names are not enough to identify a publication. Treat the image as an unverified conceptual reference.

## Source record

- Artifact: `docs/assets/quant-guide-trading-randomness-reference.jpg`
- SHA-256: `cad9b49cad2824557c1e021f1a11f91cdb0cadcd9be05d463c136a013c70b61f`
- Visible title: *The Quant Guide To Trading Randomness*
- Visible subtitle: *How to stop trading noise and start hunting real edge*
- Evidence grade: `CONCEPT_ONLY`
- Adopted: The validation workflow.
- Not adopted: The displayed distributions, implied empirical results, named authors, and institutional provenance.

## Why this belongs in Market Lab

Market Lab already guards execution timing and compares some signals with SPY. It does not yet prove that a candidate contains return information beyond broad market or sector exposure. It also does not use one fail-closed admission gate that joins out-of-sample quality, costs, regime stability, and sample sufficiency before paper queueing.

The Randomness Gate fills that gap. It is a promotion contract, not a new trading strategy.

## The gate

A strategy moves through these stages:

```text
PREDECLARE
    ↓
POINT-IN-TIME DATA
    ↓
REMOVE KNOWN EXPOSURES
    ↓
TEST THE RESIDUAL OUT OF SAMPLE
    ↓
APPLY COST AND LIQUIDITY STRESS
    ↓
CHECK REGIME AND SEGMENT STABILITY
    ↓
ADJUDICATE SAMPLE SIZE AND MULTIPLE TESTS
    ↓
RESEARCH_ONLY | PAPER_CANDIDATE | REJECT
```

No stage can silently repair or relabel evidence from an earlier stage.

## Stage contract

### 1. Predeclare the hypothesis

Before a backtest starts, save a strategy manifest with:

- Strategy ID and version.
- Economic or behavioral mechanism.
- Universe and exclusions.
- Signal formula and parameters.
- Holding horizon and rebalance schedule.
- Benchmark and sector/control set.
- Known exposure model.
- Cost assumptions and stress multipliers.
- OOS design.
- Promotion thresholds.
- Invalidation rules.

A parameter change creates a new strategy version. It does not rewrite the old result.

### 2. Enforce point-in-time data

Every input must carry source and availability metadata. Market Lab must block promotion when:

- Synthetic data enters a promotion test.
- A revised value replaces the value available at the decision time.
- Corporate actions are unadjusted or ambiguous.
- Benchmark or control data is missing.
- The signal uses later bars, filings, factors, or outcomes.

Close-of-day `t` decisions keep the current next-open rule. The earliest fill remains open `t+1`.

### 3. Remove known exposures

For asset return `r_i,t`, estimate only with information available by time `t`:

```text
r_i,t = α_i + β_market × r_market,t + β_sector × r_sector,t
        + Σ β_k × factor_k,t + ε_i,t
```

The residual `ε_i,t` is the security-specific return not explained by the declared controls. The first implementation can start with market and sector controls. Additional factors must be predeclared and justified.

Required outputs:

- Raw return.
- Expected return from controls.
- Residual return.
- Estimated exposure coefficients.
- Estimation window.
- Missing-data and fit-quality flags.

Residualization does not create an edge. It only states what remains unexplained by the selected model.

### 4. Test only unseen periods

The current single train/OOS split is useful but insufficient for promotion. Add repeated chronological walk-forward folds.

Each fold must:

- Select parameters on train data only.
- Preserve warm-up bars without counting them as OOS results.
- Evaluate a later, disjoint period.
- Purge or embargo overlapping labels when the holding horizon creates leakage.
- Store train and OOS metrics separately.

The final verdict must use OOS results. In-sample performance is diagnostic only.

### 5. Apply friction stress

Test the strategy after:

- Next-open execution.
- Commission.
- Slippage.
- Bid/ask spread when available.
- Turnover.
- Liquidity and position-size limits.
- A stricter cost scenario.

A paper candidate must not depend on zero-cost execution. A fixed five-basis-point model can remain the baseline for current equity tests, but promotion also needs a declared stress case. Market impact remains `NOT_MODELED` until volume-aware sizing exists.

### 6. Check persistence

Report performance by:

- OOS fold.
- Symbol and sector.
- Bull, bear, high-volatility, and low-volatility regime.
- Calendar period.
- Cost scenario.

Flag concentration when one symbol, fold, or regime explains most of the result. Do not average away a broken segment.

### 7. Guard against randomness

The evaluator must expose:

- Number of parameter combinations tried.
- Number of strategy variants tried.
- OOS observation count.
- OOS trade count.
- Confidence interval or bootstrap interval when valid.
- Sensitivity to small parameter changes.
- Stability across folds.

A small sample produces `INSUFFICIENT_EVIDENCE`, not `PASS`. Multiple testing requires stricter evidence. The MVP can report the test count and block promotion until the strategy manifest declares an accepted correction method.

## Admission result

The evaluator returns one result:

- `RESEARCH_ONLY`: The idea can continue in analysis but cannot enter a paper queue.
- `PAPER_CANDIDATE`: All required evidence gates pass. A separate risk review is still required.
- `REJECT`: The evidence fails a declared threshold or an integrity rule.

`PAPER_CANDIDATE` is not an order. Existing portfolio, data, timing, collateral, and risk gates remain authoritative.

## Required evidence record

Each evaluation should create an immutable `EdgeEvaluation` record:

```text
edge_evaluation_id
strategy_id
strategy_version
created_at_utc
manifest_sha256
data_catalog_sha256
benchmark_ids[]
control_ids[]
train_windows[]
oos_windows[]
raw_metrics
residual_metrics
cost_scenarios[]
regime_metrics[]
stability_metrics
multiple_test_count
quality_flags[]
gates[]
verdict
blockers[]
next_owner
next_action
```

Every gate uses `PASS | WARN | FAIL | BLOCKED | NOT_APPLICABLE`.

## Promotion thresholds

Do not use one universal Sharpe or return threshold. Each strategy manifest must declare thresholds before evaluation. The minimum contract is:

- Positive net OOS expectancy under the baseline cost case.
- No sign reversal under the declared stress-cost case unless explicitly blocked from promotion.
- Residual performance reported beside raw performance.
- More than one chronological OOS fold.
- No unresolved lookahead, data-source, benchmark, or control-set blocker.
- No direct dependence on one fold, symbol, or regime without a concentration warning and reviewer decision.
- Sufficient observations and trades for the strategy horizon.
- Independent review approval.

## Current-state map

### Implemented now

- SPY-relative guards in momentum signals and ranking.
- A deterministic train/OOS split in `market_lab/optimization.py`.
- Warm-up exclusion through `evaluation_start_index`.
- Close `t` decision and next-open execution.
- Baseline commission and slippage in `market_lab/backtest.py`.
- Basic regime labels and post-trade diagnosis.
- Source tracking that separates synthetic and live/cache data.

### Partial

- Costs: Fixed slippage and commission exist. Spread, turnover capacity, and market impact are incomplete.
- Regimes: Basic labels exist. Promotion tests do not yet require segment stability.
- Benchmarking: SPY-relative guards exist. A general benchmark-and-sector residual model does not.
- OOS: One split exists. Repeated walk-forward and purge/embargo logic do not.

### Missing

- Versioned strategy manifests with predeclared promotion thresholds.
- Market and sector residual-return series.
- One immutable `EdgeEvaluation` record.
- Multiple-testing and sample-sufficiency gates.
- Queue-level enforcement of an approved edge evaluation.
- Dashboard views for raw versus residual performance and gate failures.

## Safe implementation sequence

### Slice 1 — Evidence contract

Add a strategy manifest and `EdgeEvaluation` schema. Add a pure fail-closed evaluator. Do not wire it to paper queueing.

Acceptance:

- Invalid, missing, nonfinite, or contradictory evidence returns `BLOCKED`.
- The record is deterministic and hashable.
- Tests cover every verdict and gate status.

### Slice 2 — Residual model

Add rolling market and sector exposure estimation. Keep the model simple and auditable.

Acceptance:

- Synthetic fixtures recover known beta and residual series within tolerance.
- Estimation uses past data only.
- Missing controls block residual claims.
- Raw and residual metrics remain separate.

### Slice 3 — Robust OOS runner

Add repeated chronological walk-forward folds and optional purge/embargo periods.

Acceptance:

- No train/evaluation overlap.
- Parameters come from train data only.
- All fold boundaries are stored.
- A deliberately overfit fixture fails OOS.

### Slice 4 — Friction and persistence report

Add baseline/stress cost scenarios and segment breakdowns.

Acceptance:

- Zero-cost performance cannot substitute for net performance.
- One-regime or one-symbol concentration is visible.
- Missing liquidity inputs are explicit quality flags.

### Slice 5 — Paper promotion enforcement

Require an approved, current `EdgeEvaluation` before a strategy family can create a new paper candidate.

Acceptance:

- Missing, stale, rejected, or hash-mismatched evaluations block queue mutation.
- Existing risk gates cannot be weakened by an edge approval.
- The queue audit cites the exact evaluation ID and hash.

## Explicit non-goals

- Live trading.
- Automatic strategy invention and promotion.
- Treating residuals as proof of causality.
- Hiding raw underperformance behind a factor model.
- Optimizing until one backtest passes.
- Using the supplied image as empirical evidence.

## Founder-facing rule

Market Lab should display this sentence beside every promoted strategy:

> The edge is not the backtest. The edge is what remains after known exposures, unseen time, realistic costs, and regime change try to remove it.
