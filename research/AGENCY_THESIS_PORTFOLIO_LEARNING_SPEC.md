# Market Lab Agency Thesis Portfolio and Learning — Implementation Spec

**Status:** implementation-ready specification; no product code in this change  
**Date:** 2026-07-14 UTC  
**Scope:** link approved research memos to paper-only portfolio decisions, monitoring, exits, attribution, scorecards, postmortems, and learning loops  
**Source basis:** canonical roadmap, current repository code/tests, and `research/market-lab-v1-master-plan.md`; the delegated R&D report was unavailable and is not represented as a source  
**Safety posture:** research/mock/paper only. This layer must never create live orders, enable live trading, weaken risk gates, bypass next-open execution discipline, or treat paper decisions as investment advice.

---

## 1. Decision

Build a deterministic thesis-portfolio and learning layer that sits after approved company-intelligence and valuation/memo artifacts and before any paper candidate queue.

The first slice must convert an independently approved research memo into a bounded paper-position proposal only when it can prove:

1. the memo is immutable, evidence-addressed, independently reviewed, and not stale;
2. the security identity, benchmark, controls, valuation range, catalysts, invalidations, and principal risks are explicit;
3. quantitative validation exists separately from the memo and satisfies event-correct/no-lookahead gates;
4. sizing is computed by a deterministic policy with portfolio-level caps, not by a model or analyst prose;
5. monitoring and exit rules are predeclared before a paper fill;
6. attribution can later separate thesis, valuation, quant, timing, sizing, market, benchmark, and execution effects;
7. analyst/process scorecards measure decision quality and discipline, not only P&L;
8. postmortems and feedback events can force tune/pause/retire decisions; and
9. all output remains paper-only and leaves live/broker safety flags untouched.

Hard rule:

> An approved memo is not a trade. A memo can become a paper-position candidate only after a separate portfolio-committee gate validates portfolio fit, sizing, monitoring, exit rules, and safety. The candidate is still mock/paper-only and must fill at a later bar's open through existing paper discipline.

The system should make the agency legible: every paper position must answer which memo caused it, what the thesis was, what would invalidate it, why the size was chosen, how it will be monitored, how it exited, who/what process approved it, what happened, and how future research changed because of the outcome.

---

## 2. Current-system boundary

### 2.1 Existing contracts to preserve

This spec extends current Market Lab behavior; it does not replace the safety spine.

Repository evidence reviewed for this spec:

- The canonical roadmap defines Market Lab as a virtual analyst agency, not a trading bot, and labels the current state as a research/paper lab with early analyst-agency scaffolding (`research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md:10-26`, `607-623`).
- The roadmap's Phase 5 and Phase 6 require paper portfolio governance, evidence council diagnosis, decision logs, and postmortems before any live-adjacent phase (`research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md:306-350`).
- The master plan defines the agent council roles: Trade Reviewer, Strategy Diagnostician, Experiment Proposer, Evidence Ledger Keeper, and Risk Arbiter/Ozzy (`research/market-lab-v1-master-plan.md:42-82`).
- Source ingestion preserves direct claim provenance and intentionally avoids industry-inferred candidates (`market_lab/source_thesis.py:74-157`, `247-293`, `538-588`).
- Current mock broker state is long-only, guarded, append-only/atomic enough for the MVP, and refuses if the live flag is unexpectedly enabled (`market_lab/broker.py:45-223`).
- Existing order candidates already model close-to-next-open timing with `signal_date`, `reference_close`, and `intended_execution="next_open"` (`market_lab/broker.py:78-88`; `scripts/market_lab_daily.py:116-135`).
- Existing signal and backtest code uses close-of-day decisions and next-bar-open fills (`market_lab/signals.py:93-125`, `market_lab/backtest.py:74-126`, `183-307`).
- Existing portfolio construction has auditable target weights and next-open rebalance snapshots for dual momentum (`market_lab/portfolio_construction.py:11-40`, `68-123`, `155-223`).
- Existing SPY-relative exit governor is paper/research-only, generates next-open SELL candidates, and skips safely when data or ledger evidence is missing (`market_lab/exit_governor.py:11-207`).
- Evidence council records trade diagnoses, strategy health, failure modes, and append-only JSONL streams (`market_lab/diagnosis.py:15-201`; `market_lab/evidence.py:12-59`).
- Daily script candidate execution/queueing can be blocked by `--require-live-data` when data source is synthetic/cache/cache_synthetic (`scripts/market_lab_daily.py:209-238`).
- Risk config defaults preserve no live trading, no shorting, no margin, bounded max trade and max position sizes (`market_lab/config.py:48-84`).

### 2.2 Upstream specs consumed by this layer

The thesis-portfolio layer consumes, but does not reimplement:

- web/source evidence: immutable snapshots, exact locators, claim/evidence links, and temporal eligibility;
- company intelligence packets: issuer/security identity, exposure, business quality, moat/competition, catalyst inventory, and company packet status;
- valuation/investment memo artifacts: approved research memo, scenario valuation ranges, catalysts, invalidations, principal risks, no-false-precision gates, and safety attestation;
- quant validation/tearsheets: backtests, OOS/walk-forward results, cost stress, benchmark comparison, exposure/turnover, and kill rules.

Until those upstream artifacts exist in accepted form, this layer may run only on frozen fixtures or current strategy artifacts. It must persist `INPUT_BLOCKED`; a committee `PARK_RESEARCH` action persists `WATCH_ONLY`. Neither may fabricate links.

### 2.3 Gaps this layer closes

The current repository does not yet provide:

- a memo-to-paper-position linkage contract;
- a portfolio committee artifact that consumes approved memos separately from signals;
- deterministic thesis-derived paper sizing;
- predeclared catalyst/invalidation monitoring attached to paper positions;
- position-level exit plans tied to a memo, not only strategy signals;
- attribution that separates thesis quality from market beta, timing, valuation, sizing, and execution;
- analyst and process scorecards;
- position postmortems with learning feedback into future research gates;
- a forced decision log that prevents tuning/promoting strategies without diagnosis evidence;
- a single agency desk status from memo to paper outcome.

---

## 3. Non-goals

Version 1 must not:

- create, send, approve, or route live broker orders;
- set `RiskConfig.live_trading_enabled`, `OptionsRiskConfig.live_options_enabled`, shorting, margin, or naked options flags;
- provide investment advice, user-facing recommendations, or client/account-specific suitability decisions;
- convert a memo into a paper position without quant validation and committee gates;
- let an LLM choose position size, stop, target, probability, or override;
- use synthetic/cache-synthetic price data as execution-critical evidence;
- use stale/cache-only data when `require_live_data_for_queue=true`;
- infer orders from prose such as “buy,” “winner,” “undervalued,” or “high conviction”;
- trade options from valuation memos in MVP;
- short, use margin, or lever a position beyond existing long-only caps;
- rewrite historical memos, fills, diagnoses, scorecards, or postmortems;
- tune a strategy or promotion threshold without citing evidence/postmortem IDs;
- build a general portfolio optimizer, factor model, tax engine, execution engine, or live broker adapter;
- hide bad outcomes by excluding them from scorecards or attribution.

---

## 4. System shape

```text
approved company intelligence + approved valuation memo + quant tearsheet
                                  |
                                  v
                         [G0 input eligibility]
                                  |
                                  v
                         [committee request]
                                  |
                                  v
        [thesis-paper-position proposal + benchmark/control context]
                                  |
                                  v
     [portfolio fit] [sizing] [catalyst/invalidation monitor] [exit plan]
                                  |
                                  v
                    [committee gate + independent review]
                                  |
                                  v
       PAPER_READY | PAPER_BLOCKED | REJECTED | WATCH_ONLY
                    (reject action is REJECT_THESIS_POSITION)
                                  |
                                  v
        optional existing paper candidate queue, next-open only, no live path
                                  |
                                  v
        monitoring snapshots -> attribution -> postmortem -> feedback log
```

Models or analyst agents may draft qualitative rationale, risk hypotheses, catalyst interpretations, and postmortem prose. Deterministic code owns schema validation, evidence references, stale checks, size calculations, cap enforcement, trigger evaluation, ledger/state mutation checks, attribution arithmetic, scorecard scoring, status transitions, and safety gates.

---

## 5. Proposed future code and test layout

No product code is included in this task. A future implementation should use flat modules consistent with the current package shape:

```text
market_lab/thesis_portfolio_contracts.py      # dataclasses/enums/canonical serialization
market_lab/thesis_portfolio_policy.py         # sizing, gates, monitoring, exit policy
market_lab/thesis_portfolio_store.py          # immutable artifacts, locks, audit, replay
market_lab/thesis_portfolio_committee.py      # committee gate evaluation, no broker writes
market_lab/thesis_position_queue.py           # optional paper candidate handoff to existing broker queue
market_lab/thesis_monitoring.py               # catalyst/invalidation monitoring snapshots
market_lab/thesis_attribution.py              # benchmark, timing, sizing, execution, thesis attribution
market_lab/thesis_scorecards.py               # analyst/process scorecards
market_lab/thesis_postmortem.py               # postmortems and feedback events
market_lab/thesis_portfolio_cli.py            # build/validate/queue-monitor/postmortem/replay
scripts/market_lab_thesis_portfolio.py

tests/market_lab/test_thesis_portfolio_contracts.py
tests/market_lab/test_thesis_portfolio_gates.py
tests/market_lab/test_thesis_position_sizing.py
tests/market_lab/test_thesis_monitoring.py
tests/market_lab/test_thesis_exits.py
tests/market_lab/test_thesis_attribution.py
tests/market_lab/test_thesis_scorecards.py
tests/market_lab/test_thesis_postmortem.py
tests/market_lab/test_thesis_feedback.py
tests/market_lab/test_thesis_portfolio_safety.py
tests/market_lab/test_thesis_portfolio_replay.py
tests/market_lab/fixtures/thesis_portfolio/
```

Keep the first implementation standard-library-first: frozen dataclasses, `Enum`, `Decimal` for canonical arithmetic where economic values are persisted, `datetime`, `hashlib`, `json`, `pathlib`, and existing Market Lab modules. Do not add pandas/NumPy/SciPy/Pydantic/vendor SDKs in the MVP.

---

## 6. Run-local artifact contract

A thesis-portfolio run should live under the existing MLAB run when it is derived from a source/company/memo run. If the input is a current strategy-only artifact, use a standalone thesis portfolio run root linked to the strategy ID.

```text
<mlab-run>/
  thesis_portfolio/
    request.json
    input_refs.json
    policy_snapshot.json
    committee_packet.json
    committee_packet.md
    sizing_decision.json
    monitoring_plan.json
    exit_plan.json
    gate_report.json
    queue_intent.json                 # written/fsynced before the protected queue mutation
    paper_candidate_link.json        # finalized result of a queue attempt, including skip/cancel
    lifecycle_events.jsonl
    monitoring_snapshots.jsonl
    attribution_snapshots.jsonl
    scorecards.jsonl
    postmortems.jsonl
    feedback_events.jsonl
    learning_overrides.jsonl
    learning_override_uses.jsonl
    manifest.json
```

Rules:

- JSON artifacts are canonical: sorted keys, stable IDs, finite decimal strings for persisted economic quantities, explicit schema versions.
- Markdown is a pure rendering of JSON; semantic content must agree.
- Finalized artifacts are immutable. Corrections create a new version with `supersedes_*` links.
- Writes use same-filesystem temp file, flush, `fsync`, atomic replace, then audit append.
- JSONL appends hold a run lock, write a complete line, flush, and `fsync`.
- The manifest is committed last and records input hashes, output hashes, policy hash, code revision, and protected-state hashes.
- Replay verifies every hash, locator, status transition, and safety attestation.

---

## 7. Stable identity model

IDs must be content-derived from typed canonical JSON, never raw string concatenation or rendered
Markdown. For every ID below, build the named payload, serialize it as UTF-8 with sorted object
keys, no insignificant whitespace, `ensure_ascii=false`, finite values only, and decimal strings
for persisted economic quantities, then hash domain-separated bytes:

```text
canonical_id(domain, payload) = sha256(
  UTF8("mlab-id\u0000" + domain + "\u0000")
  || canonical_json_bytes(payload)
)
```

Every payload is an object containing `id_schema_version` and the following named fields:

```text
committee_request_id:
  domain = mlab-committee-request-id.v1
  payload = {id_schema_version, memo_id, candidate_id, analysis_cutoff_utc,
             policy_hash, request_actor_id}
thesis_position_id:
  domain = mlab-thesis-position-id.v1
  payload = {id_schema_version, committee_request_id, security_id, thesis_digest,
             benchmark_security_ids, control_security_ids}
sizing_decision_id:
  domain = mlab-sizing-decision-id.v1
  payload = {id_schema_version, thesis_position_id, portfolio_snapshot_hash,
             sizing_policy_hash}
monitoring_plan_id:
  domain = mlab-monitoring-plan-id.v1
  payload = {id_schema_version, thesis_position_id, catalyst_ids, invalidation_ids,
             review_schedule}
exit_plan_id:
  domain = mlab-exit-plan-id.v1
  payload = {id_schema_version, thesis_position_id, ordered_exit_rules, policy_hash}
paper_candidate_link_id:
  domain = mlab-paper-candidate-link-id.v1
  payload = {id_schema_version, thesis_position_id, sizing_decision_id,
             order_candidate_key, signal_date, reference_close}
monitoring_snapshot_id:
  domain = mlab-monitoring-snapshot-id.v1
  payload = {id_schema_version, thesis_position_id, observed_at_utc, input_data_hashes}
attribution_snapshot_id:
  domain = mlab-attribution-snapshot-id.v1
  payload = {id_schema_version, thesis_position_id, window_start, window_end,
             benchmark_security_ids, ordered_fill_refs, price_snapshot_hashes}
postmortem_id:
  domain = mlab-position-postmortem-id.v1
  payload = {id_schema_version, thesis_position_id, exit_event_id,
             attribution_snapshot_ids, reviewer_id}
feedback_event_id:
  domain = mlab-feedback-event-id.v1
  payload = {id_schema_version, source_postmortem_id, affected_object_type,
             affected_object_id, action, created_at_utc}
learning_override_id:
  domain = mlab-learning-override-id.v1
  payload = {id_schema_version, affected_object_type, affected_object_id,
             allowed_action, scope, approver_id, created_at_utc, expires_at_utc}
learning_override_use_id:
  domain = mlab-learning-override-use-id.v1
  payload = {id_schema_version, learning_override_id, attempted_at_utc,
             affected_change_artifact_id, requested_action, requested_scope}
lifecycle_event_id:
  domain = mlab-thesis-lifecycle-event-id.v1
  payload = {id_schema_version, thesis_position_id, event_namespace, from_status,
             to_status, source_artifact_id, occurred_at_utc}
```

Canonical collection rules are part of the ID schema and cannot be chosen by an implementer:

- set-like `catalyst_ids`, `invalidation_ids`, `benchmark_security_ids`,
  `control_security_ids`, `attribution_snapshot_ids`, evidence IDs, and input hashes are
  deduplicated and sorted by their full stable ID/hash before serialization;
- `ordered_fill_refs` are sorted by `(filled_at_utc, ledger_decision_id, fill_ref_id)` and each
  ref must provide all three fields; an unresolved tie is a blocker, not input-order fallback;
- exit rules and review schedules are semantic sequences. They retain order and each element
  carries an explicit `sequence_index`; duplicate or non-contiguous indexes are rejected;
- object key order never changes an ID. Reordering a set-like array does not change an ID;
  reordering a semantic sequence does change it.

The domain and `id_schema_version` are immutable compatibility boundaries. Changing either
creates new IDs and requires explicit supersession links.

Any additional artifact ID introduced by the schemas or a future version must declare an
equivalent domain, ID schema version, and complete named semantic payload before implementation.
Raw concatenation, implicit `str()` conversion, display text, unordered object iteration, or an
unspecified list order is a contract violation.

A UI may display short prefixes, but persisted cross-links must store full IDs.

---

## 8. Core schemas

### 8.1 Committee request

```text
schema_version: mlab-committee-request.v1
committee_request_id
created_at_utc
requested_by
request_mode: frozen | live_research
safety_mode: research_mock_only
upstream_refs:
  source_run_ids[]
  company_run_id nullable
  company_candidate_id nullable
  valuation_id nullable
  memo_id
  quant_tearsheet_ids[]
analysis_cutoff_utc
security_id
issuer_id
benchmark_security_ids[]
control_security_ids[]
requested_horizon_days
paper_only: true
```

Validation rejects missing memo ID, `paper_only=false`, future cutoff, unsupported security type, unresolved identity, missing benchmark, absent quant evidence, or stale memo/catalyst status.

### 8.2 Thesis paper position

```text
schema_version: mlab-thesis-position.v1
thesis_position_id
committee_request_id
memo_id
issuer_id / security_id / symbol
strategy_family: thesis_long | relative_strength | event_catalyst | valuation_reversion | other
thesis_summary
thesis_claim_ids[]
evidence_ids[]
valuation_summary_ref
quant_validation_refs[]
benchmark_security_ids[]
control_security_ids[]
horizon_days
expected_thesis_mechanism
key_assumptions[]
principal_risks[]
contrary_evidence_ids[]
catalyst_ids[]
invalidation_ids[]
monitoring_plan_id
exit_plan_id
thesis_position_status: DRAFT | INPUT_BLOCKED | GATED | PAPER_READY | PAPER_BLOCKED |
                        REJECTED | WATCH_ONLY | SUPERSEDED
```

`REJECT_THESIS_POSITION` is a committee action whose persisted result is `REJECTED`;
`INPUT_BLOCKED` means upstream eligibility was not reached; `PAPER_BLOCKED` means the eligible
thesis reached committee evaluation but failed a portfolio/readiness gate; and `WATCH_ONLY` is a
terminal no-queue disposition with zero size. The position is an analytic object, not an order.
It cannot contain a live broker account, routing venue, margin instruction, option leg, short
sale, or unbounded quantity.

### 8.3 Sizing decision

```text
schema_version: mlab-sizing-decision.v1
sizing_decision_id
thesis_position_id
policy_version / policy_hash
portfolio_snapshot_id
cash_available
portfolio_equity
current_symbol_exposure
current_sector_or_theme_exposure nullable
current_strategy_exposure
benchmark_beta_proxy nullable
volatility_estimate nullable
drawdown_state nullable
base_weight
confidence_multiplier
valuation_margin_multiplier
quant_quality_multiplier
catalyst_timing_multiplier
liquidity_multiplier
correlation_multiplier
risk_cap_multiplier
final_target_weight
max_notional
estimated_reference_price
proposed_quantity
rounding_lot_size
unallocated_residual_cash
reason_codes[]
blockers[]
```

All multipliers are deterministic policy outputs. If an input is missing and required, size is zero with a typed blocker. No model or analyst may directly set `final_target_weight`.

### 8.4 Monitoring plan

```text
schema_version: mlab-monitoring-plan.v1
monitoring_plan_id
thesis_position_id
created_at_utc
review_cadence: daily | weekly | catalyst_driven | manual
next_review_at_utc
price_monitoring:
  benchmark_ids[]
  max_underperformance_vs_benchmark
  drawdown_thresholds[]
  volatility_thresholds[]
catalyst_monitors[]
invalidation_monitors[]
freshness_slas[]
required_data_sources[]
missing_data_policy
escalation_policy
```

Missing data must not be interpreted as thesis success. A required monitor that cannot observe its source emits `MONITOR_BLOCKED` and can trigger forced review.

### 8.5 Catalyst monitor

```text
schema_version: mlab-catalyst-monitor.v1
catalyst_monitor_id
upstream_catalyst_id
thesis_position_id
title
mechanism
expected_window_start / expected_window_end
timezone
confirmation_source_requirement
success_observations[]
failure_observations[]
delay_observations[]
status: EXPECTED | OCCURRED_SUCCESS | OCCURRED_FAILURE | DELAYED | CANCELLED | UNOBSERVABLE | STALE
last_checked_at_utc
next_check_at_utc
source_claim_ids[] / evidence_ids[]
action_on_status: continue | force_review | reduce_size | exit_next_open | thesis_broken
```

A catalyst must have a mechanism and an observation rule. A calendar date alone is insufficient.

### 8.6 Invalidation monitor

```text
schema_version: mlab-invalidation-monitor.v1
invalidation_monitor_id
upstream_invalidation_id
thesis_position_id
thesis_component
observable_metric_or_event
operator
threshold / units
observation_window
required_source_class
current_status: ACTIVE | TRIGGERED | CLEARED | EXPIRED | UNOBSERVABLE | STALE
severity: review | size_reduction | thesis_broken
trigger_action: force_review | reduce_size | exit_next_open | reject_thesis
last_observation
last_checked_at_utc
source_claim_ids[] / evidence_ids[]
```

Invalidation conditions must be measurable. “Story changed,” “bad vibes,” or “competition increased” are invalid unless translated into source-class, metric/event, threshold, and window.

### 8.7 Exit plan

```text
schema_version: mlab-exit-plan.v1
exit_plan_id
thesis_position_id
created_at_utc
rules[]
review_required_before_exit: false
allow_partial_exit: true
reentry_policy
```

Each rule:

```text
exit_rule_id
rule_type: thesis_broken | catalyst_failure | stale_memo | benchmark_relative_trail | drawdown |
           time_stop | valuation_range_reached | quant_health_pause | safety_gate | manual_review
priority
condition
source_requirements[]
action: hold | reduce_to_weight | exit_next_open | block_new_adds | force_review
cooldown_days
reason_template
```

Hard thesis exits include invalidation severity `thesis_broken` and verified stale evidence; soft
exits include benchmark-relative underperformance, time stop, and quant health deterioration.
Those exits become next-open paper candidates, never same-close fills. A live-flag,
protected-state, fabricated-evidence, or unresolved-integrity anomaly instead activates the
audit/kill gate and blocks queue mutation until integrity is restored; it must not attempt to
“fix” unsafe state by emitting another candidate.

### 8.8 Paper candidate link

```text
schema_version: mlab-paper-candidate-link.v1
paper_candidate_link_id
thesis_position_id
sizing_decision_id
order_candidate_key
supersession_group_id
action_type: initial_entry | scale_in | reduce_to_weight | full_exit
exit_rule_id nullable
side: BUY | SELL
symbol
quantity
strategy: thesis_portfolio | thesis_portfolio_exit
confidence
reason
signal_date
reference_close
intended_execution: next_open
queue_status: NOT_QUEUED | QUEUED | SKIPPED_BLOCKED | EXECUTED | EXPIRED | CANCELLED |
              SUPERSEDED
broker_candidate_hash nullable
pending_queue_hash_before nullable
pending_queue_hash_after nullable
ledger_decision_id nullable
```

This mandatory sidecar is the only bridge to the existing `OrderCandidate`; MVP does not add
provenance fields to `market_lab.broker.OrderCandidate`. “Full upstream links” therefore means
the queued candidate's canonical hash resolves to exactly one active sidecar containing the
memo → committee → thesis → sizing lineage. It never means encoding IDs in free-text `reason`.
The exact adapter copies only these current fields into `OrderCandidate`: `side`, `symbol`,
`quantity`, `strategy`, `confidence`, `reason`, `signal_date`, `reference_close`, and
`intended_execution`. `broker_candidate_hash` hashes a domain-separated canonical JSON object
with those nine named fields and schema `mlab-broker-order-candidate-hash.v1`.

`order_candidate_key` is typed canonical data, not a display tuple:

```text
{
  "schema_version": "mlab-order-candidate-key.v1",
  "side": ...,
  "symbol": ...,
  "strategy": ...,
  "signal_date": ...,
  "thesis_position_id": ...,
  "supersession_group_id": ...,
  "sizing_decision_id": ...,
  "action_type": "initial_entry|scale_in|reduce_to_weight|full_exit",
  "exit_rule_id": null | ...
}
```

This key distinguishes same-symbol thesis decisions and reductions from full exits. Replaying
the same key is idempotent. A revised quantity requires a new sizing decision and explicit
supersession of the old key; it must not silently overwrite another thesis. Because unchanged
`OrderCandidate` cannot distinguish two links whose nine broker fields are byte-identical, a
second active sidecar with the same `broker_candidate_hash` but different lineage fails closed
until one candidate is cancelled/superseded. `confidence` is deterministic and in `[0, 1]`; MVP
uses fixed `1.0` to mean “all policy gates accepted,” never analyst conviction.

A link with `queue_status=QUEUED` may be finalized only after all gates pass. A
`SKIPPED_BLOCKED` or `CANCELLED` link may be finalized as an auditable no-mutation result, but it
cannot claim a broker hash was inserted or a ledger decision exists. `SELL` links may be
generated only for reducing/closing a ledger-proven existing paper position; no shorting.

### 8.8.1 Queue intent

```text
schema_version: mlab-queue-intent.v1
paper_candidate_link_id
created_at_utc
thesis_position_id
sizing_decision_id
memo_id
committee_request_id
order_candidate_key
broker_candidate_hash
order_candidate_payload
intended_operation: APPEND | REPLACE | REMOVE
supersedes_paper_candidate_link_id nullable
pending_queue_hash_before
pending_queue_hash_expected_after
queue_status: NOT_QUEUED
```

The intent contains enough typed data to reconstruct or reject the handoff without parsing
`reason`. It is immutable and cannot itself prove queue success.

### 8.8.2 Lifecycle event

```text
schema_version: mlab-thesis-lifecycle-event.v1
lifecycle_event_id
thesis_position_id
event_namespace: thesis_position | queue | paper_position | monitoring | postmortem | archive
from_status
to_status
source_artifact_id
occurred_at_utc
reason_codes[]
```

Lifecycle events are append-only. Each namespace uses only the typed enum and transition table
in Section 17; replay rejects a transition whose `from_status` is not the last accepted state.

### 8.9 Monitoring snapshot

```text
schema_version: mlab-monitoring-snapshot.v1
monitoring_snapshot_id
thesis_position_id
observed_at_utc
price_snapshot_refs[]
benchmark_snapshot_refs[]
catalyst_statuses[]
invalidation_statuses[]
memo_freshness_status
quant_health_refs[]
current_paper_position
monitoring_status: NOT_STARTED | ACTIVE | MONITOR_BLOCKED | FORCE_REVIEW |
                   THESIS_BROKEN | EXIT_PENDING | CLOSED
recommended_action: continue | block_adds | reduce | exit_next_open | force_review | postmortem_due
reason_codes[]
blockers[]
```

Snapshots are append-only and idempotent for the same input hashes.

### 8.10 Attribution snapshot

```text
schema_version: mlab-attribution-snapshot.v1
attribution_snapshot_id
thesis_position_id
window_start / window_end
entry_fill_refs[]
exit_fill_refs[]
position_pnl
position_pnl_pct
benchmark_pnl_pct
benchmark_relative_pnl_pct
market_beta_proxy_effect nullable
sector_or_control_effect nullable
security_specific_residual nullable
thesis_event_effect nullable
valuation_rerating_effect nullable
execution_slippage_effect
sizing_effect
cash_drag_effect
timing_effect
unexplained_residual
method_notes[]
quality_flags[]
```

Attribution is diagnostic, not proof. If a component cannot be measured cleanly, leave it null and add a quality flag. Do not force all residuals into thesis skill.

### 8.11 Analyst scorecard

```text
schema_version: mlab-analyst-scorecard.v1
scorecard_id
analyst_actor_id
period_start / period_end
role: source_analyst | company_analyst | valuation_analyst | quant_analyst |
      portfolio_manager | risk_reviewer | postmortem_reviewer
coverage_count
approved_count
blocked_count
rejected_count
forecast_calibration
catalyst_call_quality
invalidation_quality
evidence_quality
false_positive_rate
false_negative_review_count
postmortem_completion_rate
average_time_to_review
process_violations[]
score_components[]
overall_rating: improving | acceptable | watch | restricted
```

Analyst scorecards must not optimize for “more BUYs” or P&L alone. They score evidence quality, calibration, humility, blocker honesty, and postmortem discipline.

### 8.12 Process scorecard

```text
schema_version: mlab-process-scorecard.v1
process_scorecard_id
period_start / period_end
phase_coverage
input_block_rate
gate_failure_distribution
staleness_rate
monitor_block_rate
exit_rule_latency
postmortem_latency
feedback_closure_rate
safety_incidents
replay_failure_count
hash_mismatch_count
manual_override_count
learning_override_proposed_count
learning_override_used_count
learning_override_expired_or_revoked_count
override_bad_outcome_followup_due_count
recommended_process_action: continue | tighten_gate | loosen_gate_review_required | pause_lane | audit_required
```

Process scorecards measure the lab's reliability independent of individual analyst identity.

### 8.13 Postmortem

```text
schema_version: mlab-position-postmortem.v1
postmortem_id
thesis_position_id
opened_at / closed_at nullable
postmortem_trigger: closed_position | time_stop | thesis_broken | force_review | scheduled_review
outcome_summary
pnl_summary
attribution_snapshot_ids[]
original_thesis_assessment
what_happened
what_was_expected
what_was_missed
catalyst_review
invalidation_review
sizing_review
exit_review
evidence_quality_review
process_quality_review
failure_modes[]
lessons[]
learning_override_ids[]
learning_override_use_ids[]
recommended_feedback_events[]
reviewer_id
review_status: DRAFT | REVIEW_REQUIRED | APPROVED | REJECTED
```

Every closed thesis paper position needs a postmortem. Open positions crossing a time stop or forced review threshold need an interim postmortem.

### 8.14 Feedback event

```text
schema_version: mlab-feedback-event.v1
feedback_event_id
source_postmortem_id
created_at_utc
affected_object_type: analyst | policy | sizing_rule | gate | monitor | exit_rule | quant_strategy | source | memo_template
affected_object_id
action: continue | tune | tighten | loosen_review_required | pause | retire | add_test | create_research_task
rationale
supporting_evidence_ids[]
required_followup_owner
required_followup_due_at
status: proposed | accepted | implemented | rejected | superseded
```

Accepted feedback events are the normal path from postmortem learning to process changes. A
strategy, non-safety gate, or sizing rule must not be tuned unless it cites accepted feedback
events or a valid, exact-scope `LearningOverride` and accepted use event under Section 8.15.

### 8.15 Learning override and use event

An exceptional learning change must use a machine-readable, immutable override; an approver name
in prose or a populated `reviewer_override` field is not authorization.

```text
schema_version: mlab-learning-override.v1
learning_override_id
created_at_utc
created_at_cutoff_utc
effective_at_utc
expires_at_utc
approver_id
approver_authority: founder | delegated_operator
rationale
affected_object_type: analyst | policy | sizing_rule | non_safety_gate | monitor |
                      exit_rule | quant_strategy | source | memo_template
affected_object_id
allowed_action: tune | tighten | loosen_review_required | pause | retire | add_test |
                create_research_task
scope: {strategy_family_ids[], security_ids[], policy_version_from, policy_version_to}
supporting_evidence_ids[]
related_feedback_event_ids[]
one_time: true
max_uses: 1
status: PROPOSED | APPROVED | REJECTED | REVOKED
supersedes_override_record_hash nullable
protected_state_hashes
audit_hash
```

`created_at_cutoff_utc` freezes evidence eligibility. `audit_hash` is the canonical content hash
of the override excluding the hash field itself. Override records are immutable; approval,
rejection, or revocation appends a superseding record with the same logical override ID and
authority/scope, the prior record hash, and a new audit hash. MVP overrides are one-time and
expire no later
than 30 days after approval, and authorize only the exact object/action/scope named. Broader or
renewed scope requires a new override ID; overrides cannot be used to rewrite historical
artifacts or set an ad hoc position size.

Every attempted use appends an event, including rejected attempts:

```text
schema_version: mlab-learning-override-use.v1
learning_override_use_id
learning_override_id
attempted_at_utc
affected_change_artifact_id
requested_action
requested_scope
validation_status: ACCEPTED | REJECTED
reason_codes[]
policy_hash_before
policy_hash_after nullable
protected_state_hashes_before
protected_state_hashes_after
```

The validator accepts a policy/strategy/process change only when it cites one or more accepted
feedback events or an `APPROVED`, unexpired, unconsumed override whose object, action, scope,
cutoff, and approver authority match exactly. Under a dedicated learning lock, it first verifies
that no accepted use exists, then appends and `fsync`s the use event before applying the policy
artifact. The presence of that accepted use derives effective status `CONSUMED`; the immutable
override record is not rewritten. Expiration is derived from time, and revocation appends/fsyncs
a `REVOKED` superseding override record before any use. Crash recovery treats any fsynced accepted use as
consumed and must not permit a second use.

The following are non-overridable by this subsystem: G1 research-only safety; disabled live
trading/options; no shorting, margin, or naked options; protected-state mutation boundaries;
next-open/no-lookahead rules; evidence fabrication/provenance; immutable history; hash/replay
integrity; and independent-review requirements. Any override that names one of these domains is
rejected regardless of approver. Scorecards report proposed, accepted/used, rejected, expired,
and revoked override counts and rationale quality. If a used override is associated with a bad
outcome or process violation, the resulting postmortem must cite the override/use IDs and create
a follow-up feedback event; the case remains in attribution and scorecard corpora.

---

## 9. Memo-to-paper-position linkage

### 9.1 Eligibility sequence

A memo can enter committee review only if:

1. `memo_status` is `approved_research` or equivalent independently approved status;
2. `research_only=true` and safety attestation exists;
3. issuer/security identity is resolved and active at the committee cutoff;
4. memo has measurable catalysts and invalidations;
5. memo has contrary evidence and principal risks;
6. memo is not stale under its freshness policy;
7. valuation outputs are ranges, not a standalone point target;
8. method blockers and uncertainty are visible;
9. quant validation exists for the proposed position family;
10. benchmark/control securities are selected;
11. no synthetic/cache-synthetic data is used for execution-critical market evidence.

Upstream absence/staleness emits persisted thesis status `INPUT_BLOCKED`. An eligible but
unsuitable thesis receives committee action `REJECT_THESIS_POSITION` and persisted status
`REJECTED`. Neither path can create a paper candidate.

### 9.2 Link semantics

The link from memo to position is explicit and typed:

```text
memo_id -> committee_request_id -> thesis_position_id -> sizing_decision_id -> paper_candidate_link_id -> broker ledger decision_id
```

Each edge records:

- input and output hashes;
- actor and tool version;
- policy hash;
- gate status;
- created time;
- independent reviewer, when required.

No dashboard/report may show a paper position without the upstream memo ID and committee packet ID.

### 9.3 Allowed memo outcomes

- `PAPER_READY`: may create a paper candidate link when portfolio/safety gates also pass.
- `PAPER_BLOCKED`: thesis may be plausible, but missing data/gate failures prevent queueing.
- `REJECTED`: persisted result of committee action `REJECT_THESIS_POSITION`; the
  memo/thesis/security is unsuitable for paper tracking under policy.
- `WATCH_ONLY`: monitor the thesis without a paper position.

`PAPER_READY` is not live approval and not a recommendation.

### 9.4 Exact queue handoff and recovery

`queue-paper-candidate` is the only command permitted to bridge into the current pending
candidate JSONL. It must use a dedicated lock resolved beside the configured
`pending_order_candidates.jsonl`; it must not rely on the current bare append helper as an
atomic transaction. The protocol is:

1. validate G0–G6 and the pre-mutation conditions of G7, then compute
   `order_candidate_key` and the exact current-compatible `OrderCandidate`;
2. acquire the queue lock; while holding it, re-read and fully parse the candidate file, reject
   partial/invalid JSONL, re-check dedupe, supersession, caps, staleness, and protected hashes,
   and compute the exact before/after queue bytes;
3. while still holding the lock, write/fsync immutable `queue_intent.json` with full lineage,
   expected broker candidate hash, and `pending_queue_hash_before/expected_after`;
4. write the complete resulting JSONL to a same-filesystem temp file, flush and `fsync` it,
   `os.replace` it over the queue, then `fsync` the parent directory; do not expose an append
   whose sidecar has not been durably staged;
5. still under the lock, verify the actual after hash, finalize/fsync
   `paper_candidate_link.json` with `queue_status=QUEUED`, append/fsync the queue lifecycle event,
   and mark G7 passed;
6. release the lock and commit the run manifest last.

Queue reconciliation indexes all active sidecars by `order_candidate_key` and
`broker_candidate_hash`. Every pending candidate created by this adapter must resolve to exactly
one non-superseded sidecar; zero or multiple matches are `QUEUE_LINEAGE_UNRECONCILED`, block any
further queue mutation, and require audit. Every queue writer must reconcile unresolved intents
under the same lock before making a new mutation. A crash after `queue_intent.json` but before
queue replacement leaves `NOT_QUEUED` and can retry. A crash after queue replacement but before link
or manifest finalization recovers under the lock by matching the staged intent and before/after
hashes; it finalizes that one sidecar and never appends a duplicate. If the file no longer
matches either hash or lineage is ambiguous, recovery fails closed without rewriting it.

Supersession removes/replaces only the candidate named by the old canonical key and records old
and new link IDs. `EXECUTED` requires reconciliation to exactly one broker ledger decision ID;
absence is `paper_position_status=UNRECONCILED`, never an assumed fill. The sidecar and audit
events preserve lineage after a pending candidate leaves the queue.

---

## 10. Position sizing policy

### 10.1 Design principles

Sizing must be conservative, deterministic, and explainable. It should reward complete, high-quality evidence modestly and penalize uncertainty harshly.

MVP sizing starts from a small base paper weight and applies caps:

```text
raw_target_weight = base_weight
                  * confidence_multiplier
                  * valuation_margin_multiplier
                  * quant_quality_multiplier
                  * catalyst_timing_multiplier
                  * liquidity_multiplier
                  * correlation_multiplier
                  * risk_cap_multiplier

final_target_weight = min(
  raw_target_weight,
  per_position_cap,
  per_strategy_cap_remaining,
  per_theme_cap_remaining,
  cash_cap_remaining,
  existing RiskConfig.max_position_pct
)
```

Initial MVP policy:

```text
base_weight                         = 0.02  # 2% paper portfolio equity
per_position_cap                    = min(0.05, RiskConfig.max_position_pct)
per_strategy_cap                    = 0.20
per_theme_cap                       = 0.25
minimum_notional                    = RiskConfig.min_trade_notional
maximum_notional                    = RiskConfig.max_trade_notional
minimum_required_quant_status       = approved_or_reviewed
minimum_required_memo_status        = approved_research
missing_required_input              = final_target_weight 0, PAPER_BLOCKED
```

Exact numbers are workflow defaults for paper research, not capital advice. Ronak/Ozzy can change them by policy version, not ad hoc per position.

Sizing inputs are split explicitly:

```text
required_for_paper_ready:
  approved memo and valuation range
  resolved supported security identity
  approved/reviewed quant validation and kill rule
  at least one fresh, source-backed, bounded catalyst monitor
  at least one measurable invalidation monitor
  benchmark and required controls
  fresh trusted reference price and liquidity metric required for queueing
  current portfolio/cash/exposure snapshot
  monitoring plan and exit plan

optional_size_modifiers:
  confidence tier within an otherwise eligible memo
  valuation margin within an approved range
  quant robustness above the minimum
  catalyst timing inside the already bounded eligible window
  correlation/risk-cap penalties when required exposure inputs are present
```

Missing or stale `required_for_paper_ready` data forces `final_target_weight=0` and
`PAPER_BLOCKED`, or `WATCH_ONLY` when committee policy permits monitoring without a paper
position. Optional modifiers may shrink an already eligible target but can never turn missing
required evidence into `PAPER_READY`.

### 10.2 Multiplier policy

Recommended deterministic multiplier ranges:

```text
confidence_multiplier:
  LOW or single-method/high-uncertainty memo       0.50
  MEDIUM                                          0.75
  HIGH evidence completeness, not market risk      1.00

valuation_margin_multiplier:
  no approved valuation range / NO_VALUATION       0.00 or WATCH_ONLY
  price inside fair-value range                    0.50
  modest upside with method agreement              0.75
  large upside but high uncertainty                0.75
  large upside with method agreement               1.00

quant_quality_multiplier:
  no quant validation                              0.00
  weak sample / low-power                          0.50
  OOS passes but high drawdown/turnover            0.75
  robust OOS + cost stress + benchmark pass        1.00

catalyst_timing_multiplier:
  no bounded catalyst                              0.00, PAPER_BLOCKED or WATCH_ONLY
  catalyst outside horizon                         0.75
  catalyst inside horizon and monitored            1.00
  catalyst stale/rumor-only                        0.00, PAPER_BLOCKED

liquidity_multiplier:
  no trusted current liquidity metric              0.00, PAPER_BLOCKED
  turnover/volume adequate                         1.00
  stale/untrusted liquidity                         0.00, PAPER_BLOCKED

correlation_multiplier:
  high overlap with existing exposure              0.50
  normal overlap                                   1.00

risk_cap_multiplier:
  drawdown/cash/cap pressure                       0.00 to 1.00
```

No multiplier may exceed 1.0 in MVP. The system can shrink size; it cannot boost above the base policy because a narrative sounds compelling.

The former `0.50` “no bounded catalyst” and “no liquidity metric” values are not valid for
MVP paper readiness or queueing. A future non-catalyst strategy family may define such a value
only in a new policy/schema version with its own required readiness contract; `WATCH_ONLY`
analysis may display hypothetical reduced sizing but must persist zero executable size and
cannot produce a candidate.

### 10.3 Quantity conversion

When a paper candidate is allowed:

```text
max_notional = min(final_target_weight * portfolio_equity, RiskConfig.max_trade_notional)
quantity = floor(max_notional / reference_close)
```

Reject/skip when:

- `quantity <= 0`;
- `quantity * reference_close < RiskConfig.min_trade_notional`;
- resulting position would exceed current `RiskConfig.max_position_pct`;
- required live-data guard fails;
- symbol already has an open thesis position and policy disallows stacking;
- the canonical `order_candidate_key` already exists without idempotent replay or explicit
  supersession, or the broker candidate hash collides with different active lineage.

### 10.4 Scaling in and out

MVP supports only one initial paper entry and deterministic reductions/exits. Later versions may add scale-ins only if each add has:

- fresh committee packet;
- updated sizing decision;
- no stale catalyst/invalidation status;
- paper outcome not under active negative review;
- total position still below caps.

No martingale/double-down logic exists in MVP.

---

## 11. Catalysts and invalidation workflow

### 11.1 Catalyst states

Catalysts progress through:

```text
EXPECTED -> OCCURRED_SUCCESS | OCCURRED_FAILURE | DELAYED | CANCELLED | UNOBSERVABLE | STALE
```

Rules:

- `EXPECTED` requires a source-backed bounded time window.
- `OCCURRED_SUCCESS` requires the declared success observation, not merely a price rise.
- `OCCURRED_FAILURE` requires the declared failure observation.
- `DELAYED`/`CANCELLED` are explicit states and may trigger review or exit.
- `STALE` occurs when the freshness SLA expires without verification.
- `UNOBSERVABLE` means the required source is unavailable; it cannot be scored as success.

### 11.2 Invalidation states

Invalidations progress through:

```text
ACTIVE -> TRIGGERED | CLEARED | EXPIRED | UNOBSERVABLE | STALE
```

`TRIGGERED` severity controls action:

- `review`: force reviewer attention; no automatic exit unless exit plan says so.
- `size_reduction`: queue a reduction candidate after review/gate if policy allows.
- `thesis_broken`: queue exit-next-open candidate when current paper position exists.

### 11.3 Monitoring cadence

Default cadence:

- price/benchmark/drawdown: each daily report run when price data is available;
- catalysts: daily inside expected window, weekly otherwise;
- memo freshness: each committee/monitor run;
- quant health: weekly or after enough new paper observations;
- safety protected-state check: every build/queue/monitor/postmortem command.

If a required source is missing, emit a blocked monitor snapshot and next action.

---

## 12. Exit governance

### 12.1 Exit rule hierarchy

Process rules in priority order:

1. safety/integrity failure;
2. live flag or protected-state anomaly;
3. thesis-broken invalidation;
4. memo/catalyst stale beyond hard SLA;
5. quant health `pause`/`retire` for the strategy family;
6. SPY/benchmark-relative trailing exit;
7. drawdown/time stop;
8. valuation range reached or thesis resolved;
9. manual reviewer/founder decision.

Higher-priority rules override lower-priority hold signals. A lower-priority BUY signal cannot cancel a higher-priority exit.

### 12.2 Exit outputs

Exits produce `paper_candidate_link` with `side=SELL`, existing quantity or reduction quantity, strategy `thesis_portfolio_exit`, and reason containing the triggering rule ID. The actual mock broker still enforces no-shorting and next-open fill discipline.

For `reduce_to_weight`, the rule stores a target post-reduction weight. At the decision close,
using one immutable portfolio/price snapshot:

```text
target_quantity = floor(target_weight * portfolio_equity / reference_close)
sell_quantity = min(current_ledger_quantity,
                    max(0, current_ledger_quantity - target_quantity))
```

A full exit uses exactly `current_ledger_quantity`. Quantities are integral, never rounded up,
and never exceed the ledger-proven holding. A zero reduction is skipped. A partial reduction
whose notional is below `RiskConfig.min_trade_notional`, or whose residual position violates a
declared minimum-position policy, emits a typed blocker/forced review rather than rounding into
a cap violation; a full exit below the current broker minimum is also blocked/reviewed and must
not be represented as closed. Per position and signal date, evaluate all rules first: the
highest-priority full exit suppresses every reduction/hold, otherwise the highest-priority
reduction supplies the sole SELL candidate. Lower-priority rules remain in the decision audit.

Normal thesis, catalyst, valuation, and benchmark exits require a uniquely reconciled entry and
current quantity in the mock ledger. Missing or ambiguous ledger evidence emits
`LEDGER_ENTRY_UNPROVEN`, sets `paper_position_status=UNRECONCILED`, and creates no SELL candidate.
A safety/protected-state anomaly is different: it emits the safety failure and audit/kill gate
immediately, blocks all queue mutations, and never assumes an entry or fabricates an exit.

### 12.3 Re-entry

After an exit, re-entry requires a new committee request or accepted feedback event. The system must not re-enter solely because the same memo still exists.

---

## 13. Attribution model

### 13.1 Attribution questions

For every active or closed thesis paper position, attribution should answer:

- Did the security beat its benchmark/control after the paper fill?
- Was P&L mostly market beta, sector/control movement, security-specific residual, or catalyst event?
- Did the thesis mechanism occur?
- Did valuation rerate as expected, or did price move without fundamental support?
- Did sizing help or hurt relative to equal/base size?
- Did next-open execution/slippage materially change outcome?
- Did the exit rule improve or harm outcome versus hold-to-horizon?
- Was the result driven by luck/noise or by a predeclared thesis variable?

### 13.2 MVP calculations

MVP can calculate:

```text
position_return = mark_or_exit_value / entry_value - 1
benchmark_return = benchmark_end / benchmark_entry - 1
benchmark_relative = position_return - benchmark_return
execution_slippage_effect = fill_price / reference_close - 1 for BUY, reference_close / fill_price - 1 for SELL
sizing_effect = actual_position_pnl - base_weight_position_pnl
cash_drag_effect = uninvested_target_cash return difference vs benchmark
```

Advanced factor/beta attribution can remain null with quality flags until a proper model exists.

### 13.3 Attribution quality flags

Use flags rather than false precision:

```text
short_window
missing_benchmark
benchmark_proxy_weak
corporate_action_unadjusted
partial_exit
stale_price_source
synthetic_or_cache_source
catalyst_unobserved
valuation_not_refreshed
control_set_missing
```

Every attribution input carries `source_id`, `as_of_utc`, and `available_at_utc`, including
window endpoints, benchmark/control bars, fills, price snapshots, valuation refreshes, and
catalyst observations. For a normal attribution snapshot, each `available_at_utc` must be less
than or equal to the snapshot's `observed_at_utc`, and fills/bars must fall inside the declared
window under next-open semantics. Later-released or revised data is excluded. A postmortem may
use later data only when `analysis_mode=retrospective_postmortem` is explicit; those fields are
quality-flagged and cannot rewrite the original attribution or feed contemporaneous scorecards.

---

## 14. Analyst and process scorecards

### 14.1 Analyst scorecards

Score analysts by role-appropriate process quality:

- source analyst: provenance completeness, contradiction surfacing, unsupported-claim rate;
- company analyst: identity/exposure accuracy, competitor/counterevidence quality;
- valuation analyst: input lineage, method eligibility honesty, no-false-precision compliance;
- quant analyst: no-lookahead discipline, OOS/cost stress quality, weak-sample warnings;
- portfolio manager: sizing discipline, cap compliance, monitoring completeness;
- risk reviewer: blocker quality, safety incidents caught, override discipline;
- postmortem reviewer: timeliness, specificity, feedback closure.

Scorecards are periodic JSONL records. They should include counts, ratios, examples, and process violations. They must not reward excessive activity, inflated conviction, or short-term P&L alone.

### 14.2 Process scorecards

Process scorecards track whether the agency itself is improving:

- percent of positions with complete upstream links;
- percent with catalysts/invalidation monitors;
- queue attempts blocked by safety/data/staleness gates;
- postmortem completion latency;
- feedback events accepted/implemented;
- replay/hash failures;
- stale memo rate;
- monitor blocked rate;
- override count and rationale quality.

### 14.3 Scorecard actions

Allowed actions:

- `continue`: process is within expected range;
- `tighten_gate`: repeated failure/false positives require stricter criteria;
- `loosen_gate_review_required`: gate is too conservative, but loosening needs reviewer approval;
- `pause_lane`: analyst/process lane cannot create new paper candidates;
- `audit_required`: integrity or safety issue demands manual review.

---

## 15. Postmortems and feedback loop

### 15.1 Postmortem triggers

Create a postmortem when any is true:

- paper position closes;
- thesis-broken invalidation triggers;
- time stop expires;
- catalyst window closes without expected observation;
- loss/drawdown exceeds policy threshold;
- benchmark-relative underperformance exceeds threshold;
- scheduled review says evidence changed materially;
- risk reviewer requests one.

### 15.2 Required postmortem sections

Each postmortem must include:

1. original thesis and memo link;
2. original sizing and exit plan;
3. actual fill/exit and monitoring timeline;
4. catalyst and invalidation review;
5. attribution summary;
6. what was expected;
7. what happened;
8. what was missed or over-weighted;
9. whether the failure was source, company, valuation, quant, sizing, timing, execution, monitoring, market regime, or process;
10. whether future similar theses should continue, tune, pause, or retire;
11. feedback events with owners.

### 15.3 Feedback discipline

Feedback events are append-only. A future policy or strategy change must cite one or more
accepted feedback events or a valid, scoped `LearningOverride` plus its accepted use event from
Section 8.15. Free-text human/founder exceptions are invalid.

Forbidden learning shortcuts:

- tuning parameters because a single trade lost money;
- increasing size because a single trade won;
- removing a failed case from benchmark sets;
- relabeling a thesis after the fact without supersession;
- marking a catalyst successful because price rose;
- treating missing monitor data as evidence of no problem.

---

## 16. Gate model

Every gate emits:

```text
gate_id
group
status: PASS | WARN | FAIL | BLOCKED | NOT_APPLICABLE
reason_codes[]
claim_ids[] / evidence_ids[] / artifact_ids[]
checked_at_utc
policy_version / policy_hash
override_allowed
reviewer_override nullable
next_action nullable
```

`reviewer_override` is a reference to a validated `learning_override_id`, not free text. It is
permitted only when `override_allowed=true`, and only for the exact non-safety object/action/scope
authorized by Section 8.15. G1, no-lookahead/next-open discipline, protected-state integrity,
hash/replay integrity, and evidence/provenance gates always emit `override_allowed=false`.

### G0 — Input artifact eligibility

Pass conditions:

- upstream memo/company/quant artifacts exist and hashes verify;
- memo is approved research and not stale;
- security identity is resolved and supported;
- benchmark/control context exists;
- material claims are adjudicated;
- no synthetic/cache-synthetic evidence is used for execution-critical inputs.

### G1 — Research-only safety

Pass conditions:

- `paper_only=true`, `safety_mode=research_mock_only`;
- current risk configs keep live trading/options disabled;
- no order/live credential fields exist in artifacts;
- command does not mutate protected live or paper state unless explicitly running the queue handoff command.
- `override_allowed=false`; any override reference is itself a safety failure.

### G2 — Quant validation

Pass conditions:

- no same-bar fills;
- OOS/walk-forward or justified low-power warning exists;
- benchmark comparison exists;
- transaction cost stress exists;
- drawdown/exposure/turnover reported;
- kill rule exists.

### G3 — Thesis completeness

Pass conditions:

- thesis mechanism, assumptions, contrary evidence, risks, catalysts, invalidations, horizon, and controls are explicit;
- valuation range/method uncertainty is visible;
- no standalone point target or “winner” claim drives the decision.

### G4 — Portfolio fit

Pass conditions:

- current exposure, cash, existing position, and cap checks pass;
- correlation/theme overlap does not exceed policy;
- no duplicate active thesis position unless policy explicitly allows stack with reviewer approval.

### G5 — Sizing

Pass conditions:

- all required inputs are present;
- deterministic policy computes target weight and quantity;
- quantity respects min/max notional and max position;
- missing data yields zero/blocker, not default optimistic size.

### G6 — Monitoring and exits

Pass conditions:

- every material catalyst has source, window, mechanism, success/failure observations, and freshness SLA;
- every material invalidation has metric/event, threshold/window, source class, and action;
- exit plan includes hard safety exit and at least one thesis/benchmark/time stop.

### G7 — Candidate queue handoff

Pass conditions:

- all prior gates pass;
- live-data guard passes if required;
- candidate signal date is current close date;
- execution is `next_open`;
- duplicate queue key is handled deterministically;
- queue handoff follows the lock, temp-rewrite, file/directory `fsync`, sidecar, lineage, and crash
  recovery protocol in Section 9.4;
- queue handoff records protected-state hashes before and after.

### G8 — Monitoring snapshot

Pass conditions:

- source data is as-of correct;
- missing required monitor inputs become blockers;
- recommended action is one of allowed statuses;
- no same-run output can overwrite prior monitor snapshots.

### G9 — Attribution and postmortem

Pass conditions:

- fills and prices resolve;
- benchmark/control window aligns;
- calculations are deterministic;
- unmeasurable components remain null with quality flags;
- closed/triggered positions have a postmortem due or complete.

### G10 — Replay and audit

Pass conditions:

- manifest hashes verify;
- JSONL streams parse and chain if hash-chained later;
- protected-state mutation rules match command mode;
- rerun with same immutable inputs yields same semantic outputs.

---

## 17. State transitions

### 17.1 Canonical state namespaces

State is not stored in one overloaded field. Each persisted state belongs to exactly one typed
namespace and artifact:

```text
thesis_position_status (thesis_position.json):
  DRAFT | INPUT_BLOCKED | GATED | PAPER_READY | PAPER_BLOCKED | REJECTED |
  WATCH_ONLY | SUPERSEDED

queue_status (queue_intent.json/paper_candidate_link.json):
  NOT_QUEUED | QUEUED | SKIPPED_BLOCKED | EXECUTED | EXPIRED | CANCELLED |
  SUPERSEDED

paper_position_status (ledger-reconciliation lifecycle event):
  NO_POSITION | OPEN | REDUCED | CLOSED | UNRECONCILED

monitoring_status (monitoring snapshot):
  NOT_STARTED | ACTIVE | MONITOR_BLOCKED | FORCE_REVIEW | THESIS_BROKEN |
  EXIT_PENDING | CLOSED

postmortem_status (postmortem lifecycle event; review_status is the matching review subset):
  NOT_DUE | DUE | DRAFT | REVIEW_REQUIRED | APPROVED | REJECTED

archive_status (manifest/lifecycle event):
  ACTIVE | ARCHIVED | SUPERSEDED
```

Presentation aliases are forbidden in persisted JSON. In particular: `QUEUE_SKIPPED` maps to
`queue_status=SKIPPED_BLOCKED`; `QUEUE_EXPIRED` to `EXPIRED`; `QUEUE_CANCELLED` to `CANCELLED`;
`PAPER_OPEN` to `paper_position_status=OPEN`; `MONITORING` to
`monitoring_status=ACTIVE`; `POSTMORTEM_DUE` to `postmortem_status=DUE`; and
`LEARNING_RECORDED` is not a state—it is proved by accepted feedback event IDs or a consumed
learning override use. `REJECT_THESIS_POSITION` remains an action whose result is `REJECTED`.

### 17.2 Namespace transition tables

```text
thesis_position_status:
  DRAFT -> INPUT_BLOCKED | GATED | REJECTED | WATCH_ONLY
  GATED -> PAPER_READY | PAPER_BLOCKED | REJECTED | WATCH_ONLY
  INPUT_BLOCKED | PAPER_READY | PAPER_BLOCKED | REJECTED | WATCH_ONLY -> SUPERSEDED

queue_status:
  NOT_QUEUED -> QUEUED | SKIPPED_BLOCKED | CANCELLED
  QUEUED -> EXECUTED | EXPIRED | CANCELLED | SUPERSEDED
  SKIPPED_BLOCKED -> QUEUED | CANCELLED | SUPERSEDED

paper_position_status:
  NO_POSITION -> OPEN | UNRECONCILED
  OPEN -> REDUCED | CLOSED | UNRECONCILED
  REDUCED -> REDUCED | CLOSED | UNRECONCILED
  UNRECONCILED -> NO_POSITION | OPEN | REDUCED | CLOSED

monitoring_status:
  NOT_STARTED -> ACTIVE | MONITOR_BLOCKED
  ACTIVE -> MONITOR_BLOCKED | FORCE_REVIEW | THESIS_BROKEN | EXIT_PENDING | CLOSED
  MONITOR_BLOCKED -> ACTIVE | FORCE_REVIEW | THESIS_BROKEN
  FORCE_REVIEW -> ACTIVE | THESIS_BROKEN | EXIT_PENDING | CLOSED
  THESIS_BROKEN -> EXIT_PENDING | CLOSED
  EXIT_PENDING -> FORCE_REVIEW | CLOSED

postmortem_status:
  NOT_DUE -> DUE
  DUE -> DRAFT
  DRAFT -> REVIEW_REQUIRED
  REVIEW_REQUIRED -> APPROVED | REJECTED
  REJECTED -> DRAFT

archive_status:
  ACTIVE -> ARCHIVED | SUPERSEDED
```

Terminal states have no outgoing edge unless explicitly shown. Every transition appends one
`lifecycle_event`; finalized source artifacts remain immutable. Cross-namespace consequences are
deterministic: only `thesis_position_status=PAPER_READY` can move a link from `NOT_QUEUED` to
`QUEUED`; `queue_status=EXECUTED` does not imply a fill until ledger reconciliation sets
`paper_position_status`; `paper_position_status=CLOSED` forces `postmortem_status=DUE`; and
`archive_status=ARCHIVED` requires an approved postmortem for any closed position. No namespace
contains a live-trading state.

Replay rejects enum values outside these sets, skipped transitions, mismatched `from_status`, or
cross-namespace consequences without their source artifact. Recovery cases are explicit: a
crash after `PAPER_READY` but before queue intent resumes at `queue_status=NOT_QUEUED`; a crash
after queue replacement follows Section 9.4; and a closed ledger position with no completed
postmortem restores `postmortem_status=DUE` and cannot archive. An unreconciled ledger or queue
lineage is an audit/kill gate, not permission to infer state.

### 17.3 Queue expiration

A paper candidate expires if:

- no later bar exists within policy window;
- memo/catalyst/price data becomes stale before fill;
- a higher-priority exit/safety gate appears;
- risk caps change and no longer allow size;
- duplicate/superseding candidate replaces it.

---

## 18. CLI contract

Future CLI:

```text
uv run python scripts/market_lab_thesis_portfolio.py build
  --run-dir PATH
  --memo-id ID
  --quant-tearsheet ID
  --analysis-cutoff ISO8601
  --policy PATH
  --mode frozen|live_research
  --output-dir PATH

uv run python scripts/market_lab_thesis_portfolio.py validate
  --run-dir PATH
  --thesis-position-id ID
  --require-independent-review
  --require-no-side-effects

uv run python scripts/market_lab_thesis_portfolio.py queue-paper-candidate
  --run-dir PATH
  --thesis-position-id ID
  --require-live-data
  --max-candidates 1

uv run python scripts/market_lab_thesis_portfolio.py monitor
  --run-dir PATH
  --thesis-position-id ID
  --as-of ISO8601

uv run python scripts/market_lab_thesis_portfolio.py attribute
  --run-dir PATH
  --thesis-position-id ID
  --window start:end

uv run python scripts/market_lab_thesis_portfolio.py postmortem
  --run-dir PATH
  --thesis-position-id ID
  --trigger closed_position|scheduled_review|thesis_broken

uv run python scripts/market_lab_thesis_portfolio.py replay
  --run-dir PATH
  --verify-hashes
  --verify-no-unexpected-state-mutation
```

Exit codes:

```text
0 = command completed honestly and requested verification passed
2 = input/gate blocker; artifacts may be written with BLOCKED status
3 = schema/hash/replay/integrity failure
4 = independent review required or rejected
5 = safety/protected-state failure
6 = queue handoff skipped because data/caps/staleness blocked
```

`live_research` means acquisition/monitoring may request accepted evidence providers. It never means live trading.

---

## 19. Protected state and side-effect policy

Protected state paths include:

```text
mock_portfolio_state.json
mock_ledger.jsonl
pending_order_candidates.jsonl
options/paper_options_state.json
options/paper_options_ledger.jsonl
options/paper_options_candidates.jsonl
vt_trend/portfolio_state.json
vt_trend/ledger.jsonl
vt_trend/pending_candidates.jsonl
tsmom/portfolio_state.json
tsmom/ledger.jsonl
tsmom/pending_candidates.jsonl
```

These names are descriptive only. Validation resolves every configured path from the active
`MARKET_LAB_DATA_DIR`/`market_lab.config` value, normalizes it to an absolute path without
following an unexpected escape outside the configured root, and hashes that resolved path's
bytes or an explicit `ABSENT` marker. Filename-only checks and hard-coded repository-default
data roots are invalid. The same resolver and path set must be used for before/after comparison,
including when `MARKET_LAB_DATA_DIR` is overridden in tests.

All commands except `queue-paper-candidate` must leave protected state byte-identical. `queue-paper-candidate` may change only `pending_order_candidates.jsonl`, and only by appending/replacing a validated paper candidate under existing candidate semantics. It must not write portfolio state, ledger, options, VT Trend, TSMOM, or live-adjacent artifacts.

Before and after protected-state hashes are recorded in the manifest. Files absent before must remain absent unless the allowed queue file is intentionally created by the queue command.

---

## 20. Deterministic test plan

### 20.1 Contract and serialization tests

- round-trip every schema;
- reject unknown enums, future cutoffs, missing schema versions, non-finite numbers, binary floats in canonical economic fields, duplicate IDs;
- prove canonical IDs are invariant to dictionary order and set-like array order, but change
  when a semantic sequence changes;
- prove ambiguous raw-concatenation cases such as `("ab", "c")` versus `("a", "bc")` cannot
  collide under typed payloads, and every ID uses its declared domain/schema version;
- prove Markdown renderers do not alter semantic JSON content;
- reject `paper_only=false` and `safety_mode` other than `research_mock_only`.

### 20.2 Input and linkage tests

- approved memo + quant tearsheet creates committee request and thesis position;
- missing memo, stale memo, unresolved security, missing benchmark, missing quant evidence block;
- memo with point target/no range blocks;
- contradictory or unresolved upstream claims block unless explicitly `MIXED` with both branches represented;
- every paper position links back to memo, security, benchmark, policy, and gate report.

### 20.3 Sizing tests

- hand-calculate size from fixed policy and portfolio snapshot;
- missing required multiplier input yields zero/blocker;
- an otherwise strong memo with no bounded catalyst is `PAPER_BLOCKED`/`WATCH_ONLY`, size zero;
- missing or untrusted required liquidity is `PAPER_BLOCKED`, size zero;
- no multiplier exceeds 1.0;
- max position, max trade notional, minimum notional, cash, strategy cap, and theme cap are enforced;
- duplicate existing thesis position blocks or supersedes deterministically;
- quantity conversion floors correctly and never rounds up into cap violation;
- sizing cannot be set directly by analyst/model field.

### 20.4 Candidate queue tests

- paper-ready BUY creates exactly one unchanged current `OrderCandidate` plus exactly one
  mandatory sidecar with strategy `thesis_portfolio`, `signal_date`, `reference_close`,
  `intended_execution="next_open"`, and full upstream lineage;
- candidate does not fill same day;
- candidate fills only when a later bar exists through existing broker path;
- synthetic/cache/cache_synthetic source blocks when `require_live_data` is set;
- canonical dedupe/supersession behavior distinguishes same-symbol theses, reductions, and full
  exits, and blocks an identical broker hash with different active lineage;
- every queued candidate reconciles to exactly one sidecar and later ledger decision;
- queue lock, file/directory `fsync`, temp replacement, staged intent, and before/after hashes
  recover a crash after queue replacement without a duplicate;
- queue command mutates only the allowed pending-candidates file.

### 20.5 Catalyst and invalidation tests

- catalyst without mechanism/window/source blocks;
- rumor-only catalyst cannot satisfy readiness;
- delayed/cancelled/stale catalyst emits forced review according to policy;
- invalidation without metric/event/threshold/source blocks;
- frozen observed metric triggers `thesis_broken` and exit candidate;
- unobservable required monitor becomes blocker, not success.

### 20.6 Exit tests

- safety exit overrides BUY/hold;
- thesis-broken invalidation generates SELL next-open candidate for current quantity;
- benchmark-relative trailing rule matches existing SPY-relative semantics;
- time stop triggers review/exit as configured;
- no exit is generated when ledger/entry/benchmark data is missing unless safety rule requires block;
- re-entry requires new committee request or accepted feedback event.

### 20.7 Monitoring tests

- daily monitor snapshot is idempotent for same input hashes;
- monitor snapshots are append-only;
- stale memo/catalyst freshness emits correct status;
- missing benchmark or price data produces `MONITOR_BLOCKED`;
- recommended actions are valid enum values;
- state transitions are valid and reject skips.
- each persisted state belongs to exactly one enum namespace;
- replay recovers crash after `PAPER_READY` before queue intent, crash after queue replacement
  before manifest, and a closed position whose postmortem is still `DUE`.

### 20.8 Attribution tests

- compute benchmark-relative P&L from fixed fills and bars;
- compute execution slippage from reference close vs fill;
- compute sizing effect versus base weight;
- handle partial exits with quality flags;
- missing benchmark/control keeps component null and flags quality;
- non-retrospective attribution rejects any bar, fill, valuation, or catalyst observation whose
  `available_at_utc` is later than the snapshot's `observed_at_utc`;
- attribution arithmetic is deterministic and does not use displayed rounded strings.

### 20.9 Scorecard tests

- analyst scorecard aggregates approved/blocked/rejected counts correctly;
- calibration/catalyst quality handles pending outcomes without counting them as success;
- process scorecard records stale rate, monitor block rate, postmortem latency, feedback closure;
- safety incident forces `audit_required` or `pause_lane`;
- scorecards cannot optimize for BUY count or raw P&L alone.

### 20.10 Postmortem and feedback tests

- closed position requires postmortem;
- interim postmortem required on time stop or thesis-broken trigger;
- postmortem must reference attribution snapshot and original thesis position;
- feedback event requires owner and due date;
- policy/strategy change is rejected without an accepted feedback event or valid exact-scope,
  unexpired, unconsumed learning override;
- free-text overrides, out-of-scope/reused overrides, and attempts to override safety,
  no-lookahead, protected-state, provenance, or replay gates are rejected and audited;
- scorecards count override lifecycle/use outcomes, and a bad override outcome requires a cited
  postmortem follow-up event;
- failed cases remain in scorecard/attribution corpus.

### 20.11 Safety and protected-state tests

- build/validate/monitor/attribute/postmortem leave all protected state hashes unchanged;
- queue-paper-candidate changes only pending candidate file;
- protected hashes resolve from an alternate `MARKET_LAB_DATA_DIR`, not default filenames;
- no command imports live broker adapters or live credential paths;
- risk flags remain false for live trading/options, no shorting/margin enabled;
- write verbs are not added to webapp;
- options state is untouched in MVP;
- crash after artifact write but before manifest resumes safely without duplicate queue.

### 20.12 Replay and chaos tests

Inject:

- stale memo;
- post-cutoff price;
- synthetic price source;
- missing benchmark;
- duplicate candidate;
- quantity cap boundary;
- conflicting catalyst evidence;
- missing invalidation source;
- partial JSONL line;
- changed policy hash;
- protected-state mutation attempt;
- renderer mismatch;
- monitor source unavailable;
- postmortem feedback loop with missing owner.
- ambiguous canonical-ID concatenation inputs;
- queue write crash before sidecar/manifest finalization;
- missing bounded catalyst and missing trusted liquidity;
- reused or safety-targeting learning override;
- partial-reduction rounding/min-notional boundary.

Every case must fail closed with typed blockers and preserve audit integrity.

---

## 21. MVP acceptance criteria

MVP is accepted when all are true:

1. A frozen approved memo fixture can produce a valid committee packet, thesis paper position, sizing decision, monitoring plan, exit plan, and gate report.
2. A blocked fixture with stale/missing memo, missing quant validation, unresolved security, missing benchmark, synthetic execution-critical data, or invalid sizing input emits typed blockers and no paper candidate.
3. A paper-ready fixture can produce one unchanged existing-compatible `OrderCandidate` for the
   next-open paper queue plus one mandatory sidecar carrying full upstream links; reconciliation
   from queue candidate to sidecar and later ledger decision is one-to-one.
4. The same fixture cannot fill on the same close; a later bar is required.
5. Position size is deterministic, cap-bounded, and hand-calculable from the policy snapshot.
6. Every paper-ready position has at least one catalyst monitor, one invalidation monitor, one benchmark/control, one time/benchmark/drawdown exit, and one hard safety exit.
7. Monitoring snapshots can trigger `continue`, `force_review`, `reduce`, or `exit_next_open` without mutating portfolio/ledger state directly.
8. Attribution computes benchmark-relative P&L, execution slippage, and sizing effect for a frozen completed position.
9. A closed position generates a postmortem and feedback events with owners.
10. Analyst and process scorecards render from frozen events and include process-quality metrics, not only P&L.
11. Replay of a finalized run verifies hashes and produces the same semantic artifacts.
12. Build/validate/monitor/attribute/postmortem commands leave protected state byte-identical.
13. Queue handoff mutates only the existing pending paper candidate file, and only after all
    gates pass; lock/fsync, canonical dedupe, staged intent, supersession, and crash recovery
    preserve exactly-once lineage.
14. `uv run pytest tests/market_lab -q` remains green.
15. Documentation and reports state clearly that outputs are research/mock/paper-only and not investment advice or live-order approval.
16. Policy/strategy changes cite accepted feedback events or a valid consumed learning override;
    safety/no-lookahead/protected-state gates cannot be overridden, and override use is visible
    in scorecards and postmortems.

---

## 22. Implementation sequencing recommendation

The safest build sequence is:

1. contracts, policy snapshot, canonical IDs, and gate reports;
2. frozen fixture corpus and contract/gate tests;
3. committee packet renderer with no queue side effects;
4. deterministic sizing and monitoring/exit plan validation;
5. protected-state verifier;
6. queue handoff to existing `OrderCandidate` only after all above pass;
7. monitoring snapshots;
8. attribution snapshots;
9. postmortems and feedback events;
10. analyst/process scorecards and agency desk report integration.

Do not start with queueing. The first useful artifact is a committee packet that can honestly say `PAPER_READY`, `PAPER_BLOCKED`, or `REJECTED` with evidence and policy references.

---

## 23. Honest current phase after this spec

After this spec, Market Lab still has no product implementation for thesis-linked portfolio learning. It has the contract for that implementation.

Current phase remains:

**Research/paper lab with early analyst-agency scaffolding.**

The next implementation should be test-first and fixture-first. The goal is not to trade more; it is to make every paper position traceable, monitorable, attributable, reviewable, and learnable while preserving the safety gates that keep Market Lab from becoming a live trading system.
