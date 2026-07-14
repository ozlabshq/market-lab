# Re-Review — Agency Valuation and Investment Memo Spec

**Reviewed artifact:** `research/AGENCY_VALUATION_MEMO_SPEC.md`  
**Prior review:** `research/AGENCY_VALUATION_MEMO_SPEC_REVIEW.md`  
**Review date:** 2026-07-14 UTC  
**Reviewer:** ozzy-review  
**Decision:** APPROVE for Slice A implementation planning, subject to the spec's own acceptance gates and independent implementation review

## Bottom line

The corrected valuation/memo implementation spec closes every blocker from the prior independent review. I found no remaining spec-level blocker that should prevent the first implementation slice from beginning.

The updated document now gives implementers deterministic contracts for lease-adjusted capital structure, WACC weights, typed stable IDs, comparable sub-method identity, scenario-bound method results, terminal-value-share edge cases, and current diluted-share cutoff discipline. It also resolves the earlier non-blocking ambiguities around total-company display rounding, EBITDA/FCF formulas, peer TTM alignment, formula registry ownership, and web-evidence v2 dependency sequencing.

This approval is for the specification as a research-only implementation plan. It is not approval of any future valuation output, investment memo, committee decision, paper trade, or execution integration.

## Scope and method

I freshly reviewed the current corrected spec against the prior review's exact blockers and important non-blocking improvements. I did not edit `research/AGENCY_VALUATION_MEMO_SPEC.md`.

Checks performed:

- Re-read `research/AGENCY_VALUATION_MEMO_SPEC.md` and `research/AGENCY_VALUATION_MEMO_SPEC_REVIEW.md`.
- Verified every prior blocker has an explicit corrected contract in the current spec.
- Ran a marker check over the corrected spec for the required closure points: lease-adjusted EV/WACC, multi-component WACC, typed stable IDs, comparable metric results, scenario IDs, terminal-share denominator, share cutoff rules, display rounding, canonical comparable formulas, peer period policy, formula registry, and web-evidence dependency.
- Checked that the most dangerous obsolete snippets from the prior review are absent, including raw concatenated candidate IDs and the old two-component WACC form.

## Verdict by prior blocker

| Prior blocker | Current status | Evidence in corrected spec | Review result |
|---|---|---|---|
| 1. Lease adjustment omitted from enterprise-value formula | Closed | `lease_adjustment` is included in canonical EV (`research/AGENCY_VALUATION_MEMO_SPEC.md:392-402`), comparable EV-to-equity bridge (`740-755`), DCF equity bridge (`802-806`), and WACC lease component (`823-832`). Candidate/peer lease-policy consistency is required (`402`). | PASS |
| 2. WACC denominator and capital weights under-specified | Closed | WACC now defines `E + B + L + P + N` (`811-821`), keys the policy as `wacc.multi_component_gross_capital.v1` (`823`), uses cutoff market common equity and gross debt rather than DCF output equity or net debt (`825-830`), and defines preferred/NCI/lease treatment (`827-830`). | PASS |
| 3. Stable ID pseudocode conflicted with canonical JSON rule | Closed | IDs are expressed as `stable_id(domain, fields)` over canonical JSON with domain separation (`198-242`), including typed candidate/valuation/fact/peer/scenario/memo domains (`205-239`). Raw string concatenation is explicitly forbidden (`242`). | PASS |
| 4. Comparable-method reconciliation ambiguous across multiples | Closed | Each multiple is now a `ComparableMetricResult` (`457-484`), with roles assigned before seeing candidate implied values (`753`), parent comparables as a container only (`754`), metric-specific disagreements surfaced (`758`), and reconciliation units defined as base DCF plus each eligible comparable metric (`1019-1031`). | PASS |
| 5. Scenario method results lacked explicit scenario identity | Closed | `MethodResult` now includes `result_scope` and `scenario_id` with schema-invalid inconsistent scope/scenario pairs (`431-455`). `ScenarioValuation` references must match the same scenario ID (`508-529`), and verification rejects swapped labels/cross-scenario references/reused DCF artifacts (`950-963`). | PASS |
| 6. Terminal-value share gate needed a precise denominator policy | Closed | The spec defines `terminal_value_share.pv_over_ev.v1`, a positive finite EV requirement, a near-zero denominator floor, null/no-display behavior for invalid cases, and typed blockers for nonpositive/nonfinite/near-zero inputs (`834-845`). DCF structural gates consume those results (`846-866`). | PASS |
| 7. Share-count and dilution timing needed a stricter cutoff contract | Closed | `current_diluted_shares.v1` now requires the exact paired official-close timestamp, effective/available time constraints, after-hours filing handling, 120-day maximum age absent intervening events, split-basis consistency, and prohibition on reviewer override for post-price/post-cutoff/split mismatches (`624-633`). | PASS |

## Verdict by prior non-blocking improvement

| Prior improvement | Current status | Evidence | Review result |
|---|---|---|---|
| A. Clarify total-company display rounding | Closed | `company_value_scale` is explicitly defined from range endpoints/cutoff market cap with directed outward rounding and render-trace storage (`1038-1047`). | PASS |
| B. Define EBITDA and levered FCF formulas | Closed | MVP comparable formulas now define lease-adjusted EBITDA and levered FCF, including period/double-counting/SBC/dilution notes (`711-727`). | PASS |
| C. Add peer fiscal-period/calendarization policy | Closed | MVP rejects peer TTM period ends more than 90 days apart rather than silently calendarizing (`709`). | PASS |
| D. State web-evidence v2 dependency as implementation precondition | Closed | Slice B/live smoke are explicitly blocked until web-evidence v2 passes its own gates; fixture-only Slice A may proceed (`1583-1589`). | PASS |
| E. Add machine-readable formula registry | Closed | `valuation_contracts.py` must expose an immutable formula registry keyed by `formula_version` with exact formula metadata and MVP keys (`252-255`). | PASS |

## Fresh review notes

### Research-only safety remains intact

The corrected spec preserves a hard research-only boundary: the subsystem must not create, queue, size, approve, or execute orders (`9`, `26`), has explicit non-goals against broker/portfolio/candidate/options mutation (`82-99`), and requires before/after execution-state hashing in safety tests (`1365-1379`). `approved_research` is correctly scoped as memo-fidelity approval rather than approval to paper trade (`606`).

### Provenance and cutoff discipline remain strong

The evidence rule still requires every non-derived material value to resolve to `mlab-evidence.v2` records, verified snapshots, and exact segments (`649-660`). The availability-time rule is explicit for filings, market prices, capital structure, income/cash-flow facts, share count, and catalysts (`610-633`). The spec continues to reject synthetic/cache-synthetic facts and current-data leakage (`341-362`, `1066-1082`).

### Method reconciliation is now implementable

The biggest practical risk in the prior draft was accidental blending of unlike methods. The current reconciliation contract prevents that by separating base DCF, each comparable metric result, and reverse DCF roles (`1014-1032`). It requires material disagreement to be displayed rather than averaged or rank-selected (`1023-1028`).

### Scenario and memo fidelity are now testable

Scenario identity is durable through `scenario_id`, assumption hashes, method-result references, and verification of cross-scenario/dangling references (`508-529`, `950-963`). The memo contract requires JSON/Markdown agreement on numbers, statuses, catalysts, invalidations, and blockers (`985-1011`), which is enough to build deterministic renderer tests.

## Residual risks for implementation review

These are not spec blockers; they are implementation areas that should receive extra review when code lands:

1. Canonical decimal JSON and stable hashing must be implemented exactly, without Python float shortcuts.
2. Lease capitalization must avoid double-counting operating lease expense, ROU depreciation, and lease liabilities.
3. Current diluted-share reconstruction will be data-intensive; blocked outputs are preferable to stale or post-cutoff per-share values.
4. Comparable peer eligibility will require reviewer discipline so LLM/search-provider peer suggestions do not silently become economic peers.
5. The safety-state verifier should be treated as a first-class acceptance gate, not a post-hoc smoke test.

## Final decision

APPROVE.

All seven prior blockers are closed in the corrected specification, and the five prior non-blocking improvements have been incorporated sufficiently for implementation planning. Slice A may proceed using frozen provenance-complete fixtures, with Slice B/live acquisition remaining gated on accepted web-evidence v2 implementation as the spec requires.
