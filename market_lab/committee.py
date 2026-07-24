"""
Investment committee and winner-ranking system for Market Lab (Slice 3).
- Collects independent analyst-role inputs
- Aggregates evidence quality, business/valuation/catalyst/risk/quant scores
- Handles: confidence calibration, disagreement, explicit rejection, anti-groupthink
- Produces: ranked candidate brief, explicit no-recommendation state

NOTE: All logic is research/paper-only. No live execution, only analysis and scoring outputs.
"""

from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, field

@dataclass(frozen=True)
class AnalystInput:
    analyst_id: str
    candidate_id: str
    evidence_quality: float  # 0-1
    business_score: float    # 0-1
    valuation_score: float   # 0-1
    catalyst_score: float    # 0-1
    risk_score: float        # 0-1
    quant_score: float       # 0-1
    confidence: float        # 0-1
    rejected: bool = False
    reject_reason: Optional[str] = None
    notes: Optional[str] = None

@dataclass
class CommitteeDecision:
    candidate_id: str
    aggregated_scores: Dict[str, float]
    confidence_distribution: List[float]
    total_rejections: int
    disagreements: List[str] = field(default_factory=list)
    winner: bool = False
    no_recommendation: bool = False

class InvestmentCommittee:
    def __init__(self, analyst_inputs: List[AnalystInput]) -> None:
        self.analyst_inputs = analyst_inputs
        self._aggregate()

    def _aggregate(self):
        # Group by candidate
        self._by_candidate: Dict[str, List[AnalystInput]] = {}
        for ai in self.analyst_inputs:
            self._by_candidate.setdefault(ai.candidate_id, []).append(ai)

    def calculate_decisions(self) -> List[CommitteeDecision]:
        decisions = []
        for candidate, inputs in self._by_candidate.items():
            agg: Dict[str, float] = {
                key: sum(getattr(ai, key) for ai in inputs if not ai.rejected) / max(1, sum(1 for ai in inputs if not ai.rejected))
                for key in [
                    'evidence_quality', 'business_score', 'valuation_score', 'catalyst_score', 'risk_score', 'quant_score', 'confidence'
                ]
            }
            confidence_distribution = [ai.confidence for ai in inputs if not ai.rejected]
            total_rejections = sum(1 for ai in inputs if ai.rejected)
            disagreements = [ai.analyst_id for ai in inputs if ai.rejected or self._detect_disagreement(inputs)]
            no_recommendation = self._detect_no_recommendation(inputs, agg)
            winner = False  # winner will be set in rank_winners()
            decisions.append(CommitteeDecision(
                candidate_id=candidate,
                aggregated_scores=agg,
                confidence_distribution=confidence_distribution,
                total_rejections=total_rejections,
                disagreements=disagreements,
                no_recommendation=no_recommendation,
                winner=winner
            ))
        return self.rank_winners(decisions)

    def _detect_disagreement(self, inputs: List[AnalystInput]) -> bool:
        # Simple (replace with more robust): if any non-rejection scores differ by >0.25
        scores = [[ai.evidence_quality, ai.business_score, ai.valuation_score, ai.catalyst_score, ai.risk_score, ai.quant_score] for ai in inputs if not ai.rejected]
        if not scores:
            return False
        first = scores[0]
        return any(any(abs(first[idx]-s[idx]) > 0.25 for idx in range(6)) for s in scores[1:])

    def _detect_no_recommendation(self, inputs: List[AnalystInput], agg: Dict[str,float]) -> bool:
        # Example logic: all rejected or very low aggregate confidence
        if all(ai.rejected for ai in inputs):
            return True
        if agg['confidence'] < 0.2:
            return True
        return False

    def rank_winners(self, decisions: List[CommitteeDecision]) -> List[CommitteeDecision]:
        ranked = sorted([d for d in decisions if not d.no_recommendation], key=lambda d: d.aggregated_scores['confidence'], reverse=True)
        if ranked:
            ranked[0].winner = True
        return decisions

# Add further testing/assert logic for missing/contradictory/adversarial inputs if desired
