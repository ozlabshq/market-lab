# Market Lab v1 Master Plan: Research, Mock Trading, and Agent Council

**Status:** active build plan  
**Mode:** research + mock/paper only; no live trading  
**Owner:** OzLabs / Ozzy operator lane  

## North Star

Build Market Lab into a research-grade trading laboratory: fast enough to test hypotheses, strict enough to avoid fake edge, and agentic enough to analyze mock trades, propose experiments, and compound evidence over time.

Core stance: **aggressive research, conservative execution**.

## System Shape

Market Lab v1 should evolve around five layers:

1. **Data layer**
   - deterministic cached OHLCV/factor data
   - source labels for yfinance/cache/synthetic
   - synthetic data isolated from real validation
   - future sources: FRED, VIX proxies, earnings/event data, read-only options chains

2. **Research/backtest layer**
   - single-asset event-driven backtests for auditability
   - portfolio-level rebalance backtests for ETF rotation
   - vectorized/array backtest path for fast parameter sweeps
   - walk-forward optimization and OOS reporting as a default gate

3. **Strategy layer**
   - Alpha models emit signals/insights, not orders
   - Portfolio construction turns signals into target weights
   - Risk overlays can reduce/flat targets without rewriting strategy code
   - Execution model applies next-open fills, slippage, commissions, and mock-only gates

4. **Mock trading layer**
   - queued next-open candidates
   - accepted/rejected mock decisions
   - append-only ledger
   - portfolio state with atomic writes and reconciliation
   - no live execution until future approval gates

5. **Agent council layer**
   - Trade Reviewer diagnoses mock trades
   - Strategy Diagnostician monitors decay and regime dependency
   - Experiment Proposer suggests tests from evidence
   - Evidence Ledger Keeper audits data/state integrity
   - Risk Arbiter/Ozzy approves or blocks promotions

## Council Roles

### Trade Reviewer
Reviews completed or open mock trades and emits `TradeDiagnosis` records:
- P&L and benchmark-relative performance
- holding period
- regime label
- hypothesis/evidence snapshot
- failure mode if loss or underperformance

### Strategy Diagnostician
Aggregates diagnoses by strategy and emits `StrategyHealthReport` records:
- win rate, average P&L, trade Sharpe
- regime breakdown
- top failure modes
- decay alert
- recommended action: continue, tune, pause, retire

### Experiment Proposer
Converts health problems into bounded research tasks:
- hypothesis
- parameter delta or feature addition
- baseline to beat
- validation plan
- kill switch

### Evidence Ledger Keeper
Protects trust in the lab:
- append-only JSONL evidence streams
- synthetic-data flags
- state/ledger reconciliation
- orphan temp-file audit
- agent-action audit trail

## Strategy Research Tracks

### Track A: Volatility-Targeted Trend Following
Hypothesis: trend-following improves risk-adjusted returns when exposure scales inversely to recent realized volatility and drawdown guards reduce exposure in reversals.

Implementation gates:
- variable-size backtest support
- risk overlays: drawdown, vol spike, re-entry
- parameter robustness and walk-forward validation

### Track B: Dual Momentum ETF Rotation
Hypothesis: positive absolute momentum plus top relative momentum produces stronger risk-adjusted results than either alone.

Current state: initial dual momentum portfolio construction/backtest exists.

Next gates:
- inverse-vol weighting option
- turnover and concentration metrics
- macro/regime overlay
- walk-forward universe validation

### Track C: Volume-Confirmed Mean Reversion
Hypothesis: oversold pullbacks inside uptrends have better expectancy when accompanied by capitulation volume and explicit stop/time exits.

Implementation gates:
- volume/ADR indicators
- stop framework: hard stop, time stop, breakeven, RSI recovery
- expectancy and trade distribution metrics

### Track D: Regime/Macro Overlay
Hypothesis: simple stress filters reduce drawdowns across strategies without predicting exact crash timing.

Candidate features:
- SPY below SMA200
- VIXY/high-vol proxy rising
- TLT/rates stress
- equity-bond correlation spike
- composite stress score

## Universal Promotion Gates

No strategy graduates from research to mock candidate queue unless it passes:

1. no same-bar fills
2. minimum history threshold
3. train/OOS or walk-forward separation
4. transaction-cost stress at 5/10/25 bps
5. parameter robustness
6. benchmark comparison
7. turnover/concentration report
8. sample-size warning for weak evidence
9. 30-day mock tracking before trust
10. failure-mode writeup

## Immediate Build Sequence

### Gate V1-A: Evidence Ledger + Trade Diagnosis
First implementable slice. It does not change execution behavior.

Deliverables:
- `market_lab/diagnosis.py`
- `market_lab/evidence.py`
- `scripts/market_lab_review.py`
- tests for regime labels, failure modes, health summaries, append-only JSONL evidence

### Gate V1-B: Metrics/Tearsheet Layer
Extract common metrics from backtests and diagnoses:
- Sortino, Calmar, CVaR, turnover, expectancy, payoff ratio
- block/flag weak sample sizes

### Gate V1-C: Risk Overlay + Exit Framework
Unify exits and overlays:
- stop model
- time stop
- drawdown circuit breaker
- vol spike filter
- regime stress filter

### Gate V1-D: Fast Research Harness
Add array/vectorized backtesting for broad sweeps while retaining event-driven validation as source of truth.

### Gate V1-E: Council Automation
Schedule review scripts:
- daily diagnosis after mock execution
- weekly strategy health report
- experiment proposal generation when decay alerts fire

## Guardrails

- No external/client money.
- No investment-advice product.
- No live orders.
- No options execution until read-only chains, Greeks, reserved cash, multiplier accounting, and explicit approval gates exist.
- Synthetic data is for pipeline tests only, never evidence claims.
- Agent proposals do not automatically alter execution; code changes still go through tests, PR, CI, and review.
