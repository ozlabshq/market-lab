# Market Lab Agency Company Intelligence — Implementation and Acceptance Spec

**Status:** implementation-ready specification; no product code in this change

**Date:** 2026-07-14 UTC

**Scope:** theme/value-chain mapping through evidence-backed issuer and security research packets

**Safety mode:** research/mock/paper only; this layer cannot create or modify orders, positions, ledgers, or broker state

## 1. Decision

Build a bounded company-intelligence layer between adjudicated source claims and the later valuation/investment-committee layers.

The layer converts a defensible theme into:

1. a versioned theme and value-chain map;
2. an auditable issuer discovery set;
3. exact issuer-to-security mappings;
4. period- and scope-matched material-revenue-exposure assessments;
5. evidence-backed business-quality, moat, and competition assessments;
6. a filing/IR/transcript/catalyst document inventory;
7. one immutable draft company-intelligence packet per candidate; and
8. deterministic `DRAFT_READY_PENDING_REVIEW`, `PARK_RESEARCH`, or `REJECT_MAPPING` validation outcomes followed by an independently reviewed publication decision.

It does not rank “winners,” value securities, create analyst consensus, or touch a portfolio. It produces the evidence-backed company substrate those downstream stages need.

The key design rule is:

> A narrative theme may create research questions, but it cannot create an eligible company candidate. Candidate eligibility requires an explicit mapping rationale, a resolved issuer and security, claim-relative evidence, and deterministic gate results. Readiness-critical exposure must be quantified or bounded; an honestly labeled `UNKNOWN` remains useful research output but cannot be draft-ready.

## 2. Current-system boundary

### 2.1 Existing contracts to preserve

The current repository already provides useful upstream primitives:

- `SourceClaim`, `SourceThesis`, `BasketMember`, `BasketEvaluation`, and `ThesisRun` in `market_lab/source_thesis.py:74-157`;
- direct claim extraction with source URL, artifact, author, capture time, and exact line citation in `market_lab/source_thesis.py:247-293`;
- conservative candidate behavior: only explicit known ticker mentions become `SourceThesis.candidate_tickers`; industry inference is not used for source-derived candidates (`market_lab/source_thesis.py:408-418`, `538-588`);
- strict post-source market windows and synthetic/cache-like promotion blocks (`market_lab/source_thesis.py:515-531`, `631-771`);
- stable claim IDs, copied run-local source snapshots, resumable stages, append-only audit entries, claim dispositions, evidence rows, independent review, and failure-closed finalization in `market_lab/mlab_ingest.py`;
- a small `FactorSnapshot` with valuation/growth/margin fields and explicit source labels in `market_lab/factors.py:13-40`;
- synthetic factors that are deliberately placeholders and return `source="synthetic"` (`market_lab/factors.py:111-127`);
- research/mock safety flags in `market_lab/config.py:48-84`.

The current targeted baseline was executed while writing this spec:

```text
uv run pytest tests/market_lab/test_source_thesis.py \
                  tests/market_lab/test_mlab_ingest.py \
                  tests/market_lab/test_factors.py -q
16 passed in 0.31s
```

### 2.2 Accepted web-evidence dependency

Company intelligence consumes the evidence model specified by:

```text
/Users/ozlabs/OzLabs/docs/market-lab/WEB_EVIDENCE_IMPLEMENTATION_SPEC.md
```

That contract requires immutable content-addressed snapshots, exact segments/locators, claim links, source lineage, temporal fields, typed failures, budget records, and no search-snippet evidence. Company intelligence must not build a second fetcher, source store, audit ledger, or evidence standard.

Until that web-evidence layer is implemented and accepted, company intelligence may run only against catalogued frozen fixtures. A live run, or a run consuming a non-fixture evidence packet, must return `BLOCKED_UPSTREAM_EVIDENCE` rather than silently using search snippets, generated summaries, legacy free-text evidence, or unsnapshotted pages.

#### 2.2.1 Machine-checkable compatibility predicate

The company layer implements one pure validator:

```text
validate_web_evidence_input(input_root, mode, as_of_utc, accepted_policy)
  -> WebEvidenceCompatibilityResult

WebEvidenceCompatibilityResult:
  status: ACCEPTED | BLOCKED_UPSTREAM_EVIDENCE
  mode: frozen | live
  accepted_schema_versions[]
  verified_evidence_ids[]
  rejected_evidence_ids[]
  reason_codes[]
  input_digest
  verification_report_digest
```

`status=ACCEPTED` if and only if every applicable item below is true; no weighted score or reviewer prose can override a failed item:

1. Every consumed claim-evidence row has `schema_version="mlab-evidence.v2"`. Legacy `mlab_ingest.add_evidence` rows, `mlab-evidence.v1`, rows containing only `source`/free-text `note`, search results, snippets, provider answers, and generated summaries are ineligible as company evidence.
2. Every row resolves to exactly one segment record with `schema_version="web-segment.v1"` and one manifest with `schema_version="web-snapshot.v1"`; the segment shape is the section 5.3 contract of the web-evidence spec plus this explicit version tag. Unknown or mixed schema versions fail closed.
3. `snapshot_id == "sha256:" + raw_sha256`; recomputing SHA-256 over `raw.bin` equals `raw_sha256`; byte length matches; and, when extraction succeeded, recomputing the extracted artifact hash equals `extracted_sha256`.
4. The segment references that snapshot; recomputing its canonical content hash equals `segment_sha256`; its declared locator resolves against the recorded extracted artifact; and the resolved bytes/value equal `verbatim_excerpt_or_value`.
5. The evidence row references the same `claim_id`, `snapshot_id`, and `segment_id`; its locator and excerpt/value match the segment; its stance is not `context` when used to satisfy a material support gate; and its source class satisfies the claim-relative hierarchy in section 9.
6. Publication, effective, validity, retrieval, filing, amendment, and source-vintage fields pass the company run's `as_of_utc` policy. A missing required temporal field, future artifact, wrong issuer/entity, or incompatible period/unit/scope fails the affected material edge.
7. The audit ledger's first `mlab-audit.v2` event correctly anchors prior bytes, every subsequent `previous_event_hash`/`event_hash` recomputes, and each consumed row has an `evidence.linked` event whose output hashes include the verified snapshot, segment, and evidence-row digests. The source run ends in `run.web_evidence_completed`; `IN_PROGRESS`, `BLOCKED`, `DEGRADED`, missing, or invalid terminal state is not accepted for company publication.
8. The source run has a machine-readable `mlab-web-evidence-acceptance.v1` record containing its run ID, mode, input/output/audit-head digests, policy hash, verifier/tool versions, all section 16.2 hard-integrity booleans, command-result digests for the applicable section 17 gates, and independent review `{reviewer_id, author_id, decision, reviewed_digest}`. All hard booleans must be true, `decision=APPROVE`, reviewer and author must differ, and `reviewed_digest` must equal the recomputed source-run digest.
9. In `frozen` mode only, the acceptance record may instead identify a repository fixture-catalog entry. The catalog entry must pin all artifact hashes, expected semantic digest, policy hash, and `as_of_utc`; the validator recomputes them with zero network calls. An arbitrary directory or old `evidence.jsonl` is not a frozen fixture.
10. In `live` mode, no fixture exception applies: the accepted implementation record, live source-run terminal state, audit chain, hashes, locators, temporal checks, and independent approval must all pass.

The company layer recomputes this predicate; it does not trust an `accepted=true` assertion. Any failure returns `BLOCKED_UPSTREAM_EVIDENCE` with stable reason codes such as `WE_SCHEMA_UNSUPPORTED`, `WE_LEGACY_FREE_TEXT`, `WE_SNAPSHOT_HASH_INVALID`, `WE_SEGMENT_LOCATOR_INVALID`, `WE_AUDIT_CHAIN_INVALID`, `WE_SOURCE_RUN_NOT_COMPLETED`, `WE_ACCEPTANCE_RECORD_INVALID`, `WE_REVIEW_NOT_APPROVED`, or `WE_TEMPORAL_INELIGIBLE`. No packet may reach deterministic validation or publication from a blocked input.

### 2.3 Gaps this layer closes

The current code does not yet provide:

- a theme ontology or value-chain graph;
- issuer discovery beyond an explicit, small known-ticker list;
- a security master or issuer/security distinction;
- CIK/accession/form-aware company evidence;
- material exposure calculations with numerator, denominator, units, periods, and confidence;
- peer/competitor sets with explicit relationship types;
- moat claims linked to measurable evidence and counterevidence;
- transcript provenance or speaker/section locators;
- a catalyst event model;
- immutable company packets or company-intelligence gates.

`FactorSnapshot.ai_impact_score` and keyword heuristics are not substitutes for material revenue exposure. They may remain a legacy quantitative input, but they cannot satisfy any company-intelligence gate.

## 3. Non-goals

Version 1 must not:

- create, queue, evaluate, or execute any order;
- write to mock, options, TSMOM, VT Trend, candidate-queue, broker, or portfolio state;
- rank winners or emit `BUY`, `SELL`, target price, or position size;
- perform DCF, reverse DCF, comparable valuation, or scenario valuation;
- infer a candidate solely from an industry keyword, LLM answer, search rank, or ticker-like uppercase token;
- treat management guidance, an IR deck, or an earnings-call statement as independently verified fact;
- treat search snippets, generated summaries, embeddings, or analyst prose as evidence;
- scrape paywalled/licensed transcripts without permission or bypass access controls;
- estimate exact revenue exposure when the company does not disclose it;
- combine incompatible periods, currencies, segments, geographies, or gross/net revenue bases;
- create a general graph database, vector database, workflow engine, or agent swarm;
- crawl arbitrary sites recursively;
- add live-trading dependencies or weaken current safety gates.

## 4. System shape

```text
finalized/adjudicated MLAB claims + accepted web evidence
                           |
                           v
                 [G0 upstream eligibility]
                           |
                           v
              [theme definition and scope]
                           |
                           v
             [value-chain nodes and edges]
                           |
                           v
      [issuer discovery with explicit rationale]
                           |
                           v
         [issuer identity and security resolution]
                           |
                           v
 [exposure] [business quality] [moat/competition] [catalysts]
             \          |          /
                           v
      [deterministic packet validator: G0-G9]
                           |
                           v
 DRAFT_READY_PENDING_REVIEW | PARK_RESEARCH | REJECT_MAPPING
                           |
                           v
       [immutable digest + independent G10 review]
                           |
                           v
            final READY | parked | rejected
                           |
                           v
 downstream valuation and investment committee; no orders
```

Models or analyst agents may propose themes, nodes, relationships, candidate issuers, and interpretations. Deterministic code owns identity resolution, schema validation, period/unit checks, evidence eligibility, duplicate-origin handling, calculations, gates, artifact hashes, and the draft validation outcome. Independent review controls only the digest-bound G10 publication transition.

## 5. Future code and test layout

The repository currently declares `packages = ["market_lab"]`; use flat modules for the first slice:

```text
market_lab/company_intelligence.py          # versioned domain schemas and deterministic gates
market_lab/company_identity.py              # issuer/security master and resolution
market_lab/company_exposure.py              # period/unit-safe exposure calculations
market_lab/company_documents.py             # SEC/IR/transcript/catalyst normalization
market_lab/company_intelligence_store.py    # immutable run artifacts, locks, audit, replay
market_lab/company_intelligence_runner.py   # bounded orchestration over accepted evidence
market_lab/company_intelligence_cli.py      # build/validate/render/replay/benchmark
scripts/market_lab_company_intelligence.py

tests/market_lab/test_company_intelligence_contract.py
tests/market_lab/test_company_identity.py
tests/market_lab/test_company_exposure.py
tests/market_lab/test_company_documents.py
tests/market_lab/test_company_moat.py
tests/market_lab/test_company_intelligence_store.py
tests/market_lab/test_company_intelligence_pipeline.py
tests/market_lab/test_company_intelligence_cli.py
tests/market_lab/test_company_intelligence_safety.py
tests/market_lab/test_company_intelligence_benchmark.py
tests/market_lab/fixtures/company_intelligence/
```

Do not add provider SDKs in this slice. SEC and public IR acquisition must arrive through the accepted web-evidence provider protocols and snapshots. The company layer consumes snapshot/segment IDs and may issue typed acquisition requests; it does not perform raw network I/O.

## 6. Run root, artifact contract, and immutability

A company-intelligence run is separate from, but points back to, one or more source-ingest runs:

```text
${MARKET_LAB_DATA_DIR}/company_intelligence/<company_run_id>/
  status.json
  manifest.json
  policy_snapshot.json
  input_refs.json
  theme_map.json
  value_chain.json
  issuer_discovery.jsonl
  identity_resolutions.jsonl
  company_packets/
    drafts/
      <company_candidate_id>.json
    <company_candidate_id>.json
    <company_candidate_id>.md
  rejected_mappings.jsonl
  next_actions.json
  audit_log.jsonl
  independent_review.json
  independent_review.md
  publication.json
```

The source ingest run may contain a pointer-only record:

```text
<mlab-run>/company_intelligence_runs.jsonl
```

That pointer includes `company_run_id`, path, input digest, status, created time, and output digest. It does not duplicate the evidence ledger.

### 6.1 Commit protocol

For every JSON/Markdown artifact:

1. validate the in-memory object against its exact schema version;
2. serialize canonical JSON with sorted keys and finite numbers only;
3. write to a same-filesystem temporary path;
4. flush and `fsync` file contents;
5. atomically replace the destination;
6. `fsync` the parent directory where supported;
7. append the audit event under a run lock only after the artifact verifies;
8. preserve prior finalized runs; corrections create a new run with `supersedes_run_id`.

JSONL appends take the run lock, write one complete canonical line, flush, and `fsync`. Crash recovery truncates only a final partial line after recording a recovery event; it never rewrites valid prior rows.

### 6.2 Run manifest

```text
schema_version: mlab-company-run.v1
company_run_id
supersedes_run_id nullable
created_at_utc
as_of_utc
safety_mode: research_mock_only
source_run_ids[]
source_claim_ids[]
input_evidence_ids[]
input_artifact_hashes[]
policy_version / policy_hash
software_version / git_revision
requested_theme_ids[]
mode: frozen | live
run_budget
artifact_paths
```

A stable `company_run_id` is derived from the canonical digest of immutable inputs, `as_of_utc`, and policy version. The same inputs must replay to the same semantic outputs. A changed source snapshot, evidence edge, policy, or `as_of` cutoff creates a different run ID.

## 7. Identity and ID rules

IDs are hashes of canonical identity fields, not mutable names:

```text
theme_id              = sha256(namespace + canonical theme definition + as_of)
value_chain_node_id    = sha256(theme_id + canonical node label + role)
issuer_id              = registry-qualified ID when available; otherwise provisional hash
security_id            = market + security type + primary identifier + effective interval
company_candidate_id   = sha256(theme_id + issuer_id + security_id + horizon + mechanism digest)
exposure_claim_id      = sha256(candidate + metric + scope + period + source segment)
moat_claim_id          = sha256(candidate + mechanism + scope + valid interval)
catalyst_id            = sha256(candidate + event type + issuer event ID/date + source)
```

Preferred issuer identifiers:

1. SEC CIK for SEC filers;
2. LEI where lawfully and reliably available;
3. jurisdiction plus official company-registry identifier;
4. a provisional ID with `identity_status=UNRESOLVED`.

Preferred security identifiers:

1. FIGI/ISIN/CUSIP only when licensed or lawfully available;
2. exchange MIC plus local symbol plus effective dates;
3. an explicit provisional identifier.

Ticker alone is not identity. Symbols may be reused, changed, delisted, or represent multiple share classes. The packet must distinguish issuer, operating company, parent, subsidiary, ADR depositary relationship, fund, and listed security.

## 8. Core schemas

All schemas reject unknown enum values, duplicate IDs, non-finite numbers, malformed timestamps, and incompatible schema versions. Optional fields are explicit `null`; absence is not converted to zero.

### 8.1 Theme definition

```text
schema_version: mlab-theme.v1
theme_id
name
canonical_definition
included_mechanisms[]
excluded_mechanisms[]
geographies[]
horizon
as_of_utc
origin_claim_ids[]
material_claim_ids[]
counterclaim_ids[]
keywords[]
synonyms[]
ambiguous_terms[]
analyst_rationale
rationale_claim_ids[]
rationale_evidence_ids[]
falsifiers[]
status: PROPOSED | VALIDATED | BLOCKED | REJECTED
```

The theme is a bounded economic mechanism, not a label such as “AI,” “robotics,” or “energy transition.” It must say what demand, cost, regulation, capacity, substitution, or pricing mechanism transmits value and what is out of scope.

### 8.2 Value-chain graph

```text
ValueChainGraph:
  schema_version: mlab-value-chain.v1
  theme_id / as_of_utc
  nodes[] / edges[]
  coverage_gaps[]
  graph_digest

ValueChainNode:
  node_id
  label
  role: INPUT | COMPONENT | EQUIPMENT | MANUFACTURER | PLATFORM |
        DISTRIBUTOR | SERVICE | CUSTOMER | COMPLEMENT | SUBSTITUTE |
        REGULATOR | CAPITAL_PROVIDER
  description
  geography
  economic_driver
  bottleneck_type: NONE | CAPACITY | IP | REGULATORY | DATA | DISTRIBUTION |
                   SWITCHING | CAPITAL | LABOR | OTHER
  material_claim_ids[]
  evidence_ids[]
  counterevidence_ids[]
  confidence: LOW | MEDIUM | HIGH
  status: PROPOSED | EVIDENCED | DISPUTED | BLOCKED

ValueChainEdge:
  edge_id
  from_node_id / to_node_id
  relation: SUPPLIES | BUYS_FROM | ENABLES | DISTRIBUTES | COMPETES_WITH |
            SUBSTITUTES | COMPLEMENTS | REGULATES | FINANCES
  economic_transmission
  units_or_basis
  valid_from / valid_to
  claim_ids[] / evidence_ids[]
  status: PROPOSED | EVIDENCED | DISPUTED | BLOCKED
```

A graph can contain hypotheses, but only `EVIDENCED` nodes/edges may support issuer discovery eligibility. A disconnected popularity list is invalid.

### 8.3 Issuer and security identity

```text
IssuerRecord:
  schema_version: mlab-issuer.v1
  issuer_id
  legal_name / normalized_name
  aliases[]
  parent_issuer_id / ultimate_parent_issuer_id nullable
  subsidiaries[]
  jurisdiction
  sec_cik nullable
  lei nullable
  registry_identifiers[]
  entity_type: OPERATING_COMPANY | HOLDING_COMPANY | FUND | SPV |
               GOVERNMENT | PRIVATE_COMPANY | OTHER
  filer_status
  identity_effective_from / identity_effective_to
  source_evidence_ids[]
  identity_status: RESOLVED | PROVISIONAL | CONFLICTED | RETIRED

SecurityRecord:
  schema_version: mlab-security.v1
  security_id
  issuer_id
  security_type: COMMON | PREFERRED | ADR | ETF | CLOSED_END_FUND |
                 BOND | OPTION | PRIVATE | OTHER
  symbol
  exchange_mic
  currency
  share_class
  voting_rights_note
  adr_ratio nullable
  identifiers[]
  active_from / active_to
  primary_listing
  investability_status: SUPPORTED_EQUITY | RESEARCH_ONLY_UNSUPPORTED |
                        PRIVATE_NO_SECURITY | DELISTED | IDENTITY_BLOCKED
  source_evidence_ids[]
  resolution_status: RESOLVED | AMBIGUOUS | CONFLICTED
```

Version 1 can promote only `COMMON`, `ADR`, or `ETF` records explicitly supported by current Market Lab data plumbing. Other types remain research-only and cannot be silently coerced into an equity ticker.

### 8.4 Issuer discovery row

```text
schema_version: mlab-issuer-discovery.v1
discovery_id
theme_id
value_chain_node_ids[]
proposed_issuer_name
proposed_security_hint nullable
discovery_method: EXPLICIT_SOURCE | OFFICIAL_REGISTRY | PEER_FILING |
                  CUSTOMER_SUPPLIER_DISCLOSURE | ANALYST_MAPPING |
                  SECONDARY_LEAD
mechanism_rationale
rationale_claim_ids[]
rationale_evidence_ids[]
query_ids[]
origin_cluster_ids[]
as_of_utc
status: LEAD | EVIDENCE_PENDING | IDENTITY_PENDING | ELIGIBLE | REJECTED
rejection_codes[]
```

`SECONDARY_LEAD` can start research but cannot become `ELIGIBLE` without a claim-appropriate fetched source. A source with no explicit ticker may still lead to a company candidate only through a new `ANALYST_MAPPING` or official-discovery row with independent evidence and rationale. The original `SourceThesis.candidate_tickers` remains unchanged.

### 8.5 Exposure claim

```text
schema_version: mlab-exposure.v1
exposure_claim_id
company_candidate_id
issuer_id
value_chain_node_id
readiness_critical: true | false
criticality_rationale
exposure_type: REPORTED_SEGMENT_REVENUE | REPORTED_PRODUCT_REVENUE |
               REPORTED_GEOGRAPHIC_REVENUE | REPORTED_CUSTOMER_CONCENTRATION |
               REPORTED_ORDER_BACKLOG | MANAGEMENT_QUANTIFIED |
               MANAGEMENT_QUALITATIVE | ANALYST_DERIVED_RANGE | UNKNOWN
metric_name
numerator_value / numerator_low / numerator_high nullable
denominator_value nullable
currency nullable
unit
fiscal_period_start / fiscal_period_end
period_type: QUARTER | YEAR | TTM | POINT_IN_TIME
scope
accounting_basis
calculation_expression nullable
computed_share_low / computed_share_high nullable
materiality_band: IMMATERIAL | MINOR | MATERIAL | CORE | UNKNOWN
source_claim_ids[]
source_evidence_ids[]
counterevidence_ids[]
source_tier
origin_cluster_ids[]
temporal_fit
entity_scope_fit / period_fit / unit_fit / denominator_fit
confidence: LOW | MEDIUM | HIGH
status: VALID | QUALITATIVE_ONLY | ESTIMATED_RANGE | CONFLICTED | BLOCKED
blockers[]
```

`readiness_critical` is fixed in the immutable candidate input from the evidenced theme-to-issuer mechanism; it is not inferred from the measured percentage and cannot be toggled by the packet renderer. Every `false` value requires a claim-linked `criticality_rationale` explaining why that exposure does not determine candidate eligibility.

An optional sub-5% exception is a separate immutable input:

```text
schema_version: mlab-exposure-exception.v1
exception_id
company_candidate_id / exposure_claim_id
exception_type: DISPROPORTIONATE_PROFIT_OR_CASH_FLOW_SENSITIVITY
quantified_exposure_low / quantified_exposure_high
profit_or_cash_flow_mechanism
supporting_claim_ids[] / supporting_evidence_ids[]
reviewer_id / mapping_author_id
decision: APPROVE | REQUEST_CHANGES | REJECT
reviewed_input_digest / decided_at_utc
```

The exception is valid only when the exposure itself is a compatible quantified value/range, the decision is `APPROVE`, reviewer and mapping author differ, evidence/temporal gates pass, and `reviewed_input_digest` matches the candidate/exposure inputs. It can justify a quantified `IMMATERIAL`/`MINOR` critical exposure; it can never convert `UNKNOWN`, qualitative-only, conflicted, or blocked exposure into readiness.

### 8.6 Moat and competition

```text
MoatAssessment:
  schema_version: mlab-moat.v1
  company_candidate_id / as_of_utc
  claims[]
  competitor_relationships[]
  business_quality_metrics[]
  unresolved_questions[]
  overall_status: EVIDENCED | MIXED | INSUFFICIENT | REFUTED

MoatClaim:
  moat_claim_id
  mechanism: COST_ADVANTAGE | SWITCHING_COST | NETWORK_EFFECT |
             INTANGIBLE_ASSET | REGULATORY_POSITION | SCALE |
             DISTRIBUTION | DATA_ADVANTAGE | PROCESS_KNOWHOW |
             CAPACITY_BOTTLENECK | NONE | OTHER
  proposition
  measurable_indicator
  observation_period
  supporting_claim_ids[] / supporting_evidence_ids[]
  refuting_claim_ids[] / refuting_evidence_ids[]
  management_claim_only
  durability_horizon
  erosion_triggers[]
  disposition: SUPPORTED | MIXED | REFUTED | UNRESOLVED

CompetitorRelationship:
  relationship_id
  focal_issuer_id / other_issuer_id
  relationship: DIRECT | ADJACENT | SUBSTITUTE | CUSTOMER |
                SUPPLIER | COMPLEMENT | UNKNOWN
  product_scope / geography / customer_scope
  effective_from / effective_to
  evidence_ids[]
  confidence
```

The layer does not collapse moat into one unexplained score. It preserves each mechanism, evidence, counterevidence, measurable indicator, and erosion trigger.

### 8.7 Document record

```text
schema_version: mlab-company-document.v1
document_id
issuer_id
security_ids[]
document_type: SEC_10K | SEC_10Q | SEC_8K | SEC_20F | SEC_6K |
               SEC_EXHIBIT | PROXY | IR_EARNINGS_RELEASE | IR_DECK |
               IR_TRANSCRIPT | LICENSED_TRANSCRIPT | EVENT_NOTICE |
               REGULATORY_DECISION | OTHER
document_identifier
accession nullable
form nullable
filed_at / published_at / effective_at / period_end nullable
amendment_of_document_id nullable
supersedes_document_id nullable
source_tier
publisher / issuing_authority
canonical_url
snapshot_id
extracted_artifact_id
segment_ids[]
origin_cluster_id
license_terms_note
access_status
entity_match_status / temporal_fit
```

### 8.8 Transcript segment

```text
schema_version: mlab-transcript-segment.v1
transcript_segment_id
document_id
issuer_id
event_type / event_date
speaker_name
speaker_role
prepared_or_qa: PREPARED | Q_AND_A | UNKNOWN
section_heading
sequence_number
verbatim_text
segment_id / exact_locator
source_evidence_id
transcript_origin: OFFICIAL | LICENSED | SECONDARY | UNKNOWN
correction_status
confidence
```

Speaker attribution must come from the acquired document or a deterministic parser with a recorded confidence. Low-confidence attribution cannot satisfy a management-statement gate. Unofficial/secondary transcripts are discovery/context until corroborated or explicitly accepted by reviewer policy.

### 8.9 Catalyst event

```text
schema_version: mlab-catalyst.v1
catalyst_id
company_candidate_id
issuer_id
security_ids[]
event_type: EARNINGS | INVESTOR_DAY | PRODUCT_LAUNCH | CAPACITY |
            REGULATORY | TRIAL_RESULT | CONTRACT | PRICING |
            INDEX_EVENT | CAPITAL_ALLOCATION | LEGAL | MACRO |
            OTHER
name
mechanism
expected_at_start / expected_at_end
timezone
status: CONFIRMED | EXPECTED | RUMORED | OCCURRED | DELAYED |
        CANCELLED | UNKNOWN
source_claim_ids[] / source_evidence_ids[]
counterevidence_ids[]
source_tier
confirmation_level
leading_indicators[]
success_observations[]
failure_observations[]
review_trigger
last_verified_at
freshness_sla_days
```

A vague “could benefit soon” claim is not a catalyst. `CONFIRMED` requires an official dated event or an equivalent claim-appropriate source. `RUMORED` cannot make a packet `DRAFT_READY_PENDING_REVIEW` by itself.

### 8.10 Company intelligence packet

```text
schema_version: mlab-company-intelligence.v1
company_run_id
company_candidate_id
as_of_utc
safety_mode: research_mock_only
theme_id / value_chain_node_ids[]
issuer
securities[]
selected_security_id nullable
mapping_rationale
material_claim_ids[]
evidence_ids[] / origin_cluster_ids[]
exposure_claims[]
exposure_summary
business_model_summary
business_quality_metrics[]
moat_assessment
competitor_set[]
document_inventory[]
catalysts[]
risks[]
falsifiers[]
missing_information[]
source_freshness_summary
gate_results[]
validation_outcome: DRAFT_READY_PENDING_REVIEW | PARK_RESEARCH | REJECT_MAPPING
publication_status: DRAFT | FINALIZED | BLOCKED_REVIEW
outcome: READY | PARK_RESEARCH | REJECT_MAPPING | null
rejection_codes[]
next_actions[]
input_digest / draft_packet_digest
review_status / reviewed_digest nullable
publication_envelope_digest nullable
```

Every material prose assertion in the Markdown renderer must cite stable claim/evidence IDs or be labeled `ANALYST_JUDGMENT`. Generated prose is never added back as evidence. The draft packet is immutable once `draft_packet_digest` is computed. Review and publication are separate artifacts that reference that digest; they never rewrite the draft.

## 9. Source hierarchy and acquisition requirements

Source quality is claim-relative. The same source can be authoritative for “management said X” and weak for “X is objectively true.”

### 9.1 Required source classes

| Question | Preferred source | Allowed fallback | Cannot satisfy gate |
|---|---|---|---|
| Issuer identity | SEC submissions/ticker registry, exchange or official registry | official IR legal identity | search result, wiki-like summary, ticker mention |
| Security identity | exchange/issuer/SEC cover page with effective dates | licensed security master | ticker alone |
| Filed financials | exact SEC filing/XBRL fact with accession, period, unit, amendment | official annual/quarterly report snapshot | finance-site summary or model estimate |
| Segment/product exposure | filing note/table or official quantified release | management quantified statement, clearly labeled | narrative keyword count |
| Customer/supplier relation | counterparty or focal-company filing, contract/exhibit, official disclosure | reputable secondary lead pending corroboration | unsourced supply-chain list |
| Current guidance | filed 8-K/6-K exhibit, official earnings release | official call transcript | analyst paraphrase |
| Management interpretation | official/licensed transcript exact speaker segment | official interview | generated summary |
| Competitive structure | filings from focal company and peers, regulator or industry primary data | diverse secondary research with origin dedupe | company deck alone |
| Catalyst date/status | issuer event notice, filing, regulator calendar/decision | reputable report as `EXPECTED`/`RUMORED` | model-predicted date |

### 9.2 SEC requirements

For every SEC-derived fact preserve:

- CIK and resolved issuer ID;
- form, accession, filing date, report period, and amendment status;
- filing document URL and immutable snapshot ID;
- exact filing segment or XBRL concept/context/unit;
- fiscal period, start/end dates, dimensions, decimals, and currency/unit;
- whether the value is filed, amended, calculated, or company-presented non-GAAP;
- supersession/version relationship;
- entity match and `as_of` eligibility.

Do not select “latest fact” without period and filing-cutoff logic. Historical runs may use only filings available at `as_of_utc`. An amended filing controls current analysis but must not overwrite the historical vintage.

### 9.3 Investor-relations requirements

IR documents are accepted only when the canonical issuer domain and issuer relationship are resolved. Store canonical URL, snapshot, publication time, document type, event/period, and origin cluster.

IR statements are `company_stated`. They can establish what management reported, guided, scheduled, or claimed. Competitive, moat, market-size, and causal claims still require counterevidence or an explicit `management_claim_only=true` label.

### 9.4 Transcript requirements

Version 1 supports:

1. official issuer-hosted transcripts;
2. lawfully acquired licensed transcripts with retained license note;
3. filed earnings-call exhibits;
4. secondary transcripts only as context/discovery.

The system must not bypass paywalls or store content beyond applicable terms. Every cited statement requires document ID, speaker, event date, prepared/Q&A classification where available, exact locator, verbatim text, and transcript origin. Corrections create superseding documents.

### 9.5 Catalyst requirements

Every material catalyst gets:

- event type and economic mechanism;
- best-known bounded date window and timezone;
- source tier and confirmation level;
- success, failure, delay, and cancellation observations;
- a freshness SLA and next verification time;
- links to claims and immutable evidence;
- distinction between scheduled event and hoped-for outcome.

## 10. Deterministic theme and value-chain mapping

### 10.1 Theme validation

A proposed theme passes validation only when:

- at least one material upstream claim is `VERIFIED` or `MIXED` with both branches preserved;
- definition, inclusions, exclusions, horizon, geography, mechanism, and falsifiers are populated;
- every material mechanism has claim/evidence links;
- ambiguous terms are enumerated rather than silently expanded;
- counterclaims and disconfirmation questions exist;
- the graph does not use synthetic data as economic evidence.

An `UNRESOLVED` claim may remain in the map but cannot be the sole basis of an `EVIDENCED` node or edge.

### 10.2 Graph construction

The first pass may propose nodes and edges. Deterministic validation then:

1. normalizes labels and rejects duplicate IDs;
2. verifies all referenced claims/evidence and `as_of` cutoffs;
3. checks allowed node/edge enums;
4. requires a stated transmission mechanism for every edge;
5. marks unsupported edges `PROPOSED` or `BLOCKED`;
6. detects cycles but does not reject valid economic cycles;
7. requires at least one path from demand/cost/regulatory driver to the candidate node;
8. records missing value-chain stages and alternate/substitute paths;
9. preserves disputed edges instead of averaging them away.

A candidate cannot become eligible from a value-chain node unless there is an evidence-backed path from the theme mechanism to that node.

## 11. Issuer and security discovery

### 11.1 Discovery sequence

For each evidenced value-chain node:

1. extract explicit company names and securities from eligible source segments;
2. query official registries and SEC identifiers for exact entities;
3. inspect focal and peer filings for named customers, suppliers, competitors, segments, and products;
4. inspect canonical IR documents for business/segment descriptions;
5. use secondary sources only to propose leads;
6. run explicit omissions/countersearches for private companies, substitutes, foreign issuers, parents/subsidiaries, and non-pure-play alternatives;
7. resolve issuer identity before security identity;
8. create one discovery row per distinct rationale and preserve rejected leads.

### 11.2 Identity resolution

Deterministic resolution compares:

- legal and alias names;
- CIK/registry IDs;
- jurisdiction;
- parent/subsidiary relationships;
- official domain;
- security class and exchange;
- effective dates relative to `as_of_utc`.

Automatic `RESOLVED` requires an exact registry identifier or two compatible official identity sources. Conflicting official identifiers produce `CONFLICTED` and block the candidate. Fuzzy-name similarity may rank resolution candidates but cannot resolve identity by itself.

### 11.3 Security selection

The layer may select a security only when:

- the issuer-security relationship is evidenced;
- the security was active at `as_of_utc`;
- exchange, symbol, class, and currency are known;
- ADR/share-class economics are recorded where applicable;
- the security type is supported by current policy;
- no identity conflict remains.

Private companies, acquired subsidiaries, delisted securities, unsupported foreign listings, and funds with unknown holdings may remain in the value chain but cannot be selected as a direct candidate.

## 12. Material revenue exposure

### 12.1 Measurement hierarchy

Use the strongest available level and retain weaker rows separately:

1. filed product/segment revenue;
2. filed geographic or customer concentration;
3. official quantified revenue/order/backlog statement;
4. management quantified statement;
5. analyst-derived range from compatible disclosed inputs;
6. qualitative statement;
7. unknown.

A lower level cannot overwrite a higher level. Conflicting values remain separate and trigger review.

### 12.2 Calculation rules

A computed exposure share is valid only when:

- numerator and denominator refer to the same issuer scope;
- periods align or an explicit, reviewed reconciliation exists;
- currency and unit match;
- gross/net accounting basis is compatible;
- segment eliminations and intercompany revenue are handled;
- no overlapping segment/product rows are summed twice;
- the exact formula and input evidence IDs are stored;
- values were public by `as_of_utc`.

For a simple compatible ratio:

```text
exposure_share = exposure_revenue / consolidated_revenue
```

For ranges, calculate bounds from declared compatible inputs and retain the range. Do not report more precision than the least precise source. If only qualitative evidence exists, set values to `null`, `materiality_band=UNKNOWN`, and `status=QUALITATIVE_ONLY`.

### 12.3 Initial materiality policy

These are workflow thresholds, not accounting or investment truths:

```text
IMMATERIAL:  upper bound < 1%
MINOR:       lower bound < 5% and upper bound >= 1%
MATERIAL:    lower bound >= 5% and upper bound < 20%
CORE:        lower bound >= 20%
UNKNOWN:     no compatible quantified range
```

If a range crosses bands, report the least favorable/least certain combination and preserve both bounds; do not force one band. A readiness-critical theme claim requires `MATERIAL`/`CORE` or a valid `mlab-exposure-exception.v1` for a smaller quantified exposure with disproportionate profit/cash-flow sensitivity. Revenue exposure alone does not prove earnings exposure.

### 12.4 Anti-false-precision rules

- Management adjectives such as “significant” do not become percentages.
- Search-result market-share figures are not exposure evidence.
- Keyword frequency in a 10-K is not materiality.
- Backlog is not revenue unless explicitly labeled and reconciled.
- TAM multiplied by assumed market share is not issuer revenue.
- Segment growth does not equal theme growth when the segment contains unrelated products.
- Customer concentration cannot identify a theme unless the customer/theme link is separately evidenced.
- Gross revenue, net revenue, bookings, billings, ARR, GMV, and orders are distinct metrics.
- Missing exposure is `UNKNOWN`, not zero.

## 13. Business quality, moat, and competition

### 13.1 Required business-quality fields

The packet may include, when evidence supports them:

- revenue mix and concentration;
- gross/operating margin and trend;
- recurring versus transactional economics;
- capital intensity and reinvestment needs;
- working-capital/cash-conversion characteristics;
- customer/supplier concentration;
- capacity/utilization where disclosed;
- pricing and volume decomposition;
- dilution, debt, and capital-allocation context;
- management guidance history as facts, not predictive scoring.

Every metric stores period, unit, scope, source, transformation, and `as_of` eligibility. The company layer does not calculate valuation multiples.

### 13.2 Moat assessment protocol

For every proposed moat mechanism:

1. state the causal proposition;
2. identify at least one measurable indicator;
3. collect focal-company evidence;
4. collect peer/customer/regulatory counterevidence where available;
5. record durability horizon and erosion triggers;
6. classify company-only assertions;
7. adjudicate `SUPPORTED`, `MIXED`, `REFUTED`, or `UNRESOLVED`.

No aggregate moat score is required for the MVP. `SUPPORTED` requires at least one non-context eligible segment plus completed counterevidence lane. A company deck alone yields at most `UNRESOLVED` or `MIXED`, depending on contrary evidence.

### 13.3 Competition protocol

Competitor sets are scoped by product, customer, geography, and date. “Competitor” is not a permanent global label. The system must distinguish:

- direct competitors for the same customer/job;
- adjacent suppliers at different value-chain stages;
- substitutes that remove demand;
- complements that may co-benefit;
- customers or suppliers mistakenly presented as peers.

At least one competitor relationship must be evidenced for `DRAFT_READY_PENDING_REVIEW`. If no public comparable can be evidenced, G6 is `BLOCKED` and the draft is `PARK_RESEARCH` with an explicit rationale and owned next action; reviewer assertion alone cannot change G6. Peer filings should be searched for asymmetric descriptions and omitted risks.

## 14. Catalyst and risk tracking

The company packet maintains catalysts and falsifiers separately.

A catalyst answers “what observable event may change information or expectations, and when?” A falsifier answers “what observation makes the mechanism wrong or materially weaker?” Neither is a price target.

Required controls:

- use UTC internally and preserve source timezone;
- represent uncertain timing as a bounded window;
- distinguish announcement, effective date, commercial start, revenue recognition, and cash realization;
- update status through a superseding run/event; do not rewrite history;
- expired unobserved catalysts become `DELAYED`, `CANCELLED`, or `UNKNOWN`, never silently removed;
- each `DRAFT_READY_PENDING_REVIEW` packet has at least one objective monitoring/falsification trigger and a review date/event;
- rumor-only catalysts cannot be the sole reason for readiness.

## 15. Gate model

Every gate emits:

```text
gate_id
status: PASS | FAIL | BLOCKED | NOT_APPLICABLE
reason_codes[]
claim_ids[] / evidence_ids[]
artifact_ids[]
checked_at_utc
policy_version
```

### G0 — Upstream evidence eligibility

Pass conditions:

- referenced MLAB runs and claims exist;
- material origin claims are adjudicated;
- `validate_web_evidence_input` returns `ACCEPTED` for the exact input digest under section 2.2.1;
- every evidence link resolves to the accepted immutable snapshot/segment or a separately versioned deterministic data artifact;
- no search snippet, generated answer, or synthetic data is used as company evidence;
- evidence was available by `as_of_utc`;
- critical contradictions are resolved or explicitly `MIXED`.

Failure result: run-level `BLOCKED_UPSTREAM_EVIDENCE` before packet validation, using CLI exit `3`; fabricated/manipulated evidence additionally records `R_PROVENANCE_INVALID` and cannot be retried without corrected immutable inputs.

### G1 — Theme scope

Pass conditions:

- mechanism, inclusions, exclusions, horizon, geography, falsifiers, and material claims are present;
- at least one evidenced mechanism exists;
- disconfirmation questions are recorded.

Failure result: `PARK_RESEARCH`.

### G2 — Value-chain integrity

Pass conditions:

- schema-valid graph;
- candidate node has an evidenced path from the theme driver;
- proposed/disputed edges do not masquerade as evidenced;
- substitutes and missing stages are recorded.

Failure result: `PARK_RESEARCH`.

### G3 — Issuer identity

Pass conditions:

- issuer resolved through exact official identifier or compatible official sources;
- parent/subsidiary scope is explicit;
- no unresolved identity conflict.

Failure result: `PARK_RESEARCH`; proven wrong entity yields `REJECT_MAPPING`.

### G4 — Security identity and investability

Pass conditions:

- issuer-security relation, class, exchange, currency, and effective interval resolve;
- selected security was active at `as_of_utc`;
- type is supported by policy.

Failure result: `PARK_RESEARCH` for potentially resolvable data; `REJECT_MAPPING` for private/no security, delisted-at-as-of, or wrong instrument.

### G5 — Exposure materiality

Evaluate G5 after schema, evidence, period, unit, entity, scope, denominator, `as_of`, double-count, and contradiction checks. Its result is total and order-dependent:

| Condition | G5 status | Deterministic validation result |
|---|---|---|
| Any readiness-critical exposure is missing, `UNKNOWN`, `QUALITATIVE_ONLY`, `CONFLICTED`, `BLOCKED`, or lacks a compatible quantified bound | `BLOCKED` | `PARK_RESEARCH` with `B_EXPOSURE_CRITICAL_UNKNOWN` or the more specific mismatch blocker |
| Every readiness-critical exposure is quantified and at least `MATERIAL`, with all compatibility checks passing | `PASS` | eligible for `DRAFT_READY_PENDING_REVIEW` if all other mandatory gates pass |
| A readiness-critical exposure is quantified below `MATERIAL` and has a valid matching `mlab-exposure-exception.v1` | `PASS` | eligible for `DRAFT_READY_PENDING_REVIEW` if all other mandatory gates pass |
| A readiness-critical exposure is demonstrably `IMMATERIAL` after completed research and has no valid exception | `FAIL` | `REJECT_MAPPING` with `R_EXPOSURE_IMMATERIAL` |
| A readiness-critical exposure is quantified `MINOR` without a valid exception | `BLOCKED` | `PARK_RESEARCH` with `B_EXPOSURE_EXCEPTION_REQUIRED`; policy may later reject only through a new reviewed run |
| Only non-critical auxiliary rows are `UNKNOWN` | no effect on an otherwise passing G5 | allowed only when each row has `readiness_critical=false`, claim-linked `criticality_rationale`, honest null values, and an owned next action |

There is no reviewer discretion outside the versioned exception artifact and no path from critical `UNKNOWN` to draft-ready or final `READY`. At least one valid readiness-critical exposure row is required for any candidate whose mapping mechanism depends on issuer exposure.

### G6 — Business quality and competition

Pass conditions:

- business model and economic transmission are evidence-linked;
- competitor set is scoped and evidenced;
- management-only claims are labeled;
- counterevidence lane is complete;
- material risks and erosion triggers exist.

Failure result: `PARK_RESEARCH`; refuted core mechanism yields `REJECT_MAPPING`.

### G7 — Document completeness and freshness

Pass conditions:

- required SEC/official documents for the issuer type and period are inventoried;
- amendments/supersessions are handled;
- transcript origin and speaker locators validate for cited statements;
- catalyst dates/status meet freshness SLA or are explicitly blocked.

Failure result: `PARK_RESEARCH`.

### G8 — Temporal and provenance integrity

Pass conditions:

- every material input was public by `as_of_utc`;
- historical vintages are selected correctly;
- all calculations resolve to input segments;
- origin clusters prevent duplicated corroboration;
- hashes and locators verify.

Failure result: `REJECT_MAPPING` for leakage/fabrication; otherwise `PARK_RESEARCH` pending correction.

### G9 — Safety and side effects

Pass conditions:

- `safety_mode=research_mock_only`;
- no broker/order/options/portfolio modules are imported by the runner;
- protected state hashes and mtimes are unchanged;
- no output contains order action, quantity, limit price, or live instruction.

Failure result: run-level `BLOCKED_SAFETY`; no packet finalizes.

### G10 — Independent review and publication transition

G10 is not part of the deterministic G0-G9 eligibility calculation. The validator first writes an immutable draft packet and full gate report, computes `draft_packet_digest`, and emits exactly one `validation_outcome`: `DRAFT_READY_PENDING_REVIEW`, `PARK_RESEARCH`, or `REJECT_MAPPING`.

The reviewer receives that digest and the immutable run-draft digest. G10 passes only when:

- reviewer is not the mapping author;
- review decision is `APPROVE` and names both reviewed digests;
- all blockers in parked/rejected drafts have owned next actions;
- replay reproduces the draft packet, gate report, and run-draft semantic digests;
- artifact hashes and audit head verify; and
- no draft input, policy, gate result, or artifact changed after the review digest was computed.

On pass, finalization writes a new immutable publication envelope referencing—never mutating—the approved draft. It maps `DRAFT_READY_PENDING_REVIEW -> READY`, `PARK_RESEARCH -> PARK_RESEARCH`, and `REJECT_MAPPING -> REJECT_MAPPING`. Missing review, `REQUEST_CHANGES`, `REJECT`, digest mismatch, changed packet, or replay mismatch leaves `publication_status=BLOCKED_REVIEW`, preserves the original deterministic findings, and emits no final outcome.

## 16. Outcomes and rejection codes

### 16.1 Outcomes

- `validation_outcome=DRAFT_READY_PENDING_REVIEW`: G0-G9 passed; the immutable draft is eligible for independent review but is not published and cannot enter a downstream layer.
- `validation_outcome=PARK_RESEARCH`: plausible mapping but missing, stale, conflicted, or insufficient evidence remains.
- `validation_outcome=REJECT_MAPPING`: the issuer/security does not provide the claimed exposure, identity/instrument is wrong, or the core mechanism is refuted.
- final `outcome=READY`: G10 approved the unchanged draft and replay; it is complete enough for downstream valuation/committee research, not an investment recommendation or mock-order permission.

Apply outcomes in this order:

1. upstream evidence incompatibility yields run-level `BLOCKED_UPSTREAM_EVIDENCE`; safety or integrity failure blocks the run;
2. proven rejection condition yields draft `REJECT_MAPPING`;
3. any blocked mandatory G1-G9 gate yields draft `PARK_RESEARCH`;
4. all mandatory G0-G9 gates yield `DRAFT_READY_PENDING_REVIEW`;
5. G10 alone publishes the unchanged reviewed draft and maps its validation outcome to the final outcome.

### 16.2 Initial rejection codes

```text
R_IDENTITY_WRONG_ENTITY
R_IDENTITY_CONFLICT
R_SECURITY_NO_INVESTABLE_MAPPING
R_SECURITY_INACTIVE_AT_ASOF
R_EXPOSURE_IMMATERIAL
R_EXPOSURE_WRONG_SCOPE
R_EXPOSURE_DOUBLE_COUNTED
R_CORE_MECHANISM_REFUTED
R_VALUE_CHAIN_NO_EVIDENCED_PATH
R_PROVENANCE_INVALID
R_TEMPORAL_LEAKAGE
R_SYNTHETIC_AS_EVIDENCE
R_UNLAWFUL_OR_UNLICENSED_SOURCE
R_MANIPULATED_OR_DUPLICATE_CANDIDATE
R_SAFETY_SIDE_EFFECT
```

Missing data is not a rejection. It is `PARK_RESEARCH` with a typed blocker.

## 17. Public Python API contract

The MVP exposes deterministic, synchronous functions. No API performs network I/O directly.

```text
validate_theme(theme, evidence_index, policy) -> ValidationResult
validate_web_evidence_input(input_root, mode, as_of_utc, policy) -> WebEvidenceCompatibilityResult
build_value_chain(theme, proposals, evidence_index, policy) -> ValueChainGraph
propose_issuer_discoveries(theme, graph, evidence_index, proposals) -> list[IssuerDiscovery]
resolve_issuer(discovery, official_identity_records, as_of, policy) -> IdentityResolution
resolve_security(issuer, security_records, as_of, policy) -> SecurityResolution
assess_exposure(candidate, exposure_inputs, evidence_index, policy) -> ExposureAssessment
assess_moat(candidate, moat_inputs, competitor_inputs, evidence_index, policy) -> MoatAssessment
normalize_documents(raw_document_refs, evidence_index, policy) -> list[CompanyDocument]
build_catalyst_calendar(candidate, event_inputs, evidence_index, policy) -> list[Catalyst]
build_company_packet(inputs, policy) -> CompanyIntelligencePacket
validate_company_packet(packet, evidence_index, policy) -> GateReport
finalize_company_run(run_dir, independent_review, policy) -> PublicationResult
render_company_packet(packet) -> str
replay_company_run(run_dir) -> ReplayResult
```

Proposal objects are never accepted as evidence. Every API taking proposals also takes an evidence index and must label unsupported proposals.

Typed results use enums/status records rather than `None` or broad exception swallowing. Unknown schema versions, invalid hashes, broken locators, and policy violations are hard errors. Missing lawful data is a typed blocker.

The runner's top-level result has `status: COMPLETED | BLOCKED_UPSTREAM_EVIDENCE | BLOCKED_SAFETY | BLOCKED_REVIEW`. `BLOCKED_UPSTREAM_EVIDENCE` includes the compatibility result and is returned before any packet draft is built.

## 18. CLI contract

Future entry point:

```text
uv run python scripts/market_lab_company_intelligence.py <command> ...
```

### 18.1 `build`

```text
build
  --source-run <path>            repeatable
  --theme <theme.json>
  --as-of <ISO-8601 UTC>
  --mode frozen|live
  --policy <policy.json>
  --output-root <path>
  --candidate-limit <n>
  --budget-profile <name>
  --require-independent-review
```

`--mode live` means the runner may request acquisition from the accepted web-evidence layer. It is distinct from price-data `--network`. Default is `frozen` until live acceptance.

Exit codes:

```text
0  completed; all emitted packets and parked/rejected records valid
2  schema/input error
3  upstream evidence unavailable or invalid
4  deterministic gate blocked
5  budget exhausted with resumable next actions
6  independent review missing/negative
7  safety/provenance integrity failure
```

A run containing `PARK_RESEARCH` packets may exit `0` when the run completed honestly and all blockers are recorded. A run-level integrity/safety problem cannot exit `0`.

JSON output for exit `3` must include `{"status":"BLOCKED_UPSTREAM_EVIDENCE","reason_codes":[...],"input_digest":"...","verification_report_digest":"..."}`. It must not substitute exit `4`, a generic exception, or a packet-level park outcome.

### 18.2 Other commands

```text
validate-theme --theme ... --evidence-index ...
discover --run-dir ... --theme-id ...
resolve-identities --run-dir ...
validate-run --run-dir ... --require-no-side-effects
render --run-dir ... --format markdown|json
replay --run-dir ... --verify-hashes --verify-locators
benchmark --lane frozen|chaos|live --cases ... --output ... --fail-on-gate
```

Every command supports `--json` machine output. Human output goes to stdout; audit artifacts go only under the declared run root.

## 19. Audit events and resumability

Required event envelope follows the accepted audit-v2 contract and adds company fields:

```text
schema_version: mlab-audit.v2
event_id / run_id / trace_id
timestamp_utc
actor_type / actor_id / tool_version / model_version
company_candidate_ids[] / theme_id / issuer_ids[] / security_ids[]
claim_ids[] / evidence_ids[]
input_artifact_hashes[] / output_artifact_hashes[]
event_type / status / reason_code
policy_hash
previous_event_hash / event_hash
```

Minimum event types:

```text
company_run.created
theme.validated
value_chain.node_proposed
value_chain.edge_proposed
value_chain.validated
issuer.discovered
issuer.discovery_rejected
issuer.identity_resolved
issuer.identity_blocked
security.resolved
security.blocked
exposure.calculated
exposure.blocked
moat.claim_adjudicated
competitor.relationship_recorded
document.normalized
catalyst.recorded
gate.evaluated
packet.draft_written
packet.parked
packet.rejected
review.recorded
publication.written
run.finalized
run.replay_verified
run.blocked
```

Stable idempotency keys:

```text
discovery = sha256(theme_id + node_id + normalized issuer lead + rationale evidence IDs)
identity  = sha256(discovery_id + official record hashes + as_of)
exposure  = sha256(candidate_id + metric + period + scope + input evidence IDs + policy)
packet    = sha256(all normalized components + policy + as_of)
```

On resume:

- replay and validate audit events;
- verify artifacts, snapshots, locators, and calculations;
- skip completed identical operations;
- preserve typed blockers and retry only eligible upstream acquisitions;
- never reinterpret an unavailable value as zero;
- never duplicate a discovery, evidence origin, or packet;
- write owned next actions for missing identifiers, filings, exposure denominators, peer evidence, transcript access, catalyst freshness, and review.

## 20. Frozen fixture corpus

Build `OzCompanyIntelBench-v1` before any live default. At least 36 frozen cases:

| Slice | Cases | Required examples |
|---|---:|---|
| Theme/value-chain | 6 | evidenced path, unsupported edge, substitute path, ambiguous theme, mixed claim, missing stage |
| Issuer/security identity | 8 | exact CIK, alias, parent/subsidiary, two share classes, ADR ratio, private company, delisted-at-as-of, ticker reuse/conflict |
| Material exposure | 10 | filed segment ratio, product range, customer concentration, denominator mismatch, period mismatch, currency mismatch, double count, qualitative only, immaterial result, conflicting amendment |
| Moat/competition | 5 | company-only moat claim, peer corroboration, peer refutation, supplier mistaken as competitor, substitute erosion |
| Documents/transcripts/catalysts | 5 | amended 10-K, official transcript speaker, secondary transcript blocker, confirmed event timezone, expired vague catalyst |
| Safety/resume/chaos | 2+ | partial JSONL/crash resume, synthetic/snippet evidence and protected-state mutation attempts |

### 20.1 Canonical first fixture

Extend the existing Pequity robotics/bearings fixture only through new frozen company-intelligence artifacts; do not rewrite its source capture.

Expected behavior:

- original `SourceThesis.candidate_tickers` remains empty;
- the theme may be validated only from adjudicated claims/evidence;
- bearings value-chain nodes are proposed and evidence-labeled;
- issuer leads require separate analyst/official mapping rationale;
- at least one private/no-supported-security lead is preserved and parked/rejected appropriately;
- exposure estimates without compatible issuer disclosures remain `UNKNOWN` or a labeled range;
- no company becomes `DRAFT_READY_PENDING_REVIEW` or final `READY` merely because it is a known bearing manufacturer;
- no broker/order/options state changes.

### 20.2 Fixture format

Each case contains:

```text
case_id
description
frozen_as_of
policy_version
source_run fixture refs
web-evidence snapshot/segment fixtures
registry/SEC/IR/transcript/catalyst fixture refs
proposal inputs
expected theme/graph/identity/exposure results
expected gate statuses
expected validation outcome, G10 publication transition, and rejection codes
expected hashes or semantic digest
protected-state checks
```

Frozen tests make zero network calls.

## 21. Test plan

### 21.1 Contract tests

- accept only documented schema versions and enums;
- reject unknown/missing IDs, duplicate IDs, malformed periods, non-finite numbers, and unbounded ranges;
- require `as_of_utc`, safety mode, policy hash, input digest, and evidence references;
- require every material Markdown assertion to cite claim/evidence IDs or `ANALYST_JUDGMENT`;
- reject generated summaries/search snippets as evidence;
- reject legacy free-text/`mlab-evidence.v1` rows, unknown segment schemas, arbitrary fixture directories, and unsupported acceptance-record versions;
- recompute snapshot/extraction/segment/evidence hashes, locators, audit-v2 chain, source-run terminal state, acceptance record, review digest, and fixture-catalog digest;
- return typed `BLOCKED_UPSTREAM_EVIDENCE` and CLI exit `3` for each failed compatibility conjunct;
- reject synthetic factor/price data as company evidence;
- verify canonical serialization and stable IDs.

### 21.2 Theme/value-chain tests

- require mechanism, inclusions, exclusions, horizon, geography, and falsifiers;
- block unsupported material theme claims;
- preserve `MIXED` and disputed edges;
- require an evidenced path from theme driver to candidate node;
- ensure adding duplicate evidence from one origin does not improve status;
- ensure industry keyword inference alone cannot create an eligible issuer.

### 21.3 Identity tests

- exact CIK resolution;
- legal alias resolution with official support;
- parent/subsidiary distinction;
- common/ADR/multiple-share-class mapping;
- active interval at historical `as_of`;
- ticker reuse and symbol change;
- private company/no security;
- conflicting identifiers fail closed;
- fuzzy name score alone cannot resolve identity.

### 21.4 Exposure tests

- reproduce filed segment and product ratios from exact inputs;
- preserve source precision and ranges;
- reject period, unit, currency, entity, scope, and denominator mismatch;
- detect overlapping segment double count;
- distinguish revenue, backlog, bookings, ARR, GMV, units, and customer concentration;
- treat missing as `UNKNOWN`, never zero;
- classify initial materiality bands exactly at boundaries;
- preserve amended versus original values by `as_of`;
- ensure lower-quality evidence cannot overwrite filed data;
- ensure a qualitative mention cannot become an exact share.
- critical qualitative-only or `UNKNOWN` exposure always yields `PARK_RESEARCH`/`B_EXPOSURE_CRITICAL_UNKNOWN`;
- non-critical `UNKNOWN` is allowed only with `readiness_critical=false`, rationale, null values, and owned next action;
- quantified `MATERIAL`/`CORE` critical exposure can pass; quantified `MINOR` parks without a valid exception;
- a valid digest-bound sub-5% exception can pass, while stale, self-reviewed, unsupported, or `UNKNOWN` exceptions cannot;
- completed quantified `IMMATERIAL` exposure without exception yields `REJECT_MAPPING`/`R_EXPOSURE_IMMATERIAL`.

### 21.5 Document/transcript/catalyst tests

- exact SEC accession/form/period/amendment handling;
- XBRL context, dimensions, unit, and decimals preservation;
- canonical IR domain/entity match;
- transcript origin, speaker, Q&A, locator, and correction handling;
- licensed/paywall/access blockers;
- catalyst timezone normalization and bounded windows;
- scheduled event versus hoped-for outcome;
- stale, delayed, cancelled, rumored, and superseded events.

### 21.6 Moat/competition tests

- management-only moat claim cannot become `SUPPORTED` without policy-required evidence/countersearch;
- peer filing can support, qualify, or refute;
- relationship scope changes competitor classification;
- supplier/customer/complement cannot silently become direct competitor;
- erosion triggers and falsifiers are mandatory for supported claims;
- duplicate origin does not create independent corroboration.

### 21.7 Property/metamorphic tests

1. Reordering proposal, evidence, issuer, or candidate inputs cannot change IDs or outputs.
2. Duplicating one origin cluster cannot improve a gate.
3. Removing evidence cannot promote a status.
4. Adding direct refuting evidence cannot improve a mechanism without explicit adjudication.
5. Converting a quantified exposure to qualitative evidence cannot increase certainty/materiality.
6. Shifting `as_of` earlier excludes later filings, amendments, transcript corrections, and catalysts.
7. A ticker change cannot change issuer identity.
8. One issuer with two securities cannot be counted as two independent companies.
9. Missing values never become zero, `NaN`, infinity, or neutral scores.
10. A `PARK_RESEARCH` draft cannot become `DRAFT_READY_PENDING_REVIEW` without new eligible evidence or corrected identity/policy input; reviewer action alone cannot change deterministic eligibility.
11. Replay of immutable inputs reproduces semantic digests.
12. No company-intelligence function can write protected execution state.

### 21.8 Integration and chaos tests

- finalized MLAB fixture -> theme -> value chain -> issuer -> security -> exposure -> company packet;
- interrupted run resumes without duplicate rows/events;
- corrupted snapshot/locator/hash blocks G0/G8;
- partial JSONL recovery is explicit and deterministic;
- missing optional provider produces a typed next action;
- SEC 429/unavailable, IR 404, transcript paywall, malformed XBRL, and stale catalyst fail closed;
- conflicting amended filing preserves both versions and applies correct `as_of`;
- independent reviewer `REQUEST_CHANGES` prevents finalization;
- missing review preserves `DRAFT_READY_PENDING_REVIEW` and emits no final outcome;
- approved review of the exact immutable draft plus successful replay publishes final `READY`;
- changed packet/policy/gate report after review and replay mismatch both yield `BLOCKED_REVIEW` without changing deterministic gate findings;
- protected files retain hashes and mtimes;
- full Market Lab suite passes under an isolated data root.

## 22. Benchmark metrics and release gates

Do not collapse quality into one score. Report numerator, denominator, case IDs, and intervals where applicable.

Hard 100% integrity gates from the first pilot:

- schema-valid artifacts and audit events;
- zero snippet/generated-answer evidence;
- every material assertion resolves to a valid snapshot/segment or deterministic artifact;
- every selected issuer/security has resolved identity and effective dates;
- every exposure calculation reproduces from stored inputs;
- no period/unit/entity/scope mismatch is accepted;
- historical `as_of` replay excludes future documents;
- duplicate origins count once;
- frozen replay is deterministic;
- all typed blockers remain honest;
- broker/order/options/portfolio state is unchanged.

Initial quality gates on the 36+ frozen cases:

| Metric | Pilot gate |
|---|---:|
| Theme mechanism classification accuracy | >= 0.90 |
| Value-chain evidenced-edge precision | >= 0.95 |
| Issuer identity resolution precision | 1.00 on auto-resolved cases |
| Security mapping precision | 1.00 on selected securities |
| Exposure calculation accuracy | 1.00 on compatible numeric cases |
| Mismatch/double-count detection recall | 1.00 on seeded critical cases |
| Materiality-band accuracy | 1.00 on deterministic cases |
| SEC amendment/historical-vintage accuracy | >= 0.95 |
| Transcript speaker/locator validity | 1.00 on accepted segments |
| Catalyst date/status accuracy | >= 0.95 |
| Unsupported moat-promotion prevention | 1.00 |
| Honest park/reject behavior | 1.00 on blocked/adversarial cases |
| No-side-effect safety | 1.00 |

Live availability is measured separately. A live run with a lawful access blocker, rate limit, missing transcript, or stale official document may be operationally healthy but must remain `PARK_RESEARCH`/`BLOCKED`; it cannot pass by substituting weaker evidence.

## 23. Future acceptance commands

These commands are targets for the future implementation; this specification does not claim the files exist today.

### 23.1 Unit, frozen, and safety tests

```bash
cd /Users/ozlabs/market-lab
uv sync --extra dev

MARKET_LAB_DATA_DIR=/tmp/mlab_company_intel_unit_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_company_intel_unit_pycache \
uv run pytest \
  tests/market_lab/test_company_intelligence_contract.py \
  tests/market_lab/test_company_identity.py \
  tests/market_lab/test_company_exposure.py \
  tests/market_lab/test_company_documents.py \
  tests/market_lab/test_company_moat.py \
  tests/market_lab/test_company_intelligence_store.py \
  tests/market_lab/test_company_intelligence_pipeline.py \
  tests/market_lab/test_company_intelligence_cli.py \
  tests/market_lab/test_company_intelligence_safety.py \
  tests/market_lab/test_company_intelligence_benchmark.py -q
```

Required: zero failures and zero network calls.

### 23.2 Frozen benchmark

```bash
uv run python scripts/market_lab_company_intelligence.py benchmark \
  --lane frozen \
  --cases tests/market_lab/fixtures/company_intelligence/benchmark_v1.jsonl \
  --output /tmp/mlab_company_intel_frozen_metrics.json \
  --fail-on-gate
```

Required: every hard integrity gate and the pilot thresholds in section 22 pass.

### 23.3 Chaos benchmark

```bash
uv run python scripts/market_lab_company_intelligence.py benchmark \
  --lane chaos \
  --cases tests/market_lab/fixtures/company_intelligence/chaos_v1.jsonl \
  --output /tmp/mlab_company_intel_chaos_metrics.json \
  --fail-on-gate
```

Required: all injected failures are typed, no invalid evidence or calculation enters a packet, resume is idempotent, and no execution state changes.

### 23.4 Frozen end-to-end build

```bash
rm -rf /tmp/mlab_company_intel_run /tmp/mlab_company_intel_data

MARKET_LAB_DATA_DIR=/tmp/mlab_company_intel_data \
uv run python scripts/market_lab_company_intelligence.py build \
  --source-run tests/market_lab/fixtures/company_intelligence/pequity_mlab_run \
  --theme tests/market_lab/fixtures/company_intelligence/pequity_theme.json \
  --as-of 2026-07-13T23:59:59Z \
  --mode frozen \
  --policy tests/market_lab/fixtures/company_intelligence/policy_v1.json \
  --output-root /tmp/mlab_company_intel_run

uv run python scripts/market_lab_company_intelligence.py validate-run \
  --run-dir /tmp/mlab_company_intel_run/* \
  --require-no-side-effects
```

Required: source-derived ticker list remains unchanged; all discovered issuer mappings have separate rationale/evidence; unknown exposure remains unknown; packets and parked/rejected records validate.

### 23.5 Regression gate

```bash
MARKET_LAB_DATA_DIR=/tmp/mlab_company_intel_regression_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_company_intel_regression_pycache \
uv run pytest \
  tests/market_lab/test_source_thesis.py \
  tests/market_lab/test_mlab_ingest.py \
  tests/market_lab/test_factors.py -q

MARKET_LAB_DATA_DIR=/tmp/mlab_company_intel_full_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_company_intel_full_pycache \
uv run pytest tests/market_lab -q
```

Required: zero failures and unchanged default execution-state files.

## 24. MVP implementation sequence

### Slice 0 — Freeze contracts and fixtures

- add the versioned schemas/enums and policy snapshot;
- build 36+ adjudicated frozen/chaos cases;
- add protected-state hash harness;
- write failing contract, identity, temporal, exposure, and safety tests.

Exit: fixture review approved; no network or product behavior change.

### Slice 1 — Theme/value-chain and identity

- implement theme validator and graph contracts;
- implement discovery rows without automated web acquisition;
- implement SEC/official-record issuer identity and effective-dated security resolution;
- preserve every lead and rejection reason;
- render theme and identity artifacts.

Exit: frozen theme/identity cases pass with 100% selected-security precision.

### Slice 2 — Exposure and document normalization

- normalize SEC/IR/transcript/catalyst document references from accepted snapshots;
- implement compatible exposure ratios/ranges and mismatch/double-count blocks;
- add amendment and historical-`as_of` selection;
- add exact calculation lineage.

Exit: all numeric exposure cases reproduce exactly; every seeded mismatch blocks.

### Slice 3 — Moat, competition, catalysts, and packet

- implement scoped competitor relationships;
- implement moat-claim adjudication without aggregate score;
- implement catalyst/falsifier records and freshness;
- build/read/render immutable company packets;
- implement deterministic G0-G9 gates and draft validation outcomes.

Exit: end-to-end frozen packet and park/reject cases pass.

### Slice 4 — Store, replay, review, and accepted web-evidence integration

- add locked atomic store and audit events;
- add crash resume, replay, digest-bound independent review, publication envelopes, and finalization;
- integrate typed acquisition requests with the accepted web-evidence layer;
- run frozen, chaos, isolated full regression, and then live shadow canaries.

Exit: independent review approves; no side effects; live mode remains opt-in.

Do not automate analyst spawning until frozen proposal/evidence/gate contracts are stable. Do not add valuation or committee scoring inside this layer.

## 25. MVP acceptance

The MVP is accepted only when one frozen source run can produce at least three realistic issuer leads, deterministic validation emits the evidence-appropriate draft outcomes, and G10 correctly publishes the reviewed mixture of `READY`, `PARK_RESEARCH`, and/or `REJECT_MAPPING`—not because a target count must be met.

All of the following are mandatory:

1. Theme definition is bounded, falsifiable, evidence-linked, and time-scoped.
2. Value-chain graph distinguishes evidenced, proposed, disputed, and blocked nodes/edges.
3. Every issuer lead has a transparent discovery method and mapping rationale.
4. Issuer and security identities are separate, effective-dated, and exact enough for deterministic selection.
5. SourceThesis explicit-ticker behavior is unchanged; new inferred mappings are separately labeled analyst/official mappings.
6. Every exposure value/range reproduces from period/unit/scope-compatible evidence.
7. Qualitative or unavailable exposure remains honest `UNKNOWN`; readiness-critical `UNKNOWN` deterministically parks while justified non-critical `UNKNOWN` may remain in an otherwise draft-ready packet; no false precision.
8. SEC filings, amendments, IR artifacts, transcript segments, and catalysts preserve source/version/time/locator provenance.
9. Moat and competition outputs preserve counterevidence and do not turn company claims into verified advantage.
10. Every packet includes risks, falsifiers, freshness, blockers, and owned next actions.
11. Deterministic G0-G9 gates reproduce and select exactly one draft validation outcome.
12. Independent review is `APPROVE` for the unchanged draft/run digests and replay passes before G10 emits any final outcome.
13. Frozen and chaos benchmarks pass all hard gates.
14. Targeted and full Market Lab tests pass under isolated data roots.
15. Protected execution-state hashes and mtimes remain unchanged.
16. Live mode is still opt-in and returns `BLOCKED_UPSTREAM_EVIDENCE` until every conjunct in section 2.2.1 passes; frozen mode accepts only hash-pinned catalogued fixtures.

## 26. Explicit handoff to downstream layers

A `READY` packet means only:

- the economic theme and value-chain position are intelligible;
- issuer/security identity is resolved;
- exposure materiality is quantified or explicitly bounded under approved policy;
- company, competition, moat, and catalyst evidence is sufficiently complete for deeper research;
- provenance, time, and safety gates passed; and
- the publication envelope verifies against the approved immutable draft and replay digests.

`DRAFT_READY_PENDING_REVIEW` is not a downstream handoff state. Downstream loaders accept only a `publication.json` envelope whose draft digest, review digest, replay result, and final `outcome=READY` all verify.

The downstream valuation layer still must determine priced expectations and payoff. The investment committee still must assess evidence quality, valuation, quant support, downside, disagreement, and portfolio fit. Neither may treat `READY` as a recommendation.

The company layer exports stable packet/claim/evidence IDs and never copies conclusions into order state.

## 27. Definition of done

Implementation is done only when:

- schemas and artifacts are versioned, immutable after finalization, and replayable;
- a bounded theme becomes an evidence-labeled value-chain graph;
- issuer discovery and security resolution are deterministic and historically effective-dated;
- material exposure calculations are exact, period/unit/scope safe, and anti-false-precision;
- SEC/IR/transcript/catalyst inputs retain immutable provenance and valid locators;
- moat/competition analysis includes disconfirmation and scoped relationships;
- every missing fact becomes a typed blocker/next action rather than fabricated completion;
- frozen, chaos, safety, integration, and full regression tests have real passing output;
- an independent reviewer approves the exact immutable draft/run digests and replay verifies before publication;
- no broker/order/options/portfolio state changes;
- output is research substrate, not a trade instruction.

## 28. Source basis and dependency disposition

This specification is grounded in:

- `research/MARKET_LAB_VIRTUAL_AGENCY_ROADMAP.md`;
- current `market_lab/source_thesis.py`, `market_lab/mlab_ingest.py`, `market_lab/factors.py`, `market_lab/config.py`, and their tests;
- `/Users/ozlabs/OzLabs/docs/market-lab/WEB_EVIDENCE_IMPLEMENTATION_SPEC.md`;
- the adjacent R&D committee contract at `/Users/ozlabs/OzLabs/docs/market-lab/rd-swarm/INVESTMENT_COMMITTEE_RND.md` for downstream packet compatibility.

The earlier draft named `/Users/ozlabs/OzLabs/docs/market-lab/rd-swarm/COMPANY_INTELLIGENCE_RND.md` as a required dependency even though that artifact was never delivered. This correction formally removes that undeclared external report from the normative source set: the independent review identified the resulting self-block, and the correction task explicitly authorizes resolving it without inventing absent conclusions. Future R&D may propose a superseding version through normal evidence-backed review, but the missing filename is neither an implementation prerequisite nor a finalization gate for this version.
