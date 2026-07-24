"""
Analyst/process scorecards for the thesis-linked paper portfolio.

Measures decision quality and discipline, not only P&L.
Scorecards track:
- Pre-trade: thesis quality, evidence quality, process discipline
- Post-trade: outcome quality, attribution, process adherence
- Aggregate: analyst performance, process quality trends
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .postmortem import Postmortem


@dataclass(frozen=True)
class ScorecardEntry:
    """A single scorecard entry for a decision or outcome."""
    scorecard_id: str
    position_id: str
    memo_id: str
    analyst_id: str
    score_type: str   # "pre_trade" | "post_trade" | "process"
    scores: Dict[str, float] = field(default_factory=dict)
    process_discipline_score: float = 0.0
    evidence_quality_score: float = 0.0
    decision_quality_score: float = 0.0
    outcome_score: float = 0.0
    notes: str = ""
    created_at_utc: str = ""


@dataclass(frozen=True)
class AnalystScorecard:
    """Aggregated scorecard for an analyst."""
    analyst_id: str
    total_decisions: int = 0
    avg_process_discipline: float = 0.0
    avg_evidence_quality: float = 0.0
    avg_decision_quality: float = 0.0
    avg_outcome: float = 0.0
    decisions_without_postmortem: int = 0
    last_updated_utc: str = ""


def compute_pre_trade_scores(
    memo_has_evidence: bool,
    memo_is_reviewed: bool,
    sizing_was_deterministic: bool,
    exit_plan_defined: bool,
    catalyst_monitoring_defined: bool,
    conviction: float,
) -> ScorecardEntry:
    """Compute pre-trade process scores.

    Measures how well the pre-trade process was followed.
    Returns a ScorecardEntry with scores in [0, 1] range.
    """
    evidence_quality = 1.0 if memo_has_evidence else 0.0
    process_discipline = sum([
        1.0 if memo_is_reviewed else 0.0,
        1.0 if sizing_was_deterministic else 0.0,
        1.0 if exit_plan_defined else 0.0,
        1.0 if catalyst_monitoring_defined else 0.0,
    ]) / 4.0

    decision_quality = (evidence_quality + process_discipline + conviction) / 3.0
    decision_quality = min(decision_quality, 1.0)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return ScorecardEntry(
        scorecard_id=f"pre_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        position_id="",
        memo_id="",
        analyst_id="system",
        score_type="pre_trade",
        scores={
            "evidence_quality": evidence_quality,
            "process_discipline": process_discipline,
            "decision_quality": decision_quality,
            "conviction": conviction,
        },
        process_discipline_score=process_discipline,
        evidence_quality_score=evidence_quality,
        decision_quality_score=decision_quality,
        outcome_score=0.0,
        created_at_utc=now,
    )


def compute_post_trade_scorecard(
    postmortem: Postmortem,
    analyst_id: str = "system",
) -> ScorecardEntry:
    """Compute post-trade scores from a completed postmortem.

    Measures:
    - Process discipline: were process gaps identified?
    - Decision quality: was the thesis valid?
    - Outcome score: normalized P&L and alpha
    """
    result = postmortem.position_result

    # Process discipline: inversed by number of process gaps
    process_discipline = max(0.0, 1.0 - (len(postmortem.process_gaps) * 0.2))

    # Decision quality: thesis validity + finding severity
    decision_quality = 0.5 + (0.5 if postmortem.thesis_was_valid else 0.0)
    critical_findings = sum(1 for f in postmortem.findings if f.severity == "critical")
    decision_quality = max(0.0, decision_quality - (critical_findings * 0.15))

    # Outcome score: normalized P&L capped at ±20%
    raw_pnl = result.pnl_pct
    normalized_pnl = max(-0.20, min(0.20, raw_pnl))
    outcome_score = 0.5 + (normalized_pnl / 0.40)  # maps -20%→0, 0%→0.5, +20%→1.0
    outcome_score = max(0.0, min(1.0, outcome_score))

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return ScorecardEntry(
        scorecard_id=f"post_{now}",
        position_id=result.position_id,
        memo_id=result.memo_id,
        analyst_id=analyst_id,
        score_type="post_trade",
        scores={
            "process_discipline": process_discipline,
            "decision_quality": decision_quality,
            "outcome_score": outcome_score,
            "total_return": raw_pnl,
            "alpha": result.alpha_pct,
        },
        process_discipline_score=process_discipline,
        evidence_quality_score=0.0,
        decision_quality_score=decision_quality,
        outcome_score=outcome_score,
        notes=f"Post-trade scorecard for {result.position_id}",
        created_at_utc=now,
    )


def aggregate_analyst_scorecard(
    entries: List[ScorecardEntry],
    analyst_id: str,
) -> AnalystScorecard:
    """Aggregate multiple scorecard entries into an analyst scorecard."""
    if not entries:
        return AnalystScorecard(analyst_id=analyst_id)

    n = len(entries)
    avg_process = sum(e.process_discipline_score for e in entries) / n
    avg_evidence = sum(e.evidence_quality_score for e in entries) / n
    avg_decision = sum(e.decision_quality_score for e in entries) / n
    avg_outcome = sum(e.outcome_score for e in entries) / n

    post_trade = [e for e in entries if e.score_type == "post_trade"]
    postmortem_count = len(post_trade)

    return AnalystScorecard(
        analyst_id=analyst_id,
        total_decisions=n,
        avg_process_discipline=round(avg_process, 4),
        avg_evidence_quality=round(avg_evidence, 4),
        avg_decision_quality=round(avg_decision, 4),
        avg_outcome=round(avg_outcome, 4),
        decisions_without_postmortem=n - postmortem_count,
        last_updated_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def serialize_scorecard(entry: ScorecardEntry) -> str:
    """Canonical JSON serialization."""
    return json.dumps(asdict(entry), default=str, sort_keys=True, indent=2)


def serialize_analyst_scorecard(sc: AnalystScorecard) -> str:
    """Canonical JSON serialization."""
    return json.dumps(asdict(sc), default=str, sort_keys=True, indent=2)