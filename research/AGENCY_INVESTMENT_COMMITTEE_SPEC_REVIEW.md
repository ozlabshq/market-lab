# Independent Review: Market Lab Agency Investment Committee Specification

**Spec reviewed:** `research/AGENCY_INVESTMENT_COMMITTEE_SPEC.md`  
**Review timestamp:** 2026-07-14T07:32:21Z  
**Reviewer:** ozzy-review  
**Verdict:** APPROVE

## Executive verdict

The revised investment committee specification is implementation-ready for the stated research/mock MVP. It now defines a deterministic, safety-gated committee control plane with no execution side effects; complete candidate/outcome/ranking contracts; replayable scoring; explicit calibration separation; anti-groupthink controls; freshness/evidence independence rules; read-only portfolio gates; signed analyst review artifacts; and objective test/MVP boundaries.

I found no blocking gaps relative to the requested review dimensions. The remaining notes are implementation cautions, not spec blockers.

## Scope and evidence checked

I reviewed the full 1,093-line spec and spot-checked the current repository grounding it cites:

- `market_lab/config.py:48-84` confirms the research/mock safety defaults, long-only constraints, and separate options paper/live flags.
- `market_lab/broker.py:78-88`, `market_lab/broker.py:146-158`, and `market_lab/broker.py:160-202` confirm candidate next-open semantics and current mock-order risk gates.
- `market_lab/evidence.py:12-59` confirms the current append-only/atomic JSONL evidence substrate that the spec intentionally strengthens with canonical hashes and replay.
- No `tests/market_lab/test_committee_*.py` files currently exist, consistent with the spec stating they are future implementation targets.

I did not edit the spec.

## Required review dimensions

| Dimension | Verdict | Notes |
|---|---|---|
| Deterministic outcome ladder | PASS | Section 7 defines hard rejection precedence, non-hard dispositions, exactly-one outcome, total ordered decision ladder, park-vs-reject distinctions, stale snapshot mapping, and concrete `PARK_RESEARCH` owner/action requirements. The prior fallthrough risk is closed. |
| Score replay | PASS | Sections 6, 12, and 14 define canonical inputs, deterministic weighted medians/tie breaks, quantized rank keys, immutable artifacts, status replay, byte-stable packet rendering, idempotency, and superseding correction runs. |
| Calibration | PASS | Section 6.4 separates probability calibration from confidence-stability calibration and score-revision error; requires walk-forward separation; pins methods before evaluation; defines cold start, beta-binomial shrinkage, serialized transforms, and base-rate shrinkage. |
| Anti-groupthink | PASS | Sections 5, 8, and 11 require sealed first-pass reviews, role/process separation, equal skeptic budget, source-origin dedupe, correlated-cluster down-weighting, blind tie-break review, leave-one-out replay, minority preservation, and unsupported-convergence detection. |
| Freshness | PASS | Section 4.5 measures freshness against immutable `as_of_utc`, defines per-artifact age limits, handles exchange-calendar failure, future timestamps, stale portfolio snapshots, refreshable staleness, and synthetic-data exclusion. |
| Evidence independence | PASS | Sections 4.4, 6.3, 6.6, and 8 require origin clustering, one-origin/one-slot behavior, source-class fit, materiality-weighted coverage, evidence eligibility, and leave-one-evidence-origin replay. Syndicated or duplicated evidence cannot falsely corroborate a thesis. |
| Portfolio gates | PASS | Section 10 separates standalone quality from portfolio suitability, requires read-only hash-addressed snapshots, defines deterministic threshold/stress/replacement/cap logic, distinguishes `FIT`, `FIT_WITH_CAP`, `HOLD_CAPACITY`, `FAIL_PORTFOLIO`, and `BLOCKED_STALE_SNAPSHOT`, and preserves no-mutation invariants. |
| Signed artifacts | PASS | Section 5.3 requires content hashes and Ed25519 signatures for sealed analyst reviews, with canonical JSON, domain separation, pinned public keys, unknown-key/tamper rejection, and non-production fixture keys for MVP. Sections 12.1-12.5 add hash-chained audit and artifact hash finalization. |
| Tests | PASS | Section 13 is specific and broad: schema, evidence, scoring, calibration, disagreement, quant, portfolio, store, CLI, safety, property/metamorphic, adversarial, integration, recovery, and no-side-effect tests are all enumerated with concrete boundary cases. |
| MVP boundaries | PASS | Section 14 keeps MVP narrow: frozen equity cohort, prewritten sealed reports, deterministic engine, read-only portfolio checks, replay/audit/no-side-effect proof. It explicitly excludes autonomous analyst spawning, live data scheduling, order/candidate queue writes, live/sandbox broker integration, options execution, and claims of predictive alpha. |

## Safety and spec-compliance findings

### No blockers

I found no issue that should prevent implementation planning against this spec.

### Strengths worth preserving during implementation

1. Safety gates are redundant and explicit: the committee cannot place or queue orders, cannot mutate portfolio/execution state, and `MOCK_ELIGIBLE` is defined as research eligibility only.
2. Evidence integrity is treated as a hard gate rather than a soft score penalty: hash, locator, unit, timestamp, source-label, synthetic-data, and lookahead failures fail closed.
3. Outcome assignment is deterministic and conservative: high scores cannot override missing evidence, unresolved material disagreement, quant leakage, unsupported execution, hard portfolio risk, or policy exceptions.
4. Calibration is honest about cold start and provisional thresholds: the MVP validates control correctness, not investment edge.
5. Anti-groupthink controls are operational, not rhetorical: sealed reviews, correlated-cluster down-weighting, tie-break blindness, unsupported-convergence detection, and leave-one-out replay all have test hooks.
6. Portfolio fit is not used to promote weak theses: low correlation alone cannot rescue a below-threshold candidate.

## Non-blocking implementation cautions

1. `independent_review.json` should receive an explicit schema before implementation. The spec requires an independent review verdict and artifact hash, while analyst reports have fully specified signature fields. If non-repudiation is desired for the final reviewer too, mirror the analyst-review content-hash/signature contract for `independent_review.json` in the implementation plan.
2. Keep state terminology strict in code: the spec uses lifecycle stages, run verdicts, terminal non-final states, and `BLOCKED_DISAGREEMENT`. Implement these as separate enums or validated fields so a blocked disagreement stage is not confused with a finalized verdict.
3. The calibration registry should be implemented as frozen input to a run, never fitted opportunistically during replay. The spec says this clearly; tests should assert it because it is an easy implementation mistake.
4. The sealed-input-envelope MVP proves allowlist/denylist behavior, not process isolation. The spec states this boundary; implementation docs and reports should repeat it so MVP demos do not overclaim analyst independence.

## Final recommendation

APPROVE. The spec is sufficiently complete and deterministic for the next implementation slice: freeze schemas, reason codes, policy snapshots, canonicalization, and frozen fixtures; then build pure validation/scoring/replay before adding storage, portfolio checks, CLI/reporting, and only later automated analyst orchestration.
