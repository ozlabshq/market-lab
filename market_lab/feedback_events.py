"""
Feedback event hooks for the thesis-linked paper portfolio.

Produces structured feedback events that feed into learning loops.
Events can force tune/pause/retire decisions for strategies and processes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FeedbackEvent:
    """A structured feedback event."""
    event_id: str
    source: str              # "postmortem" | "scorecard" | "monitoring" | "analyst" | "system"
    event_type: str          # "process_feedback" | "thesis_feedback" | "risk_feedback" | "tune" | "pause" | "retire"
    target_type: str         # "strategy" | "thesis" | "process" | "analyst" | "position"
    target_id: str
    severity: str            # "info" | "warning" | "critical"
    description: str
    recommendation: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    created_at_utc: str = ""


@dataclass(frozen=True)
class LearningOverride:
    """A learning override that changes strategy/process behavior."""
    override_id: str
    feedback_event_id: str
    target_type: str
    target_id: str
    override_type: str       # "tune" | "pause" | "retire" | "adjust_sizing" | "adjust_risk"
    reason: str
    active: bool = True
    created_at_utc: str = ""
    applied_at_utc: Optional[str] = None


@dataclass(frozen=True)
class FeedbackStream:
    """Append-only stream of feedback events."""
    events: List[FeedbackEvent] = field(default_factory=list)
    overrides: List[LearningOverride] = field(default_factory=list)


def create_feedback_event(
    *,
    source: str,
    event_type: str,
    target_type: str,
    target_id: str,
    severity: str,
    description: str,
    recommendation: str = "",
    evidence_refs: Optional[List[str]] = None,
) -> FeedbackEvent:
    """Create a structured feedback event."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return FeedbackEvent(
        event_id=f"fb_{now}",
        source=source,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        severity=severity,
        description=description,
        recommendation=recommendation,
        evidence_refs=evidence_refs or [],
        created_at_utc=now,
    )


def process_feedback_event(
    event: FeedbackEvent,
    stream: FeedbackStream,
) -> FeedbackStream:
    """Process a feedback event and potentially create learning overrides.

    Rules:
    - "critical" severity always creates a learning override
    - "pause" event_type always creates a learning override
    - "retire" event_type always creates a learning override
    - "tune" event_type creates an override proportional to confidence
    - "warning" severity with recurring pattern creates a tune override
    """
    new_events = list(stream.events) + [event]
    new_overrides = list(stream.overrides)

    should_override = (
        event.severity == "critical"
        or event.event_type in ("pause", "retire")
    )

    if should_override or event.event_type == "tune":
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        override = LearningOverride(
            override_id=f"ovr_{now}",
            feedback_event_id=event.event_id,
            target_type=event.target_type,
            target_id=event.target_id,
            override_type=event.event_type if event.event_type in ("tune", "pause", "retire") else "adjust_risk",
            reason=event.recommendation or event.description,
            active=True,
            created_at_utc=now,
            applied_at_utc=now,
        )
        new_overrides.append(override)

    # Check for recurring warnings
    if event.severity == "warning":
        similar_events = [
            e for e in new_events
            if e.target_type == event.target_type
            and e.target_id == event.target_id
            and e.severity == "warning"
        ]
        if len(similar_events) >= 3:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            tune_override = LearningOverride(
                override_id=f"ovr_tune_{now}",
                feedback_event_id=event.event_id,
                target_type=event.target_type,
                target_id=event.target_id,
                override_type="tune",
                reason=f"Recurring warnings ({len(similar_events)}) triggered automatic tune",
                active=True,
                created_at_utc=now,
                applied_at_utc=now,
            )
            new_overrides.append(tune_override)

    return FeedbackStream(events=new_events, overrides=new_overrides)


def serialize_feedback_event(event: FeedbackEvent) -> str:
    """Canonical JSON serialization."""
    return json.dumps(asdict(event), default=str, sort_keys=True, indent=2)


def serialize_override(override: LearningOverride) -> str:
    """Canonical JSON serialization."""
    return json.dumps(asdict(override), default=str, sort_keys=True, indent=2)


def serialize_feedback_stream(stream: FeedbackStream) -> str:
    """Canonical JSON serialization."""
    return json.dumps(asdict(stream), default=str, sort_keys=True, indent=2)