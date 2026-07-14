# Market Lab Agency Architecture and Delivery Plan

Status: integrated implementation plan; research/specification only
Date: 2026-07-14 UTC
Decision owner: Ronak
Implementation posture: fixture-first, fail-closed, research/mock/paper only
Product code changed by this plan: none

## 0. Decision

Build Market Lab as a typed, resumable agency case graph with explicit promotion events between bounded subsystems. Do not build one free-form agent run, one overloaded lifecycle, or one score that substitutes for evidence, valuation, quant validation, portfolio fit, sizing, or safety.

The authoritative flow is:

```text
M0 agency control plane
  -> M1 source capture and claim proposals
  -> M2 accepted web acquisition and immutable evidence
  -> M3 company intelligence
  -> M4 valuation and investment memo
  -> M5A committee screening and research-priority rank
  -> M6 quant validation
  -> M5B final committee, disagreement closure, and read-only portfolio fit
  -> M7 thesis portfolio and paper-readiness gate
  -> explicit, separately invoked paper queue handoff
  -> existing next-open mock broker fill
  -> M8 monitoring, exits, attribution, postmortem, and learning
  -> M9 read-only Agency Desk projection
```

There are two committee passes. `M5A` prioritizes bounded quant work and cannot emit `MOCK_ELIGIBLE`, `PAPER_READY`, a portfolio weight, or a queue intent. `M5B` consumes a completed quant packet and a fresh read-only portfolio snapshot; only it may emit the research result `MOCK_ELIGIBLE`. The separate M7 gate may then emit `PAPER_READY`. Neither result is an order or fill.

Every transition is fail-closed. Missing, stale, contradictory, unreviewed, unreplayable, over-budget, hash-invalid, provenance-incomplete, or temporally ineligible inputs produce a typed block, park, reject, hold, or request-changes result with an owner and completion-evidence shape. Scores, reviewer prose, model confidence, valuation upside, and diversification cannot override a failed gate.

## 1. Authority, truth labels, and exact source pins

### 1.1 Authority order

When sources disagree, apply this order; do not average them:

1. Current repository safety invariants in `CLAUDE.md`, `market_lab/config.py`, `market_lab/broker.py`, `market_lab/options_paper.py`, and `market_lab/webapp.py`.
2. Independently accepted implementation evidence bound to an exact commit and artifact digest.
3. The independently accepted corrected adversarial audit and its explicit implementation-truth labels.
4. The independently accepted end-to-end architecture R&D artifact.
5. Approved re-reviews and the exact specification versions they reviewed.
6. Earlier reviews and superseded implementation snapshots, retained as historical evidence only.
7. Roadmap prose and unreviewed opinion, which may propose direction but cannot relax a higher-order gate.

A later acceptance supersedes an earlier rejection only for the exact reviewed artifact or commit and only inside the accepted scope. It does not rewrite historical truth.

### 1.2 Current implementation truth

| Capability | Truth label | Binding evidence |
|---|---|---|
| Existing source capture, MLAB ingest, event-correct backtests, mock broker, evidence/diagnosis streams, and safety gates | `IMPLEMENTED_CURRENT` | Shared branch `feat/t_c8f5dd37-web-evidence` at `bee4310e515da9aa208bcc6a3c0421a9ee1af3f5` plus current repository tests |
| Web evidence correction | `IMPLEMENTED_AND_INDEPENDENTLY_ACCEPTED_EXACT_COMMIT_ONLY` | Commit `e21fbe104ce8a4c3a2b16b4202cecc7548ea1b09`; acceptance digest `5802d7d66dc97557093b72975fdf8c07ec72f3f25758a0d717e3fbb35f6e6ac3` |
| Web evidence on the shared branch | `NOT_YET_INTEGRATED_TO_ACCEPTED_HEAD` | Shared head is `bee4310...`; accepted head descends it through `bbbdf20...`, `9a92973...`, and `e21fbe1...` |
| Company intelligence | `APPROVED_SPECIFICATION_ONLY` | Company spec plus APPROVE re-review |
| Valuation and memo | `APPROVED_SPECIFICATION_ONLY` | Valuation spec plus APPROVE re-review; fixture-first Slice A only until its own gates pass |
| Committee and ranking | `APPROVED_SPECIFICATION_ONLY` | Committee spec plus APPROVE review |
| Quant tearsheet and agency-wide no-lookahead enforcement | `SPECIFIED_ONLY_FUTURE_GATE` | Accepted architecture; current backtest primitives are not an accepted agency quant subsystem |
| Thesis portfolio, queue sidecar, monitoring, attribution, postmortems, and learning | `APPROVED_SPECIFICATION_ONLY` | Thesis spec plus APPROVE re-review |
| Cross-module typed IDs/events/control plane and Agency Desk | `SPECIFIED_ONLY_FUTURE_GATE` | Accepted architecture |

The accepted web slice proves its own acquisition, immutable snapshots, audit/replay, frozen/chaos, zero-result route, idempotency, and protected-state controls. It does not prove future company, valuation, committee, quant, thesis, or cross-module controls.

### 1.3 Consumed-artifact manifest

Planning consumes these exact bytes. Any drift returns the plan to `REQUEST_CHANGES` until reconciled and independently reviewed.

| Artifact | SHA-256 | Bytes | Lines | Disposition |
|---|---|---:|---:|---|
| `research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md` | `de0fd675f3c1af1b9b0e558f2b2876439a4bd72cd4ed45eeb911035d7fa55ad4` | 32,804 | 636 | roadmap; research/paper only |
| `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md` | `c6f7d88677a77b897cc8b7ee604e9c52f0dc063ecdb609f76c1c02cdff6f8527` | 76,759 | 1,663 | approved specification only |
| `research/AGENCY_COMPANY_INTELLIGENCE_SPEC_REVIEW.md` | `2e766718a67f9a71ec83352629cddbeb0ddaec3ba3e45ec519786becaa1b4ab2` | 11,734 | 187 | historical REQUEST_CHANGES |
| `research/AGENCY_COMPANY_INTELLIGENCE_SPEC_REREVIEW.md` | `aaf3e8daf2256f76ed5ad5af8f6b9e428422b58cb927cc4d89fe57ac89d32485` | 10,324 | 150 | APPROVE specification |
| `research/AGENCY_VALUATION_MEMO_SPEC.md` | `bb347b2aa0071dadba1955bddf35735cb05e5fb5f2e1a08ed07f69ac93f421f7` | 80,127 | 1,667 | approved specification only |
| `research/AGENCY_VALUATION_MEMO_SPEC_REVIEW.md` | `576caa6eb9de513b7b0847b65ffa86213a46e7a4742f02469d8f64d972b8411b` | 15,549 | 216 | historical REQUEST_CHANGES |
| `research/AGENCY_VALUATION_MEMO_SPEC_REREVIEW.md` | `652758a63b50e15ba34c41dba54e470937e50fb98591e3333f1ed5852826b77c` | 9,050 | 82 | APPROVE Slice A planning |
| `research/AGENCY_INVESTMENT_COMMITTEE_SPEC.md` | `4602e44a9551eeae5a76eeffbe4d06aab39ac01714cf93623d85ca7e13ae6741` | 66,871 | 1,093 | approved research/mock MVP spec |
| `research/AGENCY_INVESTMENT_COMMITTEE_SPEC_REVIEW.md` | `c14e8d858c3224f57e703ffa55a059679dee3753a0d8b9f44558d42e1f01f0a9` | 7,488 | 64 | APPROVE |
| `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC.md` | `17083c752184466686fb9a8ec0acd1e1fcd1561ec30bcda9029a57c45f52708a` | 77,891 | 1,882 | approved fixture/contracts-first spec |
| `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC_REVIEW.md` | `dfd4c73b0fac67f0d0ca5af0511159a7cb95f63b540d0bb6cef87aa29f7918d2` | 18,956 | 224 | historical REQUEST_CHANGES |
| `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC_REREVIEW.md` | `d98a951cb3953813d0f18c750550de73a37d7428a8b640b0aec3ffea652eda75` | 11,514 | 96 | APPROVE fixture-first planning |
| `/Users/ozlabs/OzLabs/docs/market-lab/WEB_EVIDENCE_IMPLEMENTATION_SPEC.md` | `dab0d7d8687007755561e5590a68215935cd5e3a43e3739229363cd388035c7c` | 42,731 | 904 | accepted design contract |
| `/Users/ozlabs/OzLabs/docs/market-lab/WEB_EVIDENCE_REVIEW.md` | `91cfba3f56137cc333e198fa51b905fd686c2fde219a60e9db77c148f78e68d6` | 13,987 | 208 | historical rejection of `bee4310...` |
| `/Users/ozlabs/OzLabs/docs/market-lab/WEB_EVIDENCE_ACCEPTANCE.md` | `5802d7d66dc97557093b72975fdf8c07ec72f3f25758a0d717e3fbb35f6e6ac3` | 7,366 | 98 | PASS for exact `e21fbe1...` |
| `/Users/ozlabs/OzLabs/docs/market-lab/rd-swarm/END_TO_END_AGENCY_ARCHITECTURE_RND.md` | `bfdf0f27c23f334b6a9f18ec0719abbc9a646d562f424bb01ea71f22d24ce92e` | 58,672 | 1,242 | independent PASS |
| `/Users/ozlabs/OzLabs/docs/market-lab/rd-swarm/ADVERSARIAL_PROGRAM_AUDIT.md` | `c3ddd1a833351472afc5807d0fae7fef56bbde85d5e8df03aaa7b37b7b9c83b8` | 43,445 | 519 | corrected audit; independent PASS from `t_fbc1ed19` |

The 12 Market Lab roadmap/spec/review files above are currently untracked on the shared feature branch. Exact hashes make them permissible planning inputs, not durable implementation authority. Slice 0 cannot merge until they and this plan are committed together, or Ronak records an explicit immutable-source waiver with equivalent detached hashes and review.

## 2. Non-negotiable invariants

1. Market Lab remains a virtual research and paper-trading lab, not a live trading system.
2. Search hits, snippets, titles, provider answers, generated summaries, model output, analyst prose, and `context` evidence are never proof.
3. Every material assertion resolves to an immutable source or deterministic calculation, exact locator, typed claim edge, origin lineage, time fields, and verifier version.
4. `MIXED` preserves support and refutation. No averaging, score, or majority vote erases contradictions.
5. Missing is not zero, neutral, false, stale-but-usable, or optimistic default.
6. Historical decisions use only the vintage available at the immutable cutoff. Later filings, prices, outcomes, calibrations, and postmortems cannot leak backward.
7. Models may propose queries, mappings, assumptions, interpretations, and prose. Deterministic code owns schemas, arithmetic, IDs, transitions, budgets, dedupe, gates, ranking replay, sizing, and safety.
8. Review approval is digest-bound, independent from the builder, and specific to the reviewed implementation or artifact.
9. Every transition is append-only, replayable, idempotent, actor-attributed, and tied to exact input/output hashes.
10. Every block has a typed reason, owner, resolution action, due event, and expected completion evidence.
11. `READY`, `APPROVED_RESEARCH`, `ADVANCE_TO_QUANT`, `QUANT_PASS`, `MOCK_ELIGIBLE`, `PAPER_READY`, `QUEUED`, and `OPEN` are distinct states. None implies the next.
12. The only planned execution-state mutation is a separate explicit paper queue command after every gate passes. No research, build, validate, rank, monitor, render, or replay command may mutate protected state.
13. The existing `OrderCandidate` shape remains unchanged. Full lineage lives in a mandatory one-to-one sidecar and staged queue intent.
14. Live trading, live options, margin, shorting, naked options, autonomous orders, broker credentials, and model-to-order paths remain absent and non-overridable.
15. A passing ordinary test suite is necessary but insufficient; non-empty frozen, chaos, replay, temporal, provenance, review-independence, and protected-state gates also control promotion.

## 3. Module boundaries and proposed code layout

The project packages one flat `market_lab` package. Keep the implementation flat and standard-library-first unless an accepted slice explicitly requires an existing dependency.

### 3.1 Shared control plane and contracts: M0

Proposed files:

```text
market_lab/agency_contracts.py        # TypedID, ArtifactRef, GateResult, NextAction, ReviewEnvelope
market_lab/agency_events.py           # AgencyEvent projection, canonical JSON, hash/replay rules
market_lab/agency_store.py            # atomic writes, locked JSONL, manifests, recovery
market_lab/agency_case.py             # AgencyCaseManifest and top-level status projection
market_lab/agency_policy.py           # versioned budgets, compatibility matrix, safety policy
market_lab/agency_cli.py              # create/verify/replay/status; no queue mutation
scripts/market_lab_agency.py
```

M0 owns case pointers, global budgets, compatibility checks, top-level audit projection, blockers/next actions, and read-only status. It must not fetch, adjudicate claims, value companies, score candidates, run backtests, size positions, create candidates, or write execution state.

### 3.2 M1 and M2: existing source and accepted web evidence

M1 remains in `source_thesis.py`, `mlab_ingest.py`, and their CLIs. Its outputs are proposals and immutable source capture, not verified security candidates.

M2 remains the bounded accepted web stack:

```text
market_lab/web_evidence.py
market_lab/web_evidence_providers.py
market_lab/web_evidence_store.py
market_lab/web_evidence_runner.py
market_lab/web_evidence_cli.py
scripts/market_lab_web_evidence.py
```

M2 owns query plans, provider calls, discovery-only rows, immutable snapshots, extraction, exact segments, origin/dedupe metadata, budgets, audit-v2, and accepted run verification. Downstream modules consume M2 artifacts and may issue typed acquisition requests; they perform no raw network I/O and do not create another evidence store.

### 3.3 M3: company intelligence

```text
market_lab/company_intelligence.py
market_lab/company_identity.py
market_lab/company_exposure.py
market_lab/company_documents.py
market_lab/company_intelligence_store.py
market_lab/company_intelligence_runner.py
market_lab/company_intelligence_cli.py
scripts/market_lab_company_intelligence.py
```

M3 owns theme/value-chain mapping, issuer/security identity, exposure materiality, business quality, moat/competition, document/transcript/catalyst normalization, deterministic G0-G9 draft gates, digest-bound G10 publication, and immutable company packets. It consumes accepted evidence and exports only final `READY`, `PARK_RESEARCH`, or `REJECT_MAPPING` publication envelopes. It does not value, rank, size, or queue.

### 3.4 M4: valuation and investment memo

```text
market_lab/valuation_contracts.py
market_lab/valuation_inputs.py
market_lab/valuation_methods.py
market_lab/investment_memo.py
market_lab/valuation_store.py
market_lab/valuation_runner.py
market_lab/valuation_cli.py
scripts/market_lab_valuation.py
```

M4 owns sourced financial/market facts, capital structure, peer eligibility, comparable distributions, FCFF DCF, one-variable reverse DCF, bull/base/bear scenarios, catalysts, invalidations, uncertainty, method disagreement, canonical `memo.json`, pure `memo.md`, review, and manifest. It consumes final M3 `READY` packets and accepted evidence. It must not emit one authoritative target, turn upside into conviction, size, rank globally, or mutate execution state.

### 3.5 M5A and M5B: one committee engine, two typed passes

```text
market_lab/committee_contracts.py
market_lab/committee_evidence.py
market_lab/committee_scoring.py
market_lab/committee_calibration.py
market_lab/committee_disagreement.py
market_lab/committee_portfolio_fit.py
market_lab/committee_store.py
market_lab/committee_runner.py
market_lab/committee_cli.py
scripts/market_lab_committee.py
```

Use `committee_pass: SCREEN | FINAL` and distinct typed run IDs. Shared validation/scoring code is allowed; pass contracts and permitted outputs are not interchangeable.

- M5A `SCREEN` consumes final company, approved memo or reviewed `NO_VALUATION`, non-quant sealed roles, policy/calibration available at cutoff, and a compatible cohort. It outputs `ADVANCE_TO_QUANT`, `PARK_RESEARCH`, or `REJECT`, plus a bounded `QuantRequest`.
- M5B `FINAL` consumes the exact screening packet, completed quant packet, refreshed sealed quant/portfolio roles, current policy/calibration, and a fresh read-only portfolio snapshot. It outputs `MOCK_ELIGIBLE`, `WATCHLIST`, `PARK_RESEARCH`, `PORTFOLIO_HOLD`, `HUMAN_REVIEW`, or `REJECT`.

The committee cannot queue, fill, or describe correlated same-model reports as independent votes.

### 3.6 M6: quant validation

```text
market_lab/quant_contracts.py
market_lab/quant_tearsheet.py
market_lab/quant_runner.py
market_lab/quant_store.py
market_lab/quant_cli.py
scripts/market_lab_quant.py
```

M6 wraps existing pure backtest/optimization/data primitives without changing their event timing. It owns the immutable quant request/tearsheet, next-bar fill checks, benchmark alignment, train/OOS or walk-forward splits, cost stress, turnover/exposure/drawdown, robustness neighborhood, sample-power warnings, data-source integrity, kill rules, and verdict:

```text
QUANT_PASS | QUANT_INCONCLUSIVE | QUANT_FAIL | QUANT_BLOCKED
```

`QUANT_INCONCLUSIVE` is missingness and cannot promote. Synthetic or cache-synthetic validation, same-bar fills, post-cutoff observations, an invalid benchmark, or leakage fail closed.

### 3.7 M7 and M8: thesis portfolio, paper handoff, and learning

```text
market_lab/thesis_portfolio_contracts.py
market_lab/thesis_portfolio_policy.py
market_lab/thesis_portfolio_store.py
market_lab/thesis_portfolio_committee.py
market_lab/thesis_position_queue.py
market_lab/thesis_monitoring.py
market_lab/thesis_attribution.py
market_lab/thesis_scorecards.py
market_lab/thesis_postmortem.py
market_lab/thesis_portfolio_cli.py
scripts/market_lab_thesis_portfolio.py
```

M7 owns memo-to-position linkage, its independent paper-readiness request, deterministic sizing, zero-size blockers, monitoring and exit plans, gate report, staged queue intent, unchanged `OrderCandidate`, mandatory sidecar, and exactly-once reconciliation.

M8 owns candidate/sidecar/ledger lineage, monitoring snapshots, deterministic catalyst/invalidation/benchmark/time/drawdown triggers, next-open reduction/exit proposals, attribution, scorecards, postmortems, feedback events, and one-use scoped learning overrides. It never fabricates a SELL quantity without ledger proof and never mutates a position directly.

### 3.8 M9: Agency Desk

```text
market_lab/agency_desk.py
```

M9 is a read-only projection of manifests and events. It performs no network access, directory creation, gate advancement, queueing, or state mutation. Rebuild from immutable inputs must reproduce the same semantic projection.

## 4. Canonical cross-module contracts

### 4.1 Canonical JSON

Cross-module canonical bytes use:

- UTF-8 and Unicode NFC strings;
- sorted object keys and no insignificant whitespace;
- explicit null/default semantics;
- UTC RFC 3339 timestamps;
- normalized decimal strings for persisted economic values;
- no binary floats, NaN, infinity, duplicate keys, `-0`, or implicit `str()` conversion;
- deduplicated set-like collections sorted by full typed ID/hash;
- semantic sequences preserving order with contiguous `sequence_index`;
- full SHA-256 digests persisted; short prefixes are display-only.

Subsystems retain their accepted local canonicalization and IDs. Cross-module adapters validate local IDs and wrap them; they do not rewrite accepted local artifacts.

### 4.2 `TypedID`

```text
TypedID (mlab-typed-id.v1)
  kind
  domain
  id_schema_version
  digest_sha256            # full lowercase 64-character SHA-256
  local_id                 # exact validated subsystem ID
```

The digest is domain-separated over a canonical typed payload. Cross-module equality uses `(domain, id_schema_version, digest_sha256)`, never ticker, display name, truncated hash, or untyped local string.

Issuer, security, candidate, memo, committee screen, committee final, quant request, quant tearsheet, thesis position, sizing decision, queue intent, paper candidate link, ledger decision, monitoring snapshot, postmortem, feedback, and event IDs remain distinct kinds.

### 4.3 `ArtifactRef`

```text
ArtifactRef (mlab-artifact-ref.v1)
  artifact_id: TypedID
  schema_version
  semantic_sha256
  byte_sha256
  locator
  producer_version
  source_commit nullable
  external_manifest_digest nullable
  created_at_utc
  analysis_cutoff_utc nullable
  source_available_at_utc nullable
  system_available_at_utc
  supersedes_artifact_id nullable
  review_ref nullable
```

A ref points; it never copies a claim into a new provenance root.

### 4.4 `GateResult`, `NextAction`, and `ReviewEnvelope`

```text
GateResult (mlab-gate-result.v1)
  gate_id / group
  status: PASS | WARN | FAIL | BLOCKED | NOT_APPLICABLE
  reason_codes[]
  claim_refs[] / evidence_refs[] / artifact_refs[]
  checked_at_utc
  policy_hash
  override_allowed
  override_use_ref nullable
  next_action_ref nullable

NextAction (mlab-next-action.v1)
  next_action_id: TypedID
  owner
  action_type
  reason_codes[]
  dependency_refs[]
  due_event_or_time
  completion_evidence_schema
  retry_budget_remaining
  terminal_if_unavailable

ReviewEnvelope (mlab-review-envelope.v1)
  review_id: TypedID
  reviewed_artifact_refs[]
  reviewed_manifest_hash
  builder_actor_id
  reviewer_actor_id
  reviewer_profile / reviewer_session / model_family
  decision: APPROVE | REQUEST_CHANGES | REJECT
  checks[] / findings[]
  created_at_utc
  content_hash_sha256
  signature_scheme nullable
  signer_key_id nullable
  signature nullable
```

Builder and reviewer must differ. Digest mismatch or unknown review scope invalidates approval. Cryptographic signatures are mandatory for committee analyst reports under the committee policy; detached signatures for general independent reviews are optional until a key registry is approved, but digest binding and identity separation are mandatory.

### 4.5 `AgencyCaseManifest`

```text
AgencyCaseManifest (mlab-agency-case.v1)
  agency_case_id: TypedID
  supersedes_agency_case_id nullable
  created_at_utc / analysis_cutoff_utc
  mode: offline_inspection | frozen_replay | live_research
  safety_mode: research_mock_only
  source_run_refs[] / web_evidence_run_ref
  company_run_refs[] / valuation_run_refs[]
  committee_screen_run_ref / quant_validation_refs[]
  committee_final_run_ref / thesis_portfolio_run_ref
  paper_candidate_link_ref
  monitoring_run_refs[] / attribution_refs[] / postmortem_refs[]
  feedback_event_refs[] / policy_snapshot_refs[]
  calibration_snapshot_ref / portfolio_snapshot_ref
  input_artifact_hashes[]
  audit_head_hash / status_projection_hash
  blockers[] / next_actions[]
```

### 4.6 Cross-module bridge schemas

`AgencyCandidateEnvelope (mlab-agency-candidate.v1)` resolves the committee spec's missing typed memo/company references without changing local candidate IDs:

```text
agency_candidate_id: TypedID
local_candidate_id: TypedID
company_publication_ref
company_packet_ref
valuation_ref nullable
memo_ref
memo_outcome: APPROVED_RESEARCH | NO_VALUATION
source_claim_refs[] / evidence_refs[]
security_ref / benchmark_refs[]
analysis_cutoff_utc / horizon_days / horizon_bucket
mechanism_hash / falsifier_refs[]
input_artifact_hashes[]
```

`CommitteeScreenPacket (mlab-committee-screen.v1)` stores compatible cohort, sealed screening reports, lower-bound research-priority result, dissent, missing information, and exactly one of `ADVANCE_TO_QUANT | PARK_RESEARCH | REJECT`.

`QuantRequest (mlab-quant-request.v1)` stores candidate, benchmark, cutoff, horizon, strategy/family, data policy, train/OOS plan, costs, robustness neighborhood, power threshold, resource budget, and predeclared kill rule.

`QuantTearsheet (mlab-quant-tearsheet.v1)` stores request ref, code/data/policy hashes, observation window, source labels, fills, benchmark-relative metrics, OOS/walk-forward results, cost stresses, turnover/exposure/drawdown, robustness, power flags, reason codes, and quant verdict.

`CommitteeFinalPacket (mlab-committee-final.v1)` references the exact screen and quant packets, refreshed sealed roles, disagreement closure, deterministic rank replay, read-only portfolio fit, independent review, and one final research outcome.

The M7 sidecar remains `mlab-paper-candidate-link.v1`; the staged intent remains `mlab-queue-intent.v1`. No upstream ID is encoded only in free-text `reason`.

## 5. Event, audit, time, and recovery model

### 5.1 `AgencyEvent`

```text
AgencyEvent (mlab-agency-event.v1)
  event_id: TypedID
  agency_case_id: TypedID
  subsystem / subsystem_run_id
  sequence_number / idempotency_key / event_type
  occurred_at_utc
  source_available_at_utc nullable
  system_available_at_utc
  effective_at_utc nullable
  observed_at_utc nullable
  actor_type / actor_id / mode
  state_namespace / state_before / state_after
  input_refs[] / input_hashes[]
  output_refs[] / output_hashes[]
  policy_hash
  budget_reservation_id nullable
  budget_before / budget_charge / budget_after nullable
  reason_codes[] / redactions[]
  previous_event_hash / event_hash
```

Subsystem logs may retain richer accepted schemas, but every cross-module transition projects into this envelope.

Minimum cross-module events are:

```text
case.created inputs.pinned source.captured claim.proposed
query.planned provider.called snapshot.committed segment.verified
evidence.linked evidence.rejected contradiction.opened contradiction.closed
budget.reserved budget.charged budget.exhausted
company.draft_validated company.published
valuation.method_completed valuation.blocked memo.reviewed
committee.screened quant.requested quant.completed committee.finalized
paper.gated queue.intent_committed queue.candidate_committed queue.reconciled
paper.fill_reconciled monitor.observed invalidation.triggered exit.proposed
attribution.completed postmortem.reviewed feedback.accepted override.used
next_action.created run.blocked run.request_changes run.finalized
run.superseded recovery.performed
```

### 5.2 Audit and commit rules

1. Validate schema and semantics in memory.
2. Serialize canonical bytes.
3. Write a same-filesystem temporary file, flush, and `fsync`.
4. Atomically rename, then `fsync` the parent directory where supported.
5. Re-read and verify bytes/hash.
6. Append exactly one complete canonical event under the run lock, flush, and `fsync`.
7. Commit the final manifest last.
8. `status.json` is an atomically replaced projection, never the source of truth.
9. Same idempotency key plus same input hashes returns the prior result; changed hashes block as an integrity conflict.
10. A mixed legacy/v2 ledger is valid only with a verified anchor to prior bytes.

### 5.3 Time eligibility and no-lookahead

Material facts declare applicable publication, filing, effective, validity, source-availability, retrieval, system-availability, observation, supersession, and analysis-cutoff times.

Live research eligibility is:

```text
max(source_available_at_utc, system_available_at_utc, observed_at_utc when applicable)
  <= analysis_cutoff_utc
```

Frozen replay requires source availability before the cutoff, a catalog proving the exact vintage/hash, and zero network calls. A retrospective fixture is labeled retrospective; it can test point-in-time logic but cannot be represented as contemporaneously available to Market Lab.

Close `t` decisions fill no earlier than open `t+1`. Quant train/OOS and calibration train/evaluation windows are disjoint. Later outcomes, postmortems, amendments, factors, portfolio state, share counts, and prices never rewrite or enter earlier decisions without point-in-time artifacts.

### 5.4 Recovery

Resume verifies policy/manifests, artifacts, locators, audit chain, budgets, and completed idempotency keys; quarantines only a final partial JSONL line; rejects earlier corruption; retries only typed retryable failures; and never infers success from an output file without its event and manifest.

Corrections create new immutable versions with `supersedes_*` links. Finalized source, evidence, memo, committee, fill, monitoring, attribution, and postmortem artifacts are not rewritten.

Queue recovery is stricter:

- before intent: remain `NOT_QUEUED`;
- after intent before queue replacement: retry the same idempotency key;
- after queue replacement before sidecar/manifest: reconcile exact broker hash to staged intent and create one matching sidecar or mark `UNRECONCILED`;
- sidecar without candidate: fail closed;
- same broker hash with different active lineage: conflict block;
- command-level `EXECUTED` does not prove a fill; only ledger reconciliation changes paper-position state.

## 6. State namespaces and transitions

### 6.1 Top-level projection

```text
CREATED -> INPUTS_PINNED -> SOURCE_CAPTURED -> EVIDENCE_PENDING
-> EVIDENCE_ACCEPTED -> COMPANY_PUBLISHED -> MEMO_REVIEWED
-> COMMITTEE_SCREENED -> QUANT_VALIDATED -> COMMITTEE_FINALIZED
-> PAPER_GATED -> PAPER_TRACKING -> MONITORING -> POSITION_CLOSED
-> POSTMORTEM_APPROVED -> LEARNING_RECORDED -> FINALIZED
```

At every non-final stage the projection may become `BLOCKED`, `PARKED`, `REQUEST_CHANGES`, `REJECTED`, `ABORTED`, or `SUPERSEDED`. These are projections over subsystem states, not replacements for them.

### 6.2 Subsystem state separation

Do not alias MLAB ingest stage, web status, company validation/publication, valuation status, committee pass/stage/verdict/outcome, quant verdict, thesis status, queue status, paper position, monitoring, postmortem, or archive.

Valuation:

```text
NOT_STARTED -> INPUT_BLOCKED | INPUTS_VALIDATED
INPUTS_VALIDATED -> CALCULATED | INPUT_BLOCKED
CALCULATED -> REVIEW_REQUIRED
REVIEW_REQUIRED -> APPROVED_RESEARCH | REJECTED | INPUT_BLOCKED
APPROVED_RESEARCH | REJECTED -> SUPERSEDED
```

Committee pass lifecycle:

```text
CREATED -> INPUTS_VALIDATED -> REVIEWS_SEALED -> EVIDENCE_AUDITED
-> SCORED -> DISAGREEMENTS_CLOSED | BLOCKED_DISAGREEMENT
-> PORTFOLIO_CHECKED -> FINAL_REVIEWED -> FINALIZED
```

M5A uses the same deterministic engine but omits portfolio fit and cannot emit final committee outcomes; its terminal successful stage is `SCREEN_FINALIZED`. M5B begins only from an immutable M5A screen plus quant packet and uses the complete lifecycle.

Thesis namespaces remain:

```text
thesis_position_status:
  DRAFT | INPUT_BLOCKED | GATED | PAPER_READY | PAPER_BLOCKED |
  REJECTED | WATCH_ONLY | SUPERSEDED
queue_status:
  NOT_QUEUED | QUEUED | SKIPPED_BLOCKED | EXECUTED | EXPIRED |
  CANCELLED | SUPERSEDED
paper_position_status:
  NO_POSITION | OPEN | REDUCED | CLOSED | UNRECONCILED
monitoring_status:
  NOT_STARTED | ACTIVE | MONITOR_BLOCKED | FORCE_REVIEW |
  THESIS_BROKEN | EXIT_PENDING | CLOSED
postmortem_status:
  NOT_DUE | DUE | DRAFT | REVIEW_REQUIRED | APPROVED | REJECTED
archive_status:
  ACTIVE | ARCHIVED | SUPERSEDED
```

Only `PAPER_READY` may transition a link from `NOT_QUEUED` to `QUEUED`. `QUEUED` or `EXECUTED` does not imply `OPEN`. Ledger proof controls paper-position state. `CLOSED` forces postmortem `DUE`; archive requires an approved postmortem. No namespace contains a live-trading state.

## 7. Versioned budgets and stop conditions

### 7.1 Runtime budget profile `mlab-agency-budget.v1`

| Scope | Limit |
|---|---:|
| Cases per agency run | 1 |
| Material claims | 12 |
| Company candidates | 10 |
| Committee cohort candidates | 10 |
| Quant requests | 3 |
| Paper candidates per explicit queue command | 1 |
| Global wall time | 1,800 seconds |
| Revision attempts per stage | 2 |
| Paid provider cost in offline/frozen/keyless modes | USD 0.00 |

M2 `keyless_standard` retains: 48 search/domain calls, 72 fetch attempts, 48 successful snapshots, 8 results/search, 3 discovery rounds, 2 retries/call, 300 seconds, 20 MiB/artifact, 100 MiB/run, two marginal-yield rounds, and one-new-origin threshold.

M3 defaults: one theme, 50 value-chain nodes, 100 edges, 25 issuer leads, 10 published READY packets, 300 seconds, zero raw network calls.

M4 defaults: one candidate in MVP, five forecast years, exactly bear/base/bull, 3-10 eligible peers, one reverse-DCF variable, 300 seconds, zero raw network calls.

Committee defaults: 10 cohort candidates, seven roles, at most two report versions/role, one blind tie-break/disagreement, skeptic budget at least the strongest advocate budget, 25 active monitoring triggers, 600 seconds. Same-model/provider lineage is disclosed and correlation-down-weighted.

M6 defaults: three requests/case, 100 parameter combinations/request, cost stresses at 5/10/25 bps or stricter policy equivalents, 10 walk-forward folds, 600 seconds.

### 7.2 Delivery-process budget

Each implementation slice gets one maker branch, one independent semantic reviewer, and at most two correction rounds before `BLOCKED`/human decision. Use these initial hard-build budgets unless the coordinator records a narrower per-card budget:

| Delivery resource | Limit per slice |
|---|---:|
| Maker elapsed time per attempt | 100 minutes |
| Independent review elapsed time per attempt | 60 minutes |
| Concurrent worker lanes | 3 |
| Total worker/subagent calls | 6 |
| Correction rounds after first review | 2 |
| Primary model runs per maker or reviewer role | 1 per attempt |
| Paid retrieval/model-provider spend in frozen acceptance | USD 0.00 |

Model/provider/version and inference settings must be recorded in the handoff. A reroute or fallback is a new disclosed attempt, not invisible extra consensus. A slice may use parallel research or fixture lanes, but only one integration owner writes the final branch and review starts only after the maker freezes an exact digest. No budget permits weaker evidence, skipped tests, self-approval, or silent scope reduction.

### 7.3 Deterministic stop conditions

A stage stops only when its gate passes; a typed block/park/reject is reached; required counter/freshness/disagreement work is disposed; marginal unique-origin yield stops under policy; budget exhausts with a resumable next action; safety/access policy blocks; or revision cap is reached and escalated. Prose quality, majority vote, model confidence, or “done” is not a stop condition.

## 8. Promotion gates

| Gate | Required evidence | Pass promotes to | Failure |
|---|---|---|---|
| A0 Source integrity | Raw artifact, exact citation, author/account when available, capture time, media disposition, claim proposal, no inferred security | source captured | `BLOCKED_SOURCE_PROVENANCE` |
| A1 Web evidence | Accepted exact implementation/fixture policy; snapshots, segments, temporal fit, origin dedupe, counter/freshness lanes, budgets, replay, independent review | `EVIDENCE_ACCEPTED` | `BLOCKED_UPSTREAM_EVIDENCE` |
| A2 Company | Bounded mechanism, value-chain path, identity, exposure bound, competition/moat counterevidence, catalysts, replay, digest-bound review | `COMPANY_PUBLISHED` | `PARK_RESEARCH` or `REJECT_MAPPING` |
| A3 Valuation/memo | Cutoff-correct facts, compatible units/periods/scope, capital structure, eligible methods, coherent scenarios, visible uncertainty/disagreement, measurable catalysts/invalidations, JSON/Markdown fidelity, review | `MEMO_REVIEWED` | `BLOCKED`, `NO_VALUATION`, or `REVIEW_REQUIRED` |
| A4 Committee screen | Compatible cohort, sealed roles, eligible evidence, preserved dissent, no unresolved critical claim, deterministic lower-bound priority | `COMMITTEE_SCREENED` and bounded quant request | `PARK_RESEARCH` or `REJECT` |
| A5 Quant | next-open timing, data quality, benchmark, train/OOS, power, costs, robustness, drawdown/exposure/turnover, kill rule | `QUANT_VALIDATED` only on `QUANT_PASS` | `QUANT_FAIL`, `QUANT_INCONCLUSIVE`, or `QUANT_BLOCKED` |
| A6 Final committee | exact screen/quant refs, refreshed roles, cutoff-valid calibration, disagreement closure, cohort rank replay, fresh read-only portfolio, final review, protected-state proof | `COMMITTEE_FINALIZED` | `PARK_RESEARCH`, `PORTFOLIO_HOLD`, `HUMAN_REVIEW`, or `REJECT` |
| A7 Thesis paper readiness | immutable approved upstream refs, quant pass, deterministic size, trusted liquidity, bounded catalyst, invalidation/exit plans, caps, paper-only flags, replay | `PAPER_GATED` on `PAPER_READY` | zero size plus `PAPER_BLOCKED`, `WATCH_ONLY`, or `REJECTED` |
| A8 Queue handoff | current data policy, close signal date, next-open, staged intent, one unchanged candidate, one sidecar, lock/temp/fsync, dedupe/supersession, before/after hashes | queue lineage awaiting later-open ledger proof | `SKIPPED_BLOCKED`, `CANCELLED`, `EXPIRED`, or `UNRECONCILED` |
| A9 Monitoring/learning | fresh monitor inputs, immutable snapshots, ledger quantities, next-open exits, attribution flags, postmortem, feedback/override review | monitoring/closed/postmortem/learning states | typed monitor/ledger block; never fabricated SELL or closure |
| A10 Final integrity | all hashes, locators, events, reviews, replays, blockers, next actions, durability, protected state, reproducible Desk | `FINALIZED` | no ship |

## 9. Implementation slices and dependencies

Each slice is test-first and fixture-first. “Exit” means maker evidence plus independent approval of the exact branch/digest; maker success alone does not promote.

### Slice 0 — Canonical foundation and accepted web integration

Branch: `feat/agency-s0-foundation` from accepted web head `e21fbe104ce8a4c3a2b16b4202cecc7548ea1b09`.

Deliver:

- commit the exact hash-pinned roadmap, four specs, reviews/re-reviews, and this plan, or record Ronak's detached immutable-source waiver;
- add M0 contracts, canonical JSON, typed ID adapter, artifact/review/gate/next-action envelopes, agency event projection, policy compatibility matrix, protected-state resolver, and frozen/chaos fixture catalogs;
- preserve accepted web code and tests byte-for-byte except independently reviewed integration fixes;
- no company logic, no committee scoring, no queue code.

Objective tests:

- typed-ID domain separation, local-ID validation, dictionary/set ordering, semantic-sequence ordering, duplicate key/non-finite rejection;
- event hash chain, mixed-ledger anchor, contiguous sequence, idempotency conflict, partial-line recovery, status replay;
- exact source-manifest drift blocks;
- alternate `MARKET_LAB_DATA_DIR` protected-state resolver is non-empty and byte-identical before/after;
- accepted web focused 70, frozen 2/2, chaos 8/8, full suite, and adversarial zero-result route probes remain green;
- zero network in foundation tests and no execution-state mutation.

Exit: independently reviewed foundation schemas and exact source durability; accepted web commit remains the integrated ancestor.

### Slice 1 — Company and industry intelligence

Branch: `feat/agency-s1-company` from accepted Slice 0 integration head. Depends on A1 and Slice 0.

Deliver the M3 modules and scripts listed in section 3.3; 36+ frozen `OzCompanyIntelBench-v1` cases; theme/value-chain, issuer/security identity, exposure, document/transcript/catalyst, packet, store/replay, review/publication, CLI, and safety tests.

Implement in substeps:

1. schemas, enums, policy, fixture review, and failing contract/temporal/safety tests;
2. theme/value-chain and effective-dated identity;
3. exposure arithmetic/ranges, period/unit/scope/double-count blocks, amendment selection;
4. moat/competition/catalysts and immutable packet;
5. deterministic G0-G9, G10 publication, atomic store, replay, accepted M2 adapter, frozen/chaos/live-shadow commands.

Objective exit:

- 100% selected-security precision and numeric exposure accuracy on deterministic cases;
- every seeded mismatch/double count/critical UNKNOWN blocks;
- at least three realistic leads in the canonical frozen source run without changing `SourceThesis.candidate_tickers`;
- exact digest-bound G10 review publishes only unchanged `READY` drafts;
- benchmark hard gates and documented quality thresholds pass;
- live mode uses accepted M2 only and remains opt-in;
- targeted tests and `uv run pytest tests/market_lab -q` pass under isolated data roots;
- protected state unchanged.

### Slice 2 — Valuation and investment memo

Branch: `feat/agency-s2-valuation` from accepted Slice 1 head. Depends on final M3 `READY` fixture packets and accepted M2 refs.

Deliver M4 modules/scripts, 60-case `OzValuationBench-v1`, exact formulas, provenance normalization, scenarios, canonical memo, store/replay/review, CLI, and safety gates.

Substeps:

1. contracts, `Decimal` canonicalization, IDs, formula registry, hand-calculated comparables/DCF/reverse-DCF fixtures;
2. accepted evidence and M3 input normalization, SEC/XBRL period/unit/accession/amendment/availability, capital structure and market cutoff;
3. bear/base/bull assumptions, catalysts, invalidations, method reconciliation, no-false-precision, JSON/Markdown fidelity;
4. atomic store, audit events, resume, gate report, review transition, CLI;
5. frozen/chaos plus at least 20 shadow live valuations after frozen acceptance.

Objective exit:

- all hand calculations reproduce at canonical precision;
- no synthetic, post-cutoff, context-only, missing-locator, stale, split-misaligned, or default-zero input enters a method;
- disjoint methods remain separate and visible; no blended point target;
- `NO_VALUATION` and `BLOCKED` are accepted honest outcomes;
- independent reviewer differs from builder and approves exact digest;
- frozen/chaos/targeted/full suites pass; protected state unchanged.

### Slice 3 — Committee screening, no automated analysts

Branch: `feat/agency-s3-committee-screen` from accepted Slice 2 head. Depends on company and valuation bridge fixtures plus Slice 0 contracts.

Deliver committee contracts/evidence/scoring/calibration/disagreement/store/CLI needed for `committee_pass=SCREEN`; one compatible cohort of three frozen equity candidates; prewritten signed sealed reports for non-quant roles; no agent spawning and no portfolio-fit promotion.

Objective exit:

- candidate bridge validates exact company/memo/evidence refs;
- cohort incompatibility blocks global rank;
- sealed-input allowlist rejects peer reports, aggregate, rank, suggested verdict, and unlisted paths;
- origin/model correlation weights cap duplicate influence;
- hard rejection precedes score; missingness never becomes neutral opinion;
- lower-bound score, uncertainty, coverage, calibration cold start, leave-one-role/origin sensitivity, dissent, and rank replay are deterministic;
- only `ADVANCE_TO_QUANT`, `PARK_RESEARCH`, or `REJECT` can be emitted;
- each advance emits one bounded immutable QuantRequest;
- frozen adversarial, recovery, targeted/full, review, and protected-state gates pass.

### Slice 4 — Quant request and tearsheet

Branch: `feat/agency-s4-quant` from accepted Slice 3 head. Depends on immutable QuantRequest and existing backtest/data primitives.

Deliver M6 modules/scripts and frozen fixtures covering event timing, benchmark alignment, walk-forward/OOS, costs, power, robustness, leakage, synthetic data, and replay.

Objective exit:

- same-bar close fill always fails;
- close `t` to open `t+1` passes;
- benchmark/control histories align by date and cutoff, never future-tail slicing;
- synthetic/cache-synthetic validation fails;
- 5/10/25 bps stress, drawdown, exposure, turnover, parameter neighborhood, and kill rule are present;
- low-power becomes `QUANT_INCONCLUSIVE`, not neutral/pass;
- no-edge after an adequately powered full test becomes `QUANT_FAIL`;
- exact request/data/code/policy hashes replay to the same tearsheet;
- targeted/full/no-side-effect gates and independent lookahead review pass.

### Slice 5 — Final committee and read-only portfolio fit

Branch: `feat/agency-s5-committee-final` from accepted Slice 4 head. Depends on exact M5A screen, `QUANT_PASS`, and fresh read-only snapshots.

Extend the committee engine for `committee_pass=FINAL`, refreshed quant/portfolio roles, disagreement closure, complete outcome ladder, cohort-local ranking, portfolio capacity/stress/replacement tests, final decision packet, and independent review.

Objective exit:

- quant fail/inconclusive/block cannot promote;
- stale/missing portfolio snapshot parks rather than holds;
- weak thesis cannot be rescued by low correlation;
- strong duplicate exposure becomes `FIT_WITH_CAP` or `PORTFOLIO_HOLD` under deterministic policy;
- seeded restatement from one skeptic overrides bullish majority; unsupported skeptic has no false veto;
- score, outcome, rank, portfolio cap, status projection, JSON/Markdown, and audit replay are stable;
- all seven role schemas/signatures, required origin coverage, next actions, and final independent approval verify;
- no execution-state file changes.

### Slice 6 — Thesis portfolio gate without queueing

Branch: `feat/agency-s6-thesis-gate` from accepted Slice 5 head. Depends on `MOCK_ELIGIBLE`, exact quant/committee/memo refs, and Slice 0 protected-state harness.

Deliver M7 contracts, policy, store, paper-readiness committee, sizing, monitoring plan, exit plan, gate report, build/validate/replay CLI, and frozen fixtures. Do not implement or invoke queue mutation in this slice.

Objective exit:

- exact memo -> committee final -> quant -> thesis -> sizing lineage;
- deterministic hand-calculated size with floors/caps and no model-set size;
- missing bounded catalyst or trusted liquidity yields zero and `PAPER_BLOCKED`/`WATCH_ONLY`;
- every ready thesis has catalyst, invalidation, benchmark/control, time/benchmark/drawdown exit, and hard safety exit;
- outputs are exactly `PAPER_READY`, `PAPER_BLOCKED`, `WATCH_ONLY`, or `REJECTED` under total gates;
- build/validate/replay preserve all protected state;
- independent review approves exact fixture and branch digest.

### Slice 7 — Explicit paper queue handoff and fill reconciliation

Branch: `feat/agency-s7-paper-handoff` from accepted Slice 6 head. Depends on `PAPER_READY` and human/operator authorization to test the paper-only mutation boundary.

Deliver `thesis_position_queue.py`, queue intent, unchanged `OrderCandidate` adapter, mandatory sidecar, lock/temp-rewrite/file+directory fsync, dedupe/supersession, crash matrix, expiration, later-open fill reconciliation, and SELL restrictions to ledger-proven reductions/exits.

Objective exit:

- one ready fixture creates exactly one candidate plus one sidecar;
- same fixture is idempotent and cannot fill on the signal close;
- identical broker hash with different lineage blocks;
- crash before intent, after intent, after queue replacement, and before sidecar/manifest all reconcile to exactly one lineage or `UNRECONCILED`, never duplicate;
- `--require-live-data` rejects synthetic/cache/cache-synthetic;
- queue command changes only configured `pending_order_candidates.jsonl`; all other protected paths remain byte-identical;
- no short SELL, live order, broker credential, option, margin, or autonomous execution path exists;
- independent recovery/safety review passes.

### Slice 8 — Monitoring, exits, attribution, postmortem, learning, and Desk

Branch: `feat/agency-s8-learning-desk` from accepted Slice 7 head. Depends on reconciled paper ledger fixtures.

Deliver M8 and M9 modules for immutable monitor snapshots, deterministic next-open exit proposals, ledger-proven partial/full quantities, attribution, postmortems, feedback, scorecards, one-use learning overrides, and read-only Agency Desk projection.

Objective exit:

- monitor input outage becomes `MONITOR_BLOCKED` and preserves prior snapshot;
- accepted invalidation becomes `THESIS_BROKEN` and proposes, but does not directly execute, a next-open exit;
- missing ledger entry/quantity emits `LEDGER_ENTRY_UNPROVEN`/`UNRECONCILED` and no fabricated SELL;
- non-retrospective attribution rejects later-unavailable observations; unmeasurable components remain null with quality flags;
- closed positions force postmortem due and cannot archive before approval;
- policy change requires accepted feedback or valid exact-scope, unexpired, unconsumed override;
- safety, provenance, no-lookahead, protected-state, replay, and live boundaries reject every override attempt;
- Desk rebuild is semantically stable, read-only, and network-free;
- targeted/frozen/chaos/full/protected-state/independent-review gates pass.

## 10. Objective program acceptance matrix

A slice cannot merge on unit tests alone. Its handoff must include exact branch/head, base, changed files, commands, output artifact hashes, protected-state before/after comparison, maker/reviewer identities, truth labels, risks, and next-lane inputs.

Required gates by lane:

| Gate class | S0 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Contract/schema/canonical IDs | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| Non-empty frozen corpus | yes | 36+ | 60 | 3 candidates + adversarial set | required | required | required | required | required |
| Non-empty chaos/recovery | yes | yes | yes | yes | yes | yes | yes | queue crash matrix | yes |
| Zero network frozen replay | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| Temporal/no-lookahead | yes | yes | yes | yes | independent quant review | yes | yes | next-open | yes |
| Provenance/origin/contradiction | yes | yes | yes | yes | data refs | yes | upstream refs | lineage | attribution refs |
| Independent semantic review | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| Protected-state before/after | yes | yes | yes | yes | yes | yes | all unchanged | queue-only mutation | all unchanged except explicit future queue command |
| Full `tests/market_lab` | yes | yes | yes | yes | yes | yes | yes | yes | yes |
| Agent Recorder for non-trivial code lane | required | required | required | required | required | required | required | required | required |

Global fail conditions:

- missing/empty fixture corpus reported as pass;
- ordinary suite green while a required semantic gate is absent;
- changed uncommitted/hash-pinned design source;
- builder self-approval or review of a different digest;
- future/post-cutoff or synthetic evidence entering promotion;
- snippets/generated text treated as evidence;
- unresolved critical claim converted to score;
- same-model reports described as independent without disclosed/down-weighted lineage;
- valuation method disagreement hidden or forced to a point target;
- committee screen producing mock eligibility;
- quant inconclusive treated as pass;
- portfolio diversification rescuing a weak thesis;
- missing catalyst/liquidity producing positive size;
- any build/validate/render/rank/monitor/replay command mutating protected state;
- queue command mutating anything except the configured pending paper candidate file;
- same-day fill, shorting, margin, live option, live broker, or autonomous order behavior;
- safety/provenance/no-lookahead/replay override.

## 11. Branch and integration sequence

No branch may be called accepted because its maker says it passed. Each step requires an independent reviewer on the exact head.

1. Preserve current shared branch `feat/t_c8f5dd37-web-evidence` at `bee4310...` until the accepted correction is integrated.
2. Create `feat/agency-s0-foundation` from exact accepted web head `e21fbe1...`. Verify ancestry includes, in order, `bbbdf20...`, `9a92973...`, and `e21fbe1...`; do not cherry-pick only the final commit.
3. Commit the 12 exact hash-pinned agency design files plus this plan in a docs-only commit on S0, or attach Ronak's explicit immutable-source waiver. Recompute the manifest after commit and independently review it.
4. Implement and independently accept S0 contracts/tests. Only then establish an `feat/agency-integration` branch at the accepted S0 head.
5. For each later slice, branch from the latest accepted `feat/agency-integration` head, not from another unreviewed maker branch.
6. Maker commits code/fixtures/tests without merge/push authorization claims. Independent reviewer reruns targeted, frozen, chaos/replay, full, and protected-state gates on the exact head.
7. If review is `REQUEST_CHANGES`, correction stays on the same slice lineage or a clearly superseding branch; fresh review is mandatory. Do not merge maker-only fixes.
8. After PASS, fast-forward or reviewed-merge the exact accepted slice head into `feat/agency-integration`; record base/head/reviewer/artifact hashes.
9. Re-run cross-slice replay, full suite, source-manifest, and protected-state gates after every integration.
10. Do not parallelize dependent implementation. Fixture research may run ahead, but S2 code waits for accepted S1 contracts; S3 waits for S2 bridge; S4 waits for S3 QuantRequest; S5 waits for S4; S6 waits for S5; S7 waits for S6; S8 waits for reconciled S7 fixtures.
11. A PR to `main` is separate from slice acceptance. It requires full integrated acceptance, clean tracked sources, CI, and operator review. This plan performs no commit, merge, push, or PR.

Recommended branch names:

```text
feat/agency-s0-foundation
feat/agency-s1-company
feat/agency-s2-valuation
feat/agency-s3-committee-screen
feat/agency-s4-quant
feat/agency-s5-committee-final
feat/agency-s6-thesis-gate
feat/agency-s7-paper-handoff
feat/agency-s8-learning-desk
feat/agency-integration
```

## 12. Contradictions resolved

| Tension | Binding resolution |
|---|---|
| Roadmap ranks before quant; committee mock eligibility requires quant | Two passes: M5A research-priority screen, M6 quant, M5B final committee. M5A cannot emit paper eligibility. |
| Architecture says web is rejected; later acceptance says PASS | Architecture preserves truth at its snapshot. Exact `e21fbe1...` acceptance supersedes the rejection only for that commit. Shared branch `bee4310...` is not the accepted head. |
| Approved specs are untracked | Exact hashes permit this planning document. Product implementation/merge requires tracked sources or Ronak's explicit immutable-source waiver. |
| Local ID and canonical JSON rules differ | Preserve local contracts; use validated `TypedID` and `ArtifactRef` bridges. Never compare raw local strings across modules. |
| Committee candidate schema lacks typed company/memo refs | Require `AgencyCandidateEnvelope`; committee local candidate remains unchanged and is wrapped by immutable refs. |
| Company is a separate run, valuation is nested, committee is portfolio-wide, thesis may be nested or standalone | Join through typed immutable refs in `AgencyCaseManifest`; do not force one physical directory or duplicate artifacts. |
| MLAB and future specs each define lifecycle fields | Keep every subsystem namespace; top-level state is a replayed projection only. |
| Company `READY`, valuation `APPROVED_RESEARCH`, committee `MOCK_ELIGIBLE`, thesis `PAPER_READY`, queue `QUEUED`, and paper `OPEN` sound equivalent | They are distinct typed states connected only by explicit promotion events and fresh gates. |
| Web acquisition can propose stance; query lanes can bias stance | Discovery/search rows remain ineligible. Query lane alone never sets supports/refutes. Deterministic edge evaluation and material review control claim disposition. |
| Accepted web slice has basic dedupe but agency needs origin clustering | Treat basic canonical URL/hash dedupe as implemented; multi-domain syndication/origin clustering remains a required M3/S3 gate. |
| Web slice accepted, but agency-wide contradiction/no-lookahead is not implemented | Label web controls accepted only within M2. Every downstream slice adds its own temporal and contradiction fixtures before promotion. |
| Valuation upside, analyst confidence, quant score, and portfolio fit all look like conviction | Preserve separate dimensions. None directly sets size or overrides another gate. |
| Committee spec has one lifecycle | Reuse one deterministic engine with explicit `SCREEN` and `FINAL` pass contracts and separate run IDs; M5A omits final-only outputs. |
| Committee can consume reviewed `NO_VALUATION`; valuation spec says at least one method for initial eligible MVP | `NO_VALUATION` may enter M5A only when committee policy explicitly allows it and the artifact is independently reviewed; it cannot satisfy valuation-score or mock-eligibility requirements by default. |
| Quant low power could be treated as warning | `QUANT_INCONCLUSIVE` blocks the paper path. Only `QUANT_PASS` reaches M5B paper eligibility. |
| Portfolio fit can improve diversification | Portfolio fit may cap/hold an otherwise strong candidate; it cannot promote a weak thesis or failed quant. |
| Research commands are read-only, but paper handoff mutates queue | Queueing is a separately invoked S7 command and the only allowed mutation boundary; all other commands remain byte-identical on protected state. |
| Existing `OrderCandidate` lacks lineage fields | Do not change it in MVP. Require one staged queue intent and one active mandatory sidecar per broker candidate hash. |
| Queue status `EXECUTED` sounds like a fill | It is command state only. Ledger reconciliation alone sets paper position state. |
| Learning should adapt policy, but exceptions can launder safety failures | Only accepted feedback or exact-scope, expiring, one-use overrides may affect allowed policy. Safety/provenance/no-lookahead/protected-state/replay/live boundaries are never overridable. |
| `live_research` sounds like live trading | It means current evidence acquisition inside accepted M2 only. Execution mode remains `paper_simulation`; no live-execution enum exists. |
| Supplemental acceptance manifest contains a stale self-entry | Do not trust self-referential digest manifests. Use detached outer digests; substantive web acceptance artifacts were directly recomputed and independently accepted. |

## 13. Explicit out of scope

The integrated MVP does not include:

- live trading, live options, broker credentials, live account discovery, autonomous orders, margin, shorting, naked options, or direct model-to-queue behavior;
- client/account advice, customer funds, investment-advice monetization, or cron-driven execution;
- bank/insurer residual-income or dividend models, REIT NAV/AFFO, SOTP, commodity/project NAV, precedent transactions, licensed consensus, non-USD point-in-time FX, Monte Carlo valuation, or quarterly forecasting;
- graph/vector databases, browser farms, workflow engines, vendor-managed research agents, recursive crawling, paywall/CAPTCHA bypass, login/form submission, or cookie retention;
- automatic analyst spawning in the first committee MVP, or claims of process isolation from prewritten sealed fixtures;
- learned committee weights, claims that thresholds predict alpha, global cross-horizon ranking, or provider/vendor benchmark promotion;
- options execution or broad strategy expansion inside the agency slices;
- changing `OrderCandidate` to carry agency provenance in MVP;
- using the Agency Desk as a second source of truth or mutation surface;
- external non-repudiation claims from local hash chains;
- any live-adjacent continuation flag. Such work is a separate critical-risk program requiring legal review, Ronak's written approval, credentials isolation, broker sandbox reconciliation, manual tickets, kill switches, incident response, and independent architecture review.

## 14. Final acceptance and handoff

This plan is ready for independent review only when:

1. all consumed source hashes still match section 1.3;
2. exact web acceptance and corrected adversarial-audit review remain PASS;
3. the document contains module boundaries, shared/bridge schemas, events, states, budgets, gates, slices, dependencies, objective tests, branch sequence, contradiction decisions, and out-of-scope;
4. no product or execution-state files changed;
5. structural checks and repository tests pass;
6. an independent reviewer reviews this exact file digest and returns APPROVE.

Plan approval authorizes only the next fixture-first implementation slice. It does not authorize merge to `main`, deployment, scheduling, paper queue mutation, or any live activity.
