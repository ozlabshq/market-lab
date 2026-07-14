# Market Lab Agency Company Intelligence Spec Review

Reviewer: ozzy-review  
Decision: REQUEST_CHANGES  
Date: 2026-07-14 UTC  
Reviewed artifact: `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md`

## Scope reviewed

I reviewed the company-intelligence spec against:

- `research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md`
- external web-evidence contract: `/Users/ozlabs/OzLabs/docs/market-lab/WEB_EVIDENCE_IMPLEMENTATION_SPEC.md`
- current source-thesis / ingest / factors / safety code:
  - `market_lab/source_thesis.py`
  - `market_lab/mlab_ingest.py`
  - `market_lab/factors.py`
  - `market_lab/config.py`
- current untracked web-evidence implementation files:
  - `market_lab/web_evidence.py`
  - `market_lab/web_evidence_store.py`
  - `market_lab/web_evidence_runner.py`
  - `market_lab/web_evidence_providers.py`
- current tests and package manifest.

I did not edit the company-intelligence spec.

## High-level assessment

The spec is directionally strong and substantially aligned with the roadmap: it preserves the research/mock-only posture, keeps source-derived ticker behavior conservative, separates issuer identity from security identity, rejects snippets/generated summaries as evidence, requires historical `as_of` handling, and defines meaningful tests for exposure, identity, provenance, temporal leakage, and side-effect safety.

However, I cannot approve it as implementation-ready yet. There are blocking contradictions/dependencies that would let two reasonable implementers build different readiness semantics or finalize before required upstream evidence is actually accepted.

## Blockers

### 1. The spec declares a missing upstream dependency and says finalization must not proceed

Evidence:

- `AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1554-1563` says the separately commissioned source `/Users/ozlabs/OzLabs/docs/market-lab/rd-swarm/COMPANY_INTELLIGENCE_RND.md` was not present when drafted and that the task must not be finalized until that report is available, read, and conflicts/improvements are resolved.
- I searched both `research/` and `/Users/ozlabs/OzLabs/docs/market-lab/` for `COMPANY_INTELLIGENCE_RND.md`; it is not present.

Why this blocks approval:

The spec itself defines the absence as a dependency blocker. Approving would contradict the document’s own finalization condition.

Required change:

Either:

1. obtain/read the R&D report and resolve all evidence-backed conflicts/improvements into the spec; or
2. add an explicit owner-reviewed waiver/removal of that dependency, with rationale, so the spec no longer self-blocks.

### 2. `READY` semantics for material exposure are internally ambiguous when exposure is `UNKNOWN`

Evidence:

- The core decision says candidate eligibility requires a “quantified or honestly unknown materiality assessment” (`AGENCY_COMPANY_INTELLIGENCE_SPEC.md:25-28`).
- G5 says pass conditions for `READY` include exposure being “quantified as a compatible value/range, or explicitly `UNKNOWN` with no false precision” (`AGENCY_COMPANY_INTELLIGENCE_SPEC.md:929-936`).
- The same section later says `UNKNOWN` usually produces `PARK_RESEARCH`, not rejection (`AGENCY_COMPANY_INTELLIGENCE_SPEC.md:939`).
- The MVP acceptance section requires every exposure value/range to reproduce from compatible evidence and qualitative/unavailable exposure to remain honest `UNKNOWN`, but does not clearly say whether an `UNKNOWN` critical exposure can ever be `READY` (`AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1505-1522`).

Why this blocks approval:

Material revenue exposure is the core reason this layer exists. As written, one implementer could allow `READY` for a candidate with no quantified materiality as long as the unknown is honestly labeled, while another would park it. That breaks deterministic executability and downstream committee expectations.

Required change:

Define an unambiguous G5 rule. Suggested policy:

- For any candidate whose critical mechanism depends on issuer exposure, `UNKNOWN` materiality must result in `PARK_RESEARCH`, not `READY`.
- `READY` requires compatible quantified exposure, a bounded derived range, or an explicit reviewer-approved exception explaining why sub-5% exposure has disproportionate profit/cash-flow sensitivity.
- Non-critical auxiliary exposure rows may remain `UNKNOWN` inside an otherwise `READY` packet only if the packet states why they are not readiness-critical.
- Add tests for qualitative-only, unknown-critical, unknown-noncritical, immaterial, and reviewer-exception paths.

### 3. The accepted web-evidence dependency is not yet machine-checkable from the company layer

Evidence:

- The company spec correctly states that live company-intelligence runs must return `BLOCKED_UPSTREAM_EVIDENCE` until the web-evidence layer is implemented and accepted (`AGENCY_COMPANY_INTELLIGENCE_SPEC.md:53-64`).
- The external web-evidence spec requires immutable snapshots, exact locators, audit-v2 events, zero snippet evidence, frozen/live/chaos gates, and independent approval before acceptance (`WEB_EVIDENCE_IMPLEMENTATION_SPEC.md:878-892`).
- Current repo state has untracked `web_evidence*` implementation modules, but no `tests/market_lab/test_web_evidence_*` files and no added dependencies in `pyproject.toml:11-21`; therefore the web-evidence layer is not presently accepted by its own contract.
- The company spec references “accepted web evidence” and “pre-existing evidence packets,” but does not define the concrete validation predicate the company runner must check before consuming them (`AGENCY_COMPANY_INTELLIGENCE_SPEC.md:55-64`, `AGENCY_COMPANY_INTELLIGENCE_SPEC.md:875-887`).

Why this blocks approval:

Without a machine-checkable upstream-acceptance predicate, implementers may accept arbitrary frozen fixtures, old `evidence.jsonl` rows, or context snippets as “pre-existing evidence packets.” That would undermine source provenance, temporal integrity, and the no-snippet rule.

Required change:

Add a concrete G0/web-evidence compatibility section that requires, at minimum:

- schema versions accepted by company intelligence, e.g. `mlab-evidence.v2`, `web-snapshot.v1`, and matching segment schemas;
- successful locator verification against the extracted artifact;
- snapshot hash verification;
- source-run status/review requirements;
- audit-chain validity where audit-v2 is present;
- explicit rejection of legacy free-text `mlab_ingest.add_evidence` rows as sufficient company evidence;
- `BLOCKED_UPSTREAM_EVIDENCE` as an explicit API/CLI status/result, mapped to the existing upstream-invalid exit path.

### 4. `READY` and independent review/finalization are circularly specified

Evidence:

- The packet schema includes both `outcome: READY | PARK_RESEARCH | REJECT_MAPPING` and `review_status` (`AGENCY_COMPANY_INTELLIGENCE_SPEC.md:565-598`).
- G10 says independent review `APPROVE` is required and that negative/missing review prevents finalization (`AGENCY_COMPANY_INTELLIGENCE_SPEC.md:987-997`).
- The outcomes section says all required gates plus independent review yield `READY` (`AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1007-1012`).

Why this blocks approval:

A reviewer needs a stable packet/gate report to review before finalization. If `READY` itself requires independent approval, then the system needs a pre-review readiness state; otherwise implementers may either finalize before review or hide deterministic gate results until after review.

Required change:

Define two-phase publication semantics, for example:

- deterministic validator emits `DRAFT_READY_PENDING_REVIEW`, `PARK_RESEARCH`, or `REJECT_MAPPING` plus full gate results;
- independent reviewer can approve only an immutable draft packet/run digest;
- finalization converts `DRAFT_READY_PENDING_REVIEW` to final `READY` only after reviewer approval and replay/hash verification;
- missing/negative review blocks finalization without changing the underlying deterministic gate findings.

Add tests for missing review, request-changes review, approved review, changed packet after review, and replay mismatch.

## Category checks

### Deterministic executability

REQUEST_CHANGES. The spec is mostly deterministic at schema/gate level, but the `UNKNOWN` exposure readiness rule and review/finalization sequencing must be made unambiguous before implementation.

### Historical issuer identity

Mostly acceptable. The issuer/security sections correctly reject ticker-only identity, require CIK/LEI/registry/effective intervals, distinguish parent/subsidiary/ADR/share class, and require active-at-`as_of` security selection. This area should become approvable after the web-evidence acceptance predicate is made concrete.

### Exposure materiality

REQUEST_CHANGES. The measurement hierarchy, calculation checks, anti-false-precision rules, and materiality bands are strong. The blocker is readiness semantics for `UNKNOWN` materiality and reviewer exceptions.

### Source provenance

REQUEST_CHANGES until the accepted-web-evidence predicate is explicit. The spec’s source hierarchy is strong, but it must say exactly which current/legacy evidence rows are ineligible and which snapshot/segment artifacts are sufficient.

### Temporal scope

Mostly acceptable. The spec repeatedly requires `as_of_utc`, filing availability cutoffs, amendment handling, effective intervals, and historical vintages. The main temporal risk is inherited from the undefined upstream evidence acceptance predicate.

### Missing-data / failure gates

Mostly acceptable. Missing data is usually parked rather than fabricated, and typed blockers/next actions are required. Tighten `UNKNOWN` exposure behavior and `BLOCKED_UPSTREAM_EVIDENCE` CLI/API semantics.

### Testability

Mostly acceptable. The frozen corpus, unit tests, property/metamorphic tests, chaos tests, and full regression gates are specific enough to guide implementation. Add tests for the blockers above.

### Minimal scope

Borderline but acceptable if sliced exactly as written. The full spec is broad, but the implementation sequence defers live acquisition, valuation, committee scoring, broker/order state, graph/vector databases, and agent swarms. Slice 0 should remain fixtures/contracts/tests only.

## Positive findings to preserve

- Strong research-only safety boundary: no orders, no broker/options/portfolio state mutation, and protected-state checks.
- Correct separation of source-derived explicit tickers from later analyst/official mappings.
- Strong issuer/security identity distinction; ticker alone is explicitly insufficient.
- Strong anti-false-precision language for exposure and materiality.
- Strong transcript/paywall/licensing controls.
- Good provenance requirements for SEC filings, amendments, XBRL context, periods, units, and source locators.
- Good property tests: reordering, duplicate origins, removing evidence, earlier `as_of`, ticker changes, and missing values.

## Verification performed

Targeted baseline from the spec was run under an isolated data root:

```text
MARKET_LAB_DATA_DIR=/tmp/mlab_company_intel_review_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_company_intel_review_pycache \
uv run pytest tests/market_lab/test_source_thesis.py \
              tests/market_lab/test_mlab_ingest.py \
              tests/market_lab/test_factors.py -q

16 passed in 0.31s
```

This confirms the cited current-source baseline still passes. It does not validate the future company-intelligence implementation, which does not exist yet.

## Final decision

REQUEST_CHANGES.

Approve after the missing R&D dependency is resolved/waived, `UNKNOWN` exposure readiness is made deterministic, accepted web-evidence input validation is made machine-checkable, and the review/finalization state machine is clarified.