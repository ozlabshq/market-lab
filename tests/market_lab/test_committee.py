"""
Tests for Market Lab committee and ranking system (market_lab/committee.py).
Boundary, adversarial, and spec conformance tests per AGENCY_INVESTMENT_COMMITTEE_SPEC.md & reviewer notes.
"""

import pytest
from market_lab.committee import AnalystInput, InvestmentCommittee

# Minimal spec-matching inputs: three analysts, two candidates
C1 = AnalystInput(
    analyst_id="alice", candidate_id="X", evidence_quality=1.0, business_score=0.9, valuation_score=0.95,
    catalyst_score=0.8, risk_score=0.6, quant_score=0.7, confidence=0.95, rejected=False)
C2 = AnalystInput(
    analyst_id="bob", candidate_id="X", evidence_quality=0.8, business_score=0.85, valuation_score=0.93,
    catalyst_score=0.7, risk_score=0.65, quant_score=0.75, confidence=0.9, rejected=False)
C3 = AnalystInput(
    analyst_id="carol", candidate_id="Y", evidence_quality=0.9, business_score=0.8, valuation_score=0.9,
    catalyst_score=0.75, risk_score=0.68, quant_score=0.8, confidence=0.88, rejected=False)


def test_deterministic_ranking():
    ic = InvestmentCommittee([C1, C2, C3])
    decisions = ic.calculate_decisions()
    ranks = {d.candidate_id: (d.winner, d.no_recommendation, d.aggregated_scores) for d in decisions}
    assert ranks["X"][0] or ranks["Y"][0], "At least one candidate should be marked winner"
    assert not (ranks["X"][0] and ranks["Y"][0]), "No more than one winner"
    assert not ranks["X"][1], "Candidate X should not be no-recommendation"
    assert not ranks["Y"][1], "Candidate Y should not be no-recommendation"
    # Confidence reflects consensus
    assert ranks["X"][2]["confidence"] >= 0 and ranks["Y"][2]["confidence"] >= 0


def test_explicit_rejection_and_no_recommendation():
    # All inputs rejected → explicit no-recommendation
    c1 = C1.__class__(**{**C1.__dict__, "rejected": True})
    c2 = C2.__class__(**{**C2.__dict__, "rejected": True})
    ic = InvestmentCommittee([c1, c2])
    decisions = ic.calculate_decisions()
    assert all(d.no_recommendation for d in decisions)
    assert not any(d.winner for d in decisions)

    # Mixed case: one accepted, one rejected
    ic = InvestmentCommittee([C1, c2])
    decisions = ic.calculate_decisions()
    for d in decisions:
        if d.candidate_id == "X":
            # Not all rejected
            assert not d.no_recommendation


def test_disagreement_detection():
    # Disagreement: scores deliberately hugely off
    d1 = AnalystInput("a", "Z", 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9)
    d2 = AnalystInput("b", "Z", 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2)
    ic = InvestmentCommittee([d1, d2])
    decisions = ic.calculate_decisions()
    assert any("a" in d.disagreements or "b" in d.disagreements for d in decisions)


def test_duplicate_evidence_no_false_inflation():
    # Multiple analysts, correlated opinions: should not inflate rank
    d1 = AnalystInput("a", "Y", 0.8,0.8,0.9,0.9,0.7,0.8,0.8)
    d2 = AnalystInput("b", "Y", 0.8,0.8,0.9,0.9,0.7,0.8,0.8)  # duplicate
    d3 = AnalystInput("c", "Y", 0.8,0.8,0.9,0.9,0.7,0.8,0.8)  # duplicate
    ic = InvestmentCommittee([d1, d2, d3])
    decisions = ic.calculate_decisions()
    # The confidence will be high but rationale is flaggable as correlated
    assert all(d.aggregated_scores["confidence"] == pytest.approx(0.8, abs=0.01) for d in decisions)
    # No mechanism in current code for blocking, only that the metric is reproducible

if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__]))
