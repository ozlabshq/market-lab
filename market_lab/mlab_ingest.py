from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .source_thesis import SourceClaim, SourceThesis, ThesisRun, extract_source_thesis_from_capture_dir, render_thesis_report


RUN_STAGES = (
    "created",
    "captured",
    "claims_extracted",
    "research_planned",
    "research_active",
    "adjudicated",
    "reviewed",
    "finalized",
    "blocked",
)
RUN_STAGE_INDEX = {name: idx for idx, name in enumerate(RUN_STAGES)}

DEFAULT_DISPOSITIONS = {"VERIFIED", "REFUTED", "MIXED", "UNRESOLVED"}
EVIDENCE_RESULTS = {"supports", "refutes", "context"}
DEFAULT_VERDICT = "IN_PROGRESS"


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    text: str
    citation: str
    source_url: str
    source_artifact: str
    author: str
    captured_at: str
    disposition: str | None = None
    disposition_rationale: str | None = None
    unresolved_blocker: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_text(value: str) -> str:
    return str(value).strip()


def _run_root(candidate: Path | None) -> Path:
    if candidate is not None:
        return candidate.expanduser().resolve()
    env_root = os.environ.get("MLAB_INGEST_RUN_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return (Path.home() / "OzLabs" / "media_notes" / "mlab_ingest").expanduser().resolve()


def _status_path(run_dir: Path) -> Path:
    return run_dir / "status.json"


def _audit_path(run_dir: Path) -> Path:
    return run_dir / "audit_log.jsonl"


def _claims_path(run_dir: Path) -> Path:
    return run_dir / "claims.json"


def _evidence_path(run_dir: Path) -> Path:
    return run_dir / "evidence.jsonl"


def _research_plan_path(run_dir: Path) -> Path:
    return run_dir / "research_plan.md"


def _independent_review_path(run_dir: Path) -> Path:
    return run_dir / "independent_review.md"


def _next_actions_path(run_dir: Path) -> Path:
    return run_dir / "next_actions.json"


def _final_brief_path(run_dir: Path) -> Path:
    return run_dir / "final_brief.md"


def _source_root(run_dir: Path) -> Path:
    return run_dir / "source"


def _next_action_for_stage(stage: str) -> str:
    return {
        "created": "Capture source artifacts and initialize the run state",
        "captured": "Run SourceThesis extraction to extract claim set",
        "claims_extracted": "Create/update research_plan.md and owner next actions",
        "research_planned": "Gather evidence and append evidence.jsonl entries",
        "research_active": "Assign per-claim dispositions and blockers",
        "adjudicated": "Submit independent_review.md with APPROVE decision",
        "reviewed": "Populate final brief and finalize run",
        "finalized": "Run complete",
        "blocked": "Resolve blockers and resume after stage update",
    }[stage]


def _claim_id(claim: SourceClaim) -> str:
    source = "|".join(
        [
            _safe_text(claim.text),
            _safe_text(claim.citation),
            _safe_text(claim.source_url),
            _safe_text(claim.source_artifact),
            _safe_text(claim.author),
            _safe_text(claim.captured_at),
        ]
    )
    return "claim-" + hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def _portable_source_artifact(run_dir: Path, source_artifact: str) -> str:
    source_artifact = _safe_text(source_artifact)
    if not source_artifact:
        return source_artifact
    path = Path(source_artifact)
    if not path.is_absolute():
        return source_artifact
    try:
        return str(path.relative_to(run_dir))
    except ValueError:
        return source_artifact


def _persist_analysis_artifacts(run_dir: Path, thesis_run: ThesisRun) -> None:
    analysis_json = run_dir / "analysis.json"
    analysis_md = run_dir / "analysis.md"
    _write_json(analysis_json, asdict(thesis_run))
    analysis_md.write_text(render_thesis_report(thesis_run), encoding="utf-8")
    _append_audit(
        run_dir,
        event="analysis_artifacts_written",
        details={"analysis_json": str(analysis_json), "analysis_md": str(analysis_md)},
    )


def _read_json(path: Path, *, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_audit(run_dir: Path, event: str, actor: str = "system", details: dict[str, Any] | None = None) -> None:
    payload = {
        "timestamp": _now_iso(),
        "event": event,
        "actor": actor,
        "details": details or {},
    }
    with _audit_path(run_dir).open("a", encoding="utf-8") as f:
        json.dump(payload, f)
        f.write("\n")


def _load_status(run_dir: Path) -> dict[str, Any]:
    data = _read_json(_status_path(run_dir), default={})
    if not data:
        raise FileNotFoundError(f"status.json missing for {run_dir}")
    return data


def _save_status(run_dir: Path, status: dict[str, Any], *, actor: str = "system", event: str = "status_updated") -> None:
    status = dict(status)
    status["updated_at"] = _now_iso()
    _write_json(_status_path(run_dir), status)
    _append_audit(run_dir, event=event, actor=actor, details={"status": status})


def _set_stage(run_dir: Path, *, stage: str, owner: str | None = None, actor: str = "system", reason: str | None = None) -> dict[str, Any]:
    if stage not in RUN_STAGES:
        raise ValueError(f"invalid stage: {stage}")

    status = _load_status(run_dir)
    current = status.get("stage", "created")
    if current == stage:
        return status
    if current in {"finalized", "blocked"} and stage != current:
        raise ValueError(f"cannot transition from terminal stage {current} to {stage}")

    if RUN_STAGE_INDEX[stage] < RUN_STAGE_INDEX[current] and stage != "blocked":
        # Allow only explicit blocked transitions backwards from active stages.
        raise ValueError(f"invalid stage regression from {current} to {stage}")

    status["stage"] = stage
    status["next_action"] = _next_action_for_stage(stage)
    status["next_owner"] = owner or status.get("owner", owner) or status.get("next_owner")
    status["verdict"] = "BLOCKED" if stage == "blocked" else status.get("verdict", DEFAULT_VERDICT)
    status["updated_at"] = _now_iso()
    if reason:
        blockers = list(status.get("blockers", []))
        blockers.append(reason)
        status["blockers"] = blockers
    elif stage != "blocked":
        status["blockers"] = status.get("blockers", [])

    _write_json(_status_path(run_dir), status)
    _append_audit(
        run_dir,
        event="stage_transition",
        actor=actor,
        details={"from": current, "to": stage, "reason": reason},
    )
    return status


def _is_stage_finalized(status: dict[str, Any]) -> bool:
    return status.get("stage") == "finalized"


def _ensure_required_files(run_dir: Path) -> None:
    required = {
        _research_plan_path(run_dir): "# Research plan\n\nCapture-only run pending. Fill this file with evidence collection steps.\n",
        _independent_review_path(run_dir): "# Independent review\n\nDecision: PENDING\n\n",
    }

    created = []
    for path, content in required.items():
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(str(path))

    if created:
        _append_audit(
            run_dir,
            event="required_files_initialized",
            details={"created_files": created},
        )


def initialize_run(capture_dir: Path, *, run_root: Path | None = None, owner: str = "system", run_id: str | None = None) -> Path:
    capture_dir = Path(capture_dir).resolve()
    if not capture_dir.exists():
        raise FileNotFoundError(f"capture_dir does not exist: {capture_dir}")

    root = _run_root(run_root)
    root.mkdir(parents=True, exist_ok=True)
    run_id = run_id or capture_dir.name
    run_dir = (root / run_id).resolve()
    source_root = _source_root(run_dir)

    # Existing run: resume in-place and never rewrite artifacts.
    if run_dir.exists() and _status_path(run_dir).exists():
        status = _load_status(run_dir)
        if status.get("stage") == "blocked":
            return run_dir
        if status.get("stage") == "finalized":
            return run_dir
        if status.get("stage") == "created":
            _set_stage(run_dir, stage="captured", owner=owner)
        _ensure_required_files(run_dir)
        return run_dir

    # New run.
    source_root.mkdir(parents=True, exist_ok=True)
    if source_root.exists():
        for item in source_root.iterdir():
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)

    shutil.copytree(capture_dir, source_root, dirs_exist_ok=True)

    status = {
        "run_id": run_id,
        "capture_dir": str(capture_dir),
        "run_root": str(run_dir),
        "stage": "created",
        "owner": owner,
        "next_owner": owner,
        "verdict": DEFAULT_VERDICT,
        "next_action": _next_action_for_stage("created"),
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "blockers": [],
        "media_blockers": [],
    }
    _write_json(_status_path(run_dir), status)
    _append_audit(run_dir, event="run_initialized", actor=owner, details={"capture_dir": str(capture_dir), "run_id": run_id})

    _ensure_required_files(run_dir)
    _set_stage(run_dir, stage="captured", owner=owner, actor=owner, reason=None)
    return run_dir


def _build_claim_rows(run_dir: Path, thesis_run: ThesisRun) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    for claim in thesis_run.thesis.claims:
        rows.append(
            asdict(
                ClaimRecord(
                    claim_id=_claim_id(claim),
                    text=_safe_text(claim.text),
                    citation=_safe_text(claim.citation),
                    source_url=_safe_text(claim.source_url),
                    source_artifact=_portable_source_artifact(run_dir, claim.source_artifact),
                    author=_safe_text(claim.author),
                    captured_at=_safe_text(claim.captured_at),
                )
            )
        )
    return rows


def _media_blockers_from_thesis(thesis: SourceThesis) -> list[dict[str, Any]]:
    media_blockers: list[dict[str, Any]] = []
    for media in thesis.media_assets:
        interpretation = _safe_text(media.interpretation_status)
        if interpretation and interpretation.lower() != "interpreted":
            media_blockers.append(
                {
                    "media_id": media.media_id or media.local_path or "unknown",
                    "status": interpretation,
                    "blocker": None,
                }
            )
    return media_blockers


def _run_source_thesis_capture(
    capture_dir: Path,
    *,
    network: bool = False,
    days: int = 260,
    owner: str = "system",
    run_root: Path | None = None,
) -> tuple[Path, ThesisRun]:
    run_dir = initialize_run(capture_dir, run_root=run_root, owner=owner)
    status = _load_status(run_dir)

    if status.get("stage") in {"finalized", "blocked"}:
        raise RuntimeError("cannot run extraction on finalized/blocked run")

    source_root = _source_root(run_dir)
    if not source_root.exists():
        shutil.copytree(capture_dir, source_root, dirs_exist_ok=True)
    thesis_run = extract_source_thesis_from_capture_dir(str(source_root), prefer_network=network, days=days)
    claims = _build_claim_rows(run_dir, thesis_run)
    claims_payload = {
        "run_id": status["run_id"],
        "created_at": _now_iso(),
        "claims": claims,
    }
    _write_json(_claims_path(run_dir), claims_payload)
    _persist_analysis_artifacts(run_dir, thesis_run)

    status = _load_status(run_dir)
    status["source_thesis"] = {
        "claim_count": len(claims),
        "media_assets": len(thesis_run.thesis.media_assets),
        "candidate_tickers": thesis_run.thesis.candidate_tickers,
        "market_window_start": thesis_run.market_window_start,
        "market_window_end": thesis_run.market_window_end,
        "warning_count": len(thesis_run.warnings),
    }
    status["media_blockers"] = _media_blockers_from_thesis(thesis_run.thesis)
    _write_json(_status_path(run_dir), status)
    _append_audit(
        run_dir,
        event="claims_extracted",
        actor=owner,
        details={"claim_count": len(claims), "media_assets": len(thesis_run.thesis.media_assets)},
    )

    if status["stage"] != "claims_extracted":
        _set_stage(run_dir, stage="claims_extracted", owner=owner, actor=owner)
    return run_dir, thesis_run


def run_source_thesis_capture(capture_dir: Path, *, network: bool = False, days: int = 260, run_root: Path | None = None, owner: str = "system") -> Path:
    capture_dir = Path(capture_dir).resolve()
    root = _run_root(run_root)

    run_dir = initialize_run(capture_dir, run_root=root, owner=owner)
    status = _load_status(run_dir)
    if status.get("stage") in {"finalized", "blocked"}:
        return run_dir

    claims_path = _claims_path(run_dir)
    if status.get("stage") in {"captured", "created"} or not claims_path.exists():
        run_dir, _ = _run_source_thesis_capture(capture_dir, network=network, days=days, owner=owner, run_root=root)
    return run_dir


def read_status(run_dir: Path) -> dict[str, Any]:
    return _load_status(Path(run_dir))


def read_audit_log(run_dir: Path) -> list[dict[str, Any]]:
    path = _audit_path(Path(run_dir))
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def read_claims(run_dir: Path) -> dict[str, Any]:
    return _read_json(_claims_path(Path(run_dir)), default={"claims": []})


def write_research_plan(run_dir: Path, content: str, owner: str = "system") -> None:
    run_dir = Path(run_dir)
    status = _load_status(run_dir)
    if status.get("stage") == "finalized":
        raise RuntimeError("finalized runs are immutable")
    _research_plan_path(run_dir).write_text(content.rstrip("\n") + "\n", encoding="utf-8")
    if RUN_STAGE_INDEX[status.get("stage", "created")] < RUN_STAGE_INDEX["research_planned"]:
        _set_stage(run_dir, stage="research_planned", owner=owner, actor=owner)
    _append_audit(run_dir, event="research_plan_updated", actor=owner, details={"run_id": status.get("run_id")})


def set_next_actions(run_dir: Path, *, owner: str, actions: list[dict[str, Any]], actor: str = "system") -> None:
    run_dir = Path(run_dir)
    status = _load_status(run_dir)
    if status.get("stage") == "finalized":
        raise RuntimeError("finalized runs are immutable")
    if not owner or not actions:
        raise ValueError("owner and actions are required for next_actions")

    normalized: list[dict[str, Any]] = []
    for action in actions:
        if "action" not in action or "owner" not in action:
            raise ValueError("each action must include owner and action")
        normalized.append(
            {
                "owner": _safe_text(str(action["owner"])),
                "action": _safe_text(str(action["action"])),
                "status": _safe_text(str(action.get("status", "pending"))),
                "notes": _safe_text(str(action.get("notes", ""))),
            }
        )

    payload = {
        "run_id": status.get("run_id"),
        "owner": _safe_text(owner),
        "updated_at": _now_iso(),
        "actions": normalized,
    }
    _write_json(_next_actions_path(run_dir), payload)

    if RUN_STAGE_INDEX[status.get("stage", "created")] < RUN_STAGE_INDEX["research_active"]:
        _set_stage(run_dir, stage="research_active", owner=owner, actor=actor)
    _append_audit(run_dir, event="next_actions_set", actor=actor, details={"count": len(normalized)})


def set_claim_disposition(
    run_dir: Path,
    *,
    claim_id: str,
    disposition: str,
    rationale: str = "",
    blocker: str = "",
    actor: str = "system",
) -> None:
    run_dir = Path(run_dir)
    if disposition not in DEFAULT_DISPOSITIONS:
        raise ValueError(f"invalid disposition: {disposition}")

    claims_payload = read_claims(run_dir)
    claims: list[dict[str, Any]] = [
        dict(item)
        for item in claims_payload.get("claims", [])
    ]
    if not claims:
        raise RuntimeError("no claims extracted")

    target: dict[str, Any] | None = None
    for item in claims:
        if item.get("claim_id") == claim_id:
            target = item
            break
    if target is None:
        raise KeyError(f"unknown claim_id: {claim_id}")

    if disposition == "UNRESOLVED" and not blocker:
        raise ValueError("UNRESOLVED requires an explicit blocker")
    if disposition != "UNRESOLVED" and blocker:
        raise ValueError("non-UNRESOLVED dispositions cannot include a blocker")

    target["disposition"] = disposition
    target["disposition_rationale"] = _safe_text(rationale)
    target["unresolved_blocker"] = _safe_text(blocker) if disposition == "UNRESOLVED" else None

    _write_json(_claims_path(run_dir), {"run_id": claims_payload.get("run_id"), "created_at": claims_payload.get("created_at", _now_iso()), "claims": claims})
    _append_audit(
        run_dir,
        event="claim_disposition_set",
        actor=actor,
        details={"claim_id": claim_id, "disposition": disposition},
    )

    updated = read_claims(run_dir)["claims"]
    all_disposed = all(item.get("disposition") for item in updated)
    status = _load_status(run_dir)
    if all_disposed and RUN_STAGE_INDEX.get(status.get("stage", "created"), 0) < RUN_STAGE_INDEX["adjudicated"]:
        _set_stage(run_dir, stage="adjudicated", owner=actor, actor=actor)


def add_evidence(
    run_dir: Path,
    *,
    claim_id: str,
    result: str,
    source: str,
    note: str = "",
    actor: str = "system",
) -> None:
    result = _safe_text(result).lower()
    if result not in EVIDENCE_RESULTS:
        raise ValueError(f"invalid evidence result: {result}")

    claims = read_claims(run_dir).get("claims", [])
    if not any(item.get("claim_id") == claim_id for item in claims):
        raise KeyError(f"unknown claim_id: {claim_id}")

    entry = {
        "timestamp": _now_iso(),
        "claim_id": claim_id,
        "result": result,
        "source": _safe_text(source),
        "note": _safe_text(note),
        "actor": actor,
    }
    with _evidence_path(Path(run_dir)).open("a", encoding="utf-8") as f:
        json.dump(entry, f)
        f.write("\n")
    _append_audit(run_dir, event="evidence_added", actor=actor, details={"claim_id": claim_id, "result": result})


def run_web_evidence_research(
    run_dir: Path,
    *,
    mode: str = "live",
    profile: str = "keyless_standard",
    owner: str = "web-evidence",
    max_claims: int | None = None,
) -> dict[str, Any]:
    """Advance an extracted-claims run into audited web-evidence collection.

    The acquisition layer appends candidate evidence/context only. It does not set
    claim dispositions and keeps the run verdict IN_PROGRESS unless a reviewer
    later adjudicates the claim set.
    """

    run_dir = Path(run_dir)
    status = _load_status(run_dir)
    if status.get("stage") == "finalized":
        raise RuntimeError("finalized runs are immutable")
    if RUN_STAGE_INDEX.get(status.get("stage", "created"), 0) < RUN_STAGE_INDEX["claims_extracted"]:
        raise RuntimeError("claims must be extracted before web evidence research")

    from .web_evidence_runner import collect_for_claims

    claims = read_claims(run_dir).get("claims", [])
    result = collect_for_claims(
        run_dir,
        claims,
        profile=profile,
        run_id=str(status.get("run_id") or run_dir.name),
        mode=mode,
        max_claims=max_claims,
    )

    status = _load_status(run_dir)
    status["verdict"] = DEFAULT_VERDICT
    status["web_evidence"] = {
        "profile": profile,
        "mode": mode,
        "status": result.get("status"),
        "claims": result.get("claims", 0),
        "searches": result.get("searches", 0),
        "fetches": result.get("fetches", 0),
        "evidence_added": result.get("evidence_added", 0),
        "updated_at": _now_iso(),
    }
    _write_json(_status_path(run_dir), status)
    if RUN_STAGE_INDEX.get(status.get("stage", "created"), 0) < RUN_STAGE_INDEX["research_active"]:
        _set_stage(run_dir, stage="research_active", owner=owner, actor=owner)
    _append_audit(run_dir, event="web_evidence_research", actor=owner, details=result)
    return result


def _count_evidence(run_dir: Path) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    evidence_path = _evidence_path(Path(run_dir))
    if not evidence_path.exists():
        return totals

    for raw in evidence_path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        entry = json.loads(raw)
        cid = entry.get("claim_id", "")
        if not cid:
            continue
        bucket = totals.setdefault(cid, {"supports": 0, "refutes": 0, "context": 0, "total": 0})
        bucket[entry.get("result", "context")] = bucket.get(entry.get("result", "context"), 0) + 1
        bucket["total"] += 1
    return totals


def set_media_interpretation(run_dir: Path, *, media_id: str, status_text: str, actor: str = "system", blocker: str = "") -> None:
    run_dir = Path(run_dir)
    status = _load_status(run_dir)
    blockers = list(status.get("media_blockers", []))
    normalized_id = _safe_text(media_id)
    if not normalized_id:
        raise ValueError("media_id required")

    updated = False
    for item in blockers:
        if item.get("media_id") == normalized_id:
            item["status"] = _safe_text(status_text) or "interpreted"
            item["blocker"] = _safe_text(blocker) if _safe_text(blocker) else item.get("blocker")
            updated = True
            break
    if not updated:
        blockers.append({"media_id": normalized_id, "status": _safe_text(status_text) or "interpreted", "blocker": _safe_text(blocker) or None})

    status["media_blockers"] = blockers
    _save_status(run_dir, status, actor=actor, event="media_interpretation_updated")


def write_independent_review(run_dir: Path, *, reviewer: str, decision: str, notes: str = "", actor: str = "system") -> None:
    run_dir = Path(run_dir)
    status = _load_status(run_dir)
    normalized = _safe_text(decision).upper()
    if normalized not in {"APPROVE", "REJECT", "BLOCK", "PENDING"}:
        raise ValueError("decision must be APPROVE, REJECT, BLOCK, or PENDING")

    content = [
        "# Independent review",
        f"Reviewer: {_safe_text(reviewer)}",
        f"Decision: {normalized}",
        f"Date: {_now_iso()}",
        "",
        "Notes:",
        _safe_text(notes) or "TBD",
        "",
    ]
    _independent_review_path(run_dir).write_text("\n".join(content), encoding="utf-8")
    _append_audit(run_dir, event="independent_review", actor=actor, details={"decision": normalized})

    if normalized == "APPROVE" and RUN_STAGE_INDEX[status.get("stage", "created")] < RUN_STAGE_INDEX["reviewed"]:
        _set_stage(run_dir, stage="reviewed", owner=actor, actor=actor)
    elif normalized != "APPROVE":
        if status.get("stage") not in {"blocked", "finalized"}:
            _set_stage(run_dir, stage="blocked", owner=actor, actor=actor, reason=f"independent review decision={normalized}")


def _read_review_decision(run_dir: Path) -> str:
    path = _independent_review_path(run_dir)
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("decision:"):
            return _safe_text(line.split(":", 1)[1]).upper()
    return ""


def _read_next_actions(run_dir: Path) -> dict[str, Any]:
    return _read_json(_next_actions_path(run_dir), default={"owner": "", "actions": []})


def _raise_runtime(message: str) -> None:
    raise RuntimeError(message)


def _validate_finalization(run_dir: Path) -> list[str]:
    status = _load_status(run_dir)
    if status.get("verdict") == "FINALIZED":
        return []

    reasons: list[str] = []
    claims = read_claims(run_dir).get("claims", [])
    if not claims:
        reasons.append("no claims available")
        return reasons

    evidence_by_claim = _count_evidence(run_dir)

    for claim in claims:
        cid = claim.get("claim_id")
        disposition = _safe_text(str(claim.get("disposition") or "")).upper()
        if not disposition:
            reasons.append(f"claim {cid} missing disposition")
            continue

        bucket = evidence_by_claim.get(cid, {"supports": 0, "refutes": 0, "context": 0, "total": 0})
        supports = bucket.get("supports", 0)
        refutes = bucket.get("refutes", 0)

        if disposition == "UNRESOLVED":
            if not _safe_text(str(claim.get("unresolved_blocker") or "")):
                reasons.append(f"claim {cid} unresolved without blocker")
        elif disposition == "VERIFIED":
            if supports == 0:
                reasons.append(f"claim {cid} verified without support evidence")
            if refutes > 0:
                reasons.append(f"claim {cid} has contradictory evidence (verified with refutes)")
        elif disposition == "REFUTED":
            if refutes == 0:
                reasons.append(f"claim {cid} refuted without refute evidence")
            if supports > 0:
                reasons.append(f"claim {cid} has contradictory evidence (refuted with supports)")
        elif disposition == "MIXED":
            if supports == 0 or refutes == 0:
                reasons.append(f"claim {cid} mixed needs both supporting and refuting evidence")

    unresolved_media = [
        item
        for item in status.get("media_blockers", [])
        if _safe_text(str(item.get("status", ""))).lower() != "interpreted"
    ]
    unblocked_media = [
        item
        for item in unresolved_media
        if item.get("blocker")
    ]
    if unresolved_media and len(unresolved_media) != len(unblocked_media):
        reasons.append("media interpretation pending without explicit blocker")

    decision = _read_review_decision(run_dir)
    if decision != "APPROVE":
        reasons.append("independent review decision is not APPROVE")

    next_actions = _read_next_actions(run_dir)
    owner = _safe_text(str(next_actions.get("owner", "")))
    actions = next_actions.get("actions")
    if not owner:
        reasons.append("next_actions missing owner")
    if not isinstance(actions, list) or not actions:
        reasons.append("next_actions missing actionable items")

    return reasons


def finalize_run(run_dir: Path, *, actor: str = "system") -> Path:
    run_dir = Path(run_dir)
    status = _load_status(run_dir)
    if status.get("stage") == "finalized":
        return run_dir

    if status.get("stage") not in {"reviewed", "adjudicated", "finalized"}:
        _raise_runtime("run must be reviewed before finalization")

    reasons = _validate_finalization(run_dir)
    if reasons:
        _append_audit(run_dir, event="finalize_blocked", actor=actor, details={"reasons": reasons})
        _raise_runtime("; ".join(reasons))

    claims = read_claims(run_dir).get("claims", [])
    evidence_by_claim = _count_evidence(run_dir)
    lines = [
        f"# MLAB Ingestion Final Brief ({status.get('run_id')})",
        f"Status date: {_now_iso()}",
        f"Claims extracted: {len(claims)}",
        "",
        "## Claim dispositions",
    ]
    for claim in claims:
        cid = claim.get("claim_id")
        disposition = claim.get("disposition")
        blocker = claim.get("unresolved_blocker") or ""
        counts = evidence_by_claim.get(cid, {"supports": 0, "refutes": 0, "context": 0, "total": 0})
        lines.append(
            f"- {cid}: {disposition} (supports: {counts['supports']}, refutes: {counts['refutes']}, context: {counts['context']})"
            + (f" | blocker: {blocker}" if blocker else "")
        )

    lines.extend(["", "## Next actions", "", f"Owner: {status.get('next_owner') or status.get('owner')}", ""])
    next_actions = _read_next_actions(run_dir).get("actions", [])
    if next_actions:
        for action in next_actions:
            lines.append(f"- {action.get('owner')}: {action.get('action')} ({action.get('status', 'pending')})")
    _final_brief_path(run_dir).write_text("\n".join(lines), encoding="utf-8")

    status["verdict"] = "FINALIZED"
    status["finalized_at"] = _now_iso()
    _write_json(_status_path(run_dir), status)
    _append_audit(run_dir, event="run_finalized", actor=actor, details={"claim_count": len(claims)})
    _set_stage(run_dir, stage="finalized", owner=actor, actor=actor)

    return run_dir


def read_run(run_dir: Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    return {
        "status": read_status(run_dir),
        "claims": read_claims(run_dir),
        "next_actions": _read_next_actions(run_dir),
        "audit_events": read_audit_log(run_dir),
    }


def run_ingest_from_capture(
    capture_dir: Path,
    *,
    run_root: Path | None = None,
    owner: str = "system",
    network: bool = False,
    days: int = 260,
) -> Path:
    capture_dir = Path(capture_dir)
    root = _run_root(run_root)
    run_dir = initialize_run(capture_dir, run_root=root, owner=owner)
    status = _load_status(run_dir)

    if status.get("stage") in {"finalized", "blocked"}:
        return run_dir

    claims_path = _claims_path(run_dir)
    if status.get("stage") in {"created", "captured"} or not claims_path.exists():
        run_dir = run_source_thesis_capture(
            capture_dir,
            run_root=root,
            network=network,
            days=days,
            owner=owner,
        )

    return run_dir


__all__ = [
    "initialize_run",
    "run_ingest_from_capture",
    "read_status",
    "read_audit_log",
    "read_claims",
    "write_research_plan",
    "set_next_actions",
    "set_claim_disposition",
    "add_evidence",
    "run_web_evidence_research",
    "set_media_interpretation",
    "write_independent_review",
    "finalize_run",
    "read_run",
]
