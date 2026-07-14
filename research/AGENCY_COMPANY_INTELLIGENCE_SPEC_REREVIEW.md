# Market Lab Agency Company Intelligence Spec Re-Review

Reviewer: ozzy-review  
Decision: APPROVE  
Date: 2026-07-14 UTC  
Reviewed artifact: `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md`  
Prior review: `research/AGENCY_COMPANY_INTELLIGENCE_SPEC_REVIEW.md`

## Scope reviewed

I freshly re-reviewed the corrected company-intelligence specification against the prior REQUEST_CHANGES review. I did not edit the spec.

I focused on whether the four prior blockers were closed without weakening the research-only, evidence-backed Market Lab posture:

1. missing `COMPANY_INTELLIGENCE_RND.md` dependency / self-block;
2. ambiguous readiness semantics for critical `UNKNOWN` exposure;
3. missing machine-checkable accepted-web-evidence compatibility predicate;
4. circular `READY` / independent-review finalization semantics.

## Final decision

APPROVE.

The corrected spec is now implementation-ready as a specification. All four prior blockers are closed in the document, and I found no replacement blocker requiring another spec edit before implementation planning can proceed.

This approval is for the company-intelligence specification, not for any live company-intelligence implementation. The spec still correctly requires live/non-fixture runs to return `BLOCKED_UPSTREAM_EVIDENCE` until the accepted web-evidence contract is actually implemented, accepted, and independently approved.

## Prior blocker closure verification

### 1. Missing R&D dependency / self-block — CLOSED

Prior issue: the previous draft referenced `/Users/ozlabs/OzLabs/docs/market-lab/rd-swarm/COMPANY_INTELLIGENCE_RND.md` as a required dependency even though it was absent, making the spec self-blocking.

Corrected spec evidence:

- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1654-1663` now has an explicit “Source basis and dependency disposition” section.
- It states that the earlier missing R&D artifact is formally removed from the normative source set.
- It says the missing filename is neither an implementation prerequisite nor a finalization gate for this version.

Assessment: closed. The spec no longer depends on an absent artifact or invents conclusions from it.

### 2. Critical `UNKNOWN` exposure readiness ambiguity — CLOSED

Prior issue: the previous draft could be read as allowing a candidate with readiness-critical but unquantified exposure to become `READY` if the unknown was honestly labeled.

Corrected spec evidence:

- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:30` states that readiness-critical exposure must be quantified or bounded, and that `UNKNOWN` cannot be draft-ready.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:488-505` makes `readiness_critical` an immutable candidate input and defines the only sub-5% exception path as a digest-bound, independently reviewed, quantified exception.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1002-1013` makes G5 total and order-dependent: critical missing/`UNKNOWN`/qualitative/conflicted/blocked exposure parks; quantified material/core passes; quantified minor without exception parks; quantified immaterial without exception rejects; non-critical unknown has no effect only with rationale/nulls/next action.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1609-1611` repeats the MVP acceptance rule that unavailable exposure remains honest `UNKNOWN`, but readiness-critical `UNKNOWN` deterministically parks.

Assessment: closed. The G5 semantics are deterministic and testable, and reviewer discretion cannot convert critical `UNKNOWN` into draft-ready/final `READY`.

### 3. Accepted web-evidence predicate — CLOSED

Prior issue: the previous draft required “accepted web evidence” but did not define what the company layer must machine-check, leaving room to accept snippets, free-text evidence rows, or arbitrary frozen directories.

Corrected spec evidence:

- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:56-67` accepts the web-evidence dependency while requiring non-fixture/live inputs to block until the upstream evidence layer is accepted.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:68-100` defines `validate_web_evidence_input(...) -> WebEvidenceCompatibilityResult` and an if-and-only-if acceptance predicate.
- The predicate explicitly checks schema versions, snapshot hashes, segment locator/excerpt matching, claim/snapshot/segment row consistency, temporal eligibility, audit-v2 chain, source-run completion, machine-readable `mlab-web-evidence-acceptance.v1`, independent approval, fixture-catalog pinning, and live-mode non-fixture requirements.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:89-100` explicitly rejects legacy free-text rows, search results, snippets, provider answers, generated summaries, unsupported schemas, invalid hashes, invalid locators, incomplete source runs, invalid acceptance records, and unapproved reviews.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:945-958` threads that predicate into G0 and maps failure to run-level `BLOCKED_UPSTREAM_EVIDENCE` / exit `3`.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1319-1327` adds contract-test coverage for the predicate and typed blocked status.

Assessment: closed. The company layer now has a concrete compatibility predicate it must recompute; it does not trust prose or an `accepted=true` assertion.

### 4. `READY` / independent-review circularity — CLOSED

Prior issue: the previous draft mixed deterministic packet readiness and final publication, creating ambiguity about whether independent review happened before or after `READY`.

Corrected spec evidence:

- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:23-24` names deterministic draft outcomes followed by an independently reviewed publication decision.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:660-668` separates `validation_outcome`, `publication_status`, final `outcome`, draft digest, review status/digest, and publication-envelope digest.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1061-1075` states that G10 is not part of deterministic G0-G9, review binds to immutable draft/run digests, and finalization references rather than mutates the approved draft.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1078-1091` defines outcome ordering: G0/G9 blocks first, rejection conditions next, mandatory gate blockers park, all G0-G9 pass yields `DRAFT_READY_PENDING_REVIEW`, and only G10 maps the unchanged reviewed draft to final `READY`.
- `research/AGENCY_COMPANY_INTELLIGENCE_SPEC.md:1632` explicitly says `DRAFT_READY_PENDING_REVIEW` is not a downstream handoff state; downstream loaders accept only verified publication envelopes with final `outcome=READY`.

Assessment: closed. The two-phase state machine is now clear and preserves stable reviewer inputs.

## Category checks

### Deterministic executability

APPROVE. The spec defines stable schemas, gate statuses, validation outcomes, typed blockers, CLI exit codes, replay expectations, and materiality ordering. The remaining breadth is large, but implementation is sliced and acceptance is machine-testable.

### Historical issuer/security identity

APPROVE. The spec keeps ticker-only identity invalid, requires issuer/security separation, effective dates, official identifiers or compatible official sources, parent/subsidiary handling, ADR/share-class handling, and active-at-`as_of` selection.

### Exposure materiality

APPROVE. The corrected G5 model is deterministic: critical unknown parks, critical immaterial rejects, critical material/core can pass, and sub-material pass requires a quantified digest-bound exception. Non-critical unknown rows are allowed only with rationale, null values, and owned next action.

### Source provenance and web evidence

APPROVE as a spec. The company layer now blocks on incompatible upstream evidence and defines exactly what must be verified before consumption. This does not imply that the web-evidence implementation is accepted today; it means the company-intelligence spec handles that dependency safely.

### Temporal scope

APPROVE. The spec repeatedly requires `as_of_utc`, historical filing availability, amendment/supersession handling, source-vintage checks, effective intervals, and future-document exclusion in tests and gates.

### Missing data / failure gates

APPROVE. Missing data parks with typed blockers and next actions rather than being fabricated or converted to zero. Proven wrong mapping/exposure/provenance/safety failures reject or block as appropriate.

### Safety and side effects

APPROVE. The research-only boundary is preserved: no orders, no broker/options/portfolio state mutation, no live-trading dependency, protected-state hash/mtime checks, and no output containing order action/quantity/limit/live instruction.

### Testability

APPROVE. The spec includes concrete unit, frozen benchmark, chaos benchmark, end-to-end, property/metamorphic, safety, replay, and full-regression acceptance requirements. The future company-intelligence test files are intentionally targets, not claimed present artifacts.

## Verification performed

Structural closure check:

```text
rnd_disposition: PASS
critical_unknown_blocks: PASS
web_evidence_predicate: PASS
two_phase_review: PASS
```

Targeted current-source baseline under isolated roots:

```text
MARKET_LAB_DATA_DIR=/tmp/mlab_company_intel_rereview_data \
PYTHONPYCACHEPREFIX=/tmp/mlab_company_intel_rereview_pycache \
uv run pytest tests/market_lab/test_source_thesis.py \
              tests/market_lab/test_mlab_ingest.py \
              tests/market_lab/test_factors.py -q

16 passed in 0.21s
```

These tests verify the current baseline modules cited by the spec still pass. They do not validate the future company-intelligence implementation, which has not been built yet.

## Approval notes for implementers

- Keep Slice 0 limited to contracts, frozen/chaos fixtures, protected-state harnesses, and failing tests.
- Do not implement a second web fetcher/evidence store inside company intelligence.
- Treat `BLOCKED_UPSTREAM_EVIDENCE` as a run-level block before packet drafting.
- Preserve the distinction between `DRAFT_READY_PENDING_REVIEW` and final `READY`.
- Do not allow reviewer approval to change deterministic G0-G9 outcomes; approval only publishes an unchanged replayable draft.
- Do not weaken the research/mock-only side-effect gates.
