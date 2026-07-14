# Independent Review — Agency Thesis Portfolio and Learning Spec

**Reviewed artifact:** `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC.md`  
**Review date:** 2026-07-14 UTC  
**Reviewer:** ozzy-review  
**Decision:** REQUEST_CHANGES before treating the spec as implementation-ready

## Bottom line

The spec is directionally strong and well aligned with Market Lab's research/paper-only posture. It correctly treats an approved memo as insufficient for trading, introduces a separate portfolio committee gate, requires deterministic sizing, preserves next-open paper execution, and defines monitoring, exits, attribution, scorecards, postmortems, feedback events, protected-state checks, and replay.

I would not approve it as implementation-ready yet. The document is strong at the policy level, but several contract seams would let reasonable implementers build incompatible or unsafe behavior: raw-concatenation IDs, inconsistent state/status vocabularies, an underdefined bridge into the current `OrderCandidate` queue, conflicting catalyst/readiness sizing behavior, and an unaudited override path for learning changes. These should be fixed in the spec before tests and artifacts encode the ambiguity.

## Scope reviewed

I reviewed the spec for:

- memo-to-paper-position linkage and artifact identity;
- paper-only enforcement and protected-state mutation boundaries;
- sizing, invalidation, monitoring, and exit governance;
- no-lookahead and attribution discipline;
- postmortem/feedback learning integrity;
- state recovery, replay, and crash safety;
- deterministic tests and MVP scope.

Repository context checked:

- `market_lab/config.py` — current risk flags, paths, and protected-state constants;
- `market_lab/broker.py` — current `OrderCandidate`, pending-candidate JSONL helpers, mock order risk gates, and next-open candidate conversion;
- `market_lab/exit_governor.py` — existing SPY-relative paper exit governor and next-open SELL candidates;
- `research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md` and neighboring agency spec reviews for expected safety/review posture.

I did not edit `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC.md`.

## Verdict by review dimension

| Dimension | Verdict | Notes |
|---|---|---|
| Memo-position linkage | REQUEST_CHANGES | The intended chain is right, but ID construction and current queue linkage are not yet unambiguous enough for durable audit. |
| Paper-only enforcement | PASS with additions needed | Strong non-goals, safety gates, and protected-state paths. Add exact queue-side locking/dedupe semantics and keep all non-queue commands byte-identical. |
| Sizing policy | REQUEST_CHANGES | Deterministic/capped policy is good, but required-vs-optional inputs and catalyst/liquidity blocker behavior conflict in places. |
| Invalidations and exits | PASS with additions needed | Good measurable invalidation rules and next-open exits. Add concrete reducer/exit ordering and ledger-missing behavior around thesis exits. |
| No-lookahead attribution | PASS with additions needed | Good benchmark-relative, slippage, sizing, and quality-flag posture. Add explicit as-of/source eligibility tests for attribution windows. |
| Learning integrity | REQUEST_CHANGES | Feedback events are the right primitive, but founder/Ozzy exception path must be machine-readable, scoped, and auditable. |
| State recovery/replay | REQUEST_CHANGES | Artifact hash/replay rules are strong, but status enums and transition names are inconsistent and would undermine recovery. |
| Tests | PASS with additions needed | Broad deterministic plan. Add targeted regressions for the blockers below. |
| MVP scope | PASS | Standard-library-first, fixture-first, no options/live/broker-adapter expansion is appropriate. |

## Blocking issues to fix in the spec

### 1. Stable ID formulas use ambiguous raw concatenation

Evidence:

- Section 6 requires canonical JSON artifacts with sorted keys and stable schema versions.
- Section 7 then specifies IDs as raw concatenations such as `sha256(memo_id + candidate_id + analysis_cutoff + policy_hash + request_actor)` and `sha256(thesis_position_id + catalysts + invalidations + review_schedule)`.

Why this blocks approval:

The whole layer depends on durable memo → committee → thesis position → sizing → candidate → ledger linkage. Raw concatenation is not a safe canonicalization scheme: fields can collide across boundaries, arrays can reorder silently, and complex objects such as catalysts/invalidations are undefined as strings. If implementers follow the pseudocode literally, replay and cross-artifact verification can become non-deterministic or collision-prone.

Required spec fix:

- Rewrite every ID input as a canonical JSON object or array with named fields, schema version, and domain-separation prefix, e.g. `{"schema_version":"mlab-thesis-position-id.v1", ...}`.
- Define array ordering policy for catalysts, invalidations, benchmarks, controls, and fills.
- Require the ID hash to be over UTF-8 canonical JSON bytes, not display strings.
- Add a regression test proving ambiguous concatenation cases cannot collide and reordered dictionaries produce the same ID while reordered semantic arrays only match when policy says order is irrelevant.

### 2. Status and transition vocabularies are internally inconsistent

Evidence:

- `Thesis paper position.status` allows `DRAFT | GATED | PAPER_READY | PAPER_BLOCKED | REJECTED | SUPERSEDED`.
- Section 9 separately introduces `REJECT_THESIS_POSITION` and `WATCH_ONLY`.
- Section 17 transitions through `INPUT_BLOCKED`, `QUEUE_SKIPPED`, `QUEUED`, `PAPER_OPEN`, `QUEUE_EXPIRED`, `QUEUE_CANCELLED`, `MONITORING`, `EXIT_PENDING`, `FORCE_REVIEW`, `THESIS_BROKEN`, `CLOSED`, `POSTMORTEM_DUE`, `LEARNING_RECORDED`, and `ARCHIVED`, most of which are not in the schema status enum.
- Gate failures use `INPUT_BLOCKED` in prose, while schemas/gates sometimes say `PAPER_BLOCKED` or `REJECTED`.

Why this blocks approval:

State vocabulary is not just presentation here; it drives queue eligibility, monitor behavior, postmortem requirements, replay, and crash recovery. With the current text, one implementation could store queue lifecycle in `ThesisPaperPosition.status`, another could store it in separate artifacts, and both could claim compliance. Recovery after partial writes or queue handoff would be brittle.

Required spec fix:

- Define one canonical state model, or explicitly separate `thesis_position_status`, `queue_status`, `monitoring_status`, `postmortem_status`, and `archive_status`.
- Make every state in the transition diagram appear in a typed enum or move it to the correct artifact-specific enum.
- Normalize `REJECTED` vs `REJECT_THESIS_POSITION`, `INPUT_BLOCKED` vs `PAPER_BLOCKED`, and `WATCH_ONLY` semantics.
- Add replay tests for invalid transition skips, crash after `PAPER_READY` before queue link, crash after queue append before manifest, and recovery with a `POSTMORTEM_DUE` closed position.

### 3. The queue handoff is not yet compatible enough with the current `OrderCandidate` contract

Evidence:

- Current `market_lab.broker.OrderCandidate` contains only `side`, `symbol`, `quantity`, `strategy`, `confidence`, `reason`, `signal_date`, `reference_close`, and `intended_execution`.
- The spec's `paper_candidate_link` adds `paper_candidate_link_id`, `thesis_position_id`, `sizing_decision_id`, `order_candidate_key`, `queue_status`, `broker_candidate_hash`, and `ledger_decision_id`.
- MVP acceptance says a paper-ready fixture creates one existing-compatible `OrderCandidate` with full upstream links.
- The spec mentions duplicate keys as `(symbol, signal_date, strategy, side)` and says the queue command may append/replace a candidate, but current broker helpers are bare JSONL append/rewrite helpers with no thesis ID, no candidate ID, no lock around candidate file writes, and no native provenance fields.

Why this blocks approval:

The desired audit link is correct, but the spec does not define exactly how that link survives the existing queue. If upstream IDs live only in a sidecar `paper_candidate_link.json`, then `OrderCandidate` itself is not carrying “full upstream links.” If they are encoded into `reason`, that is not machine-checkable. The dedupe key also ignores `quantity`, `thesis_position_id`, `sizing_decision_id`, and exit/reduction rule identity, which can collapse distinct same-symbol paper decisions or confuse a reduction with a full exit.

Required spec fix:

- Define the exact adapter contract from `paper_candidate_link` to current `OrderCandidate`.
- State whether current `OrderCandidate` remains unchanged with a mandatory sidecar link, or whether a future schema adds optional provenance fields.
- Define `order_candidate_key` as canonical typed data, including at least side, symbol, strategy, signal date, thesis position ID or supersession group, and action type.
- Define queue-file locking/fsync behavior for `queue-paper-candidate`; current append helpers do not fsync or lock the candidate JSONL.
- Add tests proving the queue file can be reconciled back to exactly one `paper_candidate_link` and that duplicate/superseded candidates are handled without losing the thesis lineage.

### 4. Catalyst/readiness and sizing rules conflict for missing required thesis inputs

Evidence:

- Eligibility requires measurable catalysts and invalidations before committee review.
- G6 requires every material catalyst to have source, window, mechanism, observations, and freshness SLA.
- MVP acceptance requires every paper-ready position to have at least one catalyst monitor and one invalidation monitor.
- The multiplier table says `catalyst_timing_multiplier: no bounded catalyst = 0.50`, which can still produce a nonzero `final_target_weight` if other multipliers pass.
- The liquidity table similarly says `no liquidity metric = 0.50` even though other sections say missing required inputs produce zero/blockers.

Why this blocks approval:

The spec says missing required inputs fail closed, but the multiplier table can be read as allowing a smaller paper position when a core readiness input is absent. That undermines the “memo is not a trade” gate and creates inconsistent implementer behavior.

Required spec fix:

- Split sizing inputs into explicit `required_for_paper_ready` and `optional_size_modifier` sets.
- Make missing required catalyst/invalidation/quant/live-data/security/benchmark inputs yield `PAPER_BLOCKED` or `WATCH_ONLY` with zero size, not a reduced multiplier.
- If `no bounded catalyst = 0.50` is intended only for watch-only analysis or later non-catalyst strategy families, state that it cannot produce `PAPER_READY` in MVP.
- Do the same for liquidity if liquidity is required for queueing.
- Add tests where an otherwise strong memo with no bounded catalyst or no trusted liquidity blocks instead of generating a small candidate.

### 5. Learning overrides are allowed but not auditable enough

Evidence:

- Section 15.3 says a future policy or strategy change must cite accepted feedback events or an explicit human/founder exception.
- Section 8.14 `FeedbackEvent` has no corresponding `exception_id`, scope, approver, expiration, protected-state hash, or one-time waiver fields.
- Gate schemas include `reviewer_override nullable`, but the spec does not define who can override which gates, whether safety gates are non-overridable, or how overrides enter scorecards.

Why this blocks approval:

The feedback loop is supposed to prevent cherry-picking and post-hoc tuning. An unstructured “Ronak/Ozzy exception” can become the same backdoor the spec is trying to close unless it is recorded, scoped, and scorecard-visible. This matters even in paper mode because learning artifacts determine future research behavior.

Required spec fix:

- Add a machine-readable `LearningException` or `PolicyOverride` schema with approver, authority, rationale, affected object, allowed action, expiration/scope, supporting evidence, created-at cutoff, and audit hash.
- Explicitly mark safety/live-trading gates as non-overridable by this subsystem.
- Require scorecards to count overrides and require postmortem follow-up when an override leads to bad outcomes.
- Add tests rejecting policy/strategy changes without either accepted feedback events or a valid scoped override.

## Non-blocking but important improvements

### A. Tighten no-lookahead attribution wording

The attribution section is directionally sound and avoids false precision. Add explicit rules that `window_start`, `window_end`, benchmark bars, fills, valuation refreshes, and catalyst observations must each carry source/as-of/available-at metadata and cannot use data unavailable at the attribution snapshot's `observed_at_utc` unless the snapshot is explicitly labeled as retrospective postmortem analysis.

### B. Define exit/reduction quantity policy

The spec says exits can reduce or close and that SELL links are only for existing paper positions. Add exact rules for partial reductions: whether reductions target a weight, share count, or percent of current quantity; how rounding interacts with min notional; and how a lower-priority reduction interacts with a higher-priority full exit.

### C. Clarify ledger-missing behavior for thesis exits

The exit governor currently skips safely when ledger evidence is missing. The thesis spec should distinguish between “cannot prove entry, so do not generate a normal thesis exit” and “safety/protected-state anomaly, so block/audit immediately.”

### D. Make protected-state path validation path-based, not filename-only

The protected-state list is right, but implementation should hash resolved paths under `MARKET_LAB_DATA_DIR`, not just filenames. Add tests under an alternate `MARKET_LAB_DATA_DIR` so replay/protected-state verification does not accidentally hash the repo default data directory.

### E. Define `confidence` bounds for the queue adapter

Current `OrderCandidate.confidence` is a float without enforcement. The thesis adapter should define the allowed range and source. Prefer a deterministic confidence derived from gate quality and capped to `[0, 1]`, or a fixed `1.0` meaning “policy accepted,” not analyst conviction.

## Strong points to preserve

- The hard rule that an approved memo is not a trade is exactly right.
- The separate portfolio committee gate is the right boundary between research memo approval and paper queue eligibility.
- Paper-only enforcement is broad and redundant: non-goals, G1 safety, protected-state hashes, no options MVP, no live flags, no margin, no shorting, and existing broker risk gates.
- Sizing is deterministic, capped, and cannot be set directly by a model or analyst prose.
- Missing monitor data is not treated as success.
- Invalidations must be measurable with source class, threshold, window, severity, and action.
- Exits remain next-open paper candidates and do not mutate ledger/portfolio directly during monitoring.
- Attribution is correctly framed as diagnostic rather than proof, with nulls and quality flags for weak components.
- Scorecards emphasize evidence quality, calibration, humility, blocker honesty, and postmortem discipline instead of raw P&L or more BUYs.
- Feedback events as the only normal tuning path are the right learning primitive.
- The implementation sequence wisely starts with contracts/fixtures/gates and explicitly says not to start with queueing.

## Additional tests I would add before approval

1. `stable_ids_use_canonical_typed_json_not_concat` — ambiguous raw concatenations cannot collide; dictionary ordering does not change IDs.
2. `thesis_status_enum_matches_transition_table` — every persisted state is in exactly one typed enum and invalid transitions are rejected.
3. `paper_candidate_sidecar_reconciles_to_order_candidate` — every queued `OrderCandidate` maps back to exactly one `paper_candidate_link` and upstream memo/sizing IDs.
4. `same_symbol_distinct_thesis_candidates_do_not_dedupe_wrongly` — duplicate handling respects thesis/supersession identity, not just symbol/date/strategy/side.
5. `queue_handoff_locks_fsyncs_and_hashes_pending_file` — crash/replay around queue append or replacement is recoverable.
6. `no_bounded_catalyst_blocks_paper_ready` — reduced multiplier cannot bypass catalyst/readiness gate.
7. `missing_trusted_liquidity_blocks_when_required_for_queue` — no optimistic default for required liquidity evidence.
8. `learning_policy_change_requires_feedback_or_scoped_override` — tuning without an accepted feedback event or valid override is rejected.
9. `safety_gate_override_is_rejected` — live/options/short/margin/protected-state safety gates are not overrideable by learning exceptions.
10. `attribution_respects_observed_at_availability` — post-window or post-cutoff bars/valuation/catalyst observations cannot enter a non-retrospective snapshot.
11. `partial_reduction_rounding_never_oversells_or_violates_min_notional` — reduction/exit quantity policy is deterministic.
12. `alternate_market_lab_data_dir_protected_hashes` — protected-state verifier hashes the resolved configured data root.

## Verification performed

This was a specification review, not a product-code review. I read the full 1,407-line spec and checked the current code contracts that it proposes to bridge into:

- `RiskConfig` has `max_position_pct`, `max_single_order_pct`, `min_trade_notional`, `max_trade_notional`, no shorting, no margin, and `live_trading_enabled=False` by default.
- `OrderCandidate` currently has no upstream memo/thesis/provenance fields, so the spec needs an explicit sidecar or schema-extension contract.
- Current pending-candidate helpers append/rewrite JSONL but do not by themselves provide the full lock/fsync/provenance semantics this spec wants.
- Existing SPY-relative exits already follow paper-only, next-open SELL candidate discipline and safe skip behavior when ledger/benchmark evidence is missing.

Targeted current-contract tests were run after writing this review:

```text
uv run pytest tests/market_lab/test_broker.py tests/market_lab/test_exit_governor.py -q
30 passed in 0.10s
```

These tests validate the existing broker/exit-governor baseline cited above. They do not validate the future thesis-portfolio implementation, which does not exist yet; the recommended tests above are for that future implementation.

## Final recommendation

REQUEST_CHANGES.

After the five blocking seams are closed, I would approve the spec for a fixture-first/contracts-first implementation slice. The policy direction is sound and safety-preserving, but the current ambiguity is exactly in the parts that future code will make durable: identity, state recovery, queue lineage, readiness blockers, and learning overrides. Fix those in the spec before implementation starts so Market Lab does not encode inconsistent paper-position history or postmortem learning rules.
