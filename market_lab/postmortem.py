"""
Postmortem analysis for thesis-linked paper positions.

Captures what happened, why, and what to learn. Produces structured
postmortem artifacts that feed into future research gates.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PositionResult:
    """Outcome of a paper position."""
    position_id: str
    proposal_id: str
    memo_id: str
    entry_price: float
    exit_price: Optional[float]
    pnl_pct: float
    pnl_absolute: float
    holding_bars: int
    entry_date: str
    exit_date: Optional[str]
    exit_reason: str
    benchmark_return_pct: float
    alpha_pct: float


@dataclass(frozen=True)
class AttributionBreakdown:
    """Separate thesis, valuation, timing, sizing, execution, and market effects."""
    thesis_alpha: float = 0.0
    valuation_alpha: float = 0.0
    timing_alpha: float = 0.0
    sizing_alpha: float = 0.0
    execution_alpha: float = 0.0
    market_beta: float = 0.0
    benchmark_alpha: float = 0.0
    unexplained: float = 0.0


@dataclass(frozen=True)
class PostmortemFinding:
    """A single finding from a postmortem analysis."""
    category: str            # "thesis" | "valuation" | "timing" | "sizing" | "execution" | "process" | "risk"
    description: str
    severity: str            # "info" | "warning" | "critical"
    recommendation: str = ""


@dataclass(frozen=True)
class Postmortem:
    """Complete postmortem for a thesis-linked paper position."""
    position_result: PositionResult
    attribution: AttributionBreakdown
    findings: List[PostmortemFinding] = field(default_factory=list)
    thesis_was_valid: bool = False
    process_gaps: List[str] = field(default_factory=list)
    learning_actions: List[str] = field(default_factory=list)
    created_at_utc: str = ""


def build_postmortem(
    result: PositionResult,
    attribution: AttributionBreakdown,
    prior_findings: Optional[List[PostmortemFinding]] = None,
) -> Postmortem:
    """Build a postmortem from a position result.

    Generates findings based on outcome data, attribution, and exit reason.
    """
    findings: List[PostmortemFinding] = list(prior_findings or [])
    learning_actions: List[str] = []
    process_gaps: List[str] = []

    # Thesis validity assessment
    thesis_was_valid = result.alpha_pct > 0

    # Check for negative alpha
    if result.alpha_pct < -0.05:
        findings.append(PostmortemFinding(
            category="thesis",
            description=f"Thesis underperformed benchmark by {abs(result.alpha_pct):.2%}",
            severity="warning",
            recommendation="Review thesis assumptions and evidence quality",
        ))
        learning_actions.append("schedule thesis review")

    # Check exit reason quality
    if result.exit_reason == "stop_loss":
        findings.append(PostmortemFinding(
            category="risk",
            description=f"Position hit stop loss at {result.pnl_pct:.2%}",
            severity="info",
            recommendation="Evaluate stop level calibration",
        ))
    elif result.exit_reason == "thesis_invalidation":
        findings.append(PostmortemFinding(
            category="thesis",
            description="Position exited due to thesis invalidation",
            severity="info",
            recommendation="Review invalidation trigger accuracy",
        ))
        learning_actions.append("review invalidation triggers")

    # Check for large drawdowns
    if result.pnl_pct < -0.15:
        findings.append(PostmortemFinding(
            category="risk",
            description=f"Large drawdown of {result.pnl_pct:.2%}",
            severity="critical",
            recommendation="Review sizing and risk controls for this thesis type",
        ))
        process_gaps.append("sizing may have been too aggressive for thesis confidence")

    # Attribution summary
    if abs(attribution.thesis_alpha) > 0.05:
        findings.append(PostmortemFinding(
            category="thesis",
            description=f"Thesis alpha contribution: {attribution.thesis_alpha:.2%}",
            severity="info",
        ))

    if result.holding_bars < 5:
        findings.append(PostmortemFinding(
            category="timing",
            description=f"Short holding period ({result.holding_bars} bars) may indicate timing issue",
            severity="info",
            recommendation="Review entry timing criteria",
        ))

    return Postmortem(
        position_result=result,
        attribution=attribution,
        findings=findings,
        thesis_was_valid=thesis_was_valid,
        process_gaps=process_gaps,
        learning_actions=learning_actions,
        created_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )


def compute_attribution(
    entry_price: float,
    exit_price: Optional[float],
    benchmark_entry: float,
    benchmark_exit: float,
    position_size_pct: float,
) -> AttributionBreakdown:
    """Compute simple attribution breakdown.

    Separates:
    - Market beta (benchmark return)
    - Benchmark alpha (excess return over benchmark)
    - Sizing effect (scaled by position size)
    - Unexplained remainder

    This is a simplified attribution. Future versions can separate thesis,
    valuation, timing, and execution with more granular data.
    """
    if exit_price is None or exit_price <= 0 or benchmark_exit <= 0:
        return AttributionBreakdown()

    asset_return = (exit_price / entry_price) - 1.0
    benchmark_return = (benchmark_exit / benchmark_entry) - 1.0

    market_beta = benchmark_return * position_size_pct
    benchmark_alpha = (asset_return - benchmark_return) * position_size_pct
    sizing_alpha = position_size_pct * asset_return  # simplified

    return AttributionBreakdown(
        market_beta=market_beta,
        benchmark_alpha=benchmark_alpha,
        thesis_alpha=benchmark_alpha * 0.6,  # simplified: thesis is largest alpha driver
        valuation_alpha=benchmark_alpha * 0.15,
        timing_alpha=benchmark_alpha * 0.15,
        execution_alpha=benchmark_alpha * 0.05,
        sizing_alpha=sizing_alpha * 0.05,
        unexplained=0.0,
    )


def serialize_postmortem(postmortem: Postmortem) -> str:
    """Canonical JSON serialization."""
    return json.dumps(asdict(postmortem), default=str, sort_keys=True, indent=2)