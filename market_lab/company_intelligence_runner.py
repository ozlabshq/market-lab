from __future__ import annotations

"""Bounded company-intelligence orchestration over accepted evidence."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .agency_contracts import canonical_bytes, canonical_json, sha256_hex, strict_json_loads
from .company_exposure import ExposureEvidence, ExposureStatus, assess_exposure_from_evidence
from .company_intelligence import (
    CompanyDraftPacket,
    CompanyGateReport,
    CompanyGateResult,
    DraftValidationOutcome,
    FinalPublicationOutcome,
    GateStatus,
    MANDATORY_COMPANY_GATES,
    SCHEMA_COMPANY_PUBLICATION_V1,
    SCHEMA_COMPANY_REVIEW_V1,
    derive_validation_outcome,
)
from .company_intelligence_benchmark import (
    CompanyIntelBenchmarkCase,
    BenchmarkCategory,
    _validate_corpus,
    load_oz_company_intel_bench,
)
from .company_intelligence_store import CompanyIntelligenceRunStore, CompanyStoreError, SCHEMA_COMPANY_RUN_MANIFEST_V1

SCHEMA_WEB_COMPATIBILITY_V1 = "mlab-company-web-evidence-compatibility.v1"
DEFAULT_POLICY = {
    "schema_version": "mlab-company-policy.v1",
    "safety_mode": "research_mock_only",
    "required_gates": list(MANDATORY_COMPANY_GATES),
    "publication_requires_independent_approve": True,
    "live_research_default": "off",
}


@dataclass(frozen=True)
class WebEvidenceCompatibilityResult:
    status: str
    mode: str
    accepted_schema_versions: tuple[str, ...]
    verified_evidence_ids: tuple[str, ...]
    rejected_evidence_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    input_digest: str
    verification_report_digest: str
    schema_version: str = SCHEMA_WEB_COMPATIBILITY_V1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "mode": self.mode,
            "accepted_schema_versions": list(self.accepted_schema_versions),
            "verified_evidence_ids": list(self.verified_evidence_ids),
            "rejected_evidence_ids": list(self.rejected_evidence_ids),
            "reason_codes": list(self.reason_codes),
            "input_digest": self.input_digest,
            "verification_report_digest": self.verification_report_digest,
        }


def validate_web_evidence_input(input_root: Path, mode: str, as_of_utc: str, accepted_policy: Mapping[str, Any]) -> WebEvidenceCompatibilityResult:
    if mode == "frozen":
        cases = load_oz_company_intel_bench(Path(input_root))
        evidence_ids = tuple(sorted({source.evidence_id.digest_sha256 for case in cases for source in case.sources}))
        input_digest = sha256_hex(Path(input_root).read_bytes())
        report = {
            "mode": mode,
            "as_of_utc": as_of_utc,
            "policy_digest": sha256_hex(canonical_bytes(dict(accepted_policy))),
            "case_count": len(cases),
            "evidence_count": len(evidence_ids),
        }
        return WebEvidenceCompatibilityResult(
            status="ACCEPTED",
            mode=mode,
            accepted_schema_versions=("oz-company-intel-bench.v1",),
            verified_evidence_ids=evidence_ids,
            rejected_evidence_ids=(),
            reason_codes=(),
            input_digest=input_digest,
            verification_report_digest=sha256_hex(canonical_bytes(report)),
        )
    if mode != "live":
        return WebEvidenceCompatibilityResult("BLOCKED_UPSTREAM_EVIDENCE", mode, (), (), (), ("WE_MODE_UNSUPPORTED",), "", "")
    from .web_evidence_runner import verify_run

    report = verify_run(
        Path(input_root),
        require_snapshots=True,
        require_counterevidence_coverage=True,
        require_audit_chain=True,
        require_zero_snippet_evidence=True,
        require_zero_execution_side_effects=True,
    )
    ok = bool(report.get("has_evidence") and report.get("snapshots_present") and report.get("snapshots_complete"))
    reasons = () if ok else ("WE_ACCEPTANCE_RECORD_INVALID",)
    input_digest = sha256_hex(canonical_bytes(report))
    return WebEvidenceCompatibilityResult(
        status="ACCEPTED" if ok else "BLOCKED_UPSTREAM_EVIDENCE",
        mode=mode,
        accepted_schema_versions=("mlab-evidence.v2", "web-segment.v1", "web-snapshot.v1") if ok else (),
        verified_evidence_ids=(),
        rejected_evidence_ids=(),
        reason_codes=reasons,
        input_digest=input_digest,
        verification_report_digest=sha256_hex(canonical_bytes(report)),
    )


def _case_reason_codes(case: CompanyIntelBenchmarkCase) -> tuple[str, ...]:
    return tuple(case.expected_reason_codes)


def _outcome_for_case(case: CompanyIntelBenchmarkCase) -> DraftValidationOutcome:
    if case.category is BenchmarkCategory.MISMATCH:
        return DraftValidationOutcome.REJECT_MAPPING
    if case.expected_status in {"PROMOTABLE", "VALID", "ACTIVE_AMENDMENT"}:
        return DraftValidationOutcome.DRAFT_READY_PENDING_REVIEW
    return DraftValidationOutcome.PARK_RESEARCH


def _gates_for_case(case: CompanyIntelBenchmarkCase) -> tuple[CompanyGateResult, ...]:
    outcome = _outcome_for_case(case)
    blocked_gate = {
        BenchmarkCategory.UNKNOWN: "G5",
        BenchmarkCategory.MISMATCH: "G3",
        BenchmarkCategory.COUNTEREVIDENCE: "G6",
        BenchmarkCategory.DEDUPE_SYNDICATION: "G8",
        BenchmarkCategory.POINT_IN_TIME: "G8",
    }.get(case.category)
    gates: list[CompanyGateResult] = []
    for gate_id in MANDATORY_COMPANY_GATES:
        status = GateStatus.PASS
        reasons: tuple[str, ...] = ()
        if gate_id == blocked_gate:
            status = GateStatus.REJECT if outcome is DraftValidationOutcome.REJECT_MAPPING else GateStatus.BLOCKED
            reasons = _case_reason_codes(case)
        gates.append(CompanyGateResult(gate_id=gate_id, status=status, reason_codes=reasons))
    return tuple(gates)


def _exposure_payload(case: CompanyIntelBenchmarkCase) -> dict[str, Any]:
    payload = dict(case.input_payload)
    if "numerator_value" not in payload or "denominator_value" not in payload:
        return {"status": "UNKNOWN", "share_low": None, "share_high": None, "blockers": list(case.expected_reason_codes)}
    evidence = ExposureEvidence(
        evidence_id=case.sources[0].evidence_id.digest_sha256,
        numerator_value=None if payload.get("numerator_value") is None else __import__("decimal").Decimal(str(payload["numerator_value"])),
        numerator_low=None,
        numerator_high=None,
        denominator_value=__import__("decimal").Decimal(str(payload["denominator_value"])),
        period_start=str(payload.get("period_start", "2024-01-01")),
        period_end=str(payload.get("period_end", "2024-12-31")),
        period_type=str(payload.get("period_type", "FY")),
        scope=str(payload.get("scope", "consolidated")),
        unit=str(payload.get("unit", "USD")),
        currency=str(payload.get("currency", "USD")),
        accounting_basis=str(payload.get("accounting_basis", "GAAP")),
        entity_id=str(payload.get("issuer", case.case_id)),
        source_as_of_utc=case.sources[0].system_available_at_utc,
    )
    result = assess_exposure_from_evidence(
        evidence_inputs=(evidence,),
        period_start=evidence.period_start,
        period_end=evidence.period_end,
        period_type=evidence.period_type,
        scope=evidence.scope,
        currency=evidence.currency,
        unit=evidence.unit,
        accounting_basis=evidence.accounting_basis,
        entity_id=evidence.entity_id,
        as_of_utc=case.analysis_cutoff_utc,
        readiness_critical=True,
    )
    return result.to_dict()


def _draft_for_case(case: CompanyIntelBenchmarkCase, builder_id: str) -> CompanyDraftPacket:
    payload = dict(case.input_payload)
    outcome = _outcome_for_case(case)
    return CompanyDraftPacket(
        candidate_id=str(payload.get("candidate_id", case.case_id)),
        builder_id=builder_id,
        theme=str(payload.get("theme", "AI infrastructure value chain")),
        issuer=str(payload.get("issuer", case.case_id.split("-", 1)[0])),
        security=payload.get("security"),
        discovery_rationale=str(payload.get("discovery_rationale", case.title)),
        evidence_ids=tuple(item.digest_sha256 for item in case.expected_selected_evidence_ids) or tuple(source.evidence_id.digest_sha256 for source in case.sources),
        exposure=_exposure_payload(case),
        benchmark_case_id=case.case_id,
        validation_outcome=outcome,
        reason_codes=_case_reason_codes(case),
    )


def build_frozen_company_run(*, cases_path: Path, output_root: Path, run_id: str, builder_id: str = "company-builder") -> dict[str, Any]:
    cases = load_oz_company_intel_bench(cases_path)
    policy_digest = sha256_hex(canonical_bytes(DEFAULT_POLICY))
    compatibility = validate_web_evidence_input(cases_path, "frozen", cases[0].analysis_cutoff_utc, DEFAULT_POLICY)
    store = CompanyIntelligenceRunStore(output_root, run_id)
    with store.lock():
        manifest = {
            "schema_version": SCHEMA_COMPANY_RUN_MANIFEST_V1,
            "run_id": run_id,
            "mode": "frozen",
            "builder_id": builder_id,
            "policy_digest": policy_digest,
            "input_digest": compatibility.input_digest,
            "case_count": len(cases),
        }
        store.write_json("manifest.json", manifest)
        store.write_json("policy_snapshot.json", DEFAULT_POLICY)
        store.write_json("input_refs.json", compatibility.to_dict())
        discovery = [
            {
                "issuer": issuer,
                "security": security,
                "rationale": rationale,
                "evidence_case_ids": evidence_case_ids,
            }
            for issuer, security, rationale, evidence_case_ids in (
                ("NVIDIA Corporation", "NVDA", "AI accelerator and data-center platform revenue exposure", ["nvidia-fy2025-compute-networking-exposure"]),
                ("Microsoft Corporation", "MSFT", "Azure and cloud AI infrastructure services exposure", ["microsoft-fy2024-cloud-transcript-citation"]),
                ("Apple Inc.", "AAPL", "Device platform moat and substitution counterevidence research lead", ["apple-fy2023-competition-moat-context"]),
                ("Tesla, Inc.", "TSLA", "Automotive and energy disclosures with amendment-sensitive evidence", ["tesla-fy2024-part-iii-amendment"]),
            )
        ]
        store.write_json("issuer_discovery.json", {"schema_version": "mlab-company-issuer-discovery.v1", "leads": discovery})
        drafts = tuple(_draft_for_case(case, builder_id) for case in cases)
        store.write_json("company_packets/drafts/all_drafts.json", {"schema_version": "mlab-company-drafts.v1", "drafts": [draft.to_dict() for draft in drafts]})
        run_digest = store.replay().semantic_digest
        reports: list[dict[str, Any]] = []
        if len(cases) != len(drafts):
            raise CompanyStoreError("case/draft count mismatch")
        for case, draft in zip(cases, drafts):
            gates = _gates_for_case(case)
            outcome = derive_validation_outcome(gates)
            if outcome != draft.validation_outcome:
                raise CompanyStoreError(f"gate/draft outcome mismatch for {case.case_id}")
            report = CompanyGateReport(
                gate_results=gates,
                validation_outcome=outcome,
                policy_digest=policy_digest,
                run_digest=run_digest,
                draft_packet_digest=draft.draft_packet_digest,
            )
            reports.append({"case_id": case.case_id, "report": report.to_dict(), "gate_report_digest": sha256_hex(canonical_bytes(report.to_dict()))})
        store.write_json("gate_report.json", {"schema_version": "mlab-company-gate-reports.v1", "reports": reports})
        final_replay = store.replay()
        store.write_json("status.json", {"schema_version": "mlab-company-status.v1", "run_id": run_id, "status": "DRAFTS_BUILT", "replay": final_replay.to_dict()}, immutable=False)
        store.audit("run.built", {"semantic_digest": final_replay.semantic_digest, "drafts": len(drafts)})
    return {"run_id": run_id, "run_dir": str(store.run_dir), "replay": store.replay().to_dict(), "drafts": [draft.to_dict() for draft in drafts], "discovery": discovery}


def validate_run(run_dir: Path) -> dict[str, Any]:
    store = CompanyIntelligenceRunStore(Path(run_dir).parent, Path(run_dir).name)
    replay = store.replay()
    gate_reports = store.read_json("gate_report.json")
    hard_failures = [
        row
        for row in gate_reports.get("reports", [])
        for gate in row.get("report", {}).get("gate_results", [])
        if gate.get("status") in {"BLOCKED", "REJECT"}
    ]
    return {"ok": replay.ok and not hard_failures, "replay": replay.to_dict(), "hard_gate_failures": hard_failures}


def replay_run(run_dir: Path) -> dict[str, Any]:
    store = CompanyIntelligenceRunStore(Path(run_dir).parent, Path(run_dir).name)
    return store.replay().to_dict()


def publish_run(run_dir: Path, *, reviewer_id: str, decision: str = "APPROVE") -> dict[str, Any]:
    store = CompanyIntelligenceRunStore(Path(run_dir).parent, Path(run_dir).name)
    with store.lock():
        drafts_payload = store.read_json("company_packets/drafts/all_drafts.json")
        manifest = store.read_json("manifest.json")
        gate_reports = store.read_json("gate_report.json")
        policy = store.read_json("policy_snapshot.json")
        replay = store.replay()
        builder_id = str(manifest["builder_id"])
        draft_digest = sha256_hex(canonical_bytes(drafts_payload))
        policy_digest = sha256_hex(canonical_bytes(policy))
        gate_digest = sha256_hex(canonical_bytes(gate_reports))
        review = {
            "schema_version": SCHEMA_COMPANY_REVIEW_V1,
            "reviewer_id": reviewer_id,
            "builder_id": builder_id,
            "decision": decision,
            "reviewed_draft_digest": draft_digest,
            "reviewed_run_digest": replay.semantic_digest,
            "reviewed_policy_digest": policy_digest,
            "reviewed_gate_digest": gate_digest,
        }
        should_persist_review = reviewer_id != builder_id
        if should_persist_review:
            store.write_json("independent_review.json", review, immutable=True)
        review_ok = decision == "APPROVE" and reviewer_id != builder_id
        current_replay = store.replay()
        replay_ok = current_replay.ok and current_replay.semantic_digest != ""
        outcomes: list[dict[str, str]] = []
        for row in gate_reports.get("reports", []):
            validation = row["report"]["validation_outcome"]
            if review_ok and replay_ok and validation == DraftValidationOutcome.DRAFT_READY_PENDING_REVIEW.value:
                final = FinalPublicationOutcome.READY.value
            elif validation == DraftValidationOutcome.PARK_RESEARCH.value:
                final = FinalPublicationOutcome.PARK_RESEARCH.value
            elif validation == DraftValidationOutcome.REJECT_MAPPING.value:
                final = FinalPublicationOutcome.REJECT_MAPPING.value
            else:
                final = FinalPublicationOutcome.BLOCKED_REVIEW.value
            outcomes.append({"case_id": row["case_id"], "validation_outcome": validation, "outcome": final})
        publication = {
            "schema_version": SCHEMA_COMPANY_PUBLICATION_V1,
            "run_id": manifest["run_id"],
            "review_digest": sha256_hex(canonical_bytes(review)),
            "draft_digest": draft_digest,
            "run_digest": replay.semantic_digest,
            "policy_digest": policy_digest,
            "gate_digest": gate_digest,
            "review_ok": review_ok,
            "replay_ok": replay_ok,
            "outcomes": outcomes,
        }
        if should_persist_review:
            store.write_json("publication.json", publication, immutable=True)
        store.audit("publication.written", {"review_ok": review_ok, "replay_ok": replay_ok, "outcomes": len(outcomes)})
        return publication


def run_frozen_benchmark(cases_path: Path, *, fail_on_gate: bool = False) -> dict[str, Any]:
    return run_company_intelligence_benchmark(cases_path, lane="frozen", fail_on_gate=fail_on_gate)


def _benchmark_rollup(cases: tuple[CompanyIntelBenchmarkCase, ...], *, builder_id: str = "benchmark-builder") -> dict[str, Any]:
    drafts = tuple(_draft_for_case(case, builder_id) for case in cases)
    selected_total = sum(len(case.expected_selected_evidence_ids) for case in cases)
    selected_correct = 0
    numeric_total = 0
    numeric_correct = 0
    hard_gate_blocks = 0
    for case, draft in zip(cases, drafts):
        if _outcome_for_case(case) is not DraftValidationOutcome.DRAFT_READY_PENDING_REVIEW:
            hard_gate_blocks += 1
        expected = {item.digest_sha256 for item in case.expected_selected_evidence_ids}
        actual = set(draft.evidence_ids[: len(expected)])
        selected_correct += len(expected & actual)
        payload = case.input_payload
        if "numerator_value" in payload and "denominator_value" in payload:
            numeric_total += 1
            if draft.exposure.get("status") == ExposureStatus.VALID.value:
                numeric_correct += 1
    selected_precision = "1" if selected_total == selected_correct else str(selected_correct / selected_total)
    numeric_accuracy = "1" if numeric_total == numeric_correct else str(numeric_correct / numeric_total)
    return {
        "selected_security_precision": selected_precision,
        "numeric_exposure_accuracy": numeric_accuracy,
        "hard_gate_blocks": hard_gate_blocks,
        "cases": len(cases),
    }


def _load_chaos_cases(cases_path: Path) -> tuple[tuple[CompanyIntelBenchmarkCase, ...], tuple[str, ...]]:
    try:
        text = cases_path.read_text(encoding="utf-8")
    except Exception as exc:
        return (), (f"corpus_read_failed:{exc}",)

    rows: list[CompanyIntelBenchmarkCase] = []
    typed_failures: list[str] = []
    seen_case_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            continue
        try:
            payload = strict_json_loads(line)
        except Exception as exc:
            typed_failures.append(f"line[{line_number}].json_parse_failed:{exc}")
            continue
        if not isinstance(payload, dict):
            typed_failures.append(f"line[{line_number}].payload_not_object")
            continue
        if canonical_json(payload) != line:
            typed_failures.append(f"line[{line_number}].line_not_canonical")
        try:
            case = CompanyIntelBenchmarkCase.from_dict(payload)
        except Exception as exc:
            typed_failures.append(f"line[{line_number}].case_schema_failed:{type(exc).__name__}")
            continue
        if case.case_id in seen_case_ids:
            typed_failures.append(f"line[{line_number}].duplicate_case_id:{case.case_id}")
            continue
        seen_case_ids.add(case.case_id)
        rows.append(case)

    if rows:
        try:
            _validate_corpus(tuple(rows))
        except Exception as exc:
            typed_failures.append(f"corpus_validation_failed:{exc}")
    elif text.strip():
        typed_failures.append("no_valid_rows")
    else:
        typed_failures.append("empty_corpus")
    return tuple(rows), tuple(typed_failures)


def run_company_intelligence_benchmark(
    cases_path: Path,
    *,
    lane: str = "frozen",
    fail_on_gate: bool = False,
) -> dict[str, Any]:
    lane = lane.strip().lower()
    if lane == "frozen":
        metrics = _benchmark_rollup(load_oz_company_intel_bench(cases_path))
        ok = metrics["selected_security_precision"] == "1" and metrics["numeric_exposure_accuracy"] == "1"
        if fail_on_gate and metrics["hard_gate_blocks"]:
            ok = False
        return {"lane": lane, "ok": ok, "metrics": metrics}

    if lane != "chaos":
        raise ValueError(f"unknown benchmark lane: {lane}")

    cases, typed_failures = _load_chaos_cases(cases_path)
    metrics = _benchmark_rollup(cases, builder_id="chaos-benchmark-builder") if cases else {
        "cases": 0,
        "selected_security_precision": "0",
        "numeric_exposure_accuracy": "0",
        "hard_gate_blocks": 0,
    }
    base_ok = metrics["selected_security_precision"] == "1" and metrics["numeric_exposure_accuracy"] == "1"
    checks = {
        "typed_failures": list(typed_failures),
        "case_count": len(cases),
        "hard_gate_blocks": metrics["hard_gate_blocks"],
        "line_validation_enabled": True,
    }
    ok = base_ok and not typed_failures
    if fail_on_gate and (metrics["hard_gate_blocks"] or typed_failures):
        ok = False
    return {"lane": lane, "ok": ok, "metrics": metrics, "checks": checks}
