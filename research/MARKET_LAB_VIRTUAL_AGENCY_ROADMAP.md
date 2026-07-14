# Market Lab Virtual Research Agency Roadmap

**Status:** Canonical roadmap, research-only / paper-only posture  
**Date:** 2026-07-14  
**Owner:** OzLabs / Ozzy operator lane; Ronak remains final decision maker  
**Scope:** Analyst-agency architecture and promotion gates. This document is not investment advice and does not claim guaranteed winners.

---

## 0. North star

Market Lab should become a virtual analyst agency, not a trading bot.

The agency's job is to ingest market-relevant information, preserve provenance, extract and verify claims, cut noise, discover and rank high-conviction candidate winners, validate those candidates quantitatively, paper-test portfolios under strict controls, learn from outcomes, and only consider any live execution path after explicit legal, safety, and founder gates.

The intended output is not "guaranteed winners." It is a continuously audited research process that can say:

- what was claimed,
- where the claim came from,
- what evidence supports or refutes it,
- which securities, baskets, or strategies deserve bounded research attention,
- whether historical and out-of-sample tests clear minimum evidence bars,
- whether paper outcomes confirm or falsify the thesis,
- when to stop, pause, or escalate to Ronak.

Core stance: aggressive information processing, conservative execution.

---

## 1. Non-negotiable operating posture

Market Lab is currently a research and mock/paper-trading lab only.

Evidence in the current repository:

- `README.md:3-11` states the system is research-first, with no live broker execution, no autonomous orders, no margin, no shorting/options execution, and reports as research artifacts.
- `market_lab/config.py:48-84` defines frozen risk configs with `live_trading_enabled=False`, `allow_short=False`, `allow_margin=False`, `live_options_enabled=False`, and paper options enabled separately from live options.
- `market_lab/broker.py:160-164` refuses equity orders if live trading is unexpectedly enabled.
- `market_lab/options_paper.py:127-129` refuses paper option orders if paper options are disabled or live options are enabled.
- `market_lab/options_paper.py:160-168` blocks naked calls even when `allow_naked_calls` is set.
- `market_lab/webapp.py:108-114` builds dashboard snapshots only from local artifacts and explicitly avoids network fetches and broker writes.
- `market_lab/webapp.py:552` returns HTTP 405 `read_only_dashboard` for write verbs.
- `scripts/market_lab_daily.py:209-212` refuses candidate execution/queueing when `--require-live-data` sees synthetic/cache fallback.

Implication: no roadmap phase may weaken these gates. Any live path requires a separate legal/safety/founder gate; it is not a default destination.

---

## 2. Current-state inventory with evidence

### 2.1 Information ingestion and provenance

What exists:

- Source capture extraction exists in `market_lab/source_thesis.py`.
- The source thesis model records `SourceClaim`, `SourceMediaAsset`, `SourceThesis`, `BasketMember`, `BasketEvaluation`, and `ThesisRun` (`market_lab/source_thesis.py:74-157`).
- Direct claim extraction preserves source URL, source artifact, author, captured timestamp, and citation (`market_lab/source_thesis.py:247-293`).
- Media manifests preserve local paths, dimensions, interpretation status, and source artifact (`market_lab/source_thesis.py:321-389`).
- Source-derived candidates are only explicit ticker mentions; industry inference is kept for compatibility but not used for candidates (`market_lab/source_thesis.py:538-578`, `market_lab/source_thesis.py:581-588`).
- Source thesis reports show direct quotes with provenance, media provenance, controls, benchmarks, and warnings (`market_lab/source_thesis.py:791-891`).
- `mlab_ingest` provides lifecycle stages from capture through finalized/blocked states (`market_lab/mlab_ingest.py:15-30`), run initialization/resume (`market_lab/mlab_ingest.py:253-306`), append-only audit entries (`market_lab/mlab_ingest.py:166-176`), claim dispositions, evidence entries, independent review, finalization validation, and final brief generation (`market_lab/mlab_ingest.py:473-758`).

Test evidence:

- `tests/market_lab/test_source_thesis.py:37-57` verifies key claims are extracted with provenance.
- `tests/market_lab/test_source_thesis.py:58-71` verifies media provenance and dimensions.
- `tests/market_lab/test_source_thesis.py:72-77` verifies no source-derived candidate inference when no explicit tickers exist.
- `tests/market_lab/test_source_thesis.py:79-85` verifies same-day source evidence is blocked.
- `tests/market_lab/test_source_thesis.py:87-121` verifies claim fidelity / contradiction guard behavior.
- `tests/market_lab/test_mlab_ingest.py:37-76` verifies lifecycle advancement and resume without losing state.
- `tests/market_lab/test_mlab_ingest.py:124-143` verifies append-only audit behavior.
- `tests/market_lab/test_mlab_ingest.py:145-205` verifies finalization is blocked on contradictory evidence.

Current gap:

- This is an ingestion pipeline, not yet a fully staffed agency desk. Claim extraction is heuristic and source-capture based; there is no automated multi-source claim adjudication, retrieval plan execution, citation quality scoring, or agent assignment layer that reliably turns every claim into external verification tasks.

### 2.2 Market data and synthetic-source discipline

What exists:

- `market_lab/data.py:97-133` fetches prices through yfinance, real cache, synthetic cache, then deterministic synthetic generation.
- Synthetic prices are stored separately through `SYNTHETIC_PRICE_DIR` (`market_lab/config.py:8-10`, `market_lab/data.py:36-38`, `market_lab/data.py:56-63`, `market_lab/data.py:126-133`).
- Source labels propagate as `yfinance`, `cache`, `cache_synthetic`, or `synthetic` (`market_lab/data.py:97-133`).
- `scripts/market_lab_daily.py:46-48` treats `synthetic`, `cache`, and `cache_synthetic` as not live for execution/queueing guard purposes.
- The dashboard also labels cached real versus cached synthetic bars (`market_lab/webapp.py:38-45`).

Test evidence:

- `tests/market_lab/test_hardening.py:58-61` covers the synthetic-price cache isolation path.
- `tests/market_lab/test_daily_script_safety.py:8-13` verifies live-data guard behavior.

Current gap:

- Data breadth remains narrow: daily OHLCV, yfinance factors, cached option chains, and local artifacts. There is no production-grade source registry, market calendar/staleness service, corporate-action adjustment audit, earnings/events feed, transcript ingestion, supply-chain/news/social feed, or data-quality dashboard.

### 2.3 Signal generation and candidate ranking

What exists:

- Strategy signals include TSMOM, RSI pullback, legacy baseline scoring, volatility-targeted trend following, and cross-sectional momentum ranks (`market_lab/signals.py:48-263`).
- The ensemble blends family signals (`market_lab/signals.py:225-241`).
- Factor overlay can nudge confidence but is deliberately capped so fundamentals/narrative do not independently flip a SELL into a BUY (`market_lab/signals.py:266-294`).
- Daily orchestration builds ensemble signals, strategy-family signals, cross-sectional ranks, factors, backtests, candidate queueing, option screens, and reports (`scripts/market_lab_daily.py:160-283`).

Test evidence:

- `tests/market_lab/test_research_strategies.py:25-105` covers TSMOM, cross-sectional momentum, multi-strategy outputs, next-open backtest behavior, and order-candidate conversion.
- `tests/market_lab/test_research_strategies.py:107-243` covers vt_trend sizing, drawdown guards, no-lookahead behavior, reentry, and final pending trade behavior.
- `tests/market_lab/test_factors.py:17-30` covers factor score and factor overlay evidence recording.

Current gap:

- Ranking is still mostly rule/indicator based. There is no analyst-style thesis score that fuses verified source claims, alternative data, sector/base-rate context, valuation regime, catalysts, risk flags, and quantitative evidence into one auditable conviction score.

### 2.4 Quantitative validation

What exists:

- Backtests use next-bar-open fills with slippage and commission (`market_lab/backtest.py:28-35`, `market_lab/backtest.py:74-126`, `market_lab/backtest.py:129-180`).
- Backtests support warm-up context excluded from reported metrics (`market_lab/backtest.py:50-71`).
- Optimization supports parameter sweeps and train/OOS walk-forward selection (`market_lab/optimization.py:63-122`).
- Reports include SPY benchmark support through `compute_spy_benchmark` and daily script wiring (`market_lab/data.py:141-181`, `scripts/market_lab_daily.py:272-280`).

Test evidence:

- `tests/market_lab/test_optimization.py:36-68` covers ranked parameter sweeps and walk-forward OOS reporting.
- `tests/market_lab/test_spy_benchmark.py:22-204` covers SPY benchmark computation and report wiring.
- `tests/market_lab/test_dual_momentum.py:20-177` covers dual momentum filtering, weighting, monthly rebalance, common-date alignment, and next-open behavior.

Current gap:

- There is no unified research-tearsheet standard across every candidate/strategy. Required metrics like turnover, exposure, beta, factor attribution, distribution of returns, capacity/liquidity stress, event sensitivity, and multiple-hypothesis/overfit controls are not yet universal gates.

### 2.5 Mock/paper portfolio testing

What exists:

- Equity mock broker supports guarded long-only order decisions, atomic state writes, portfolio lock, append-only ledger, and queued `OrderCandidate` objects for close-to-next-open timing (`market_lab/broker.py:14-44`, `market_lab/broker.py:78-88`, `market_lab/broker.py:117-158`, `market_lab/broker.py:160-223`).
- The daily script executes pending candidates only when a later bar exists (`scripts/market_lab_daily.py:116-135`) and queues new candidates after the execution step (`scripts/market_lab_daily.py:214-239`).
- Options paper support includes option contracts/chains, screeners, paper portfolio, cash/share reservation, DTE/liquidity/delta/per-symbol/assignment gates, and active position views (`market_lab/options_paper.py:52-217`, `market_lab/options_screeners.py` tests below).
- Independent vt_trend and TSMOM tracking scripts exist and are runnable via `scripts/market_lab_independent_tracks.py` without live broker orders (`scripts/market_lab_independent_tracks.py:1-15`, `scripts/market_lab_independent_tracks.py:73-136`).

Test evidence:

- `tests/market_lab/test_broker.py:9-69` covers broker risk gates, custom path safety, persistence, and no-short behavior.
- `tests/market_lab/test_options_support.py:55-586` covers option chain roundtrips, screeners, paper reserve accounting, naked-call rejection, kill switches, stale chain rejection, yfinance normalization, atomic saves, and fsynced ledger appends.
- `tests/market_lab/test_vt_trend_tracking.py:31-176` and `tests/market_lab/test_tsmom_tracking.py:31-176` cover independent track state isolation, queues, fill cycle, diagnosis integration, and synthetic-data refusal.

Current gap:

- Paper testing is still a lab harness, not a full portfolio committee. It lacks a unified portfolio-level risk budget, cross-strategy correlation controls, automatic rebalancing governance, tax/borrow/liquidity assumptions, option assignment lifecycle automation, and sandbox broker reconciliation.

### 2.6 Outcome learning and evidence council

What exists:

- `diagnosis.py` records trade diagnoses, regime labels, failure modes, and strategy health summaries (`market_lab/diagnosis.py:15-201`).
- `evidence.py` appends and loads fsynced JSONL evidence streams (`market_lab/evidence.py:12-59`).
- `scripts/market_lab_review.py:113-152` diagnoses open mock BUY decisions, keeps updated snapshots, propagates synthetic/live-or-cache data quality, and appends evidence.
- `scripts/market_lab_review.py:155-173` writes idempotent strategy health reports.
- Regime labeling now uses pre-entry bars when post-entry bars are too short (`scripts/market_lab_review.py:125-141`, `market_lab/diagnosis.py:128-135`).

Research-doc evidence:

- `research/track-evidence-comparison-20260604.md:9-130` documented early evidence quality issues and recommended safer next experiments.
- `research/independent-track-evidence-20260605.md:95-143` documented the regime-label issue and a research-only fix path.
- `research/ensemble-evidence-assessment-20260605.md:30-148` documented ensemble underperformance, low statistical power for independent tracks, and reporting gaps.

Test evidence:

- `tests/market_lab/test_diagnosis_council.py:28-388` covers regime labels, P&L/failure modes, decay actions, append-only records, review idempotence, open-lot handling, and pre-entry regime labeling.

Current gap:

- Learning is not yet closed-loop. Evidence can recommend `continue`, `tune`, `pause`, or `retire`, but no agency process yet forces strategy changes to cite diagnosis records, compare against baselines, or quarantine noisy signals until enough new evidence exists.

### 2.7 Dashboard/reporting

What exists:

- Daily reports render ensemble signals, backtests, mock decisions, queued candidates, options research, paper positions, SPY benchmark, and independent tracks (`market_lab/report.py` and `scripts/market_lab_daily.py:280-283`).
- Dashboard snapshot is read-only and includes portfolio, signals, strategy health, candidates, backtests, options mode/guardrails, paper positions, reports, and sources (`market_lab/webapp.py:108-220`, continuing through the returned payload).

Test evidence:

- `tests/market_lab/test_webapp.py` covers dashboard behavior.
- `tests/market_lab/test_independent_tracks.py:128-168` verifies report inclusion/exclusion of independent tracks and read-only state behavior.
- `tests/market_lab/test_options_support.py:219-287` covers options reporting/dashboard surfacing.

Current gap:

- There is no single "analyst agency desk" view that starts from source claims and carries them through verification, ranked conviction, quant validation, paper outcome, and kill/promotion status.

---

## 3. Seven-phase target architecture

### Phase 1 — Capture and provenance desk

Purpose: ingest source material without losing context.

Inputs:
- social/media captures,
- articles/blogs/research notes,
- filings/transcripts/earnings when added,
- screenshots/media manifests,
- analyst notes and manual hypotheses.

Core services:
- source registry with immutable IDs,
- raw artifact vault,
- metadata normalizer,
- media manifest interpreter,
- claim extractor,
- provenance renderer.

Promotion gate out of Phase 1:
- every extracted claim has source URL or local artifact, citation, author or source account, capture timestamp, and raw artifact path;
- media claims are blocked unless media is interpreted or explicitly marked unavailable;
- no inferred ticker becomes a candidate without explicit source support or separate analyst rationale.

Current maturity: partially built through SourceThesis and MLAB ingest.

### Phase 2 — Claim verification and noise-cutting desk

Purpose: turn raw claims into adjudicated evidence.

Core services:
- claim type classifier: factual, forecast, causal, valuation, catalyst, operational, market-size, sentiment;
- evidence retrieval plan per claim;
- independent source search and citation capture;
- source-quality scoring;
- contradiction detection;
- claim dispositions: VERIFIED, REFUTED, MIXED, UNRESOLVED;
- blockers and reviewer approval before finalization.

Promotion gate out of Phase 2:
- at least two independent sources for material factual claims unless explicitly marked as single-source/unverifiable;
- VERIFIED claims require supporting evidence and no unaddressed refuting evidence;
- REFUTED claims require refuting evidence;
- MIXED claims require both supporting and refuting evidence;
- UNRESOLVED claims require blockers;
- independent review decision is APPROVE.

Current maturity: lifecycle and finalization guards exist, but automated retrieval/adjudication coverage is missing.

### Phase 3 — Thesis and candidate discovery desk

Purpose: convert verified evidence into candidate research ideas without overclaiming.

Core services:
- thesis assembler: source claims + verified evidence + market context;
- ticker/basket mapper with explicit rationale;
- control and benchmark selector;
- sector/base-rate comparator;
- catalyst calendar;
- qualitative risk register;
- conviction pre-score.

Candidate classes:
- single-name long candidate,
- sector/basket candidate,
- relative-strength candidate,
- hedged or rotation candidate,
- options-income candidate for paper-only evaluation.

Promotion gate out of Phase 3:
- thesis names what would make it wrong;
- at least one explicit security/basket mapping rationale;
- controls and benchmarks are defined;
- known missing data is documented;
- no source-derived promotion if evidence is synthetic/stale/cache-only for the relevant market window;
- no "winner" language without quantified uncertainty and base-rate comparison.

Current maturity: explicit-ticker and control/benchmark scaffolding exists; thesis scoring and candidate discovery are not yet agency-grade.

### Phase 4 — Quant validation desk

Purpose: test whether candidate ideas survive historical, out-of-sample, cost, and robustness checks.

Core services:
- standardized event-driven backtest;
- fast research harness for broad sweeps, with event-driven validation as source of truth;
- walk-forward/OOS optimizer;
- benchmark alignment;
- transaction-cost stress;
- parameter sensitivity;
- sample-size warning;
- turnover/exposure/risk tearsheet;
- failure-case replay.

Promotion gate out of Phase 4:
- no same-bar fills;
- minimum history threshold met;
- OOS or walk-forward results reported separately from train results;
- costs tested at 5/10/25 bps or a strategy-appropriate equivalent;
- benchmark comparison included;
- parameters robust within a defined neighborhood;
- drawdown and exposure reported;
- weak sample size explicitly warns/block-promotes;
- strategy has a kill rule before paper tracking.

Current maturity: event-driven backtests, next-open fills, OOS wrappers, SPY benchmark, and many strategy tests exist; unified tearsheet and overfit controls are missing.

### Phase 5 — Paper portfolio committee

Purpose: paper-test only the candidates that survived validation, with explicit portfolio governance.

Core services:
- paper portfolio ledger per strategy and combined portfolio;
- candidate queue with close-to-next-open discipline;
- risk budget allocator;
- cross-strategy exposure/correlation checks;
- option assignment/reserve lifecycle for options paper;
- sandbox broker reconciliation when/if a sandbox adapter is approved;
- read-only dashboard and reports.

Promotion gate out of Phase 5:
- at least 30 trading days of paper tracking or a strategy-specific minimum observation count;
- no synthetic/cache-only execution when `--require-live-data` is required;
- all paper fills have timestamp, strategy, signal date, execution date, requested/reference price, fill price, and reason;
- portfolio exposure never exceeds configured caps;
- options remain defined-risk/collateralized;
- evidence council can diagnose outcomes.

Current maturity: main mock portfolio, paper options, and independent vt_trend/TSMOM tracks exist; combined committee-level governance is missing.

### Phase 6 — Outcome learning and research governance desk

Purpose: learn from paper outcomes and decide continue/tune/pause/retire.

Core services:
- trade diagnosis stream;
- strategy health report stream;
- failure-mode taxonomy;
- decay alerts;
- experiment proposer;
- evidence ledger keeper;
- promotion/kill decision log;
- postmortem templates.

Promotion gate out of Phase 6:
- strategy has enough paper observations for a meaningful read or is explicitly marked low-power;
- win rate, average P&L, trade Sharpe, benchmark-relative P&L, failure modes, and regime breakdown are reported;
- proposed tuning cites actual failure modes;
- any strategy with persistent negative expectancy, repeated whipsaw, or unexplained underperformance is paused or demoted;
- a human/founder-visible decision record exists.

Current maturity: evidence council exists and is tested; governance automation and forced decision logs are incomplete.

### Phase 7 — Legal/safety/founder-gated execution readiness

Purpose: define the only path by which Market Lab could approach live execution. This is intentionally a gate, not a near-term promise.

Core services required before this phase:
- legal/regulatory review of any investment-advice, RIA, brokerage, and account-control implications;
- explicit Ronak founder approval;
- separate production credentials and secret-management policy;
- broker sandbox validation with reconciliation;
- dry-run/order-ticket mode;
- manual approval queue;
- hard kill switches;
- incident response and rollback plan;
- audit logging of every decision and human approval;
- capital allocation policy and loss limits.

Promotion gate into any live-adjacent work:
- all prior phases are green for the specific strategy, not just the codebase;
- legal/safety review is complete and documented;
- live execution is explicitly approved by Ronak in writing;
- order tickets are human-approved before any broker submission;
- no autonomous live orders;
- no margin, no naked options, no shorting unless a new legal/safety review explicitly expands scope.

Current maturity: not reached. Current repo has research/mock/paper gates only.

---

## 4. Measurable promotion gates by artifact

### Source claim gate

A claim may move from raw source to verified evidence only if:

- source artifact exists;
- claim text is quoted or directly extracted;
- timestamp is parseable or missing timestamp is called out;
- source URL / author / capture artifact are present where available;
- claim disposition is one of VERIFIED / REFUTED / MIXED / UNRESOLVED;
- unresolved claims have blockers;
- contradictory evidence blocks finalization until resolved or reclassified.

### Candidate gate

A security or basket may become a candidate only if:

- mapping rationale is explicit;
- source-derived candidates are not inferred from industry text alone;
- controls and benchmarks are listed;
- post-source market window exists;
- data source quality is not synthetic/cache-only for a claim requiring fresh market confirmation;
- risk thesis and falsification criteria are stated.

### Quant gate

A strategy/candidate may enter paper tracking only if:

- backtest uses next-open or event-correct fills;
- train/OOS or walk-forward separation exists;
- benchmark and transaction cost stress are included;
- max drawdown, Sharpe/return, exposure, and turnover are reported;
- parameter robustness is documented;
- sample-size warning is emitted when evidence is weak;
- known failure modes and kill criteria are written.

### Paper tracking gate

A paper candidate may continue beyond initial tracking only if:

- live data requirement passes when execution/queueing is enabled;
- candidate/fill metadata is complete;
- risk caps are respected;
- diagnoses are produced after sufficient bars;
- strategy health does not recommend pause/retire;
- paper outcomes are benchmark-relative, not just absolute.

### Live-adjacent gate

No strategy may approach live execution unless:

- legal review complete;
- Ronak explicitly approves;
- safety review complete;
- paper evidence clears a defined threshold;
- broker sandbox reconciliation passes;
- manual order-ticket process is tested;
- hard kill switches are proven;
- the decision is documented outside code.

---

## 5. Dependencies

### Technical dependencies

- Reliable market data: yfinance today; possible Tradier sandbox for options chain/paper validation; future earnings/events and filings feeds.
- Storage discipline: immutable raw artifacts, JSONL evidence streams, atomic state writes, cache source labels.
- Test discipline: `python3 -m pytest tests/market_lab -q` remains the current gate.
- Local artifact dashboard/reporting: read-only webapp and markdown reports.
- Optional future scheduling: only after manual runs are stable; no cron-driven trading actions.

### Human/legal dependencies

- Ronak founder decision for promotion/kill choices.
- Legal/regulatory review before investment-advice or live execution paths.
- Human-provided broker sandbox credentials when/if Tradier or another provider is actually implemented.
- Human review of strategy promotions and safety gates.

### Organizational dependencies

- Clear agent roles: ingestion analyst, verification analyst, quant researcher, paper portfolio manager, risk reviewer, evidence council, final Ozzy/Ronak decision lane.
- A single canonical agency status report tying every claim/candidate/strategy to phase, evidence, blocker, and next action.

---

## 6. Missing capabilities

Highest-priority missing capabilities:

1. Automated evidence retrieval and adjudication for claims.
2. Source-quality scoring and citation deduplication.
3. Unified thesis/candidate conviction score that combines verified claims, base rates, catalysts, valuation/factors, technicals, and risks.
4. Standard quant tearsheet for every strategy/candidate.
5. Portfolio-level risk committee: exposure, correlation, concentration, drawdown budget, and strategy allocation.
6. Closed-loop learning that forces tune/pause/retire decisions to cite evidence records.
7. Agency desk dashboard from raw claim to candidate to quant validation to paper outcome.
8. Options assignment/expiration lifecycle automation before scaling options paper.
9. Sandbox broker adapter/reconciliation, if still desired, with independent kill switches and no live URL path.
10. Legal/safety review package template for any live-adjacent consideration.

---

## 7. 30 / 60 / 90-day sequence

### Days 0-30: Canonical agency spine

Goal: make the current system legible as an analyst agency.

Deliverables:

- Create an agency status schema: source run, claim IDs, candidate IDs, strategy IDs, phase, gate status, blockers, next owner.
- Add a canonical "Agency Desk" report that links:
  - SourceThesis / MLAB ingest runs,
  - claim dispositions,
  - candidate mappings,
  - quant validation status,
  - paper tracking status,
  - evidence council health.
- Define a standard quant tearsheet markdown/JSON schema.
- Require every new candidate to include falsification criteria and benchmark.
- Backfill current strategies into the phase model:
  - ensemble: paper tracking, under review/tune unless newer evidence proves otherwise;
  - vt_trend: independent paper track, low-power evidence;
  - TSMOM: independent paper track, low-power evidence;
  - paper options: paper-only, defined-risk, low-power evidence.
- Keep full test suite green.

30-day success metrics:

- 100% of active candidates/strategies appear in the agency status report.
- 100% of source claims in active ingest runs have disposition or blocker.
- Every paper-tracked strategy has a benchmark and kill rule.
- No product code path weakens safety gates.

### Days 31-60: Verification and quant discipline

Goal: improve evidence quality before adding complexity.

Deliverables:

- Implement retrieval-plan templates for factual, catalyst, valuation, and operational claims.
- Add source-quality scoring and claim-evidence citation tables.
- Implement standardized quant tearsheets for existing strategies.
- Add transaction-cost stress, turnover, exposure, and parameter sensitivity into all strategy reports.
- Add paper outcome reports that compare strategy performance against SPY and relevant controls.
- Add evidence-council decision log: continue / tune / pause / retire with cited records.

60-day success metrics:

- Every promoted candidate has at least one quant tearsheet.
- Every paper strategy has regime/failure-mode diagnostics.
- No strategy is tuned without citing a diagnosis/evidence record.
- Any strategy below kill criteria is paused or explicitly granted a time-boxed exception by Ronak.

### Days 61-90: Portfolio committee and sandbox-readiness research

Goal: evolve from isolated tracks to governed paper portfolios.

Deliverables:

- Build portfolio-level risk report: total exposure, per-symbol exposure, per-sector exposure if available, correlation/proxy overlap, drawdown budget, option collateral, cash usage.
- Define paper promotion thresholds per strategy type.
- Add options assignment/expiration event model before scaling options paper.
- If still desired, implement or revisit Tradier sandbox adapter only as a validation supplement, not live execution.
- Draft legal/safety readiness checklist for any future live-adjacent discussion.

90-day success metrics:

- Paper strategies are governed by portfolio-level risk, not just per-order gates.
- Options paper positions have assignment/expiration accounting before scale-up.
- Sandbox adapter, if built, never changes existing paper simulation or live gates.
- A live-adjacent checklist exists, but current phase remains research/paper unless Ronak explicitly changes it.

---

## 8. Kill criteria

### Claim/source kill criteria

Kill or quarantine a source/candidate if:

- material claims cannot be traced to source artifacts;
- verification finds contradictory evidence not resolved in the thesis;
- source timestamp prevents a valid post-source evidence window;
- media evidence is central but uninterpreted/unavailable;
- the source repeatedly produces unverifiable or promotional noise.

### Strategy/candidate kill criteria

Pause, tune, or retire a strategy if any of the following hold:

- OOS return is materially worse than benchmark after costs;
- drawdown exceeds predeclared limit;
- parameter sensitivity shows the result only works in a narrow cherry-picked pocket;
- paper tracking underperforms benchmark over the minimum observation window;
- evidence council emits persistent `pause` or `tune` without successful remediation;
- dominant failure mode repeats without a fix;
- data quality is synthetic/stale/cache-only for execution-critical decisions;
- strategy cannot explain what would falsify it.

### Portfolio kill criteria

Stop new paper candidates if:

- aggregate exposure exceeds risk budget;
- cash/collateral reserve accounting is inconsistent;
- ledger and state diverge materially;
- dashboard/reporting cannot show current risk;
- options assignment/expiration lifecycle is missing for active short options;
- any safety flag unexpectedly flips live-enabled.

### Live-adjacent kill criteria

Abort any live-adjacent effort if:

- legal review is missing or negative;
- Ronak has not explicitly approved;
- an autonomous order path exists;
- secrets are mishandled;
- sandbox reconciliation fails;
- incident response / kill switch has not been tested;
- the team cannot clearly explain liability, suitability, and operational risks.

---

## 9. Honest current phase

Market Lab is currently between Phase 2 and Phase 5, with uneven maturity:

- Phase 1 capture/provenance: partially built and tested.
- Phase 2 claim verification/noise-cutting: lifecycle gates exist, but automated external verification is incomplete.
- Phase 3 thesis/candidate discovery: early scaffolding exists; agency-grade conviction scoring is missing.
- Phase 4 quant validation: solid foundations exist for event-driven backtests, OOS wrappers, and strategy tests; standardized tearsheets and overfit controls are incomplete.
- Phase 5 paper portfolio: equity mock, independent tracks, and paper options exist; portfolio committee governance is incomplete.
- Phase 6 outcome learning: evidence council exists and is tested; closed-loop governance is not yet enforced.
- Phase 7 live readiness: not reached.

The most honest label is:

**Current phase: research/paper lab with early analyst-agency scaffolding.**

It can ingest some source claims, test strategies, paper-track outcomes, and diagnose failures. It is not yet a fully autonomous analyst agency and is not ready for live execution.

---

## 10. Near-term routing recommendation

The next work should not be more trading features by default. The next safest sequence is:

1. Build the Agency Desk report/schema so every source, claim, candidate, strategy, and paper track has a phase and gate status.
2. Standardize quant tearsheets and promotion/kill thresholds.
3. Enforce evidence-council decision logs before strategy tuning.
4. Only then expand data sources, options workflows, or sandbox broker validation.

This keeps the lab aligned with Ronak's north star: discover and validate high-conviction opportunities through a disciplined analyst agency, while preserving the redundant safety gates that make Market Lab a research lab rather than a live trading system.
