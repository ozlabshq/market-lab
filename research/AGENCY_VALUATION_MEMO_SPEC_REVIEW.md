# Independent Review — Agency Valuation and Investment Memo Spec

**Reviewed artifact:** `research/AGENCY_VALUATION_MEMO_SPEC.md`  
**Review date:** 2026-07-14 UTC  
**Reviewer:** ozzy-review  
**Decision:** REQUEST_CHANGES before treating the spec as implementation-ready

## Bottom line

The spec is directionally strong and unusually careful on provenance, cutoff integrity, no-false-precision, scenario discipline, and research-only safety. It correctly refuses synthetic inputs, hidden defaults, point targets, unreviewed source claims, and execution-state mutation.

I would not yet approve it as implementation-ready because several formula/policy seams can create real valuation inconsistency even if engineers implement the document literally. The highest-risk issues are the lease/capital-structure bridge, WACC capital-weight policy, ambiguous hash/ID construction, comparables metric reconciliation, and scenario/method identity. These should be fixed in the spec before implementation starts so the first code slice does not encode inconsistent accounting semantics.

## Scope reviewed

I reviewed the spec for:

- formula correctness and economic consistency;
- units, periods, time cutoffs, and valuation as-of handling;
- evidence/provenance requirements against the current MLAB and web-evidence contracts;
- no-false-precision controls;
- missing data behavior;
- scenario and method reconciliation logic;
- testability and acceptance criteria;
- MVP scope and safety boundaries.

Context checked in the repository:

- `market_lab/source_thesis.py` — current `SourceClaim` provenance fields;
- `market_lab/mlab_ingest.py` — claim IDs, run artifacts, finalization gates, independent review requirement;
- `market_lab/factors.py` — lightweight float-based factor snapshots and synthetic factor placeholders;
- `market_lab/config.py` and `market_lab/broker.py` — research-only risk flags and mock broker refusal of live-trading mode;
- `research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md` — valuation/thesis gaps and promotion gates;
- `/Users/ozlabs/OzLabs/docs/market-lab/WEB_EVIDENCE_IMPLEMENTATION_SPEC.md` — immutable snapshots, evidence segments, and schema-v2 evidence rows.

I did not edit `research/AGENCY_VALUATION_MEMO_SPEC.md`.

## Verdict by review dimension

| Dimension | Verdict | Notes |
|---|---|---|
| Research-only safety | PASS | The spec repeatedly forbids broker/order/portfolio/options mutation and requires before/after state hashing. |
| Provenance discipline | PASS with minor dependency note | Strong evidence-v2, snapshot, segment, cutoff, and locator requirements. Implementation depends on the accepted web-evidence layer being available or fixture-mocked. |
| Temporal/cutoff logic | PASS with additions needed | Availability-time rules are solid. Add sharper policies for share-count timing, peer fiscal-period alignment, and current-vs-historical dilution. |
| Unit correctness | REQUEST_CHANGES | Unit rules are strong, but capital-structure/WACC/lease semantics are not fully closed. |
| Formula correctness | REQUEST_CHANGES | DCF core math is mostly right, but lease adjustment, WACC weights, terminal-value share denominator, and comparable metric reconciliation need correction/clarification. |
| No false precision | PASS with minor clarification | Good range/rounding/display policy. Total-company display rounding needs a less ambiguous “value scale” definition. |
| Missing data behavior | PASS | The spec correctly says missing facts remain missing and blocked methods emit no values. |
| Scenario logic | REQUEST_CHANGES | Bull/base/bear operating-state discipline is good, but method results need scenario identity and reconciliation semantics. |
| Valuation as-of dates | PASS with additions needed | Good cutoff and availability rules. Add explicit tests for same-day market close, after-hours filings, amendments, and share-count cutoff mismatches. |
| Testability | PASS with additions needed | The test plan is broad and deterministic. Add targeted cases for the blockers below. |
| MVP scope | PASS | The slice is appropriately flat, standard-library first, and excludes banks/REITs/non-USD/options/consensus/SDKs. |

## Blocking issues to fix in the spec

### 1. Lease adjustment is defined but omitted from the enterprise-value formula

The `CapitalStructure` schema includes `lease_adjustment`, but the canonical enterprise-value formula is:

```text
enterprise_value = market_cap
                 + short_term_debt + long_term_debt
                 + preferred_equity + noncontrolling_interest
                 - cash_and_equivalents - eligible_non_operating_investments
```

This creates an implementation ambiguity: either lease obligations are debt-like and should enter EV/WACC/multiples, or they are deliberately excluded with a documented policy. The current text says “policy and evidence required” but does not define how the number affects EV, DCF, or peer comparability.

Required spec fix:

- define whether `lease_adjustment` is added to enterprise value in MVP;
- define whether it is included in debt for WACC weights and post-tax cost of debt;
- require peer/candidate consistency for lease treatment;
- add tests where including vs excluding leases changes EV/EV-EBITDA and the implementation must choose the documented policy.

### 2. WACC denominator and capital weights are under-specified

The WACC formula uses:

```text
WACC = E/(D+E) * cost_of_equity + D/(D+E) * post_tax_cost_of_debt
```

But the capital-structure schema includes short-term debt, long-term debt, leases, preferred equity, noncontrolling interest, cash, and non-operating investments. The spec does not say whether `D` is book debt, market debt, lease-adjusted debt, gross debt, net debt, or includes preferred/NCI in a separate capital component. It also does not explicitly say whether `E` is market common equity at cutoff or an output value from the valuation model; using output equity value in WACC would create circularity.

Required spec fix:

- define each WACC capital component and source hierarchy;
- state that MVP uses cutoff market common equity for capital weights unless a separately reviewed policy is chosen;
- define treatment for preferred equity, NCI, and leases;
- explicitly reject netting cash into `D` unless a documented policy does so;
- add fixtures covering gross debt vs net debt, preferred equity, and lease-adjusted capital weights.

### 3. Stable ID pseudocode conflicts with the canonical JSON rule

The spec says IDs use canonical UTF-8 JSON, but the displayed formulas read like raw concatenation:

```text
candidate_id = sha256(run_id + issuer_id + security_id + mapping_rationale_hash)
```

Raw concatenation is ambiguous without separators or typed fields: `ab|c` and `a|bc` style collisions are easy if implementers follow the pseudocode literally.

Required spec fix:

- rewrite ID inputs as canonical JSON objects or arrays with named fields and schema versions;
- include domain-separation prefixes such as `mlab-candidate-id.v1`;
- add a regression test proving ambiguous string concatenations do not collide.

### 4. Comparable-method reconciliation is ambiguous when several multiples are available

The spec treats comparables as one method but MVP supports EV/revenue, EV/EBITDA, P/E, and FCF yield. It does not fully define how those metric-level ranges become method-level outputs, which metrics are primary vs cross-check, or how conflicts among valid multiples are surfaced.

Risk: an implementation could average EV/revenue, EV/EBITDA, and P/E into one “comps value” despite the no-blending policy, or could let a weak metric override a better-supported one.

Required spec fix:

- model each comparable multiple as its own metric result or sub-method result;
- require metric roles before viewing attractiveness;
- define whether method reconciliation operates across comparable sub-methods, DCF, and reverse DCF separately;
- add tests where EV/revenue and P/E disagree materially and the memo must surface the disagreement rather than blend it.

### 5. Scenario method results need explicit scenario identity

`ScenarioValuation` contains `method_results[]`, while `MethodResult` has assumptions but no explicit `scenario_id` or `scenario_name`. If DCF is computed under bear/base/bull assumptions, the method result needs a durable scenario link. Otherwise, memo JSON/Markdown fidelity and audit traces can confuse base DCF with bull/bear DCF.

Required spec fix:

- add `scenario_id` or `scenario_name` to `MethodResult`, or define a wrapper that binds method results to scenarios;
- state whether non-scenario method results are allowed for market/current comparables;
- add a test that swapped scenario labels or method-result references are caught.

### 6. Terminal-value share gate needs a precise denominator policy

The spec blocks DCF when terminal value exceeds 85% of enterprise value and warns above 70%. This is sensible, but the denominator can become misleading when explicit-period PV is negative, EV is near zero, or EV is negative. A naive `terminal_value / enterprise_value` can produce negative or nonsensical percentages.

Required spec fix:

- define terminal-value share as PV terminal value divided by enterprise value only when enterprise value is positive and finite;
- define blocker behavior for zero/negative EV, negative PV terminal value, or negative explicit PV combinations;
- add DCF tests for low/negative EV and negative explicit FCFF paths.

### 7. Share-count and dilution timing require a stricter cutoff contract

The spec correctly distinguishes weighted-average diluted shares for EPS from current diluted shares for per-share equity value. It also says current diluted share estimates need policy notes. The remaining gap is the exact cutoff policy for a historical valuation when share count data are stale, post-cutoff, affected by a split, or sourced from a filing after the market-price timestamp.

Required spec fix:

- require `available_at_utc` and `effective_as_of_utc` for current diluted-share estimates;
- define how to handle after-hours filings relative to an official-close price;
- require split-adjusted consistency between price and shares;
- add tests for post-cutoff 10-Q share data leaking into an earlier valuation.

## Non-blocking but important improvements

### A. Clarify total-company display rounding

The no-false-precision rule says modeled currency values should display with at most three significant digits and a minimum rounding increment equal to the larger of 1% of cutoff price/value scale or tick. “Value scale” is underspecified for enterprise value, market cap, revenue, and FCFF values.

Suggested fix: define display units and increments by field family, e.g. per-share dollars, total company USD millions/billions, rates, and multiples.

### B. Define EBITDA and levered FCF formulas explicitly

The spec requires reviewed definitions but should still provide MVP canonical formulas or formula-version contracts for:

- TTM EBITDA from operating income plus D&A, with period compatibility checks;
- levered FCF and whether it includes interest, debt repayment, SBC treatment, and working-capital policy.

Without this, two compliant implementations could produce different comparable multiples.

### C. Add peer fiscal-period/calendarization policy

Peer eligibility checks mention accounting-period fit, but the comparable calculation section should say what happens when peer fiscal years differ, recent quarter availability differs, or TTM windows are offset. MVP can reject incompatible fiscal windows rather than calendarize, but the policy should be explicit.

### D. State the dependency on web-evidence v2 as an implementation precondition

The spec references accepted `mlab-evidence.v2` records and immutable snapshots. That is correct. Since this valuation subsystem cannot safely resolve live inputs without that layer, the implementation sequence should state:

- Slice A can use frozen fixtures without live evidence acquisition;
- Slice B and live smoke cannot start until web-evidence v2 artifacts exist and pass their own acceptance tests.

### E. Add a machine-readable formula registry

The spec uses `formula_version`, but does not define where formulas are registered. A small registry in the contracts or methods module would make audit traces and tests easier.

## Strong points to preserve

- The hard rule that a number is not an input until issuer/concept/unit/scope/period/availability/source/locator/transformation lineage are validated is exactly right.
- The spec correctly rejects `FactorSnapshot`, `yfinance_info`, search snippets, synthetic/cache-synthetic prices, and LLM-generated numbers as audited valuation inputs.
- Availability-time rules are strong and should prevent lookahead if implemented literally.
- Missing facts remain missing; no silent zero/default policy is allowed.
- Blocked/not-applicable methods emit no numeric value.
- Reverse DCF is correctly labeled as market-implied expectations and excluded from fair-value blending.
- Bull/base/bear scenarios are operating states, not output haircuts.
- The memo content contract requires contrary evidence, unknowns, blockers, invalidation triggers, freshness, and independent review.
- Safety tests hash broker/order/options/independent-track state before and after valuation commands.
- The MVP scope is appropriately narrow: mature US-listed non-financial operating companies, USD only, standard library first, no vendor valuation SDK, no portfolio action.

## Additional tests I would add before approval

1. `lease_adjustment_changes_ev_and_wacc_weights` — proves documented lease policy affects EV and WACC consistently.
2. `wacc_rejects_ambiguous_capital_component_policy` — preferred/NCI/lease/debt cases cannot silently pass without policy.
3. `stable_ids_use_canonical_typed_inputs_not_concat` — ambiguous raw concatenation examples do not collide.
4. `comparable_sub_methods_disagree_without_blending` — EV/revenue and P/E both valid but materially disagree; memo surfaces disagreement.
5. `scenario_method_result_swap_detected` — base/bull DCF method-result references swapped between scenarios cause verification failure.
6. `terminal_value_share_negative_or_zero_ev_blocks` — near-zero/negative EV does not produce a fake terminal-share percentage.
7. `after_hours_filing_share_count_cutoff` — share count filed after close cannot support same-close per-share valuation unless policy explicitly allows pairing.
8. `peer_fiscal_period_mismatch_blocks_or_labels` — peer TTM periods with incompatible cutoffs do not enter the same distribution.
9. `total_company_rounding_policy` — EV/equity/revenue display units obey deterministic no-false-precision increments.
10. `ebitda_formula_version_trace` and `levered_fcf_formula_version_trace` — comparable denominator definitions are auditable and reproducible.

## Final recommendation

Request changes to close the formula and identity seams above, then approve the spec for Slice A implementation. The document is already strong enough to guide the safety/provenance posture, but the capital-structure, WACC, comparable reconciliation, and scenario-linkage issues are the kinds of ambiguities that become expensive to unwind after tests and artifacts are built around them.

Until those fixes land, implementation should be limited to exploratory spike work or fixture design, not production code paths that claim conformance to this spec.
