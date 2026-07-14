# Re-Review — Agency Thesis Portfolio and Learning Spec

**Reviewed artifact:** `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC.md`  
**Prior review:** `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC_REVIEW.md`  
**Review date:** 2026-07-14 UTC  
**Reviewer:** ozzy-review  
**Decision:** APPROVE for fixture-first/contracts-first implementation planning, subject to the spec's own acceptance gates and independent implementation review

## Bottom line

The corrected thesis-portfolio and learning spec closes every blocker from the prior independent review. I found no remaining spec-level blocker that should prevent a first implementation slice from beginning.

The updated document now gives implementers deterministic contracts for typed stable IDs, separated lifecycle state namespaces, unchanged-`OrderCandidate` queue lineage via a mandatory sidecar, fail-closed catalyst/liquidity readiness, and machine-auditable learning overrides. It also incorporates the prior non-blocking improvements around attribution availability, deterministic partial reductions, ledger-missing behavior, protected-state path resolution, and queue confidence bounds.

This approval is for the specification as a research/mock/paper-only implementation plan. It is not approval of any future paper candidate, paper fill, live trading path, options flow, investment advice, or broker integration.

## Scope and method

I freshly reviewed the current corrected spec against the prior review's exact blockers and important non-blocking improvements. I did not edit `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC.md`.

Checks performed:

- Re-read `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC.md` and `research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC_REVIEW.md`.
- Verified every prior blocker has an explicit corrected contract in the current spec.
- Ran a marker/obsolete-snippet check over the corrected spec for required closure points: canonical typed IDs, lifecycle namespaces, sidecar queue lineage, required-vs-optional readiness inputs, learning overrides, attribution as-of metadata, partial-reduction policy, ledger-missing behavior, and protected-state path resolution.
- Checked that the most dangerous obsolete snippets from the prior review are absent, including raw `sha256(memo_id + candidate_id ...)` ID construction and old `0.50` reduced-size behavior for missing bounded catalysts or missing liquidity.

## Verdict by prior blocker

| Prior blocker | Current status | Evidence in corrected spec | Review result |
|---|---|---|---|
| 1. Stable ID formulas used ambiguous raw concatenation | Closed | IDs are now defined as `canonical_id(domain, payload)` over UTF-8 canonical JSON bytes with domain separation (`research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC.md:216-228`), each payload has named fields and `id_schema_version` (`230-282`), collection ordering is explicit (`285-295`), and raw concatenation/implicit string conversion are contract violations (`297-303`). Tests cover dictionary order, set-like ordering, semantic sequence changes, and ambiguous concatenation cases (`1678-1687`). | PASS |
| 2. Status and transition vocabularies were internally inconsistent | Closed | The schema separates `thesis_position_status` from committee actions and defines `INPUT_BLOCKED`, `PAPER_BLOCKED`, `WATCH_ONLY`, and `REJECTED` semantics (`363-370`, `878-909`). Lifecycle events carry an `event_namespace` (`605-620`). Section 17 defines typed namespaces for thesis, queue, paper position, monitoring, postmortem, and archive states (`1480-1508`), maps presentation aliases such as `QUEUE_SKIPPED`, `PAPER_OPEN`, `POSTMORTEM_DUE`, and `LEARNING_RECORDED` out of persisted state (`1510-1515`), and gives transition/recovery rules (`1517-1568`). | PASS |
| 3. Queue handoff was not compatible enough with current `OrderCandidate` | Closed | The spec now states that the mandatory `paper_candidate_link` sidecar is the only MVP bridge and that `OrderCandidate` remains unchanged (`515-550`). The adapter copies exactly the current nine broker fields (`547-550`), uses a typed canonical `order_candidate_key` that includes thesis/sizing/action identity (`552-567`), distinguishes same-symbol theses/reductions/exits and broker-hash lineage collisions (`569-575`), stages `queue_intent.json` (`582-603`), and defines lock/re-read/temp-rewrite/fsync/reconcile/crash-recovery behavior for `queue-paper-candidate` (`911-947`). Candidate queue tests now require unchanged current `OrderCandidate` plus exactly one sidecar and one-to-one reconciliation (`1709-1722`). | PASS |
| 4. Catalyst/readiness and sizing rules conflicted for missing required inputs | Closed | Sizing now explicitly splits `required_for_paper_ready` from `optional_size_modifiers` (`994-1019`). Missing or stale required evidence forces zero size and `PAPER_BLOCKED`/`WATCH_ONLY`, and optional modifiers cannot turn missing required evidence into `PAPER_READY` (`1016-1019`). The multiplier table sets `no bounded catalyst` and missing/stale liquidity to `0.00, PAPER_BLOCKED` rather than reduced nonzero sizing (`1044-1053`), and the old `0.50` behavior is explicitly barred from MVP queueing (`1065-1069`). Tests cover no bounded catalyst and missing/untrusted liquidity blocking with zero size (`1697-1707`). | PASS |
| 5. Learning overrides were allowed but not auditable enough | Closed | The spec adds immutable `LearningOverride` and `learning_override_use` schemas with approver authority, cutoff, expiry, exact object/action/scope, evidence, one-time/max-use constraints, protected-state hashes, and audit hashes (`782-838`). Validation requires accepted feedback events or an approved unexpired unconsumed exact-scope override, appends/fsyncs accepted use before applying policy artifacts, and treats accepted use as consumed (`840-847`). Safety/live/no-lookahead/protected-state/provenance/replay/independent-review domains are non-overridable (`849-856`). Gate `reviewer_override` is now a validated override reference, not free text, and safety/provenance/replay gates force `override_allowed=false` (`1350-1370`). Feedback tests reject free-text, reused, out-of-scope, and safety-targeting overrides (`1773-1785`). | PASS |

## Verdict by prior non-blocking improvement

| Prior improvement | Current status | Evidence | Review result |
|---|---|---|---|
| A. Tighten no-lookahead attribution wording | Closed | Attribution inputs now carry `source_id`, `as_of_utc`, and `available_at_utc`, and normal snapshots reject later-unavailable bars, fills, valuation refreshes, and catalyst observations unless explicitly retrospective postmortem analysis (`1250-1256`). Tests cover this availability rule (`1754-1763`). | PASS |
| B. Define exit/reduction quantity policy | Closed | `reduce_to_weight` now has deterministic target/sell quantity formulas, floor/no-round-up behavior, min-notional/residual blockers, full-exit precedence, and single highest-priority reduction selection (`1173-1189`). Tests cover partial exits and rounding/min-notional boundaries (`1733-1740`, `1816-1820`). | PASS |
| C. Clarify ledger-missing behavior for thesis exits | Closed | Normal thesis exits require unique reconciled ledger evidence and current quantity; missing/ambiguous evidence emits `LEDGER_ENTRY_UNPROVEN`, sets `paper_position_status=UNRECONCILED`, and creates no SELL candidate. Safety/protected-state anomalies instead activate audit/kill and block queue mutation (`1191-1195`). | PASS |
| D. Make protected-state validation path-based | Closed | Protected state validation resolves configured paths from active `MARKET_LAB_DATA_DIR`/`market_lab.config`, hashes resolved absolute paths or `ABSENT`, forbids filename-only/default-root checks, and requires alternate-data-dir tests (`1644-1673`, `1787-1796`). | PASS |
| E. Define queue `confidence` bounds | Closed | The queue link requires deterministic `confidence` in `[0, 1]`; MVP uses fixed `1.0` to mean policy gates accepted, never analyst conviction (`569-575`). | PASS |

## Fresh review notes

### Research-only safety remains intact

The corrected spec preserves the hard boundary that approved memos are not trades (`27-31`), keeps live trading/options/shorting/margin out of scope (`84-101`), requires all output to remain paper-only (`1-7`, `849-856`), and limits queue mutation to the existing pending paper candidate file under a dedicated command (`911-947`, `1644-1673`).

### The bridge to current broker code is now implementable

The highest-risk integration seam is now explicit: current `OrderCandidate` stays byte-shape-compatible, while the sidecar, `broker_candidate_hash`, `order_candidate_key`, queue intent, and reconciliation rules carry thesis lineage. That is the right MVP boundary because it avoids smuggling IDs into `reason` while also avoiding a premature broker schema migration.

### Recovery and replay are now specifiable as tests

The spec no longer leaves recovery as a prose aspiration. Crash after `PAPER_READY`, crash after queue replacement, unresolved queue/ledger lineage, partial JSONL, changed policy hash, and protected-state mutation attempts are all named fail-closed cases in the state/replay/chaos plans (`1563-1568`, `1798-1822`).

### Learning controls are appropriately narrower than founder discretion

Ronak/Ozzy exceptions remain possible only as exact, immutable, one-time learning overrides with expiry, authority, audit hash, protected-state hashes, accepted use events, and scorecard/postmortem visibility. The spec correctly excludes safety/no-lookahead/provenance/replay/independent-review gates from this override subsystem.

## Residual risks for implementation review

These are not spec blockers; they are implementation areas that should receive extra review when code lands:

1. Canonical JSON, decimal serialization, and stable hashing must be implemented exactly, without Python float or display-string shortcuts.
2. Queue handoff locking/fsync/directory-fsync behavior should be tested on the target filesystem, including crash simulation and partial JSONL recovery.
3. Sidecar reconciliation must fail closed on identical broker hashes with different active lineage, even if that temporarily blocks otherwise valid paper candidates.
4. Protected-state resolution should be tested under alternate `MARKET_LAB_DATA_DIR` before trusting replay reports.
5. Learning override consumption should be validated under concurrent attempted uses so the one-time guarantee is real, not only a schema field.

## Verification performed

```text
python3 marker/obsolete-snippet check over research/AGENCY_THESIS_PORTFOLIO_LEARNING_SPEC.md
PASS: typed canonical IDs, namespaced state model, unchanged-OrderCandidate sidecar, required-vs-optional readiness, learning override markers, attribution/partial-reduction/ledger/protected-state additions
PASS: obsolete raw-concat ID snippets absent
PASS: obsolete missing-catalyst/liquidity 0.50 sizing snippets absent
```

Product tests run after writing this re-review:

```text
uv run pytest tests/market_lab -q
239 passed, 6 subtests passed in 13.51s
```

## Final decision

APPROVE.

All five prior blockers are closed in the corrected specification, and all five prior non-blocking improvements have been incorporated sufficiently for implementation planning. The next implementation should proceed fixture-first and contracts-first, with queue handoff delayed until canonical IDs, gates, protected-state verification, sidecar reconciliation, and replay checks are green.
