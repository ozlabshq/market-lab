# Market Lab Agency Valuation and Investment Memo — Implementation Spec

**Status:** Implementation-ready independent specification, corrected after independent review; the commissioned valuation R&D brief was unavailable and is not represented as a source; no product code in this change

**Date:** 2026-07-14 UTC

**Scope:** Sourced valuation and research-memo generation for the Market Lab virtual analyst agency

**Safety posture:** Research/mock/paper only. This subsystem must never create, queue, size, approve, or execute an order.

---

## 1. Decision

Build a deterministic, evidence-addressed valuation kernel and memo assembler inside an existing MLAB research run.

The first production slice must:

1. accept one explicitly mapped US-listed common-equity candidate and a frozen analysis cutoff;
2. resolve every reported financial, capital-structure, market, peer, catalyst, and thesis input to acquired evidence;
3. compute comparable-company ranges, an FCFF DCF when eligible, and a one-variable reverse DCF when eligible;
4. express uncertainty through bull/base/bear scenarios, sensitivity tables, method status, blockers, and ranges rather than a single target-price claim;
5. render a structured JSON artifact and a human-readable memo from the same typed model;
6. record catalysts, measurable invalidation conditions, contrary evidence, and evidence freshness;
7. fail closed on missing provenance, stale/incompatible periods, unsupported units, synthetic inputs, circular assumptions, or invalid method economics; and
8. leave all broker, candidate queue, portfolio, option, and live-trading state untouched.

Hard rule:

> A number is not a valuation input merely because it appears in a filing, provider response, spreadsheet, search result, model answer, or narrative. It becomes an input only after its issuer, concept, units, scope, reference period, availability time, source artifact, exact locator, and transformation lineage are recorded and validated for the analysis cutoff.

The output is a bounded research range and an audit trail, not an investment recommendation and not a promise that a security is a “winner.”

---

## 2. Current-system boundary and gaps

### 2.1 Existing contracts to preserve

The implementation must extend, not replace, these current boundaries:

- The canonical roadmap describes valuation and agency-grade thesis scoring as missing (`research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md:112-115`, `467-477`) and requires falsification criteria, benchmarks, uncertainty, and base-rate comparison before promotion (`248-275`).
- `SourceClaim` preserves source URL, artifact, author, capture time, and citation (`market_lab/source_thesis.py:74-82`).
- `ClaimRecord` adds a stable `claim_id` and adjudication fields (`market_lab/mlab_ingest.py:33-45`); its ID is content-derived (`114-125`).
- MLAB runs already own `status.json`, `claims.json`, `evidence.jsonl`, `audit_log.jsonl`, review, and next-action artifacts (`market_lab/mlab_ingest.py:64-97`). The valuation layer must not create a competing run lifecycle.
- Finalization currently blocks unsupported, contradictory, or unresolved claim states and requires independent review and owned next actions (`market_lab/mlab_ingest.py:643-709`).
- The accepted web-evidence specification defines immutable snapshots, exact evidence segments, temporal fields, source lineage, and schema-v2 claim-evidence links (`/Users/ozlabs/OzLabs/docs/market-lab/WEB_EVIDENCE_IMPLEMENTATION_SPEC.md:95-202`). Valuation inputs must reference those artifacts rather than free-text notes.
- `FactorSnapshot` currently contains P/E, P/B, revenue growth, gross margin, FCF yield, an as-of date, and one source label (`market_lab/factors.py:13-40`). It remains a light signal overlay, not a valuation source of truth.
- Synthetic factors are explicitly placeholders, not evidence (`market_lab/factors.py:111-127`).
- The daily report labels its factor section a lens and renders single-point provider values (`market_lab/report.py:199-210`). The new memo must not relabel those values as audited valuation.
- Research-only/live-disabled risk flags are frozen in `market_lab/config.py:48-84`; `broker.evaluate_order` rejects an unexpectedly enabled live flag (`market_lab/broker.py:160-164`).

### 2.2 Gaps this slice closes

The repository has no current contract for:

- issuer/security/capital-structure identity at an analysis cutoff;
- XBRL concept, fiscal period, amendment, unit, and filing-availability lineage;
- normalized enterprise value and diluted share count;
- comparable peer eligibility and multiple normalization;
- DCF formulas, forecast assumptions, terminal-value constraints, or sensitivity;
- reverse-DCF expectations and solver diagnostics;
- scenario-specific assumptions and outcomes;
- catalyst/invalidation monitoring records;
- memo-level evidence completeness, uncertainty, method disagreement, and no-false-precision gates; or
- a machine-verifiable statement that a memo did not mutate execution state.

### 2.3 Explicit non-reuse

Do not use the following as audited valuation inputs without upgrading them through the evidence contract:

- `FactorSnapshot` values or `yfinance_info` fields;
- search snippets or provider-generated summaries;
- synthetic factors or synthetic/cache-synthetic prices;
- model-generated peer sets, forecasts, WACC, terminal growth, or probabilities;
- source-post claims that have not been independently adjudicated;
- current values fetched after the analysis cutoff for a historical run; or
- displayed memo numbers parsed back into calculations.

---

## 3. Non-goals

Version 1 must not:

- support banks, insurers, broker-dealers, REIT-specific NAV/FFO, partnerships, closed-end funds, SPACs, crypto assets, private companies, or option valuation;
- build a universal accounting normalizer;
- forecast quarterly earnings, produce consensus estimates, or scrape/paywall-bypass analyst research;
- infer a peer set solely from text similarity or an LLM;
- use a model to perform arithmetic, solve a DCF, select a multiple, or silently repair missing data;
- produce a single authoritative price target;
- optimize scenario probabilities to match the current price;
- turn valuation upside into conviction, ranking, sizing, or an order;
- update broker, portfolio, candidate, option, or live-execution artifacts;
- make automated claim dispositions or approve its own memo;
- add a graph database, workflow engine, vector database, notebook runtime, or vendor valuation SDK; or
- claim that a filed value is economically comparable merely because it shares a label.

Companies outside the MVP must return `unsupported_company_type` with an owned next action, not a plausible-looking generic DCF.

---

## 4. MVP eligibility envelope

A candidate is eligible for the first slice only when all are true:

- US-listed common equity;
- SEC-reporting operating company with resolved CIK and security identifier;
- reporting currency and valuation currency are USD;
- at least three annual periods of reported revenue and the fields required by the chosen method;
- a validated common-share market price and diluted share count at or before the cutoff;
- no unresolved stock split, major acquisition/disposition, restatement, or class-conversion event that makes the input periods incomparable;
- candidate mapping has an explicit thesis/candidate rationale and benchmark/control context;
- material source claims used by the memo are `VERIFIED` or `MIXED` with both branches represented; and
- at least one valuation method can pass all of its method-specific gates.

Version 1 supports mature non-financial operating companies. Negative current earnings do not automatically block all valuation, but they block P/E and can block DCF if a path to cash generation cannot be expressed without unsupported assumptions. A memo may validly end in `BLOCKED` or `NO_VALUATION`.

---

## 5. Proposed future code and test layout

The project currently packages a flat `market_lab` module list. Keep the first implementation bounded and flat:

```text
market_lab/valuation_contracts.py       # enums, dataclasses, canonical serialization
market_lab/valuation_inputs.py          # evidence resolution, period/unit normalization
market_lab/valuation_methods.py         # comparables, FCFF DCF, reverse DCF, sensitivity
market_lab/investment_memo.py           # scenarios, catalysts, invalidations, rendering
market_lab/valuation_store.py           # atomic artifacts, hashes, audit integration
market_lab/valuation_runner.py          # resumable orchestration and gates
market_lab/valuation_cli.py             # build, render, verify, benchmark
scripts/market_lab_valuation.py

tests/market_lab/
  test_valuation_contracts.py
  test_valuation_inputs.py
  test_valuation_comparables.py
  test_valuation_dcf.py
  test_valuation_reverse_dcf.py
  test_valuation_scenarios.py
  test_investment_memo.py
  test_valuation_gates.py
  test_valuation_pipeline.py
  test_valuation_cli.py
  test_valuation_benchmark.py
  fixtures/valuation/
```

Use the Python standard library first: frozen dataclasses, `Enum`, `Decimal`, `datetime`, `hashlib`, and canonical JSON. Do not add NumPy, pandas, SciPy, Pydantic, a templating engine, or a finance package for this slice. A small deterministic bisection solver is sufficient for reverse DCF.

---

## 6. Run-local artifacts

Valuation lives under the existing MLAB run:

```text
<run>/
  status.json
  claims.json
  evidence.jsonl
  audit_log.jsonl
  web_evidence/...
  valuation/
    request.json
    input_facts.jsonl
    normalized_financials.json
    peer_set.json
    method_comparables.json
    method_dcf.json
    method_reverse_dcf.json
    scenarios.json
    catalysts.json
    invalidations.json
    gate_report.json
    memo.json
    memo.md
    manifest.json
```

Rules:

- `memo.json` is canonical; `memo.md` is a pure rendering of it.
- Every artifact has `schema_version`, `run_id`, `candidate_id`, `analysis_cutoff_utc`, `created_at_utc`, `generator_version`, and a content hash.
- Derived artifacts list all input artifact hashes.
- Finalized MLAB runs remain immutable. Revaluation requires a new run or a new immutable valuation version linked by `supersedes_valuation_id`.
- Writes use temp file, flush, `fsync`, atomic rename, then an audit event. A manifest is committed last.
- Resume verifies hashes and skips an operation only when its idempotency key and dependency hashes match.
- No generated valuation artifact is stored in `market_lab/factors.py` CSV files or broker state.

---

## 7. Canonical identities and versions

### 7.1 Stable IDs

```text
stable_id(domain, fields) = sha256(UTF8(canonical_json({
  "domain": domain,
  "id_schema_version": "mlab-stable-id.v1",
  "fields": fields
})))

candidate_id = stable_id("mlab-candidate-id.v1", {
  "issuer_id": issuer_id,
  "mapping_rationale_hash": mapping_rationale_hash,
  "run_id": run_id,
  "security_id": security_id
})
valuation_id = stable_id("mlab-valuation-id.v1", {
  "analysis_cutoff_utc": analysis_cutoff_utc,
  "candidate_id": candidate_id,
  "request_hash": request_hash
})
fact_id = stable_id("mlab-financial-fact-id.v1", {
  "concept": concept,
  "issuer_id": issuer_id,
  "period": period_object,
  "source_segment_id": source_segment_id,
  "transformation": transformation_object,
  "units": units
})
peer_set_id = stable_id("mlab-peer-set-id.v1", {
  "analysis_cutoff_utc": analysis_cutoff_utc,
  "candidate_id": candidate_id,
  "peer_eligibility_record_hashes": sorted_unique_record_hashes
})
scenario_id = stable_id("mlab-scenario-id.v1", {
  "assumption_set_hash": assumption_set_hash,
  "scenario_name": scenario_name,
  "valuation_id": valuation_id
})
memo_id = stable_id("mlab-memo-id.v1", {
  "method_hashes": sorted_unique_method_hashes,
  "scenario_hashes": sorted_unique_scenario_hashes,
  "thesis_hash": thesis_hash,
  "valuation_id": valuation_id
})
```

Canonical JSON means Unicode NFC strings, lexicographically sorted object keys, no insignificant whitespace, decimal values serialized as normalized decimal strings, UTC timestamps normalized to `YYYY-MM-DDTHH:MM:SS[.ffffff]Z`, and rejection of floats, NaN, infinity, duplicate keys, or implicit null/default fields. Arrays preserve order when order is semantic; set-like arrays are deduplicated and lexicographically sorted before hashing. The domain string is mandatory domain separation and is not concatenated outside the JSON object. Full SHA-256 is stored in artifacts; UI/reporting may show a short prefix but must never persist only the prefix. Raw string concatenation is forbidden for IDs, hashes, semantic keys, and idempotency keys.

### 7.2 Version rules

- Financial restatements create new facts; they do not overwrite prior facts.
- A later filing can supersede a current-view fact but cannot enter a historical `as_of` run if it was unavailable at the cutoff.
- Scenario changes create a new valuation version.
- Rendering changes alone may update `renderer_version` without changing the memo’s semantic hash.
- A memo is stale when any required source passes its freshness SLA, a superseding filing is detected, the market-price cutoff changes, or a material catalyst/invalidation event occurs.

### 7.3 Formula registry

`valuation_contracts.py` must expose an immutable registry keyed by `formula_version`. Each entry contains the exact symbolic formula, required input concepts, units, period rules, capital-structure policy version, and implementation function name. Method artifacts reject an unknown formula version. MVP registry keys include at least `enterprise_value.lease_adjusted.v1`, `wacc.multi_component_gross_capital.v1`, `ttm_ebitda.lease_adjusted.v1`, `levered_fcf.cfo_less_capex.v1`, `comparable_implied_value.v1`, `fcff_dcf.gordon.lease_adjusted.v1`, and `terminal_value_share.pv_over_ev.v1`. Changing economic semantics requires a new key; display-only changes do not.

---

## 8. Core schemas

All numeric JSON fields described below are serialized as decimal strings, not binary floating-point values. Currency is ISO 4217. Percent/rate fields are unit fractions (`0.10` means 10%). Dates and timestamps are ISO 8601 UTC.

### 8.1 `ValuationRequest`

```text
schema_version = "mlab-valuation-request.v1"
run_id
candidate_id
issuer_id                 # CIK-based for MVP
security_id               # ticker plus exchange and share class
analysis_cutoff_utc
valuation_currency = "USD"
requested_methods[]       # comparables | dcf_fcff | reverse_dcf
forecast_years            # 5 in MVP; explicit, never inferred
terminal_method           # gordon_growth; exit_multiple only a cross-check in MVP
scenario_names            # exactly bear, base, bull
source_claim_ids[]
company_profile_artifact_id
requested_by
research_only = true
```

Validation rejects a future cutoff, unsupported currency/company type, missing candidate mapping, unknown claim IDs, any scenario set other than bear/base/bull, or `research_only != true`.

### 8.2 `FinancialFact`

```text
schema_version = "mlab-financial-fact.v1"
fact_id
issuer_id
concept                    # normalized internal concept
source_concept             # e.g. exact XBRL tag or table label
value
units
currency
scale                       # 1, 1000, 1000000; explicit
fiscal_period_type          # instant | quarter | year | TTM
period_start / period_end
filed_at_utc
available_at_utc
form / accession / amendment
source_snapshot_id
source_segment_id
exact_locator
source_tier
origin_cluster_id
is_audited
is_company_stated
restatement_status
transformation             # none or formula with input fact IDs
quality_flags[]
```

Required normalized concepts for the full MVP path:

```text
revenue
operating_income
income_tax_expense
pretax_income
net_income_common
cash_and_equivalents
total_debt
preferred_equity
noncontrolling_interest
depreciation_amortization
capital_expenditures
change_in_net_working_capital
stock_based_compensation
basic_shares
diluted_weighted_average_shares
options_rsus_incremental_shares
net_cash_from_operations
lease_liabilities_current
lease_liabilities_noncurrent
operating_lease_expense
right_of_use_asset_depreciation
```

A missing concept remains absent. Never coerce it to zero unless the source explicitly reports zero or a reviewed transformation proves zero.

### 8.3 `MarketFact`

```text
schema_version = "mlab-market-fact.v1"
market_fact_id
security_id
timestamp_utc
session_date
price_type                 # official_close | adjusted_close | last
price
currency
shares_outstanding
market_cap                 # derived; includes input IDs
split_adjustment_factor
source_snapshot_id
source_segment_id
provider_id
source_status
quality_flags[]
```

Synthetic, `cache_synthetic`, undated, post-cutoff, wrong-share-class, or unresolved split-adjustment inputs are blocking. Plain cache may be used only when its observation timestamp, original provider, artifact hash, and freshness are preserved; a source label of only `cache` is insufficient.

### 8.4 `CapitalStructure`

```text
schema_version = "mlab-capital-structure.v1"
as_of_utc
market_cap
cash_and_equivalents
non_operating_investments
short_term_debt
long_term_debt
lease_adjustment           # current + non-current lease liabilities not already in debt
lease_policy_version       # lease_adjusted_debt.v1 in MVP
preferred_equity
noncontrolling_interest
enterprise_value
basic_shares
diluted_shares
share_count_effective_as_of_utc
share_count_available_at_utc
share_count_price_timestamp_utc
share_count_split_basis
share_count_policy_version
net_debt
input_fact_ids[]
policy_notes[]
gate_status
```

Canonical formula:

```text
enterprise_value = market_cap
                 + short_term_debt + long_term_debt
                 + lease_adjustment
                 + preferred_equity + noncontrolling_interest
                 - cash_and_equivalents - eligible_non_operating_investments
```

MVP uses `lease_adjusted_debt.v1`: `lease_adjustment` is the evidenced current plus non-current operating and finance lease liability not already included in short- or long-term debt. It is debt-like in enterprise value, the DCF equity bridge, WACC capital weights, and peer EV calculations. A reconciliation must prove that lease liabilities were not double-counted in reported debt. Candidate and every peer in a given EV-multiple distribution must use the same lease policy version; otherwise that peer/metric is blocked as `inconsistent_lease_policy`. An unadjusted metric may be shown only as a separately labeled cross-check with an independently constructed unadjusted distribution, never mixed with lease-adjusted observations.

Every adjustment must have an input fact or be an explicit zero reported by a source. Do not silently treat debt, leases, preferred equity, minority interest, or non-operating assets as zero. `net_debt` is a displayed derived fact only; it is not substituted for gross debt in WACC.

For the per-share equity bridge, `diluted_shares` means the evidenced current basic shares plus incremental dilution under `current_diluted_shares.v1`, an explicit treasury-stock/if-converted policy. It is not interchangeable with period-weighted diluted shares used for EPS. The policy, security terms, cutoff market price, and all included/excluded options, RSUs, convertibles, and share classes must be preserved in `policy_notes` and input lineage; unresolved material dilution blocks per-share output. Section 9.1 defines the effective-time, availability, staleness, and split gates.

### 8.5 `ForecastAssumption`

```text
schema_version = "mlab-forecast-assumption.v1"
assumption_id
scenario_name
metric                     # revenue_growth, EBIT_margin, tax_rate, D&A, capex, delta_NWC, WACC, terminal_growth
forecast_period
value_or_range
units
basis                      # reported_history | management_guidance | industry_base_rate | analyst_judgment
source_claim_ids[]
evidence_ids[]
rationale
counterevidence_ids[]
uncertainty                 # low | medium | high
reviewer_status
```

`analyst_judgment` is allowed but never disguised as evidence. A material judgment must include rationale, a bounded range, and counterevidence or an explicit statement that none was found after the required search lane.

### 8.6 `MethodResult`

```text
schema_version = "mlab-valuation-method-result.v1"
method_id
method_type
result_scope                # scenario | market_current | market_implied
scenario_id                # required for scenario; null otherwise
method_role                # primary | cross_check | blocked | not_applicable
status                     # calculated | blocked | not_applicable | review_required | approved
analysis_cutoff_utc
input_fact_ids[]
assumption_ids[]
formula_version
enterprise_value_range
common_equity_value_range
per_share_value_range
sensitivity_rows[]
quality_flags[]
blockers[]
role_rationale
calculation_trace[]
reviewer
reviewed_at_utc
```

No blocked/not-applicable method emits a numeric value. Solver traces store brackets and convergence status, not hundreds of false-precision iterations. A DCF method result is scenario-bound and must carry the exact `scenario_id`; a market-current comparable result and a market-implied reverse DCF carry `scenario_id = null`. A result with an inconsistent scope/scenario pair is schema-invalid.

### 8.6.1 `ComparableMetricResult`

Each supported multiple is a separate sub-method result; there is no numeric parent “comparables” range.

```text
schema_version = "mlab-comparable-metric-result.v1"
comparable_metric_id
method_id
metric_type                 # ev_revenue | ev_ebitda | pe | fcf_yield
method_role                 # assigned before candidate implied value is viewed
role_rationale
formula_version
lease_policy_version
denominator_definition
candidate_denominator_fact_ids[]
peer_set_id
included_peer_observations[]
excluded_peer_observations[]
distribution
implied_enterprise_value_range
implied_common_equity_value_range
implied_per_share_value_range
status / quality_flags[] / blockers[]
calculation_trace[]
```

`comparable_metric_id` uses `stable_id("mlab-comparable-metric-id.v1", {"formula_version": ..., "metric_type": ..., "peer_set_id": ..., "valuation_id": ...})`. The containing `MethodResult` has `result_scope = market_current` and `scenario_id = null`.

### 8.7 `PeerEligibilityRecord`

```text
schema_version = "mlab-peer-eligibility.v1"
peer_issuer_id / peer_security_id
candidate_peer_role        # included | excluded | watch
business_model_fit
revenue_mix_fit
geography_fit
size_fit
margin/growth_regime_fit
capital_intensity_fit
accounting_period_fit
share_class_fit
financial_company_flag
selection_source_ids[]
selection_rationale
exclusion_reason
reviewer_status
```

A peer must be selected for economic comparability, not because a search provider, LLM, or finance site listed it. Both inclusions and exclusions are preserved.

### 8.8 `ScenarioValuation`

```text
schema_version = "mlab-scenario-valuation.v1"
scenario_id
name                       # bear | base | bull
description
assumption_ids[]
method_result_ids[]
revenue_path[]
margin_path[]
fcff_path[]
common_equity_value_range
per_share_value_range
upside_downside_range_vs_cutoff_price
scenario_probability       # nullable in MVP
probability_basis           # nullable; never implied
key_dependencies[]
quality_flags[]
```

Every referenced method result must have `result_scope = scenario` and the same `scenario_id` as its `ScenarioValuation`; duplicate, missing, cross-scenario, or dangling references are hard failures. Market-current comparables and market-implied reverse DCF results are allowed outside scenarios but must not appear in `method_result_ids[]`. The memo always shows unweighted scenarios. Probability-weighted expected value is omitted in MVP unless probabilities are independently reviewed, sum exactly to one, and are labeled subjective. Absence of probabilities is not an error.

### 8.9 `Catalyst`

```text
schema_version = "mlab-catalyst.v1"
catalyst_id
title
mechanism                   # how the event could change cash flows, risk, or multiple
expected_window_start / expected_window_end
status                      # expected | occurred | delayed | cancelled | unconfirmed
materiality                 # low | medium | high
direction                   # positive | negative | two_sided
dependency_claim_ids[]
evidence_ids[]
confirmation_source_requirement
monitoring_query_or_identifier
last_checked_at_utc
next_review_at_utc
uncertainty
```

A calendar date without a mechanism is not a catalyst. A management aspiration without an external/filing event is `unconfirmed` and cannot satisfy the catalyst gate.

### 8.10 `InvalidationCondition`

```text
schema_version = "mlab-invalidation-condition.v1"
invalidation_id
thesis_component
observable_metric_or_event
operator                    # lt | lte | gt | gte | eq | event_occurs | event_absent_by
threshold / units
observation_window
required_source_class
monitoring_identifier
severity                    # review | thesis_broken
linked_assumption_ids[]
linked_claim_ids[]
action_on_trigger            # force_review | mark_rejected; never trade
rationale
status                       # active | triggered | cleared | expired | unobservable
```

Every material thesis component needs at least one measurable condition. “The story changes,” “competition increases,” and “growth disappoints” are not valid conditions.

### 8.11 `InvestmentMemo`

```text
schema_version = "mlab-investment-memo.v1"
memo_id / valuation_id / run_id / candidate_id
issuer / security / analysis_cutoff_utc
research_only = true
memo_status                 # blocked | draft | review_required | approved_research | rejected
executive_summary
thesis_claim_ids[]
company_and_security_mapping
why_now
reported_financial_summary
valuation_methods[]
scenario_valuations[]
method_reconciliation
catalysts[]
invalidations[]
principal_risks[]
contrary_evidence_ids[]
unknowns_and_blockers[]
provenance_summary
uncertainty_summary
staleness_and_next_review
benchmark_and_controls
quant_validation_link       # nullable, downstream
committee_decision_link     # nullable, downstream
review
safety_attestation
```

`approved_research` means an independent reviewer approved the memo’s fidelity. It is not approval to paper trade. The downstream committee must consume the immutable `memo_id` and apply separate quant, portfolio-fit, and paper gates.

---

## 9. Temporal, units, and provenance rules

### 9.1 Availability-time rule

A historical run may use only information whose `available_at_utc <= analysis_cutoff_utc`. For filings, preserve both fiscal period and filing availability. A later amendment or restatement is excluded from the historical calculation but linked in a current-view supersession check.

Market price, share count, debt, and cash must be aligned to a documented cutoff policy. MVP policy:

- market price: official close on the latest completed session at or before the cutoff;
- capital-structure balance-sheet facts: latest filed period available by the paired market-price timestamp; an after-hours filing waits for the next completed official close for EV/WACC/equity-bridge use;
- income/cash-flow facts: TTM assembled only from filings available by the cutoff;
- share count: diluted weighted average for per-share earnings metrics; current diluted share estimate for equity-value conversion, with the difference explained;
- catalysts: only events known by the cutoff; later outcomes belong to monitoring/postmortem.

`current_diluted_shares.v1` is strict point-in-time policy:

1. The anchor is the exact official-close `MarketFact.timestamp_utc`, not merely its session date or the later command time.
2. Every basic-share, option, RSU, convertible, treasury-stock, and if-converted input must have both `effective_as_of_utc <= MarketFact.timestamp_utc` and `available_at_utc <= MarketFact.timestamp_utc <= analysis_cutoff_utc`. The latest eligible version is used; a later filing never backfills the historical estimate.
3. A filing released after that official close cannot support the same-close per-share valuation even when the command cutoff is later that evening. The builder either uses the previously available share evidence if it remains eligible or pairs the new filing with the next completed official close. It never mixes the after-hours share count with the earlier close.
4. The effective date of the anchor basic-share fact may be no more than 120 calendar days before the price timestamp. Older evidence, or any unmodeled issuance, repurchase, conversion, award vesting, acquisition consideration, or class change between the effective date and price timestamp, blocks per-share output as `stale_or_intervening_share_event`.
5. Price, basic shares, incremental dilution, and weighted-average diluted shares must be expressed on the same split basis. Splits effective on or before the price timestamp are applied to every component with an evidenced factor; splits effective later are not. An announced/effective ambiguity, inconsistent factor, or unresolved class conversion blocks all per-share and P/E outputs.
6. TTM EPS, when displayed as an earnings cross-check, uses period-weighted diluted shares for the same TTM earnings window, split-adjusted to that window. Canonical comparable P/E remains total common-equity market capitalization divided by TTM net income common; P/E-derived per-share value divides the implied total common-equity value by the current diluted estimate above. Current diluted shares must never replace period-weighted shares in EPS.

Each estimate stores its effective time, availability time, paired price timestamp, split basis/factor lineage, policy version, and component fact IDs. A reviewer cannot override post-price availability, a post-cutoff fact, a split mismatch, or an unresolved material dilutive security.

### 9.2 Unit rule

Every arithmetic operation validates dimensions:

- currency values require matching currency or an evidenced FX conversion at the cutoff;
- percentages are unit fractions;
- per-share and total-company values are never mixed;
- annual and quarterly values are never mixed without an explicit TTM transformation;
- fiscal periods cannot overlap in a TTM sum;
- enterprise-value multiples use enterprise numerators and operating denominators;
- equity-value multiples use equity numerators and common-equity denominators.

Version 1 rejects non-USD conversion rather than inventing an FX policy.

### 9.3 Evidence rule

Each non-derived material value must resolve to an `mlab-evidence.v2` record and verified snapshot/segment. Each derived fact lists exact input fact IDs and formula version. Search hits, snippets, generated summaries, and `context` stance cannot satisfy a required input.

Preferred sources follow claim fit:

- SEC filing/XBRL and exact accession for historical financials, debt, dilution, SBC, and filed guidance;
- filed exhibit, then official IR for current management guidance;
- registered government/statistical source for macro assumptions;
- timestamped market-data artifact for price and market cap;
- peer filings for comparable denominators;
- original event calendar/filing/regulator source for catalysts.

### 9.4 Contradiction rule

Conflicting values are classified before use:

```text
restatement_or_amendment
period_mismatch
concept_definition_mismatch
unit_or_scale_mismatch
share_class_mismatch
provider_error
true_source_disagreement
compatible
```

Material unresolved conflicts block the affected method. The engine does not choose the value that produces the most attractive output.

---

## 10. Comparable-company valuation

### 10.1 Supported multiples

MVP supports:

- EV / TTM revenue;
- EV / TTM EBITDA, only when EBITDA has a reviewed definition;
- market cap / TTM net income attributable to common (P/E equivalent);
- levered free-cash-flow yield, with its FCF definition shown.

Price/book, PEG, forward-consensus multiples, sum-of-the-parts, and precedent transactions are out of MVP.

### 10.2 Peer gate

A primary comparable range requires at least five included peers after exclusions. Three or four valid peers may be rendered only as `review_required` cross-check. Fewer than three is `blocked_insufficient_peers`.

Required peer checks:

- same broad business/economic value driver;
- comparable revenue mix and capital intensity;
- compatible financial-company status;
- same metric definition and period basis;
- current, matching share class and capital structure;
- no negative/zero denominator for a ratio where that is nonsensical;
- no unresolved extraordinary transaction or stale filing;
- documented reason for every inclusion/exclusion.

MVP does not calendarize peers. Candidate and peer TTM observations must be built from non-overlapping filed periods available by the common analysis cutoff, use the same denominator formula version, and have TTM period ends no more than 90 calendar days apart. A wider gap, mixed annual/TTM basis, or a later peer filing unavailable at the cutoff excludes that peer from that metric distribution with a typed reason; it does not block otherwise compatible metrics.

### 10.3 Calculation

For each valid peer:

```text
EV/Revenue = enterprise_value / TTM_revenue
EV/EBITDA  = enterprise_value / TTM_lease_adjusted_EBITDA
P/E        = common_equity_market_cap / TTM_net_income_common
FCF_yield  = levered_FCF / common_equity_market_cap

TTM_lease_adjusted_EBITDA = TTM_operating_income
                          + TTM_depreciation_and_amortization
                          + TTM_operating_lease_expense
levered_FCF = TTM_net_cash_from_operations - TTM_cash_capital_expenditures
```

The EBITDA inputs must cover the identical TTM period and must not double-count D&A already added in a supplied EBITDA subtotal. The operating-lease-expense add-back is required only for operating leases capitalized by `lease_adjusted_debt.v1`; finance-lease depreciation is already within D&A and finance-lease interest is already below operating income. A company-defined adjusted EBITDA is not substituted; it may appear only as a separately defined cross-check. Levered FCF uses cash capital expenditures as a positive subtraction, includes cash interest through US-GAAP operating cash flow, excludes debt issuance/repayment, and carries SBC/dilution policy into the result. Missing or incompatible components block only the affected metric.

Report the peer distribution: count, minimum, 25th percentile, median, 75th percentile, maximum, and each underlying observation. The valuation range uses the reviewed 25th-to-75th percentile applied to the candidate denominator; the median is a reference, not a target. Percentiles use deterministic linear interpolation over sorted exact `Decimal` observations: for percentile `p`, compute zero-based rank `(n - 1) * p`; if the rank is integral use that observation, otherwise interpolate between its floor and ceiling observations. Store the sorted inputs and unrounded result; apply display rounding only after valuation.

Do not silently winsorize. An outlier can be excluded only with a recorded deterministic reason (bad denominator, transaction distortion, non-comparable business, stale/incorrect capital structure). Statistical extremeness alone is a warning, not an exclusion reason.

### 10.4 Reconciliation

Each metric produces its own `ComparableMetricResult` and is reconciled as a sub-method, not averaged into a composite comparables number:

```text
EV metrics:
  implied_EV_range = candidate_denominator * [peer_Q25, peer_Q75]
  implied_common_equity_range = implied_EV_range
      - short_term_debt - long_term_debt - lease_adjustment
      - preferred_equity - noncontrolling_interest
      + cash_and_equivalents + eligible_non_operating_investments

P/E:
  implied_common_equity_range = TTM_net_income_common * [peer_Q25, peer_Q75]

FCF yield, where 0 < peer_Q25 <= peer_Q75:
  implied_common_equity_range = [candidate_levered_FCF / peer_Q75,
                                 candidate_levered_FCF / peer_Q25]
```

- `method_role` and rationale are fixed from business fit, denominator quality, peer count, and formula comparability before candidate implied values are calculated. Output attractiveness cannot change the role.
- EV/revenue, EV/EBITDA, P/E, and FCF yield keep independent IDs, peer sets/distributions, ranges, blockers, and roles. The parent comparables artifact is a container only and emits no combined range.
- Enterprise-value ranges are converted to common equity using the candidate’s evidenced, lease-consistent capital structure; per-share ranges then use the reviewed current diluted share estimate.
- Negative implied equity value remains visible and floors only per-share limited-liability display at zero; the calculation trace preserves the negative value.
- A valid sub-method with three/four peers is cross-check only. A sub-method with fewer than three peers, a non-positive P/E/FCF denominator or yield, or incompatible definitions is blocked and emits no value.
- Reconciliation operates across eligible comparable sub-methods and the base-scenario DCF under section 15. Bear/bull DCFs remain scenario outcomes, and reverse DCF remains market-implied. When two eligible comparable sub-method ranges do not overlap, emit `material_comparable_metric_disagreement`, show both ranges and their definition/peer differences, and require review; never average, midpoint, rank-select, or let one silently override the other.

---

## 11. FCFF DCF

### 11.1 Eligibility

FCFF DCF is eligible when:

- operating economics can be expressed through revenue, EBIT margin, tax, D&A, capex, and working capital;
- at least three annual historical periods support the base-rate view;
- forecast assumptions are explicit and evidence/rationale linked;
- capital structure inputs are complete;
- WACC and terminal growth pass structural gates; and
- the company is not in an unsupported financial/REIT/commodity-project category.

Current negative FCFF is permitted only when the forecast shows an explicit, bounded transition supported by unit economics, management guidance labeled as such, or industry/base-rate evidence. Unsupported hockey-stick convergence blocks DCF as a primary method.

### 11.2 Formula

For each explicit forecast year:

```text
lease_adjusted_EBIT_t = reported_EBIT_t
                      + operating_lease_expense_t
                      - right_of_use_asset_depreciation_t
NOPAT_t = lease_adjusted_EBIT_t * (1 - normalized_cash_tax_rate_t)
FCFF_t  = NOPAT_t
        + depreciation_and_amortization_t
        - capital_expenditures_t
        - change_in_net_working_capital_t
PV_FCFF = sum(FCFF_t / (1 + WACC)^t)
```

When `lease_adjustment = 0`, the three lease adjustment terms are evidenced zero and `lease_adjusted_EBIT_t = reported_EBIT_t`. When `lease_adjustment > 0`, forecast D&A includes the evidenced/forecast ROU-asset depreciation, and the reinvestment schedule includes ROU-asset additions or equivalent lease-capital expenditure. This reclassifies operating-lease financing cost without double-counting lease expense and lease liability. If operating lease expense, ROU depreciation, or reinvestment cannot be separated consistently, DCF is blocked as `incomplete_lease_capitalization`; the engine may not include lease debt while leaving unadjusted operating cash flows. Stock-based compensation is never automatically added back as “free.” If included in reported cash flow, the memo must show dilution treatment and the chosen economic policy.

Terminal value under Gordon growth:

```text
FCFF_N_plus_1 = normalized_FCFF_N * (1 + terminal_growth)
terminal_value = FCFF_N_plus_1 / (WACC - terminal_growth)
PV_terminal_value = terminal_value / (1 + WACC)^N
enterprise_value = PV_FCFF + PV_terminal_value
common_equity_value = enterprise_value
                    - short_term_debt - long_term_debt - lease_adjustment
                    - preferred_equity - noncontrolling_interest
                    + cash_and_equivalents + eligible_non_operating_assets
per_share_value = common_equity_value / current_diluted_shares
```

### 11.3 WACC contract

```text
cost_of_equity = risk_free_rate + beta * equity_risk_premium + reviewed_premia
post_tax_cost_of_borrowing = pre_tax_cost_of_borrowing * (1 - marginal_tax_rate)
post_tax_cost_of_leases = pre_tax_cost_of_leases * (1 - marginal_tax_rate)
total_capital = E + B + L + P + N
WACC = E/total_capital * cost_of_equity
     + B/total_capital * post_tax_cost_of_borrowing
     + L/total_capital * post_tax_cost_of_leases
     + P/total_capital * cost_of_preferred
     + N/total_capital * cost_of_equity
```

MVP `wacc.multi_component_gross_capital.v1` defines the weights without circularity:

- `E` is evidenced common-equity market capitalization at the paired cutoff official close. It is never the DCF output equity value.
- `B` is gross short-term plus long-term interest-bearing borrowing at carrying principal from the latest filing available at the price timestamp. MVP does not substitute net debt or net cash and does not mix selectively available debt market quotes into this carrying-value policy.
- `L` is `lease_adjustment` under `lease_adjusted_debt.v1`; its pre-tax cost is the evidenced weighted-average lease discount rate. Using an evidenced current marginal borrowing rate instead is an explicit reviewed judgment with a range and sensitivity, not a hidden fallback.
- `P` is preferred-equity market capitalization at the cutoff when publicly traded, otherwise evidenced liquidation/redemption value; `cost_of_preferred` is the contractual current yield. A material nonzero preferred claim without value or cost evidence blocks WACC.
- `N` is evidenced noncontrolling interest carrying value from the latest available filing. Because consolidated FCFF includes subsidiary cash flows, NCI is an equity-like capital component weighted at `cost_of_equity` and is subtracted in the common-equity bridge. A material unmeasured NCI blocks WACC.
- Cash and non-operating investments are excluded from `total_capital`; they enter only the enterprise-to-common-equity bridge. Every zero component must be source-reported or derived from complete evidence, never assumed.

Every component needs a source, cutoff, units, and rationale. Beta source/window/frequency must be recorded. No hidden “industry standard” constants. If a component is analyst judgment, provide a range and sensitivity. Any forecast/peer using a different lease, preferred, NCI, or gross-debt policy receives a typed incompatibility blocker rather than silently changing weights.

### 11.3.1 Terminal-value share denominator

`terminal_value_share.pv_over_ev.v1` uses discounted values only:

```text
ev_denominator_floor = max(USD 1,
                           0.000001 * max(abs(PV_FCFF), abs(PV_terminal_value), USD 1))
terminal_value_share = PV_terminal_value / enterprise_value
```

The share is calculated only when every term is finite, `PV_terminal_value > 0`, `enterprise_value > 0`, and `enterprise_value >= ev_denominator_floor`. Otherwise the ratio is `null`, no percentage is displayed, and DCF is blocked with `nonpositive_terminal_value`, `nonpositive_enterprise_value`, `near_zero_enterprise_value`, or `nonfinite_terminal_share_input` as applicable. The engine never uses `abs(enterprise_value)` or another denominator to manufacture a percentage. Negative `PV_FCFF` is allowed only when enterprise value still passes the denominator gate; it naturally produces a terminal share above 100% and is blocked by the 85% gate. The calculation trace stores `PV_FCFF`, `PV_terminal_value`, enterprise value, denominator floor, ratio/status, and formula version.

### 11.4 Structural gates

DCF is blocked when any is true:

- `WACC <= terminal_growth`;
- `WACC - terminal_growth < 0.015` in MVP;
- terminal growth is unsupported or inconsistent with its currency/economy maturity basis;
- forecast periods or currencies are mixed;
- debt/cash/share count is missing or stale;
- terminal-value share is undefined under section 11.3.1 or exceeds `0.85`;
- the result depends on a negative denominator or non-finite value;
- the base case contains an internally impossible margin, tax, reinvestment, or working-capital path; or
- required facts are synthetic, post-cutoff, or unresolved.

Warnings, requiring review but not necessarily blocking:

- defined terminal-value share exceeds `0.70` and is at most `0.85`;
- modest sensitivity (`WACC +/- 1 percentage point`, terminal growth `+/- 0.5 percentage point`, subject to structural validity) changes per-share value by more than 20%;
- revenue growth or margin expansion exceeds both company history and peer base rates without direct evidence;
- diluted shares are estimated rather than filed/current; or
- normalized cash tax differs materially from reported tax.

### 11.5 Sensitivity

Always emit a two-dimensional WACC/terminal-growth grid around each calculated scenario. Invalid cells are `null` with a reason; never clamp them. Also emit one-at-a-time sensitivities for revenue CAGR, terminal EBIT margin, capex/revenue, and dilution.

The engine stores full deterministic precision but renders ranges and rounded values under section 16.

---

## 12. Reverse DCF / expectations valuation

### 12.1 Purpose

Reverse DCF answers “what operating assumption is implied by the cutoff market price under an explicit model?” It does not assert that the implied assumption will occur and does not produce an independent target price.

### 12.2 MVP solve variables

Solve exactly one variable per run while holding a reviewed baseline constant:

- revenue CAGR over the explicit forecast horizon; or
- terminal EBIT margin.

Do not solve growth and margin simultaneously. Do not use an unconstrained optimizer.

### 12.3 Deterministic solver

Use bounded bisection:

1. Define an economically reviewed lower/upper bracket.
2. Evaluate equity value at both ends.
3. Require monotonicity over sampled bracket points.
4. Require the observed equity value to be bracketed.
5. Bisect until the economic display tolerance is met or 100 iterations, whichever comes first.
6. Recalculate the solved model and verify residual.

Failure statuses:

```text
not_bracketed
non_monotonic
invalid_model_cell
iteration_limit
missing_market_value
unsupported_baseline
```

No failed solve emits an implied assumption.

### 12.4 Interpretation record

The result must show:

- cutoff price and market cap evidence;
- solved variable and bracket;
- all fixed assumptions;
- the implied path, not only endpoint CAGR/margin;
- historical and peer distribution comparison;
- residual and display tolerance;
- whether the implied value lies outside observed/base-rate ranges;
- a plain-language interpretation labeled `market_implied`, not `forecast`.

Reverse DCF is especially useful when forward forecasts are weak; however, missing capital structure or an invalid DCF baseline still blocks it.

---

## 13. Bull/base/bear scenario construction

### 13.1 Required independence

Every scenario must be a coherent operating state, not a mechanical percentage haircut to the final target price. Assumptions are set before valuation outputs are viewed where practical and are independently reviewable.

Required scenario dimensions:

- revenue growth path;
- operating margin path;
- cash tax;
- D&A, capex, and working-capital intensity;
- dilution/current diluted shares;
- WACC/risk adjustment;
- terminal growth;
- catalyst outcomes;
- invalidation/risk outcomes.

### 13.2 Ordering invariants

The engine checks but does not force:

```text
bear common_equity_value <= base common_equity_value <= bull common_equity_value
bear operating assumptions are not economically stronger than base without an offsetting risk explanation
bull assumptions are not weaker than base without an offsetting valuation explanation
```

If values cross, status is `review_required_scenario_crossing`; the engine must not sort or relabel them after calculation.

Method identity is part of the invariant. Each bear/base/bull DCF is a distinct `MethodResult` whose `scenario_id`, `assumption_ids[]`, and calculation trace bind to exactly one `ScenarioValuation`. The scenario aggregate derives its range only from method results carrying that same ID. Verification reconstructs each `scenario_id` from valuation ID, canonical scenario name, and assumption-set hash, then rejects swapped labels, cross-scenario references, or a method artifact reused under another scenario. The base-scenario DCF alone may enter cross-method fair-value reconciliation; bear and bull remain disclosed operating outcomes rather than extra independent methods.

### 13.3 Scenario evidence

- Base should anchor to reported history, verified current guidance, and external base rates.
- Bull must identify what additional evidence/catalyst must become true.
- Bear must incorporate contrary evidence and at least one thesis invalidation path.
- Each material assumption records uncertainty and evidence/judgment basis.
- Unknowns are not assigned convenient values. They become ranges, sensitivity axes, or blockers.

### 13.4 Probability policy

MVP omits probabilities by default. If enabled later, scenario probabilities must:

- be assigned before weighted value calculation;
- be independently reviewed;
- sum exactly to 1;
- be displayed as subjective judgments;
- preserve the unweighted scenarios; and
- never increase confidence merely because they create a precise expected value.

---

## 14. Memo content contract

The Markdown memo renders these sections in this order:

1. **Research-only banner and status** — cutoff, memo ID, review status, blockers.
2. **Candidate identity** — issuer, security/share class, CIK, mapping rationale.
3. **Executive summary** — bounded thesis, why now, what is priced in, uncertainty.
4. **Evidence-backed thesis** — material claim IDs with supporting and contrary evidence.
5. **Company economics** — revenue drivers, margins, reinvestment, capital structure, dilution.
6. **Reported financials** — period-aligned history with filing/accession citations.
7. **Valuation overview** — method statuses and ranges; no blended point target.
8. **Comparable companies** — peer rationale, inclusions/exclusions, distribution.
9. **DCF** — assumptions, formulas/version, scenario ranges, terminal share, sensitivity.
10. **Reverse DCF** — market-implied operating requirement and base-rate comparison.
11. **Bull/base/bear** — coherent assumptions and outcomes.
12. **Catalysts** — timing, mechanism, evidence, confirmation rule.
13. **Invalidation conditions** — measurable triggers and forced-review actions.
14. **Principal risks and contrary evidence** — not buried in footnotes.
15. **Unknowns/blockers** — required missing research and owner.
16. **Provenance and freshness** — source classes, cutoff, stale/superseded flags.
17. **Uncertainty/no-false-precision statement** — method disagreement and sensitivity.
18. **Benchmark/controls and downstream links** — quant/committee links only when available.
19. **Independent review** — reviewer, decision, time, notes.
20. **Safety attestation** — confirms no execution-state mutation.

The JSON and Markdown must agree on every number, status, catalyst, invalidation, and blocker. Rendering tests compare semantic content, not only file existence.

---

## 15. Method reconciliation

Do not average every available method.

Reconciliation policy:

1. Reconciliation units are the base-scenario DCF `MethodResult` and each separately eligible `ComparableMetricResult`; the comparables container, bear/bull DCFs, and reverse DCF are not reconciliation units.
2. Classify every reconciliation unit as `primary`, `cross_check`, `blocked`, or `not_applicable` before viewing its candidate implied range. Store the pre-output role decision and rationale in the artifact hash.
3. Show every calculated range, metric definition, scenario identity where applicable, peer count, role, and status reason.
4. Compute overlap only among independently eligible primary units. Do not first combine comparable sub-methods.
5. If all primary units share a non-empty intersection, report that intersection as `primary_method_overlap` alongside every full range; the intersection is not a new target or blended estimate.
6. If any pair of primary ranges has no overlap, report `material_method_disagreement`, retain all ranges, identify the disagreeing unit IDs, and require review. No averaging, midpointing, confidence weighting, or silent preferred-metric selection is allowed.
7. Reverse DCF is `market_implied`, is shown as an expectations cross-check, and is never averaged into fair value.
8. A comparable sub-method with fewer than five peers is cross-check only and cannot override an eligible base DCF. One comparable metric cannot override another merely because its range is more attractive.
9. A DCF with undefined terminal-value share or share above 85% is blocked and contributes no range.
10. If only one primary unit passes, report that unit’s range with `single_method_high_uncertainty`; calculated cross-checks remain separately visible.
11. If no fair-value unit passes, publish a blocked memo with no numeric fair-value range, even if reverse DCF calculated successfully.

No “consensus target,” confidence-weighted blend, or model-selected preferred answer exists in MVP.

---

## 16. Uncertainty and no-false-precision gates

### 16.1 Storage versus display

- Store source precision and deterministic calculation precision separately.
- Serialize decimal values exactly; never use binary float as canonical data.
- Display per-share modeled values no finer than the larger of `$0.10` or 1% of cutoff price.
- For each modeled total-company range in USD, define `company_value_scale = max(abs(range_low), abs(range_high), abs(cutoff_market_cap), USD 1)`. Select the coarser increment implied by three significant digits or `0.01 * company_value_scale`; round the low endpoint toward negative infinity and the high endpoint toward positive infinity so display rounding never narrows the canonical range. Express both endpoints in the largest common unit among USD, USD millions, or USD billions that keeps both absolute endpoint magnitudes at least one unit. Store the exact USD endpoints and the chosen display unit, increment, and directed-rounding mode in the render trace.
- Display source-reported revenue, cash flow, debt, and share values in their evidenced source unit/precision; do not apply modeled-range rounding to the historical financial table.
- Display rates no finer than 0.1 percentage point; subjective probabilities no finer than 5 percentage points.
- Never display solver iteration precision as economic precision.
- A source-reported exact value may retain its source precision in the financial table, clearly separated from modeled output.

### 16.2 Mandatory range behavior

Every calculated fair-value method emits low/high. A base-case midpoint may be shown only inside its method table and never alone in the executive summary. Upside/downside is a range versus one evidenced cutoff price.

### 16.3 Uncertainty labels

Method-level uncertainty is deterministic:

```text
LOW      # all required facts primary/current, >=5 good peers or stable DCF, low sensitivity, methods agree
MEDIUM   # reviewed judgments, one material warning, or moderate method spread
HIGH     # single method, sparse peers, high terminal share/sensitivity, estimated dilution, or material disagreement
BLOCKED  # any hard gate fails
```

`LOW` is not a statement of low market risk. The memo explains the dimensions contributing to the label.

### 16.4 Hard no-false-precision gates

Block approval when any is true:

- a modeled point target appears without a range;
- a range endpoint lacks a calculation trace;
- an input lacks evidence/transformation lineage;
- a default assumption was inserted to fill missing data;
- scenario probabilities are hidden or do not sum to one;
- method ranges are blended despite blocked/ineligible inputs;
- material method disagreement is hidden;
- a source/model output is quoted beyond its actual precision;
- current data leaks into a historical cutoff;
- synthetic facts/prices are used;
- risk/catalyst/invalidation prose has no structured record;
- an LLM-generated number enters arithmetic; or
- memo JSON and Markdown differ semantically.

---

## 17. Gate model and state transitions

### 17.1 Valuation artifact states

These are sub-artifact states inside the existing MLAB run, not a second run lifecycle:

```text
NOT_STARTED
  -> INPUT_BLOCKED | INPUTS_VALIDATED
INPUTS_VALIDATED
  -> CALCULATED | INPUT_BLOCKED
CALCULATED
  -> REVIEW_REQUIRED
REVIEW_REQUIRED
  -> APPROVED_RESEARCH | REJECTED | INPUT_BLOCKED
APPROVED_RESEARCH
  -> SUPERSEDED
REJECTED
  -> SUPERSEDED
```

No transition points to an order or paper position. A downstream committee consumes `APPROVED_RESEARCH` as one input and applies separate gates.

### 17.2 Gate groups

`gate_report.json` contains one row per gate:

```text
gate_id
group                      # identity | evidence | temporal | accounting | method | scenario | memo | safety | review
status                     # pass | warn | fail | not_applicable
reason_code
message
artifact_ids[]
owner
next_action
override_allowed
reviewer_override          # nullable
```

Hard failures are not overrideable in MVP. Warnings may be accepted by an independent reviewer with rationale. Required hard groups:

- issuer/security identity;
- cutoff and availability time;
- exact provenance and locator resolution;
- units/period/currency consistency;
- capital structure completeness;
- method-specific economics;
- bull/base/bear completeness;
- catalysts and measurable invalidations;
- contrary evidence;
- range/rounding/no-false-precision;
- JSON/Markdown consistency;
- no execution side effects; and
- independent reviewer identity distinct from memo builder.

### 17.3 Promotion outcome

```text
APPROVED_RESEARCH     all hard gates pass; reviewer approves
REVIEW_REQUIRED       no hard failure, but warnings/unreviewed judgments remain
BLOCKED               one or more hard gates fail
REJECTED              reviewer finds unsupported thesis or unusable valuation
NO_VALUATION          valid research result; no eligible method
```

`NO_VALUATION` is preferable to fabricated precision.

---

## 18. Audit events and resumability

Use the accepted `mlab-audit.v2` envelope and run ledger lock. Minimum new events:

```text
valuation.requested
valuation.input_linked
valuation.input_rejected
valuation.transformation_applied
valuation.peer_included
valuation.peer_excluded
valuation.method_started
valuation.method_calculated
valuation.method_blocked
valuation.reverse_dcf_solved
valuation.scenarios_validated
valuation.catalyst_recorded
valuation.invalidation_recorded
valuation.memo_rendered
valuation.gates_evaluated
valuation.reviewed
valuation.approved_research
valuation.rejected
valuation.superseded
valuation.safety_verified
```

Stable idempotency keys:

```text
input: stable_id("mlab-input-idempotency.v1", {
  "evidence_segment_id": evidence_segment_id,
  "fact_semantic_key": fact_semantic_key_object,
  "valuation_id": valuation_id
})
method: stable_id("mlab-method-idempotency.v1", {
  "assumption_hashes": sorted_unique_assumption_hashes,
  "formula_version": formula_version,
  "input_hashes": sorted_unique_input_hashes,
  "method_type": method_type,
  "scenario_id": scenario_id,
  "valuation_id": valuation_id
})
memo: stable_id("mlab-memo-idempotency.v1", {
  "method_hashes": sorted_unique_method_hashes,
  "renderer_semantic_version": renderer_semantic_version,
  "scenario_hashes": sorted_unique_scenario_hashes,
  "thesis_hashes": sorted_unique_thesis_hashes,
  "valuation_id": valuation_id
})
```

On resume:

- verify all source snapshots, segments, fact transformations, and artifact hashes;
- replay only committed events;
- recompute when a dependency hash changed;
- never reuse an artifact from another cutoff/candidate;
- preserve typed blockers and owned next actions;
- never convert missing data into zero or a default; and
- verify broker/order/options state hashes before and after the run.

---

## 19. CLI contract

Future CLI:

```text
market_lab_valuation.py build
  --run-dir PATH
  --candidate-id ID
  --analysis-cutoff ISO8601
  --mode frozen|live
  --forecast-years 5
  --output-dir PATH
  [--require-approvable]

market_lab_valuation.py render
  --run-dir PATH
  --valuation-id ID

market_lab_valuation.py verify
  --run-dir PATH
  (--valuation-id ID | --valuation-id-from-manifest)
  --require-provenance
  --require-cutoff-integrity
  --require-no-false-precision
  --require-independent-review
  --require-zero-execution-side-effects

market_lab_valuation.py benchmark
  --lane frozen|chaos|live
  --cases PATH
  --output PATH
  --fail-on-gate
```

`--mode live` permits acquisition through the accepted web-evidence layer; it never permits broker/network execution. The valuation CLI must not import `market_lab.broker`, `options_paper`, or daily execution helpers except a test-only state-path inventory in the verifier.

The CLI resolves `--analysis-cutoff NOW` exactly once at command start, writes that UTC timestamp into `request.json`, and passes only the resolved timestamp downstream. Resume reuses the persisted cutoff; it never resolves `NOW` again.

Exit codes:

```text
0 = artifact produced and requested verification passed
2 = honest input/method blocker
3 = schema/integrity/safety failure
4 = independent review required or rejected
```

A blocked research memo is still written when safe to do so, but `build --require-approvable` exits non-zero.

---

## 20. Deterministic test plan

### 20.1 Contract and serialization tests

- round-trip every schema with decimal strings and canonical hashes;
- reject floats, NaN, infinity, unknown enums, missing units, and future cutoffs;
- prove stable IDs under dictionary ordering changes;
- prove `stable_id` domain separation and typed canonical objects distinguish ambiguous raw-concatenation pairs such as `("ab", "c")` and `("a", "bc")`;
- prove semantic memo hash is renderer-independent;
- reject `research_only=false`.

### 20.2 Input/provenance tests

- resolve a filed fact to exact accession, XBRL concept/context, period, units, snapshot, and segment;
- reject search snippets, context-only evidence, missing locator, bad hash, post-cutoff filing, and stale market fact;
- preserve restatements and choose only the version available at cutoff;
- detect period overlap, scale error (`thousands` versus units), currency mismatch, share-class mismatch, and split mismatch;
- reject an after-hours share-count filing paired with the preceding official close, post-cutoff share data, share evidence older than 120 days, and mismatched pre/post-split price-share bases;
- reject synthetic/cache-synthetic factors and prices;
- prove a missing fact remains missing rather than zero.

### 20.3 Comparable tests

- hand-calculate EV/revenue, EV/EBITDA, P/E, FCF yield for frozen peers;
- verify percentile/distribution calculations against fixed expected decimals;
- reject negative denominators where required;
- retain included/excluded peer rationales;
- block fewer than three peers; mark three/four `review_required`; allow five-plus;
- prove statistical outliers are not silently removed;
- verify enterprise/equity numerator-denominator consistency.
- prove lease inclusion changes candidate/peer EV consistently and rejects a mixed lease-policy distribution;
- make EV/revenue and P/E produce disjoint valid ranges, then verify separate sub-method IDs/ranges and `material_comparable_metric_disagreement` with no composite value;
- reject peer TTM period-end gaps above 90 days rather than silently calendarizing.

### 20.4 DCF tests

- hand-calculate a five-year FCFF DCF and equity bridge;
- hand-calculate lease-adjusted EBIT/FCFF, EV bridge, and multi-component WACC weights with borrowing, leases, preferred, and NCI;
- prove WACC uses cutoff market common equity and gross capital, never DCF-output equity or net debt;
- test zero/negative FCFF transition with explicit assumptions;
- reject WACC <= g and WACC-g < 150 bps;
- block undefined terminal-value share for zero, negative, near-zero, or non-finite EV/PV inputs; block share >85% and warn only for defined shares >70%;
- verify every sensitivity cell independently and mark invalid cells null;
- test tax, capex, working-capital, debt/cash, dilution, and SBC policy changes;
- reject unsupported terminal growth, mixed periods, and missing capital structure;
- prove calculations use `Decimal` canonical paths, not display strings.

### 20.5 Reverse-DCF tests

- solve a known revenue CAGR and terminal margin from a generated target market cap;
- verify bracket, monotonicity, residual, and iteration cap;
- reject non-bracketed, non-monotonic, invalid, and missing-market-value cases;
- prove exactly one variable changes;
- ensure output is labeled market-implied and is not included in fair-value blending.

### 20.6 Scenario tests

- require bear/base/bull exactly once;
- require all material assumption dimensions;
- reject swapped bear/base/bull labels, cross-scenario method-result references, and a reused DCF result whose `scenario_id` does not match its assumption-set hash;
- detect scenario crossing without relabeling/sorting;
- reject a mechanical final-price haircut with no operating assumptions;
- require bull catalyst dependencies and bear invalidation path;
- omit weighted value when probabilities are null;
- reject probabilities that are post-output, hidden, too precise, or do not sum to one.

### 20.7 Catalyst and invalidation tests

- reject catalyst without mechanism, source, window, or confirmation requirement;
- reject qualitative invalidation without metric/event, threshold, window, and source class;
- trigger deterministic invalidation from a frozen filing event;
- ensure trigger action is forced review/rejection only, never an order;
- mark unobservable conditions and block approval where material.

### 20.8 Memo/gate tests

- JSON and Markdown contain identical numbers/statuses/IDs;
- memo shows blocked methods and contrary evidence;
- no executive-summary point target appears alone;
- display rounding follows policy while canonical values remain exact;
- total-company range rounding records deterministic USD scale/unit/increment separately from per-share rounding;
- material method disagreement is surfaced;
- blocked memo emits no numeric method value;
- independent reviewer cannot equal builder actor;
- approval fails on any hard no-false-precision gate.

### 20.9 Temporal and lookahead tests

- reconstruct the same issuer at two cutoffs and prove later filing/price/catalyst data cannot enter the earlier run;
- ensure amended facts affect current view only after amendment availability;
- freeze all provider responses in unit tests;
- prove peer financial availability is also cutoff-correct;
- verify no current diluted share count leaks into historical reverse DCF without explicit historical treatment.

### 20.10 Safety tests

Before and after build/render/verify, hash:

```text
mock_portfolio_state.json
mock_ledger.jsonl
pending_order_candidates.jsonl
options/paper_options_state.json
options/paper_options_ledger.jsonl
options/paper_options_candidates.jsonl
vt_trend/ and tsmom/ state/ledger/candidate files
```

Files absent before must remain absent. Existing hashes must remain identical. Also assert no valuation module imports or calls order placement/candidate append functions and no write HTTP verb is added to the webapp.

### 20.11 Chaos tests

Inject:

- malformed XBRL scale;
- duplicate peer under two tickers;
- post-cutoff restatement;
- stale/split-misaligned price;
- debt omitted as zero;
- swapped EV/equity denominator;
- WACC below terminal growth;
- reverse-DCF non-monotonic model;
- crossed bull/base/bear labels;
- model-generated unsupported assumption;
- one source syndicated across several URLs;
- memo renderer changing a sign/rounding endpoint;
- crash after method artifact but before manifest; and
- safety-state mutation attempt.

Every case must fail with a typed blocker, preserve artifacts/audit integrity, and resume idempotently.

---

## 21. Benchmark and quality gates

Create a frozen `OzValuationBench-v1` before live default use:

| Slice | Cases |
|---|---:|
| Accounting/unit/period/capital-structure normalization | 12 |
| Comparable eligibility and multiples | 10 |
| FCFF DCF and sensitivity | 10 |
| Reverse DCF | 6 |
| Scenarios/catalysts/invalidations | 8 |
| Temporal/lookahead/restatement cases | 6 |
| Memo fidelity/no-false-precision/safety chaos | 8 |
| **Total** | **60** |

Every case includes a frozen cutoff, exact source segments, expected normalized facts, method eligibility, hand-checked calculation ranges, expected blockers/warnings, and allowed memo status.

Hard integrity gates are 100%:

- schema validity and canonical hash reproducibility;
- calculation agreement with hand-checked fixtures at canonical precision;
- zero unsupported/synthetic/post-cutoff inputs;
- every material number resolves to source or transformation lineage;
- zero hidden method/scenario disagreement;
- correct blockers for invalid methods;
- JSON/Markdown semantic agreement;
- independent-review separation; and
- zero execution-state changes.

Do not collapse these into one quality score. Report each numerator, denominator, and case IDs. Live availability and evidence coverage are separate from arithmetic correctness.

---

## 22. Exact future acceptance commands

### 22.1 Focused frozen tests

```bash
cd /Users/ozlabs/market-lab
uv sync --extra dev

MARKET_LAB_DATA_DIR=/tmp/mlab_valuation_unit_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_valuation_unit_pycache \
uv run pytest \
  tests/market_lab/test_valuation_contracts.py \
  tests/market_lab/test_valuation_inputs.py \
  tests/market_lab/test_valuation_comparables.py \
  tests/market_lab/test_valuation_dcf.py \
  tests/market_lab/test_valuation_reverse_dcf.py \
  tests/market_lab/test_valuation_scenarios.py \
  tests/market_lab/test_investment_memo.py \
  tests/market_lab/test_valuation_gates.py \
  tests/market_lab/test_valuation_pipeline.py \
  tests/market_lab/test_valuation_cli.py \
  tests/market_lab/test_valuation_benchmark.py -q
```

Required: zero failures and zero network calls.

### 22.2 Frozen end-to-end build

```bash
cd /Users/ozlabs/market-lab
rm -rf /tmp/mlab_valuation_acceptance
cp -R tests/market_lab/fixtures/valuation/mature_us_issuer_run \
  /tmp/mlab_valuation_acceptance

MARKET_LAB_DATA_DIR=/tmp/mlab_valuation_data \
uv run python scripts/market_lab_valuation.py build \
  --run-dir /tmp/mlab_valuation_acceptance \
  --candidate-id fixture-candidate \
  --analysis-cutoff 2025-12-31T23:59:59Z \
  --mode frozen \
  --forecast-years 5 \
  --output-dir /tmp/mlab_valuation_acceptance/valuation

uv run python scripts/market_lab_valuation.py verify \
  --run-dir /tmp/mlab_valuation_acceptance \
  --valuation-id-from-manifest \
  --require-provenance \
  --require-cutoff-integrity \
  --require-no-false-precision \
  --require-zero-execution-side-effects
```

Required: comparables, DCF, reverse DCF, scenarios, memo JSON/Markdown, gate report, and manifest exist; hashes and hand-checked ranges pass; no execution state changes.

### 22.3 Frozen benchmark and chaos

```bash
cd /Users/ozlabs/market-lab
uv run python scripts/market_lab_valuation.py benchmark \
  --lane frozen \
  --cases tests/market_lab/fixtures/valuation/benchmark_v1.jsonl \
  --output /tmp/mlab_valuation_frozen_metrics.json \
  --fail-on-gate

uv run python scripts/market_lab_valuation.py benchmark \
  --lane chaos \
  --cases tests/market_lab/fixtures/valuation/chaos_v1.jsonl \
  --output /tmp/mlab_valuation_chaos_metrics.json \
  --fail-on-gate
```

Required: all integrity gates pass; replay uses no network; every chaos defect yields its expected blocker.

### 22.4 Live evidence smoke

Only after the accepted web-evidence layer exists:

```bash
cd /Users/ozlabs/market-lab
uv run python scripts/market_lab_valuation.py build \
  --run-dir /tmp/mlab_valuation_live_run \
  --candidate-id acceptance-us-issuer \
  --analysis-cutoff NOW \
  --mode live \
  --forecast-years 5 \
  --output-dir /tmp/mlab_valuation_live_run/valuation
```

The smoke must use an SEC-reporting non-financial issuer, capture exact filing/XBRL and market artifacts, and may honestly end `REVIEW_REQUIRED` or `BLOCKED`. It passes integrity only if every used input is source-resolved and no order state changes. A live network success is not independent-review approval.

### 22.5 Existing regressions

```bash
cd /Users/ozlabs/market-lab
MARKET_LAB_DATA_DIR=/tmp/mlab_valuation_regression_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_valuation_regression_pycache \
uv run pytest \
  tests/market_lab/test_mlab_ingest.py \
  tests/market_lab/test_source_thesis.py \
  tests/market_lab/test_factors.py \
  tests/market_lab/test_daily_script_safety.py \
  tests/market_lab/test_broker.py \
  tests/market_lab/test_options_support.py -q

MARKET_LAB_DATA_DIR=/tmp/mlab_valuation_full_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_valuation_full_pycache \
uv run pytest tests/market_lab -q
```

Required: zero failures.

---

## 23. MVP acceptance criteria

The MVP is accepted only when one frozen mature-US-issuer case and the full 60-case benchmark prove:

1. candidate, issuer, security/share class, and cutoff are explicit;
2. every material input resolves to exact evidence or a transparent derived-fact chain;
3. financial periods, availability times, units, currency, scale, and capital structure validate;
4. comparable peers have preserved inclusion/exclusion rationales and valid distribution math;
5. FCFF DCF formulas, terminal constraints, equity bridge, and sensitivity match hand calculations;
6. reverse DCF solves one bounded variable and is labeled market-implied;
7. bull/base/bear scenarios are coherent operating cases with no silent sorting or hidden probabilities;
8. catalysts include timing, mechanism, evidence, and confirmation rules;
9. invalidation conditions are measurable and trigger review/rejection only;
10. uncertainty and method disagreement remain visible;
11. no modeled point estimate appears without a range and calculation trace;
12. blocked methods and missing data produce blockers, not defaults or zeros;
13. memo JSON and Markdown agree semantically;
14. an independent reviewer distinct from the builder approves the research artifact;
15. crash/resume and artifact hashes are deterministic; and
16. broker, order candidate, portfolio, options, and independent-track state are byte-for-byte unchanged.

Until all are true, the valuation/memo layer remains an experimental research artifact and cannot become a committee or paper-portfolio prerequisite.

---

## 24. Implementation sequence

### Slice A — contracts and frozen arithmetic

- Add schemas, decimal/canonical serialization, IDs, formulas, and hand-checked unit fixtures.
- Implement comparable distribution, FCFF DCF, sensitivity, and bisection reverse DCF.
- Use only frozen, provenance-complete fixture artifacts. No live acquisition and no memo approval.

### Slice B — provenance and temporal normalization

- Resolve input facts from accepted web-evidence snapshots/segments.
- Add SEC/XBRL period, unit, accession, amendment, and availability handling.
- Add capital-structure and market-fact cutoff gates.
- Slice B and every live smoke are blocked until the web-evidence v2 implementation exists and independently passes its provenance, immutable-snapshot, segment-locator, and cutoff acceptance gates. Fixture-only Slice A may proceed without network acquisition.

### Slice C — scenarios and memo

- Add assumption records, bull/base/bear validation, catalysts, invalidations, reconciliation, canonical memo JSON, and Markdown renderer.
- Add no-false-precision and JSON/Markdown fidelity tests.

### Slice D — run integration and review

- Add run-local atomic store, audit-v2 events, resume, CLI, gate report, safety-state verifier, and independent review transition.
- Keep downstream committee/paper integration disabled.

### Slice E — benchmark and shadow use

- Pass frozen, chaos, focused, and full-suite gates.
- Run at least 20 shadow live valuations across eligible non-financial issuers, including blocked cases.
- Independently review accounting errors, peer quality, lookahead leakage, method disagreement, and memo fidelity.
- Promote only after 100% integrity invariants and documented reviewer approval.

---

## 25. Deferred work

After MVP evidence, separate specs may add:

- bank/insurer residual-income or dividend-discount models;
- REIT NAV/AFFO;
- sum-of-the-parts;
- non-USD issuers and point-in-time FX;
- commodity/project NAV;
- precedent transactions;
- licensed consensus-estimate ingestion;
- probabilistic/Monte Carlo valuation with calibration evidence;
- quarterly forecast models;
- structured committee scoring; and
- thesis-linked paper-position sizing and monitoring.

None should be prebuilt into the MVP abstraction.

---

## 26. Kill criteria

Stop or demote the implementation if:

- frozen hand-calculated cases do not reproduce exactly at canonical precision;
- more than 1% of material values in shadow runs lack exact provenance;
- any post-cutoff fact enters a historical valuation;
- peer selection cannot be explained independently of model output;
- missing inputs are repeatedly filled by defaults/manual zeros;
- memo prose disagrees with canonical JSON;
- method disagreement or contrary evidence is routinely hidden;
- terminal-value or sensitivity warnings are treated as cosmetic;
- blocked/no-valuation outcomes are operationally pressured into numeric answers;
- independent review is performed by the same actor/model instance that built the memo;
- any valuation run mutates execution state; or
- downstream ranking treats numeric upside as sufficient evidence of conviction.

---

## 27. Definition of done

This specification’s future implementation is done only when Market Lab can take one eligible, provenance-complete candidate at a frozen cutoff and produce an independently reviewed, reproducible memo whose valuation ranges, market-implied expectations, scenarios, catalysts, invalidations, uncertainty, and blockers are all machine-verifiable—and can prove that it created no execution side effect.

A polished memo without those properties is a failure. An honest `NO_VALUATION` or `BLOCKED` artifact with complete evidence is a successful research outcome.

---

## 28. Source basis

This spec is grounded in:

- `research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md`;
- `/Users/ozlabs/OzLabs/docs/market-lab/WEB_EVIDENCE_IMPLEMENTATION_SPEC.md`;
- `/Users/ozlabs/OzLabs/docs/market-lab/MARKET_RESEARCH_SOURCE_HIERARCHY.md`;
- current `market_lab/source_thesis.py`, `market_lab/mlab_ingest.py`, `market_lab/factors.py`, `market_lab/evidence.py`, `market_lab/diagnosis.py`, `market_lab/report.py`, `market_lab/config.py`, and `market_lab/broker.py`;
- current SourceThesis, MLAB ingest, factor, safety, broker, and options tests; and
- the research-only posture in `README.md` and `CLAUDE.md`.

The commissioned R&D swarm brief `/Users/ozlabs/OzLabs/docs/market-lab/rd-swarm/VALUATION_MEMO_RND.md` was unavailable at finalization after the delegated research lane timed out. Per coordinator authorization, that unavailable report is non-blocking: this document is an independent specification derived from the canonical roadmap, accepted web-evidence and source-hierarchy contracts, current repository code/tests, and explicit analysis above. No claim or recommendation in this specification is attributed to the missing report; if it is produced later, reconcile it as a separately reviewed change rather than silently rewriting this artifact's source basis.
