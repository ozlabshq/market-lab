# Market Lab Agency Investment Committee Specification

**Status:** Implementation-ready specification; no product code is defined as existing by this document  
**Date:** 2026-07-14  
**Scope:** Research and mock/paper evaluation only  
**Decision owner:** Ronak  
**Posture:** Aggressive research, conservative execution

---

## 0. Purpose and normative language

This specification defines the Market Lab virtual investment committee: independent analyst roles, evidence-bound candidate scoring, confidence calibration, deterministic ranking and rejection, disagreement handling, quant and portfolio-fit gates, anti-groupthink controls, immutable audit artifacts, objective tests, and MVP acceptance.

The committee produces a ranked **research decision packet**. It does not produce an order instruction and cannot change portfolio or broker state.

`MUST`, `MUST NOT`, `SHOULD`, and `MAY` are normative. Proposed files, schemas, tests, and commands are future implementation targets unless explicitly identified as current repository behavior.

## 1. Hard boundaries and decision rights

1. Market Lab remains research/mock/paper only.
2. The committee MUST NOT place or queue orders, update positions, reserve collateral, or mutate any execution-state artifact.
3. The committee MUST NOT weaken current safety, source-quality, next-open execution, risk, option-collateral, or live-trading gates.
4. No candidate may be promoted from narrative, snippets, LLM prose, duplicated syndication, context-only evidence, or synthetic data.
5. A high aggregate score cannot override evidence integrity, quant leakage, unsupported execution, hard portfolio risk, or unresolved material disagreement.
6. A committee result of `MOCK_ELIGIBLE` means only that the candidate may be handed to the existing mock-candidate workflow through a separate explicit action. It is not an order.
7. Ronak retains final decision rights. Policy exceptions and any live-adjacent work require explicit human review outside this committee.
8. The committee MUST add restrictions rather than relax an upstream gate when contracts conflict.

No-side-effect invariants cover at least:

- `mock_ledger.jsonl`;
- `mock_portfolio_state.json`;
- `pending_order_candidates.jsonl`;
- options paper state, candidate, and ledger files;
- VT Trend state, candidate, and ledger files;
- TSMOM state, candidate, and ledger files.

## 2. Grounding in the current repository

The proposed committee is a new control plane over current research artifacts, not a replacement for them.

| Current capability | Repository evidence | Committee implication |
|---|---|---|
| Research/paper safety defaults | `market_lab/config.py:48-84` | Policy snapshots MUST preserve `live_trading_enabled=False`, no shorting/margin, and separate paper/live option flags. |
| Mock-order risk gates | `market_lab/broker.py:160-202` | Portfolio fit MUST model current limits but MUST NOT call order mutation paths. |
| Candidate next-open timing | `market_lab/broker.py:78-88`, `market_lab/broker.py:146-158` | A future handoff may reference next-open semantics; committee ranking itself has no fill semantics. |
| Technical confidence and ranking | `market_lab/signals.py:11-24`, `market_lab/signals.py:225-241`, `market_lab/signals.py:297-299` | Existing signal confidence is an input feature, not calibrated committee confidence or a final rank. |
| Capped factor overlay | `market_lab/signals.py:266-294`; `market_lab/factors.py:177-206` | Factor evidence may nudge a thesis but cannot substitute for claim evidence or flip hard gates. |
| Cross-sectional/dual momentum | `market_lab/signals.py:244-263`; `market_lab/portfolio_construction.py:68-122` | Existing ordinal ranks are quant inputs inside compatible cohorts, not the agency-wide ranking. |
| Leakage-aware backtests | `market_lab/backtest.py`; `market_lab/optimization.py` | Applicable quant packets MUST preserve next-bar execution, train/OOS separation, and benchmark/cost reporting. |
| Source thesis provenance | `market_lab/source_thesis.py:74-157` | Candidate packets SHOULD reference source claims and artifacts by stable ID/hash rather than copy untraceable prose. |
| Ingest claim adjudication | `market_lab/mlab_ingest.py:473-554`, `market_lab/mlab_ingest.py:643-709` | `VERIFIED`, `REFUTED`, `MIXED`, and `UNRESOLVED` dispositions are upstream inputs; unresolved or contradictory claims fail closed. |
| Independent ingest review | `market_lab/mlab_ingest.py:598-632`, `market_lab/mlab_ingest.py:697-709` | Committee final review remains a separate role and MUST NOT be inferred from ingest approval. |
| Append-only evidence | `market_lab/evidence.py:12-59` | Committee audit uses inspectable JSONL plus stronger hash chaining and immutable finalization. |
| Outcome diagnosis | `market_lab/diagnosis.py:15-53`, `market_lab/diagnosis.py:166-201` | Resolved mock outcomes feed calibration and continue/tune/pause/retire learning; they do not retroactively rewrite old runs. |

The roadmap identifies the current state honestly as a research/paper lab with early analyst-agency scaffolding (`research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md:607-623`). The committee fills parts of roadmap Phases 3 through 6; it does not advance the lab to live readiness.

## 3. System boundary and run lifecycle

### 3.1 Inputs

A committee run consumes immutable references to:

- finalized MLAB/source-thesis claim and evidence artifacts;
- candidate manifests;
- strategy/backtest/tearsheet artifacts where applicable;
- market, factor, liquidity, and option-chain snapshots where applicable;
- one read-only portfolio snapshot;
- policy and calibration snapshots;
- sealed analyst reports.

The committee MUST reference input hashes and stable IDs. It MUST NOT silently copy a claim into a new provenance root.

### 3.2 Proposed run root

```text
${MARKET_LAB_DATA_DIR}/investment_committee/<committee_run_id>/
```

Proposed artifacts:

```text
status.json
manifest.json
policy_snapshot.json
calibration_snapshot.json
portfolio_snapshot.json
cohort.json
candidate_inputs/<candidate_id>.json
sealed_reviews/<role_id>/<candidate_id>.json
audit_log.jsonl
source_lineage.json
dimension_scores.jsonl
disagreements.json
portfolio_fit.json
ranking.json
rejections.jsonl
independent_review.json
independent_review.md
next_actions.json
decision_packet.json
decision_packet.md
```

Finalized artifacts are immutable. A correction creates a new run with `supersedes_run_id`; it never rewrites a finalized run.

### 3.3 Lifecycle

```text
CREATED
  -> INPUTS_VALIDATED
  -> REVIEWS_SEALED
  -> EVIDENCE_AUDITED
  -> SCORED
  -> DISAGREEMENTS_CLOSED | BLOCKED_DISAGREEMENT
  -> PORTFOLIO_CHECKED
  -> FINAL_REVIEWED
  -> FINALIZED
```

Terminal non-final states are `BLOCKED`, `REQUEST_CHANGES`, and `ABORTED`. A queued, running, or partially scored run is never reported as complete.

Only `DISAGREEMENTS_CLOSED` may advance to `PORTFOLIO_CHECKED`. `BLOCKED_DISAGREEMENT` remains blocked until new evidence or adjudication produces an append-only revision and a valid transition; the diagram does not imply that the blocked branch can continue.

Every transition MUST be deterministic, append an audit event, name an actor/owner, cite inputs, and reject invalid predecessor states. Retrying the same transition with the same idempotency key MUST produce no duplicate artifact or audit event.

## 4. Candidate and cohort contracts

### 4.1 Candidate manifest

Every candidate MUST conform to `mlab-candidate.v1`:

```text
schema_version
candidate_id
candidate_type: equity | etf | strategy | defined_risk_option | basket
symbol_or_strategy_id
as_of_utc
horizon_days
horizon_bucket
benchmark_ids[]
cohort_id
proposed_portfolio_role
proposed_mock_weight
thesis_summary
falsifiers[]
source_run_ids[]
material_claim_ids[]
counterclaim_ids[]
market_data_artifact_ids[]
factor_artifact_ids[]
backtest_artifact_ids[]
liquidity_artifact_ids[]
option_chain_artifact_ids[]
requested_action: research | watchlist | mock_track
input_artifact_hashes[]
```

A ticker alone is not a candidate. A candidate is a falsifiable hypothesis with an `as_of`, horizon, benchmark, mechanism, and intended portfolio role. The same security may have multiple candidate IDs when horizons or mechanisms differ.

For the equity MVP, `proposed_mock_weight` is a finite decimal in `(0, 0.10]`. Common IDs are lowercase ASCII and match `candidate_id = cand_[a-z0-9][a-z0-9_-]{7,63}` and `committee_run_id = icr_[a-z0-9][a-z0-9_-]{7,63}`; claim, evidence, report, artifact, event, and action IDs use their schema prefix plus the same suffix rule. IDs are immutable within a lineage.

### 4.2 Comparable cohort rule

Ordinal rank is valid only within a cohort whose members share compatible:

- candidate type;
- horizon bucket;
- benchmark or explicitly normalized benchmark family;
- `as_of` cutoff;
- data-vintage and transaction-cost assumptions;
- portfolio snapshot.

A two-week catalyst thesis and a multi-year compounder thesis MUST NOT appear in one ordinal list. Cross-cohort output is a grouped dashboard, not a global winner rank.

### 4.3 Material claim contract

Every material claim MUST include:

```text
claim_id
normalized_proposition
subject / predicate / object
qualifiers / units / scope / geography
valid_from / valid_to / as_of
materiality: low | medium | high | critical
disposition: VERIFIED | REFUTED | MIXED | UNRESOLVED
required_source_class
supporting_evidence_ids[]
refuting_evidence_ids[]
qualifying_evidence_ids[]
unresolved_blocker
adjudicator_id / adjudication_version
```

`UNRESOLVED` is permitted only for `PARK_RESEARCH` or `REJECT`. An unresolved critical claim is never converted to neutral score or escalated as a substitute for research. `HUMAN_REVIEW` is reserved for evidence-backed policy/risk conflicts or exceptions, not missing factual adjudication. `MIXED` claims must preserve both supporting and refuting edges.

### 4.4 Evidence eligibility

Score-eligible evidence MUST resolve to:

- an immutable artifact or deterministic market-data result;
- an exact locator, query, table cell, code revision, or test/backtest result;
- canonical source lineage and origin cluster;
- claim-appropriate source authority;
- publication, effective, observation, vintage, and retrieval times as applicable;
- a declared `supports`, `refutes`, or `qualifies` edge;
- matching entity, unit, scope, and time;
- non-synthetic data for investment conclusions;
- a reproducible transformation/calculation reference.

Search snippets, generated summaries, unsourced analyst prose, and `context` evidence may explain a claim but cannot satisfy it or improve score. Many articles derived from one release count as one origin. Many analysts citing one filing do not create independent evidence.

### 4.5 As-of and freshness policy

Freshness is measured against the run's immutable `as_of_utc`, never the wall clock at replay. A policy-pinned exchange calendar defines trading-day age; if the calendar or required observation time is unavailable, the input is stale and the candidate parks. Future-dated artifacts relative to `as_of_utc` are integrity failures.

Initial maximum ages:

| Artifact/input | Freshness requirement |
|---|---|
| Equity/ETF close, volume, spread, and liquidity | Latest completed trading session and no more than `1` trading day old |
| Intraday portfolio price used for fit | Observed no more than `60` minutes before `portfolio_snapshot.as_of_utc`; otherwise use latest completed close and label `eod` |
| Portfolio snapshot | No more than `60` minutes old and no intervening mock ledger/candidate/collateral event |
| Factor snapshot | No more than `14` calendar days old, matching current factor-cache discipline |
| Option chain/Greeks | No more than `OptionsRiskConfig.max_chain_age_days` (`2` calendar days currently), with quote time present |
| Catalyst/news assertion | No more than `7` calendar days old unless the claim's validity interval explicitly remains open |
| Filing/fundamental value | Latest effective filing available at `as_of`; age `<=120` calendar days for quarterly data or `<=400` for annual-only data; amendments supersede originals according to effective time |
| Backtest/tearsheet | Generated within `30` calendar days, code/data/policy hashes reproduce, and its final observation is at or before candidate `as_of` |
| Calibration snapshot | Generated within `30` calendar days and trained only on outcomes resolved before `as_of` |
| Durable reference evidence | May be older only when `valid_to` is absent or after `as_of`, no superseding source exists, and the analyst explains continuing applicability |

Candidate-type policy MAY tighten these limits but cannot relax them inside a run. Refreshable staleness of market, research, portfolio, or calibration inputs produces `PARK_RESEARCH` with a refresh action. `R07` is reserved for permanent/current non-investability after a completed refresh attempt (for example delisted, invalid instrument, no supported market), not ordinary age-based staleness. Synthetic fallback never satisfies freshness.

## 5. Independent analyst roles

No analyst is chair. Deterministic code owns validation, hard gates, calibration, aggregation, outcome assignment, and ranking.

| Role | Primary question | Mandatory output | Blocking authority |
|---|---|---|---|
| Business and Fundamental Analyst | Is the economic mechanism real, durable, and measurable? | mechanism map, economics/quality, industry structure, claim assessments, falsifiers | Only through evidence-linked hard rejection or unresolved critical mechanism claim |
| Market and Quant Analyst | Is there benchmark-relative empirical support without leakage? | OOS/relative metrics, robustness, regimes, sample limits, data-quality findings | Leakage, synthetic validation, invalid benchmark, or failed required quant gate |
| Valuation and Payoff Analyst | What is priced in and what are bull/base/bear payoffs? | valuation frame, scenario probabilities, expected payoff, downside | Undefined loss, incoherent payoff, or stale/missing critical valuation input |
| Catalyst and Timing Analyst | Why now and what should occur within the horizon? | catalyst/dependency calendar, decay rules, monitoring triggers | May force a research park for unresolved critical timing; no unsupported veto |
| Skeptic and Disconfirmation Analyst | What makes the thesis wrong, late, crowded, reflexive, fraudulent, or uninvestable? | strongest counter-thesis, disconfirming evidence, failure modes, kill rules | Dissent alone is not veto; eligible hard-failure evidence is |
| Evidence and Provenance Auditor | Are claims supported by appropriate, current, independent evidence? | eligibility table, origin lineage, freshness, locator, contradiction, hash checks | Yes: evidence integrity is a hard gate |
| Portfolio and Risk Analyst | Does the candidate improve the current portfolio under constraints? | marginal contribution, overlap, stress loss, capacity, replacement test | Yes for hard risk; otherwise may emit `PORTFOLIO_HOLD` without rejecting standalone thesis |

### 5.1 Sealed-stage independence

For the initial pass:

1. Each role receives only the candidate packet, role rubric, policy snapshot, and allowed evidence scope.
2. Roles MUST NOT see peer reviews, peer scores, aggregate score, candidate rank, suggested verdict, or analyst identity ordering.
3. One agent process MUST NOT fill two roles in one run.
4. Reports use separate sessions and signed artifacts.
5. Same-model or same-provider roles are permitted only when capacity requires it; the shared lineage MUST be disclosed and correlation-down-weighted.
6. The skeptic receives at least the same retrieval/tool budget as the strongest advocate lane.
7. Every role records model/provider/version, rubric and prompt hashes, input digest, tool-call manifest, source IDs, and start/submission times.
8. Hidden chain-of-thought is neither requested nor stored. The audit retains concise evidence-linked rationale assertions.

### 5.2 Revision rules

Original sealed reports are immutable. A revision appends a new version and declares exactly one reason:

- `NEW_EVIDENCE`, with evidence IDs;
- `CORRECTED_ERROR`, with the exact error;
- `RUBRIC_REINTERPRETATION`, with policy section;
- `PEER_PERSUASION_ONLY`.

`PEER_PERSUASION_ONLY` remains visible but cannot increase effective confidence. Silent convergence is prohibited.

### 5.3 Analyst review schema

`mlab-analyst-review.v1` requires:

```text
committee_run_id / candidate_id / role_id
analyst_instance_id / report_version / supersedes_report_id
model_provider / model_id / model_version
rubric_version / prompt_hash / input_digest
started_at_utc / submitted_at_utc
independence_group
source_origin_cluster_ids[]
claim_assessments[]
dimension_ratings[]
raw_probability_outperform
raw_confidence
bull_case / base_case / bear_case
strongest_disconfirming_case
falsifiers[] / missing_information[]
hard_gate_findings[]
recommended_outcome
rationale_assertions[]
revision_reason / revision_evidence_ids[]
content_hash_sha256
signature_scheme: ed25519
signer_key_id
signature
```

Every material rationale assertion links `claim_ids[]` and `evidence_ids[]`. Unlinked material prose is excluded from scoring and final narrative.

Compute `content_hash_sha256` from RFC 8785 canonical JSON with both `content_hash_sha256` and `signature` omitted; store it as 64 lowercase hexadecimal characters. The detached Ed25519 signature covers the domain-separated bytes `MLAB_ANALYST_REVIEW_V1\x00` plus that 32-byte binary digest. Public keys and signatures use unpadded base64url; `signer_key_id` resolves to a public key pinned in the policy snapshot. Invalid encoding, unknown-key, duplicate, or failed signatures invalidate the report; private keys are never stored in committee artifacts. Frozen MVP fixtures use dedicated non-production test keys disclosed in the fixture manifest.

Probability, confidence, and evidence quality are separate:

- **Probability:** forecast that the candidate beats its named benchmark net of modeled costs over the named horizon.
- **Confidence:** expected stability of that assessment under plausible new information.
- **Evidence quality:** source fit, coverage, freshness, and integrity.

## 6. Scoring policy

### 6.1 Dimensions

Ratings are `0.0` to `5.0` in `0.5` increments. `2.5` is neutral. For risk dimensions, a higher rating means better downside control.

| Dimension | Weight | High-score meaning |
|---|---:|---|
| Claim and evidence quality | 15% | Current, source-appropriate, independently corroborated material claims with no unresolved critical contradiction |
| Economic mechanism and fundamental quality | 10% | Clear, measurable, durable mechanism linking driver to security/strategy outcome |
| Valuation and expected payoff | 15% | Explicit expectations and scenario-weighted upside that compensates for downside and costs |
| Empirical and benchmark edge | 15% | Leakage-safe OOS/claim-appropriate support, benchmark comparison, robustness, and honest sample limits |
| Catalyst, path, and horizon fit | 10% | Credible observable path inside the stated horizon with decay rules |
| Downside, robustness, and falsifiability | 15% | Bounded bear cases, stress survival, objective falsifiers and kill rules |
| Implementability, liquidity, and costs | 5% | Supported instrument, current liquid market, and robust costs/turnover |
| Portfolio fit and marginal contribution | 10% | Differentiated driver within risk budget that improves or replaces a weaker holding/candidate |
| Monitorability and learning value | 5% | Measurable leading indicators, review dates, and useful mock experiment |

Weights MUST total `1.0` exactly in the policy snapshot. They are policy defaults, not proven predictive truth.

### 6.2 Mandatory role coverage

Each dimension requires at least two eligible role opinions. Evidence quality requires the Evidence Auditor plus one domain role. Portfolio fit requires the Portfolio/Risk Analyst plus the Quant or another applicable domain role.

A missing required opinion creates missingness; it does not become a neutral rating. Missing mandatory role coverage blocks `MOCK_ELIGIBLE`.

### 6.3 Evidence factor

For each analyst/dimension:

```text
q = coverage * source_fit * temporal_fit * integrity
```

Each component is in `[0, 1]` and is stored separately:

- `coverage`: materiality-weighted share of required claims with eligible evidence;
- `source_fit`: claim-relative source authority after origin dedupe;
- `temporal_fit`: evidence validity for candidate `as_of` and horizon;
- `integrity`: `1` only when hashes, locators, transforms, units, and source labels pass; otherwise `0`.

A zero-integrity finding also invokes the applicable hard gate; score shrinkage does not sanitize it.

The policy snapshot contains a claim-type/materiality evidence-slot matrix. Initial defaults are: critical/high factual or causal claims require two independent origins including one claim-required canonical/primary class; medium claims require one claim-required origin; low claims require one eligible origin; valuation, forecast, and catalyst claims require the named input artifact plus one independent challenge origin when rated high/critical. One origin fills at most one independence slot.

For analyst `i` and dimension `d`:

- `coverage_i,d` is the materiality-weighted fraction of required slots filled across the dimension's cited claims.
- Each filled slot receives source score `1.00` for the claim-required canonical/primary class, `0.75` for an authoritative independent secondary explicitly allowed by claim policy, `0.50` for a corroborated lower-tier secondary allowed only for low/medium materiality, and `0` for context, mismatch, or ineligible evidence. `source_fit_i,d` is the materiality-weighted mean across required slots, with unfilled slots scored `0`.
- `temporal_fit_i,d` is `1` only when every conclusion-critical cited artifact meets Section 4.5 and claim validity covers `as_of`; otherwise it is `0` and the applicable stale-input outcome runs.
- `integrity_i,d` is binary. One failed hash, locator, unit, transform, entity, or source-label check makes it `0` and invokes `R02` when material.

A dimension rating citing no material claim is invalid except implementability, portfolio fit, and monitorability, which may cite only their required market/portfolio/monitoring artifacts. All component calculations and slot assignments are emitted in `dimension_scores.jsonl`.

Candidate-level material evidence coverage is reproducible rather than analyst-assigned. Claim materiality weights are `critical=4`, `high=3`, `medium=2`, and `low=1`. For each material claim, `claim_coverage` is the fraction of policy-required evidence slots that resolve to eligible, independent origin clusters; a refuting/qualifying slot counts when the claim contract requires it, and an unresolved critical claim has coverage `0`. Then:

```text
material_evidence_coverage =
    sum(claim_materiality_weight * claim_coverage) /
    sum(claim_materiality_weight)
```

A candidate with no material claims is schema-invalid. Repeated citations from one origin cannot fill multiple independence slots.

### 6.4 Forecast and confidence calibration

Calibration registry keys SHOULD be as granular as sample size permits:

```text
candidate_type / role_id / model_id / rubric_version / horizon_bucket
sample_count
cohort_base_rate
brier_score / brier_skill / probability_ece / log_loss
confidence_stability_ece / score_revision_error
calibration_method
transform_spec
training_window / holdout_window
valid_from / valid_to
artifact_hash
```

Resolved mock outcomes are eligible only after the forecast horizon closes. Training and evaluation windows MUST be walk-forward; the same outcome cannot fit and evaluate a calibrator.

Probability and confidence calibration use different targets:

- `probability_ece` compares issued outperform probabilities with benchmark-relative binary outcomes after the full horizon.
- `confidence_stability_ece` compares issued `raw_confidence` with a binary stability target. A review is stable only when, before horizon close, no allowed revision changes outcome, changes probability by `>= 0.10`, or changes any material dimension by `>= 1.0`; revisions caused only by post-horizon outcomes are excluded.
- `score_revision_error` is the mean absolute pre/post allowed-revision dimension change divided by `5.0`, clipped to `[0,1]`.

Both ECE metrics use fixed deciles `[0,.1), ... [.9,1]` and `ECE = sum_j((n_j/N) * abs(mean_forecast_j - mean_binary_target_j))`; empty bins contribute zero. The registry MUST preserve the observations and bucket boundaries used to reproduce each metric. Probability ECE MUST NOT be reused as confidence stability error.

Calibration behavior:

- `sample_count >= 50`: use the probability-calibration method pinned by the prior policy version; default is beta calibration. A run never chooses a method after seeing its evaluation cohort. `transform_spec` serializes the complete fitted transform: beta stores finite decimal `a/b/c`, clipping epsilon `1e-6`, and applies `sigmoid(a*ln(p)+b*ln(1-p)+c)` after clipping `p`; isotonic stores ordered finite `x_breakpoints[]/y_values[]` and uses right-continuous step lookup with endpoint clipping. Isotonic may replace beta only in a new policy version approved from a separate, already resolved evaluation cohort. Missing/invalid parameters force cold-start behavior and a blocker; they are never refit during replay.
- `20 <= sample_count < 50`: deterministic beta-binomial reliability-bucket shrinkage is used. Raw forecasts are assigned to fixed policy bins `[0,.2), [.2,.4), [.4,.6), [.6,.8), [.8,1]`; bins with fewer than five observations merge with the nearest adjacent bin, lower bin first on equal distance. For a merged bin with `s` successes in `n` resolved forecasts and cohort base rate `b`, use prior strength `m=10`, `alpha0=m*b`, `beta0=m*(1-b)`, and `p_model=(s+alpha0)/(n+alpha0+beta0)`.
- `sample_count < 20`: cold start.
- Incompatible horizons or candidate types MUST NOT be pooled merely to increase sample size.

Confidence multiplier:

```text
if sample_count < 20:
    k = 0.50
else:
    confidence_calibration_error = max(confidence_stability_ece, score_revision_error)
    k = clamp(0.25, 1.00, 1 - confidence_calibration_error / 0.25)

effective_confidence = raw_confidence * k
```

Probability calibration:

```text
p_model = calibrated(raw_probability_outperform)  # when a valid held-out calibrator exists
p_model = beta_binomial_bucket_mean                # for 20-49 compatible resolved forecasts
p_model = raw_probability_outperform               # for cold start, retained for audit

if sample_count < 20:
    k_probability = 0.50
else:
    k_probability = clamp(0.25, 1.00, 1 - probability_ece / 0.25)

p_effective = cohort_base_rate + k_probability * (p_model - cohort_base_rate)
```

When no compatible resolved cohort exists, policy defines a neutral base rate of `0.50` and records `calibration_status=cold_start`; it MUST NOT pretend the value is empirically calibrated.

### 6.5 Score shrinkage

For raw dimension rating `r`, effective confidence `c`, and evidence factor `q`:

```text
adjusted_rating = 2.5 + (r - 2.5) * c * q
```

Lower confidence or weaker evidence always moves bullish and bearish ratings toward neutral. A hard rejection remains a hard rejection.

### 6.6 Independence weighting

Reports are clustered by model/provider lineage, rubric/prompt lineage, evidence-origin concentration, and shared generated-summary/tool lineage.

```text
independence_weight = 1 / correlated_cluster_size
```

A correlated cluster contributes at most one full unit of weight. Reports remain visible; they are not described as independent votes.

### 6.7 Dimension aggregation

For each dimension:

1. Exclude schema-invalid and evidence-ineligible ratings.
2. Apply neutral shrinkage.
3. Weight by `effective_confidence * q * independence_weight`.
4. Use deterministic weighted median as the aggregate dimension rating.
5. Preserve the full distribution, role names, effective weights, and dissent.
6. Resolve an exact weighted-median tie by the lower adjusted rating, making ambiguity conservative.
7. If no eligible opinion remains, set the replay-only aggregate to neutral `2.5`, mark the full dimension weight as missing, and block `MOCK_ELIGIBLE`; the neutral placeholder is never described as an opinion.

### 6.8 Candidate score and uncertainty

```text
raw_committee_score = 20 * sum(dimension_weight * aggregate_dimension_rating)

dimension_dispersion_d = clamp(0, 1,
    weighted_median(abs(adjusted_rating_i,d - aggregate_dimension_rating_d)) / 2.5
)
dispersion = sum(dimension_weight_d * dimension_dispersion_d)
missingness = total policy weight of dimensions lacking mandatory coverage
opinion_weight_i,d = dimension_weight_d * independence_weight_i
calibration_gap = 1 - (
    sum(opinion_weight_i,d * effective_confidence_i * q_i,d) /
    sum(opinion_weight_i,d)
)

uncertainty = clamp(0, 1,
    0.50 * dispersion +
    0.30 * missingness +
    0.20 * calibration_gap
)

lower_bound_score = max(0, raw_committee_score - 20 * uncertainty)
```

The dispersion weighted median uses the same `effective_confidence * q * independence_weight` opinion weights as dimension aggregation. Missing dimensions contribute neutral only to `raw_committee_score`; `missingness`, outcome gates, and the packet expose them explicitly.

If the calibration-gap denominator is zero, set `calibration_gap=1`, park the candidate, and prohibit scoring finalization except for a recorded rejection caused by an earlier hard gate.

For each role forecast, define `q_forecast` as the minimum `q_i,d` across the policy-required dimensions that the role used in its probability rationale; an empty dimension set invalidates the forecast. Candidate benchmark-outperformance probability is the weighted median of `p_effective` across eligible domain roles using `effective_confidence * q_forecast * independence_weight`. An exact tie resolves toward `0.50`. The packet MUST preserve each role probability, required dimension set, `q_forecast`, and calibration status rather than exposing only the aggregate.

## 7. Rejection and outcome policy

### 7.1 Hard rejection codes

Hard rejection precedes scoring:

| Code | Meaning |
|---|---|
| `R01_UNLAWFUL_OR_NONPUBLIC_INPUT` | Depends on material nonpublic, stolen, private, paywall-bypassed, or impermissible information |
| `R02_DATA_INTEGRITY_FAILURE` | Hash, locator, provenance, timestamp, transform, unit, or source-label integrity fails |
| `R03_LOOKAHEAD_OR_LEAKAGE` | Uses future information, same-bar execution, contaminated labels, or invalid as-of alignment |
| `R04_SYNTHETIC_AS_EVIDENCE` | Synthetic data supports edge, valuation, promotion, or portfolio fit |
| `R05_UNSUPPORTED_EXECUTION` | Requires live trading, margin, shorting, naked options, or unsupported instrument behavior |
| `R06_UNBOUNDED_OR_POLICY_VIOLATING_LOSS` | Undefined/violated max loss, collateral, assignment, concentration, or other hard risk constraint |
| `R07_NON_INVESTABLE_OR_STALE_MARKET` | After a completed refresh attempt, instrument is unavailable, invalid, delisted, or has no supported policy-compliant market; temporary age-based staleness parks instead |
| `R08_FAILED_REQUIRED_STRATEGY_GATE` | Required OOS, cost, robustness, benchmark, sample, or lookahead test was performed and failed |
| `R09_REFUTED_CORE_MECHANISM` | Eligible evidence refutes a critical thesis dependency |
| `R10_NO_BENCHMARK_EDGE_AFTER_FULL_TEST` | Adequately powered, cost-aware full test finds no required benchmark-relative edge |
| `R11_DUPLICATE_OR_MANIPULATED_CANDIDATE` | Identity, evidence, or scores were duplicated/altered to gain rank |

Missing evidence normally yields `PARK_RESEARCH`, not a bearish score and not `R10`. The engine MUST distinguish `not tested`, `tested inconclusively`, and `tested and failed`.

Non-hard dispositions are `D01_FULLY_RESEARCHED_BELOW_WATCHLIST` when complete evidence has no hard failure, the candidate misses watchlist score/probability thresholds, and no concrete value-of-information action remains; and `D02_UNRESOLVABLE_RESEARCH_GAP` when required evidence or statistical power cannot be obtained inside the declared horizon and no hard rejection code applies. Neither code may be reported as a hard safety or integrity failure.

### 7.2 Outcomes

Each candidate receives exactly one outcome:

- `REJECT`: hard failure, or a fully researched thesis below decision thresholds with no remaining value-of-information action.
- `PARK_RESEARCH`: missing, stale, contradictory, low-coverage, or incomplete required evidence.
- `WATCHLIST`: plausible and monitorable, but score, confidence, timing, quant, or portfolio readiness does not justify mock eligibility.
- `MOCK_ELIGIBLE`: all evidence, score, disagreement, quant, and portfolio gates pass.
- `PORTFOLIO_HOLD`: standalone mock gates pass but current capacity, overlap, risk, collateral, or replacement economics fail.
- `HUMAN_REVIEW`: an evidence-backed disagreement or policy/risk exception cannot be resolved deterministically; missing factual adjudication parks instead.

### 7.3 Default thresholds

Defaults are hypotheses to validate on frozen and mock-history cases, not claims of predictive edge.

| Outcome | Required conditions |
|---|---|
| `REJECT` by score | No missing material evidence, no unresolved disagreement, and `lower_bound_score < 45` |
| `PARK_RESEARCH` | Unresolved critical claim, required role missing, material evidence coverage `< 0.75`, or uncertainty `> 0.45` |
| `WATCHLIST` | No hard reject, `lower_bound_score >= 55`, aggregate effective probability `>= 0.52`, and objective monitoring trigger |
| `MOCK_ELIGIBLE` | No hard reject; raw score `>= 70`; lower bound `>= 65`; aggregate effective probability `>= 0.55`; evidence coverage `>= 0.85`; uncertainty `<= 0.30`; all applicable quant gates pass; disagreement closes; portfolio result is `FIT` or `FIT_WITH_CAP` |
| `PORTFOLIO_HOLD` | Standalone `MOCK_ELIGIBLE` gates pass but portfolio result is `HOLD_CAPACITY` or `FAIL_PORTFOLIO` |
| `HUMAN_REVIEW` | Critical policy/risk exception or evidence-backed rank-sensitive dissent remains after tie-break; missing factual adjudication parks instead |

Precedence is:

```text
hard reject
> unresolved legal/integrity/safety block
> mandatory missing evidence/coverage
> unresolved disagreement/human exception
> quant gate
> standalone score thresholds
> portfolio-fit gate
> rank
```

The outcome function MUST be total; no score, probability, quant, timing, or portfolio state may fall through. Apply this decision ladder in order:

1. Any hard rejection code emits `REJECT`.
2. An unresolved critical claim, missing mandatory role, evidence coverage below `0.75`, uncertainty above `0.45`, untested applicable quant gate, or statistically inconclusive quant result emits `PARK_RESEARCH` with a concrete evidence/power action. If an adequately powered quant test fails, emit the applicable `R08`/`R10` rejection instead.
3. An unresolved evidence-backed disagreement or policy/risk exception after tie-break emits `HUMAN_REVIEW`; a missing factual adjudication remains `PARK_RESEARCH`.
4. A complete candidate with `lower_bound_score < 45` emits `REJECT` by score.
5. A complete candidate with lower-bound score in `[45,55)`, or score `>=55` but effective probability `<0.52`, emits `PARK_RESEARCH` only when a named feasible action can resolve the gap inside the horizon; otherwise emit `REJECT` with non-hard `D01_FULLY_RESEARCHED_BELOW_WATCHLIST`.
6. A candidate with lower-bound score `>=55` and probability `>=0.52` but no objective monitoring trigger emits `PARK_RESEARCH` with a trigger-definition action; if the thesis is inherently unmonitorable, emit `REJECT` with `D01`.
7. A candidate clearing watchlist gates but missing one or more stricter mock score, probability, coverage, uncertainty, timing, or complete applicable quant conditions emits `WATCHLIST` only when all evidence required for watchlist is complete and an objective trigger exists; otherwise it parks under an earlier rule.
8. A standalone candidate clearing every `MOCK_ELIGIBLE` gate receives the portfolio result: `FIT`/`FIT_WITH_CAP` -> `MOCK_ELIGIBLE`; `HOLD_CAPACITY`/`FAIL_PORTFOLIO` -> `PORTFOLIO_HOLD`.
9. `BLOCKED_STALE_SNAPSHOT` emits `PARK_RESEARCH` with a snapshot-refresh action and cannot silently become `PORTFOLIO_HOLD`.

Every `PARK_RESEARCH` result MUST carry a feasible owner, action, and due event inside the horizon. If a park condition has no feasible resolution path, emit `REJECT` with `D02_UNRESOLVABLE_RESEARCH_GAP`.

### 7.4 Ranking

Only comparable candidates are ranked. Within a cohort:

1. outcome class: `MOCK_ELIGIBLE`, `WATCHLIST`, `PARK_RESEARCH`;
2. lower-bound score descending;
3. aggregate effective benchmark-outperformance probability descending;
4. material evidence coverage descending;
5. lower marginal portfolio risk contribution when return expectations are otherwise tied;
6. stable `candidate_id` ascending.

For rank only, score, probability, coverage, and risk values are quantized to six decimal places with decimal round-half-even; “otherwise tied” means exact equality of outcome class and the quantized keys 2 through 4. Define the ascending scalar:

```text
marginal_risk_contribution = max(
    max(0, abs(beta_after) - abs(beta_before)) / 0.10,
    max(0, volatility_after - volatility_before) / 0.02,
    max_stress(max(0, loss_after_s - loss_before_s)) / 0.02,
    max(0, issuer_weight_after - issuer_weight_before) / 0.10,
    max(0, sector_weight_after - sector_weight_before) / 0.30,
    max(0, theme_weight_after - theme_weight_before) / 0.40,
    max(0, origin_weight_after - origin_weight_before) / 0.25
)
```

All weights/losses are fractions of portfolio equity. Missing an applicable component blocks portfolio fit and rank publication; it does not default to zero. Exact risk-key ties proceed to `candidate_id`.

`REJECT`, `PORTFOLIO_HOLD`, and `HUMAN_REVIEW` appear in named separate lists and are never silently dropped.

Run leave-one-analyst-out and leave-one-evidence-origin-out replay. If outcome changes or rank moves by more than two places, set `rank_sensitive=true` and open disagreement review.

## 8. Disagreement protocol

Disagreement is preserved as information; no simple majority vote is allowed.

### 8.1 Automatic triggers

Open a case when any of these holds:

- rating range `>= 2.0` on a material dimension;
- raw/effective probability spread `>= 0.20`;
- normalized dispersion `> 0.30`;
- any hard-gate finding;
- skeptic conflicts with every advocate lane;
- Evidence Auditor rejects a source used by another analyst;
- one analyst/evidence-origin removal changes outcome or rank by more than two;
- critical claim is `MIXED` or has incompatible entity, unit, scope, time, or definition;
- post-reveal scores converge without new evidence.

### 8.2 Resolution

1. Freeze sealed reports and first-pass scores.
2. Produce an issue map of disputed claim IDs, evidence edges, assumptions, dimensions, and affected gates.
3. Recheck source lineage and remove false independence.
4. Run targeted retrieval for the highest-value disputed fact, explicitly searching for disconfirmation, correction, amendment, and alternate definitions.
5. Assign a blind tie-break reviewer who was absent from maker and analyst roles.
6. The tie-break reviewer sees the dispute/evidence before rank, aggregate, or analyst identities.
7. Re-adjudicate factual claims or retain `MIXED`/`UNRESOLVED`.
8. Recompute scores deterministically and record every before/after value and reason.
9. Escalate risk preference/policy exceptions to Ronak as `HUMAN_REVIEW`.
10. Material unresolved disagreement blocks `MOCK_ELIGIBLE`.

A tie-break reviewer may adjudicate evidence and policy compliance. The reviewer may not erase or rewrite a role report.

### 8.3 Dissent record

Every final candidate card includes strongest bull case, strongest bear case, minority opinion, disputed claim/evidence IDs, outcome effect, rank sensitivity, resolving observation, and later mock validation status when available.

## 9. Quant gates

Quant checks are evidence gates, not score decorations.

### 9.1 Universal quant/data gate

Every candidate MUST have:

- one declared `as_of` and horizon;
- benchmark and comparison methodology;
- fresh, non-synthetic market/liquidity inputs for conclusions;
- transaction-cost and implementation assumptions;
- explicit empirical claim type (`backtest`, `event_study`, `cross_sectional`, `scenario_only`, or `not_applicable` with rationale);
- leakage/as-of review;
- sample-size and power limitations;
- falsifier and monitoring rule.

A single-name fundamental thesis need not invent a strategy backtest, but empirical claims it does make MUST use an appropriate, reproducible method. Missing applicable quant evidence parks the candidate; failed adequate evidence may reject it.

### 9.2 Strategy gate

Before strategy candidates become `MOCK_ELIGIBLE`, they MUST provide:

- next-bar/event-correct execution semantics;
- minimum history threshold;
- train/OOS or walk-forward separation;
- 5/10/25 bps cost stress or documented strategy-appropriate equivalent;
- benchmark-relative result;
- parameter-neighborhood robustness;
- turnover, exposure, concentration, drawdown, and sample-size report;
- lookahead-bias review independent from the strategy author;
- predeclared kill rule.

Failed required gates map to `R08`; no benchmark edge after an adequately powered full test maps to `R10`. Untested gates map to `PARK_RESEARCH`.

### 9.3 Defined-risk option gate

Option candidates additionally require fresh, trusted chain/Greeks status; DTE, spread, open interest, volume, multiplier, assignment, maximum loss, and collateral assumptions; and current `OptionsRiskConfig` compliance. Naked calls, margin, live execution, degenerate Greeks, stale chains, or undefined collateral fail closed.

## 10. Portfolio-fit gate

Standalone quality and portfolio suitability are separate.

### 10.1 Snapshot contract

One read-only, hash-addressed snapshot records:

- cash and existing mock positions;
- current target and actual weights;
- sector/industry/geography/asset/theme/factor exposure;
- beta, volatility, normal/stress/downside correlation, and drawdown co-movement;
- strategy, benchmark, and thesis-origin overlap;
- liquidity, spread, turnover, capacity, and days-to-exit assumptions;
- pending mock candidates and reserved option collateral;
- current risk configuration and policy version;
- market-input source and freshness.

The committee MUST NOT mutate this snapshot or any underlying state.

### 10.2 Fit tests

1. Current `RiskConfig` and candidate-type constraints.
2. Issuer, sector, factor, theme, benchmark, and thesis-origin overlap.
3. Normal, stress-period, and downside correlation.
4. Marginal volatility, beta, concentration, drawdown, and scenario-loss contribution at proposed weight.
5. Liquidity, spread, slippage, turnover, capacity, and stale-market checks.
6. Equity selloff, rates shock, volatility spike, liquidity widening, thesis failure, and relevant data-outage stress.
7. Replacement comparison against the weakest current/pending candidate serving the same portfolio role.
8. Sensitivity at proposed weight and a smaller deterministic cap.
9. Common-cause/crowding dependency detection.
10. Monitoring burden and achievable freshness.

### 10.3 Deterministic MVP portfolio policy

Every threshold is versioned in `policy_snapshot.json`; changing one creates a new policy version and score replay. The initial frozen-equity MVP uses these conservative defaults:

| Check | Default pass condition |
|---|---|
| Current hard risk | Long-only; no margin; no live path; projected issuer weight `<= RiskConfig.max_position_pct` (`10%` currently); future handoff order slice `<= max_single_order_pct` (`5%`) and `<= max_trade_notional` (`$5,000`) |
| Gross/cash | Projected long gross exposure `<=100%`; cash and reserved collateral remain non-negative |
| Sector / named theme | Projected sector weight `<=30%`; policy-defined theme or common-cause exposure `<=40%` |
| Thesis-origin concentration | Positions dependent on one material thesis-origin cluster `<=25%` of mock equity |
| Marginal beta / volatility | Candidate raises absolute portfolio beta by `<=0.10` and forecast annualized volatility by `<=2.0` percentage points |
| Stress loss | Candidate raises loss in any required stress by `<=2.0%` of portfolio equity and projected portfolio loss remains `<=15%` |
| Downside correlation | Downside correlation to every existing position serving a different portfolio role `<0.80`; same-role replacements are evaluated by replacement rules instead |
| Equity/ETF liquidity | Quoted spread `<=0.50%`; liquidation `<=5` trading days at `10%` of observed ADV; no stale/non-investable flag |
| Monitoring capacity | Every required trigger has an owner and source that can meet its freshness SLA; no more than policy `max_active_monitoring_triggers` (default `25`) |

Required frozen stress vectors are broad equity `-20%`, candidate-specific bear case, liquidity spread/slippage `3x`, volatility `+50%` relative, and a policy-supplied rates `+200 bps` factor shock where duration exposure exists. The portfolio snapshot MUST carry each position/candidate shocked return or a reproducible factor mapping; the committee MUST NOT invent a missing sensitivity. Missing applicable stress input parks the candidate.

Replacement is deterministic. If no incumbent or pending candidate serves the same `proposed_portfolio_role`, the replacement test is `NOT_APPLICABLE` and passes. Otherwise compare with the lowest-lower-bound incumbent or pending candidate in that role, breaking ties by stable candidate/position ID. Replacement passes when either (a) candidate lower-bound score is at least `5` points higher with no worse maximum stress loss, or (b) maximum stress loss improves by at least `1.0%` of portfolio equity while lower-bound score is no more than `3` points lower. Costs and liquidation assumptions must be included for both sides.

Weight-cap algorithm:

1. Start at `min(proposed_mock_weight, RiskConfig.max_position_pct)`.
2. Evaluate the exact start weight, then deterministic weights downward in `1` percentage-point increments. Include an exact `1%` test when the start is at least `1%`; if start is below `1%`, test only the exact start. Duplicate decimal weights are removed without binary-float rounding.
3. The largest weight passing every hard, concentration, marginal-risk, stress, liquidity, replacement, and monitoring rule is the cap.
4. Pass at proposed weight -> `FIT`; pass only below proposed weight -> `FIT_WITH_CAP`.
5. No passing weight solely because current cash/collateral/temporary capacity is exhausted -> `HOLD_CAPACITY` if the same snapshot replay with the temporary capacity constraint removed passes.
6. No passing weight because of concentration, common cause, stress, liquidity, replacement, or structural risk -> `FAIL_PORTFOLIO`.
7. Missing/stale snapshot input -> `BLOCKED_STALE_SNAPSHOT` before any fit label.

These defaults are governance hypotheses, not validated optimal allocations. The MVP tests their determinism and safety; later mock evidence may justify a new version.

### 10.4 Results

- `FIT`: passes at proposed mock weight.
- `FIT_WITH_CAP`: passes only at a lower deterministic cap.
- `HOLD_CAPACITY`: no weight passes solely because current cash/collateral/temporary capacity is unavailable, and the capacity-removed replay passes.
- `FAIL_PORTFOLIO`: no tested weight passes because at least one non-capacity concentration, common-cause, marginal-risk, stress, liquidity, replacement, or monitoring rule fails.
- `BLOCKED_STALE_SNAPSHOT`: inputs are too stale to decide.

A weak standalone thesis cannot be promoted merely because it has low correlation. `FIT` and `FIT_WITH_CAP` satisfy a research gate only and queue no order.

## 11. Anti-groupthink controls

Mandatory controls:

1. Sealed first-pass reviews.
2. Required disconfirmation/correction/alternate-definition search.
3. Skeptic budget at least equal to strongest advocate.
4. Source-origin lineage dedupe.
5. Same-model/prompt/evidence cluster down-weighting.
6. No majority-rule promotion.
7. Preserved named minority report.
8. Blind tie-break review.
9. Immutable pre/post score history and revision reasons.
10. Leave-one-analyst and leave-one-origin sensitivity.
11. Rotating skeptic rubric variants and analyst ordering.
12. Model/provider diversity for high-impact candidates when practical, with disclosure otherwise.
13. Independent final reviewer absent from maker, analyst, and policy-author roles for the run.
14. Falsifier-first monitoring.
15. Outcome feedback that scores minority warnings as well as consensus forecasts.

Run-level metrics include model-lineage concentration, evidence-origin concentration, pre/post reveal dispersion, unsupported convergence rate, minority survival rate, lone-dissenter catch rate on seeded cases, leave-one-out rank-flip rate, explicit-falsifier coverage, and calibration by role/confidence bucket.

Target unsupported convergence is zero. Lower dispersion is not inherently better.

## 12. Audit and output schemas

### 12.1 Hash-chained audit event

Every `audit_log.jsonl` event conforms to `mlab-committee-audit-event.v1`:

```text
schema_version
event_id
committee_run_id
sequence_number
idempotency_key
event_type
occurred_at_utc
actor_type: deterministic_engine | analyst | reviewer | human
actor_id
stage_before / stage_after
candidate_ids[]
input_artifact_ids[] / input_hashes[]
output_artifact_ids[] / output_hashes[]
policy_hash / calibration_hash / portfolio_hash
reason_codes[]
details_redacted
previous_event_hash
event_hash
```

`event_hash` is SHA-256 over UTF-8 RFC 8785/JCS canonical JSON containing every event field except `event_hash`; implementations MUST reject non-finite numbers and duplicate JSON keys. Timestamps use UTC RFC 3339 second precision (`YYYY-MM-DDTHH:MM:SSZ`), IDs are NFC-normalized ASCII policy tokens, and numbers use JCS finite-number serialization with no `-0`. Sequence numbers are contiguous and `previous_event_hash` forms a replayable chain. The first event uses the policy-defined 64-character all-zero SHA-256 genesis hash. Raw secrets, private credentials, and hidden chain-of-thought MUST NOT enter the log.

All hashed JSON artifacts use the same canonical rules. Human Markdown is generated from canonical JSON using UTF-8, LF line endings, no trailing whitespace, deterministic list ordering, and exactly one final newline. Replay compares canonical JSON bytes and rendered Markdown bytes; operational timestamps are read from the frozen manifest rather than regenerated.

Required event types include run creation, input validation, review assignment/submission/unseal, evidence eligibility decision, calibration application, score calculation, hard finding, disagreement open/research/adjudication/close, portfolio-fit result, final review, request changes, next-action assignment, finalization, abort, and supersession.

### 12.2 Status contract

`status.json` conforms to `mlab-committee-status.v1`:

```text
schema_version
committee_run_id
stage
verdict: IN_PROGRESS | BLOCKED | REQUEST_CHANGES | ABORTED | FINALIZED
completed_gates[]
blocked_gates[]
blockers[]: blocker_id / gate / candidate_ids[] / reason_code / owner / resolution_action
current_owner
next_action / next_action_id
candidate_counts_by_outcome
artifact_manifest[]: artifact_id / relative_path / exists / sha256 / schema_version
policy_hash / calibration_hash / portfolio_hash
audit_head_hash / audit_event_count
updated_at_utc
```

`stage` and `verdict` are separate: a run may be at `SCORED` with verdict `BLOCKED`. The status file is an atomically replaced projection of the audit log, not an independent source of truth. Replay MUST regenerate it exactly from audit events and frozen manifest timestamps. Finalization fails if an existence flag/hash disagrees with disk, counts disagree with decision objects, or a blocker lacks owner and resolution action.

### 12.3 Decision packet

`mlab-investment-committee.v1` top level:

```text
committee_run_id / supersedes_run_id
created_at_utc / finalized_at_utc / as_of_utc
cohort
policy_version / policy_hash
calibration_snapshot_id / calibration_hash
portfolio_snapshot_id / portfolio_hash
input_artifact_hashes[]
run_status
safety_mode: research_mock_only
ranked_candidates[]
portfolio_holds[]
rejected_candidates[]
human_review_candidates[]
run_level_disagreements[]
review_verdict
reviewer_id / review_artifact_hash
next_actions[]
audit_head_hash
```

Every candidate object contains identity/type/horizon/benchmark, outcome/rank/prior rank, raw/lower-bound score, uncertainty components, effective probability and calibration status, evidence coverage, all dimension inputs/results, review/claim/evidence/origin IDs, bull/bear/minority cases, disagreements, hard findings and rejection codes, portfolio result/weight cap, falsifiers, monitoring triggers, review event/date, and owned next action.

Every score MUST replay from reports, policy, calibration, evidence, and portfolio artifacts.

### 12.4 Human packet

`decision_packet.md` MUST show:

1. safety banner and `as_of`;
2. cohort definition and comparison limits;
3. ranked table with raw/lower-bound score, uncertainty, probability/calibration status, coverage, and portfolio result;
4. separate rejected, parked, held, and human-review lists with reason codes;
5. concise evidence-backed card per candidate;
6. dissent and rank sensitivity;
7. missing/stale evidence;
8. portfolio concentration/stress summary;
9. falsifiers and monitoring dates/events;
10. owned next actions;
11. independent-review verdict and artifact hashes.

Material factual sentences cite stable claim/evidence IDs. Portfolio assertions cite snapshot/calculation artifacts. Analyst judgment cites a report ID and remains labeled as judgment.

### 12.5 Finalization gate

Finalization requires:

- all candidate inputs hash-valid and cohort-compatible;
- all material claims have outcomes-compatible dispositions;
- all mandatory sealed reviews exist;
- every scoring assertion is eligible and linked;
- every disagreement has resolution, park, or escalation;
- score/rank replay matches stored outputs;
- portfolio checks use the declared snapshot;
- independent review is `APPROVE`;
- every next action has owner, due trigger, and completion-evidence shape;
- execution-state pre/post hashes and mtimes prove no side effects.

## 13. Test specification

### 13.1 Future test modules

```text
tests/market_lab/test_committee_contract.py
tests/market_lab/test_committee_evidence.py
tests/market_lab/test_committee_scoring.py
tests/market_lab/test_committee_calibration.py
tests/market_lab/test_committee_disagreement.py
tests/market_lab/test_committee_quant_gate.py
tests/market_lab/test_committee_portfolio_fit.py
tests/market_lab/test_committee_store.py
tests/market_lab/test_committee_cli.py
tests/market_lab/test_committee_safety.py
```

### 13.2 Contract and unit cases

Tests MUST cover:

- unknown schema versions, malformed/prefix-invalid IDs, invalid proposed weights, missing horizon/benchmark/as-of/hash;
- cross-cohort ranking rejection;
- material assertion links to eligible claim/evidence IDs;
- rejection of snippets, summaries, context-only evidence, broken locators, stale vintages, and synthetic sources;
- exact per-artifact freshness boundaries, refreshable-stale park versus post-refresh `R07`, exchange-calendar failure, future timestamps, amendment precedence, and no-intervening-event portfolio freshness;
- one origin counted once across many citations/reviews;
- materiality-weighted candidate/dimension coverage, required evidence slots, source-fit tier values, binary temporal/integrity factors, origin slot dedupe, and zero-material-claim rejection;
- exact dimension weights and rating increments/ranges;
- monotonic shrinkage toward neutral as confidence or `q` falls;
- hard-rejection precedence over any score;
- total outcome assignment across every threshold boundary, including `D01`, `D02`, inconclusive quant, missing trigger, low probability, and stale-snapshot mapping;
- missing roles create missingness, never neutral opinions;
- weighted median, conservative ties, zero-opinion neutral replay placeholder, normalized dispersion, calibration-gap zero denominator, `q_forecast`, uncertainty, lower bound, six-decimal rank quantization, marginal-risk scalar, and deterministic rank;
- cold-start multipliers, fixed beta-binomial bucket/merge/posterior behavior, serialized beta/isotonic transforms, pinned method selection, invalid-transform fallback, and probability shrinkage to base rate;
- separation of probability ECE from confidence-stability ECE and score-revision error;
- incompatible calibration cohort rejection and walk-forward separation;
- every disagreement trigger and resolution state;
- preservation of pre/post reveal scores and unsupported-convergence flag;
- strategy quant gate distinctions among untested, inconclusive, and failed;
- every default portfolio threshold/stress, deterministic 1-point cap grid, `FIT_WITH_CAP`, `HOLD_CAPACITY`, stale snapshot, concentration, common-cause, and both replacement branches;
- option freshness/Greeks/collateral requirements;
- analyst content hashes, hex/base64url encoding, Ed25519 signatures, unknown keys, and tampered signed reports;
- RFC 8785 canonical audit hashes, duplicate-key/non-finite-number rejection, immutable finalization, superseding correction, replayable chains, and idempotent retries;
- exact status projection/replay, artifact existence/hash mismatches, blocker ownership, and outcome counts;
- sealed-input-envelope allowlist/denylist behavior without claiming process isolation;
- finalization failure without independent approval or owned next actions.

### 13.3 Property/metamorphic tests

1. Reducing confidence or `q` cannot move adjusted rating farther from `2.5`.
2. Duplicating a report in one independence cluster cannot increase cluster weight.
3. Duplicating one evidence origin cannot improve independence/coverage.
4. Adding eligible refuting evidence cannot improve a dimension absent explicit adjudication.
5. Hard reject always beats high score.
6. Input order cannot change results or stable tie breaks.
7. Final packets contain no NaN, infinity, unknown reason, or missing required dimension.
8. `PARK_RESEARCH` cannot become `MOCK_ELIGIBLE` without new evidence, corrected input/policy, or explicit adjudication.
9. Declared leave-one-out sensitivity exactly matches replay.
10. Committee code cannot mutate execution state.

### 13.4 Frozen adversarial cases

| Fixture | Expected result |
|---|---|
| Shared press-release consensus | One origin; no false corroboration |
| Same model in five roles | Shared lineage disclosed and cluster weight capped |
| Lone skeptic finds a restatement | Evidence hard trigger overrides bullish majority |
| Loud but unsupported skeptic | Dissent preserved without unsupported veto |
| Post-reveal herding | Unsupported convergence flagged; no confidence gain |
| Unit mismatch | Mismatch classified; no invented contradiction |
| Stale filing vs amended filing | Correct vintage selected for `as_of` |
| Great standalone, duplicate exposure | `PORTFOLIO_HOLD` or `FIT_WITH_CAP` |
| Weak standalone, apparent diversification | No promotion from low correlation alone |
| Synthetic backtest winner | `R04_SYNTHETIC_AS_EVIDENCE` |
| Lookahead winner | `R03_LOOKAHEAD_OR_LEAKAGE` |
| Missing evidence | `PARK_RESEARCH`, not bearish score |
| Fully tested no edge | `R10_NO_BENCHMARK_EDGE_AFTER_FULL_TEST` |
| One analyst controls rank | Leave-one-out disagreement trigger |
| Conflicting horizons | Cohort/input failure, not averaged forecasts |

### 13.5 Integration, recovery, and safety tests

Frozen end-to-end tests cover finalized ingest -> candidate -> sealed reports -> evidence audit -> score -> disagreement -> portfolio fit -> final packet. Additional cases cover interrupted resume, corrupt report, missing/stale snapshot, bad hash, partial JSONL append, unavailable analyst/model, unavailable calibration registry, `REQUEST_CHANGES`, deterministic replay, and isolated full-suite execution.

Before and after every safety test, hash and stat all broker/order/options/TSMOM/VT Trend state. Any content or mtime change fails the run.

## 14. MVP implementation slice and acceptance

### 14.1 MVP scope

The MVP is deliberately narrow:

1. One compatible cohort of three frozen equity candidates sourced from finalized MLAB artifacts.
2. Prewritten sealed reports for all seven roles; no automated agent spawning.
3. Candidate, claim/evidence-link, role-report, policy, calibration, and portfolio schemas.
4. Deterministic hard gates, neutral shrinkage, independence weighting, weighted medians, uncertainty, outcomes, and rank.
5. Disagreement triggers plus one frozen blind tie-break artifact.
6. Read-only portfolio-fit checks with `FIT`, `FIT_WITH_CAP`, and hold/block outcomes.
7. JSON/Markdown decision packet, status, next actions, and hash-chained audit.
8. Replay, idempotency, immutable finalization, and no-side-effect proof.
9. A sealed-input-envelope contract: deterministic fixture builder emits one role-specific manifest containing only candidate, policy, rubric, and allowed evidence hashes; loader rejects any envelope containing peer report, aggregate, rank, suggested verdict, or unlisted path.

Prewritten reports prove schema, signature, sealed-envelope validation, and scoring behavior. They do **not** prove that a model process was isolated while generating the fixture. Process-level sandbox/tool isolation is a mandatory release gate before automated analyst runs.

Out of MVP: live data scheduling, autonomous analysts, process-level analyst orchestration, automatic order/candidate queue writes, learned dimension weights, live/sandbox broker integration, client advice, options execution, global cross-horizon ranking, and claims that thresholds predict alpha.

### 14.2 Objective MVP acceptance

MVP is accepted only when all are true:

- all three frozen candidates validate or fail with expected reason codes;
- 100% required schemas and evidence links validate;
- 100% hard-rejection precedence cases pass;
- 100% seeded leakage and synthetic-evidence cases are detected;
- 100% sealed-input-envelope allowlist/denylist fixtures pass, with no claim of process-level generation isolation;
- 100% seeded critical dissent and shared-origin consensus cases trigger correctly;
- unsupported consensus revisions yield zero confidence increases;
- score, uncertainty, outcome, and rank replay are byte-stable from immutable inputs;
- duplicate same-input run is idempotent;
- correction creates a superseding run;
- frozen portfolio fit/capacity/staleness cases pass;
- independent final review is `APPROVE`;
- all next actions have owner, trigger/due date, and completion evidence shape;
- all execution-state hashes and mtimes remain unchanged;
- full existing Market Lab suite passes in an isolated data root.

Predictive promotion thresholds remain provisional until sufficient resolved mock observations support walk-forward calibration. The MVP validates control correctness, not investment edge.

### 14.3 Future acceptance commands

These are targets for future implementation; the committee test files do not exist at specification time.

```bash
cd /Users/ozlabs/market-lab

MARKET_LAB_DATA_DIR=/tmp/mlab_committee_test_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_committee_test_pycache \
uv run pytest \
  tests/market_lab/test_committee_contract.py \
  tests/market_lab/test_committee_evidence.py \
  tests/market_lab/test_committee_scoring.py \
  tests/market_lab/test_committee_calibration.py \
  tests/market_lab/test_committee_disagreement.py \
  tests/market_lab/test_committee_quant_gate.py \
  tests/market_lab/test_committee_portfolio_fit.py \
  tests/market_lab/test_committee_store.py \
  tests/market_lab/test_committee_cli.py \
  tests/market_lab/test_committee_safety.py -q

MARKET_LAB_DATA_DIR=/tmp/mlab_committee_full_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_committee_full_pycache \
uv run pytest tests/market_lab -q
```

## 15. Delivery dependencies and sequencing

The downstream integrated agency plan should preserve this sequence:

1. Freeze schemas, reason codes, policy snapshot, audit canonicalization, and frozen fixtures.
2. Implement pure validation/scoring/replay without agent spawning.
3. Add immutable store and finalization.
4. Add read-only portfolio snapshot and fit checks.
5. Add CLI/reporting and full no-side-effect acceptance.
6. Only after frozen acceptance, automate sealed analyst orchestration.
7. Only after sufficient resolved mock outcomes, evaluate calibration methods and policy thresholds.

The committee depends on stronger upstream claim/evidence lineage and downstream agency reporting, but it MUST remain replayable from frozen artifacts if external retrieval or models are unavailable.

## 16. Open empirical questions

Measure rather than assume:

- weighted median versus correlation-aware trimmed mean;
- incremental value of model diversity after evidence-origin dedupe;
- lower-bound score versus calibrated probability as primary rank key;
- sample size required for role/candidate/horizon calibration;
- replacement tests versus threshold-only portfolio admission;
- which disagreement triggers catch real errors rather than add ceremony;
- conditions under which lone dissent predicts future failure;
- candidate-type-specific role sets;
- value of information from `PARK_RESEARCH` next actions;
- calibration and false-promotion rates of the proposed 70/65/0.55 thresholds.

Until resolved mock-history evidence answers these questions, preserve component metrics and do not call one aggregate score a proven edge.

## 17. Completion definition

A committee run is complete only when inputs and snapshots are versioned/hash-valid; every mandatory role has a sealed first pass; material assertions are evidence-linked or explicitly judgment; hard gates and blockers have run; scores/ranks replay deterministically; disagreements are resolved, parked, or escalated; portfolio fit is read-only and complete; independent review approves; next actions are owned and testable; audit finalization is immutable; and execution state is unchanged.

The committee exists to make evidence, uncertainty, dissent, calibration, and portfolio tradeoffs explicit. It must never manufacture consensus or convert confidence directly into trades.
