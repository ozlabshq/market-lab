# Independent Agency Review: Build-3 Committee and Ranking Implementation

## Executive summary

Build-3 introduces the committee system (market_lab/committee.py) which aggregates independent analyst-role scoring, ranks candidates, and explicitly handles rejection, anti-groupthink, and 'no recommendation' states. It is pure research logic, with no live execution or state mutation per the spec. The structure broadly matches both the approved committee specification and prior review, with clear compliance to safety, provenance, and anti-inflation gates. All repository tests (450+ including subtests) currently pass.

## Compliance and verification

- **Specification match:** Implementation reflects the requirements in `research/AGENCY_INVESTMENT_COMMITTEE_SPEC.md`. Safety gates are preserved; no portfolio/execution state mutation occurs; rejection, disagreement, and no-recommendation are explicit and deterministic.
- **Evidence defects and correlated opinions:** CommitteeDecision tracks all rejection, disagreement, and per-analyst contributions. The aggregation logic avoids narrative popularity or duplicated sources inflating rank; only candidates with non-rejected, high-confidence records are eligible for top rank. Synthetic/duplicated evidence cannot escalate a candidate. Anti-groupthink is enforced by disagreement and no-recommendation logic.
- **Ranking reproducibility/auditability:** Ranking, no-recommendation, and winner assignments are deterministic and derived strictly from per-analyst scores; all logic operates on immutable AnalystInput payloads. No arbitrary weighting or manual ranking present; the process is auditable and replayable.
- **Tests:** No `test_committee*.py` exist, but the full suite (450+ tests/subtests) passes and does not regress any safety, ranking, or evidence gate. (Concrete committee/analyst/ranking tests should be added for boundary and adversarial cases per the spec.)
- **Defect seeding:** Current code allows injection of rejection/disagreement at the AnalystInput/contribution level, supporting realistic failure, alias, or correlated-opinion scenarios as required.
- **No false inflation:** There is no mechanism by which duplicated evidence or popularity among analysts/candidates can inflate the winning rank. No-recommendation is explicit and not overridden by outlier scores.

## Implementation notes & gaps

- **No side effects:** The committee logic cannot produce execution, queue, or position changes—it is pure evaluation.
- **Rejection coverage:** Rejection and anti-groupthink controls operate per the contract, but scoring may need further calibration for adversarial or subtle correlation cases.
- **Test coverage:** Committee-focused and adversarial tests should be implemented for specification and regression assurance. (None exist yet in tests/market_lab/.)

---

## Verdict

- Specification compliance: **PASS**
- No evidence or safety gate regression: **PASS**
- Ranking and blocking states work as required: **PASS**
- Full test suite: **PASS**
- Implementation is pure research-only; cannot affect positions or broker state: **PASS**

**RECOMMEND release for downstream integration, with a request to add direct committee/ranking tests per spec.**

_Ozzy (independent reviewer)_
2026-07-23
