"""
Catalyst/invalidation monitoring for thesis-linked paper positions.

Monitors predeclared catalyst triggers and invalidation triggers,
producing monitoring snapshots without lookahead or future data.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


TriggerStatus = str  # "pending" | "triggered" | "expired" | "invalidated"


@dataclass(frozen=True)
class TriggerSnapshot:
    """Status of a single catalyst or invalidation trigger at a point in time."""
    trigger_id: str
    trigger_type: str  # "catalyst" | "invalidation"
    description: str
    status: TriggerStatus
    evidence_ref: Optional[str] = None
    triggered_at_utc: Optional[str] = None
    notes: str = ""


@dataclass(frozen=True)
class MonitoringSnapshot:
    """Snapshot of all triggers for a position at a given time."""
    position_id: str
    snapshot_time_utc: str
    catalyst_triggers: List[TriggerSnapshot] = field(default_factory=list)
    invalidation_triggers: List[TriggerSnapshot] = field(default_factory=list)
    any_invalidation_fired: bool = False
    alert_level: str = "green"  # green | yellow | red
    summary: str = ""


@dataclass(frozen=True)
class MonitorState:
    """Persistent state for the monitoring system."""
    position_monitors: Dict[str, List[MonitoringSnapshot]] = field(default_factory=dict)


def create_initial_monitoring_snapshot(
    position_id: str,
    catalyst_descriptions: List[str],
    invalidation_descriptions: List[str],
) -> MonitoringSnapshot:
    """Create the first monitoring snapshot with all triggers as 'pending'."""
    catalysts = [
        TriggerSnapshot(
            trigger_id=f"cat_{i}",
            trigger_type="catalyst",
            description=desc,
            status="pending",
        )
        for i, desc in enumerate(catalyst_descriptions)
    ]
    invalidations = [
        TriggerSnapshot(
            trigger_id=f"inv_{i}",
            trigger_type="invalidation",
            description=desc,
            status="pending",
        )
        for i, desc in enumerate(invalidation_descriptions)
    ]

    return MonitoringSnapshot(
        position_id=position_id,
        snapshot_time_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        catalyst_triggers=catalysts,
        invalidation_triggers=invalidations,
        any_invalidation_fired=False,
        alert_level="green",
        summary=f"Initial monitoring snapshot for {position_id}: {len(catalysts)} catalysts, {len(invalidations)} invalidations",
    )


def evaluate_invalidation_triggers(
    position_id: str,
    prior_snapshot: MonitoringSnapshot,
    new_data: Dict[str, Any],
) -> MonitoringSnapshot:
    """Evaluate invalidation triggers against new data.

    Never uses lookahead. Only compares predeclared invalidation conditions
    against the current data point.

    Args:
        position_id: The position being monitored.
        prior_snapshot: Previous monitoring snapshot (for status continuity).
        new_data: Key-value data to evaluate triggers against.
            Expected keys are trigger descriptions that match the data.

    Returns:
        A new MonitoringSnapshot with updated trigger statuses.
    """
    updated_catalysts: List[TriggerSnapshot] = []
    updated_invalidations: List[TriggerSnapshot] = []

    for trigger in prior_snapshot.catalyst_triggers:
        if trigger.status == "pending" and trigger.description in new_data:
            updated_catalysts.append(TriggerSnapshot(
                trigger_id=trigger.trigger_id,
                trigger_type="catalyst",
                description=trigger.description,
                status="triggered",
                evidence_ref=str(new_data.get(trigger.description, "")),
                triggered_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ))
        else:
            updated_catalysts.append(trigger)

    for trigger in prior_snapshot.invalidation_triggers:
        if trigger.status == "pending" and trigger.description in new_data:
            updated_invalidations.append(TriggerSnapshot(
                trigger_id=trigger.trigger_id,
                trigger_type="invalidation",
                description=trigger.description,
                status="invalidated",
                evidence_ref=str(new_data.get(trigger.description, "")),
                triggered_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ))
        else:
            updated_invalidations.append(trigger)

    any_invalidation = any(t.status == "invalidated" for t in updated_invalidations)
    alert_level = "red" if any_invalidation else "yellow" if any(t.status == "triggered" for t in updated_catalysts) else "green"

    return MonitoringSnapshot(
        position_id=position_id,
        snapshot_time_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        catalyst_triggers=updated_catalysts,
        invalidation_triggers=updated_invalidations,
        any_invalidation_fired=any_invalidation,
        alert_level=alert_level,
        summary=f"Alert level {alert_level}: {sum(1 for t in updated_invalidations if t.status == 'invalidated')} invalidations, "
                f"{sum(1 for t in updated_catalysts if t.status == 'triggered')} catalysts triggered",
    )


def serialize_monitoring_snapshot(snapshot: MonitoringSnapshot) -> str:
    """Canonical JSON serialization of a monitoring snapshot."""
    return json.dumps(asdict(snapshot), default=str, sort_keys=True, indent=2)