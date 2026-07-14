from __future__ import annotations

"""Web evidence runner.

Orchestrates claims -> query -> fetch -> snapshot -> evidence linking.
"""

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .web_evidence import (
    BudgetProfile,
    EvidenceRecord,
    EvidenceSegment,
    FetchRequest,
    SearchRequest,
    SCHEMA_EVIDENCE_V2,
    canonicalize_url_for_dedupe,
    load_budget_profile,
    make_evidence_id,
    normalize_query,
    origin_cluster_id_for,
    request_id_for,
    sha256_hex,
    utcnow,
)
from .web_evidence_providers import (
    DDGSProvider,
    DirectHTTPProvider,
    build_keyless_registry,
    build_optional_registry,
)
from .web_evidence_store import (
    append_audit_chain,
    append_budget_report,
    append_evidence_record,
    append_provider_call,
    append_query_event,
    append_provider_health,
    append_search_results,
    append_segment,
    commit_snapshot,
    ensure_layout,
    ensure_layout as _ensure_layout,
    load_audit_chain,
    make_text_segment,
    read_jsonl,
    read_snapshot_manifest,
    verify_segment_locator,
    write_plan,
    verify_audit_chain,
)


ALLOWED_PROFILE_FLAGS = {"off", "frozen", "live"}


def build_registry(profile: str = "keyless_standard", include_optional: bool = True) -> list[Any]:
    providers = build_keyless_registry(profile)
    if include_optional:
        providers.extend(build_optional_registry(profile))
    return providers


def _provider_by_id(providers: list[Any], provider_id: str):
    for provider in providers:
        if provider.provider_id == provider_id:
            return provider
    raise KeyError(f"provider not found: {provider_id}")


def check_health(
    profile: str = "keyless_standard",
    include_optional: bool = True,
    require_core_ready: bool = False,
) -> dict[str, Any]:
    providers = build_registry(profile, include_optional=include_optional)
    health_rows: list[dict[str, Any]] = []
    for provider in providers:
        health = provider.health()
        health_rows.append(asdict(health))

    ready = {row["provider_id"]: row["status"] for row in health_rows}
    if require_core_ready:
        if ready.get("direct_http") != "ready":
            raise RuntimeError("core provider direct_http not ready")
        if ready.get("ddgs") != "ready":
            raise RuntimeError("core provider ddgs not ready")

    return {
        "profile": profile,
        "providers": health_rows,
        "snapshot_root": "web_evidence",
        "recorded_at_utc": utcnow(),
    }


def _claim_text(claim: dict[str, Any]) -> str:
    return normalize_query(str(claim.get("text") or claim.get("claim") or claim.get("claim_text") or ""))


def _classify_source_type(claim_text: str) -> str:
    low = claim_text.lower()
    if any(term in low for term in ["10-k", "10-q", "8-k", "sec", "filing", "revenue", "debt"]):
        return "filed_company_disclosure"
    if any(term in low for term in ["doi", "study", "paper", "trial", "arxiv"]):
        return "scholarly"
    if any(term in low for term in ["bls", "census", "regulation", "agency", "approval"]):
        return "official_government"
    return "web_document"


def _build_claim_queries(claim: dict[str, Any], idx: int, run_id: str, profile: BudgetProfile) -> list[SearchRequest]:
    claim_id = claim.get("claim_id") or claim.get("id") or f"claim-{idx}"
    text = _claim_text(claim)[:250]
    if not text:
        text = "company disclosure"
    variants = [
        ("primary_source", text),
        ("counterevidence", f'"{text[:160]}" correction OR denied OR restatement OR retraction OR not'),
        ("freshness_supersession", f'"{text[:160]}" amendment OR updated OR superseded OR latest'),
    ]
    source_type = _classify_source_type(text)
    if source_type == "filed_company_disclosure":
        variants[0] = ("primary_source", f"{text} site:sec.gov")
    elif source_type == "official_government":
        variants[0] = ("primary_source", f"{text} site:.gov")
    requests: list[SearchRequest] = []
    for lane, query in variants[: max(1, profile.max_queries_per_claim)]:
        requests.append(
            SearchRequest(
                request_id=request_id_for("search", f"{run_id}:{claim_id}:{idx}:{lane}"),
                query_id=request_id_for("query", f"{run_id}:{claim_id}:{idx}:{lane}"),
                run_id=run_id,
                claim_ids=[claim_id],
                exact_query=normalize_query(query)[:300],
                lane=lane,
                max_results=min(profile.max_results_per_query, 10),
                timeout_seconds=profile.search_timeout_seconds,
                budget_reservation_id=f"budget:{run_id}:{claim_id}",
            )
        )
    return requests


def _build_fetch(request: SearchRequest, url: str, claim_id: str, run_id: str, profile: BudgetProfile) -> FetchRequest:
    return FetchRequest(
        request_id=request_id_for("fetch", f"{run_id}:{claim_id}:{url}"),
        run_id=run_id,
        claim_ids=[claim_id],
        query_ids=[request.query_id],
        url=url,
        timeout_seconds=profile.fetch_timeout_seconds,
        max_bytes=profile.max_bytes_per_fetch,
        max_redirects=profile.max_redirects,
        allow_third_party_transform=True,
        budget_reservation_id=f"budget:{run_id}:{claim_id}",
    )


def _write_claim_plan(run_dir: Path, plan: list[dict[str, Any]]) -> None:
    write_plan(run_dir, {"generated_at_utc": utcnow(), "plan": plan})


def collect_for_claims(
    run_dir: Path,
    claims: list[dict[str, Any]],
    *,
    profile: str = "keyless_standard",
    run_id: str = "run",
    mode: str = "off",
    max_claims: int | None = None,
    budget_profile: BudgetProfile | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    mode = mode.strip().lower()
    if mode not in ALLOWED_PROFILE_FLAGS:
        raise ValueError(f"unknown web-evidence mode: {mode}")

    budget = budget_profile or load_budget_profile(profile)
    result: dict[str, Any] = {
        "status": "completed" if mode != "off" else "off",
        "profile": profile,
        "run_id": run_id,
        "claims": 0,
        "searches": 0,
        "fetches": 0,
        "evidence_added": 0,
    }

    if not claims or mode == "off":
        append_budget_report(run_dir, {"profile": profile, "budget": asdict(budget)})
        return result

    base = ensure_layout(run_dir)
    providers = build_registry(profile, include_optional=False)
    append_provider_health(
        run_dir,
        [asdict(provider.health()) for provider in providers],
    )
    append_budget_report(run_dir, {"profile": profile, "budget": asdict(budget)})

    ddgs = _provider_by_id(providers, "ddgs")
    direct_http = _provider_by_id(providers, "direct_http")
    total_claims = len(claims)
    if max_claims is not None:
        total_claims = min(total_claims, max_claims)

    result["claims"] = total_claims
    plan: list[dict[str, Any]] = []
    seen_canonical_urls: set[str] = set()
    seen_content_hashes: set[str] = set()

    for i, claim in enumerate(claims[:total_claims]):
        claim_id = claim.get("claim_id") or claim.get("id") or f"claim-{i}"
        claim_text = _claim_text(claim)
        used_fetches = 0

        for search_request in _build_claim_queries(claim, i, run_id, budget):
            append_query_event(run_dir, asdict(search_request))
            plan.append(
                {
                    "claim_id": claim_id,
                    "query_id": search_request.query_id,
                    "query": search_request.exact_query,
                    "lane": search_request.lane,
                    "source_type": _classify_source_type(claim_text),
                }
            )

            search_response = ddgs.search(search_request)
            append_search_results(run_dir, search_response)
            append_provider_call(
                run_dir,
                {
                    "event": "search",
                    "provider_id": search_response.provider_id,
                    "query_id": search_response.query_id,
                    "request_id": search_response.request_id,
                    "status": search_response.status,
                    "result_count": search_response.result_count,
                    "typed_error": search_response.typed_error,
                    "raw_payload_hash": search_response.raw_payload_hash,
                    "latency_ms": search_response.latency_ms,
                },
            )
            result["searches"] += 1
            if not search_response.hits:
                append_audit_chain(
                    run_dir,
                    {
                        "event_type": "claim_search_empty",
                        "claim_id": claim_id,
                        "run_id": run_id,
                        "query_id": search_request.query_id,
                        "lane": search_request.lane,
                        "status": search_response.status,
                        "typed_error": search_response.typed_error,
                    },
                )
                continue

            for hit in search_response.hits:
                if used_fetches >= budget.max_fetches_per_claim:
                    break

                canonical_url = canonicalize_url_for_dedupe(hit.url)
                if canonical_url in seen_canonical_urls:
                    append_provider_call(
                        run_dir,
                        {"event": "dedupe_skip", "reason": "canonical_url", "url": hit.url, "canonical_url": canonical_url, "claim_id": claim_id},
                    )
                    continue
                seen_canonical_urls.add(canonical_url)

                used_fetches += 1
                result["fetches"] += 1
                fetch_request = _build_fetch(search_request, hit.url, claim_id, run_id, budget)
                fetch_response = direct_http.fetch(fetch_request)
                append_provider_call(run_dir, {k: v for k, v in asdict(fetch_response).items() if k not in {"payload"}})

                if fetch_response.status != "success" or not fetch_response.payload:
                    append_audit_chain(
                        run_dir,
                        {
                            "event_type": "fetch_failed",
                            "claim_id": claim_id,
                            "run_id": run_id,
                            "query_id": search_request.query_id,
                            "provider_id": fetch_response.provider_id,
                            "status": fetch_response.status,
                            "typed_error": fetch_response.typed_error,
                            "url": hit.url,
                            "latency_ms": fetch_response.latency_ms,
                        },
                    )
                    continue

                raw_hash = sha256_hex(fetch_response.payload)
                if raw_hash in seen_content_hashes:
                    append_provider_call(
                        run_dir,
                        {"event": "dedupe_skip", "reason": "content_hash", "url": hit.url, "raw_sha256": raw_hash, "claim_id": claim_id},
                    )
                    continue
                seen_content_hashes.add(raw_hash)

                snapshot_id, manifest_path = commit_snapshot(
                    run_dir,
                    provider_id=fetch_response.provider_id,
                    request_id=fetch_response.request_id,
                    claim_ids=fetch_response.claim_ids,
                    query_ids=fetch_response.query_ids,
                    requested_url=hit.url,
                    response=fetch_response,
                    response_body=fetch_response.payload,
                    response_headers=fetch_response.response_headers,
                )
                manifest = read_snapshot_manifest(run_dir, snapshot_id)
                if manifest.get("extraction_status") != "success":
                    append_audit_chain(
                        run_dir,
                        {
                            "event_type": "extraction_blocked",
                            "claim_id": claim_id,
                            "run_id": run_id,
                            "snapshot_id": snapshot_id,
                            "status": manifest.get("extraction_status"),
                            "content_type": manifest.get("content_type"),
                        },
                    )
                    continue

                extracted_text = (Path(manifest_path).parent / "extracted.txt").read_text(encoding="utf-8")
                segment = make_text_segment(snapshot_id, extracted_text, claim_text, segment_seed=f"{claim_id}:{hit.url}")
                if segment is None or not verify_segment_locator(run_dir, segment):
                    append_audit_chain(
                        run_dir,
                        {"event_type": "segment_locator_failed", "claim_id": claim_id, "run_id": run_id, "snapshot_id": snapshot_id},
                    )
                    continue

                append_segment(run_dir, segment)
                stance = "refutes" if search_request.lane == "counterevidence" else "context"
                record = EvidenceRecord(
                    schema_version=SCHEMA_EVIDENCE_V2,
                    evidence_id=make_evidence_id(run_id=run_id, claim_id=claim_id, segment_id=segment.segment_id, stance=stance),
                    run_id=run_id,
                    claim_id=claim_id,
                    segment_id=segment.segment_id,
                    snapshot_id=snapshot_id,
                    stance=stance,
                    source_type=_classify_source_type(claim_text),
                    source_tier="candidate",
                    source_quality_reason="fetched_extracted_locator_verified",
                    publisher="",
                    title=hit.title[:160],
                    canonical_url=fetch_response.canonical_url or hit.url,
                    document_identifier=raw_hash,
                    retrieved_at_utc=utcnow(),
                    exact_locator=segment.locator,
                    verbatim_excerpt_or_value=segment.verbatim_excerpt_or_value,
                    query_ids=[search_request.query_id],
                    provider_id=fetch_response.provider_id,
                    provider_call_id=fetch_response.provider_call_id,
                    source_lineage="web_evidence.v1",
                    origin_cluster_id=origin_cluster_id_for(fetch_response.canonical_url or hit.url),
                    version="1",
                    confidence=0.4,
                )
                append_evidence_record(run_dir, record)
                append_audit_chain(
                    run_dir,
                    {
                        "event_type": "evidence_linked",
                        "claim_id": claim_id,
                        "run_id": run_id,
                        "snapshot_id": snapshot_id,
                        "segment_id": segment.segment_id,
                        "provider_id": fetch_response.provider_id,
                        "provider_call_id": fetch_response.provider_call_id,
                        "source_url": hit.url,
                        "query_id": search_request.query_id,
                        "lane": search_request.lane,
                        "origin_cluster_id": record.origin_cluster_id,
                    },
                )
                result["evidence_added"] += 1
                if stance == "context":
                    break

    _write_claim_plan(run_dir, plan)
    # Persist provider-health and audit artifacts in web_evidence root.
    append_audit_chain(
        run_dir,
        {
            "event_type": "collect_complete",
            "run_id": run_id,
            "claims": result["claims"],
            "searches": result["searches"],
            "fetches": result["fetches"],
            "evidence_added": result["evidence_added"],
        },
    )
    return result


def run_smoke(
    run_dir: Path,
    *,
    profile: str = "keyless_standard",
    query: str | None = None,
    url: str | None = None,
    sec_cik: str | None = None,
    crossref_doi: str | None = None,
    arxiv_id: str | None = None,
    government_url: str | None = None,
    lane: str = "frozen",
) -> dict[str, Any]:
    base = _ensure_layout(run_dir)
    providers = build_registry(profile, include_optional=False)
    ddgs = _provider_by_id(providers, "ddgs")
    direct = _provider_by_id(providers, "direct_http")
    sec = _provider_by_id(providers, "sec")
    crossref = _provider_by_id(providers, "crossref")
    from .web_evidence_providers import ArxivProvider

    arxiv = _provider_by_id(providers, "arxiv") if any(p.provider_id == "arxiv" for p in providers) else ArxivProvider()
    gov = _provider_by_id(providers, "government_http")

    append_provider_health(run_dir, [asdict(provider.health()) for provider in providers])

    run_id = run_dir.name or "smoke"
    result: dict[str, Any] = {
        "profile": profile,
        "lane": lane,
        "run_dir": str(run_dir),
        "query": query or "",
        "paid_provider_cost_usd": 0.0,
    }

    if query:
        search_request = SearchRequest(
            request_id="smoke-ddgs",
            query_id="smoke-ddgs",
            run_id=run_id,
            claim_ids=["smoke"],
            exact_query=query,
            lane="smoke",
            max_results=3,
            timeout_seconds=20,
            budget_reservation_id="smoke",
        )
        response = ddgs.search(search_request)
        append_search_results(run_dir, response)
        result["ddgs"] = {"status": response.status, "result_count": response.result_count, "typed_error": response.typed_error}
    else:
        result["ddgs"] = {"status": "skipped", "result_count": 0, "typed_error": ""}

    if url:
        request = FetchRequest(
            request_id="smoke-direct",
            run_id=run_id,
            claim_ids=["smoke"],
            query_ids=["smoke-ddgs"],
            url=url,
            timeout_seconds=20,
            max_bytes=20 * 1024 * 1024,
            max_redirects=5,
        )
        response = direct.fetch(request)
        if response.status == "success" and response.payload:
            snapshot_id, _ = commit_snapshot(
                run_dir,
                provider_id=response.provider_id,
                request_id=response.request_id,
                claim_ids=response.claim_ids,
                query_ids=response.query_ids,
                requested_url=url,
                response=response,
                response_body=response.payload,
                response_headers=response.response_headers,
            )
            result["direct_http"] = {"status": "success", "snapshot_id": snapshot_id}
        else:
            result["direct_http"] = {"status": response.status, "snapshot_id": None}
    else:
        result["direct_http"] = {"status": "skipped", "snapshot_id": None}

    if sec_cik:
        response = sec.fetch(
            FetchRequest(
                request_id="smoke-sec",
                run_id=run_id,
                claim_ids=["smoke"],
                query_ids=["smoke-sec"],
                url=str(sec_cik),
                timeout_seconds=20,
                max_bytes=20 * 1024 * 1024,
                max_redirects=5,
            )
        )
        if response.status == "success" and response.payload:
            snapshot_id, _ = commit_snapshot(
                run_dir,
                provider_id=response.provider_id,
                request_id=response.request_id,
                claim_ids=response.claim_ids,
                query_ids=response.query_ids,
                requested_url=sec_cik,
                response=response,
                response_body=response.payload,
                response_headers=response.response_headers,
            )
            result["sec"] = {"status": "success", "snapshot_id": snapshot_id}
        else:
            result["sec"] = {"status": response.status, "snapshot_id": None}
    else:
        result["sec"] = {"status": "skipped", "snapshot_id": None}

    if crossref_doi:
        response = crossref.fetch(
            FetchRequest(
                request_id="smoke-crossref",
                run_id=run_id,
                claim_ids=["smoke"],
                query_ids=["smoke-crossref"],
                url=crossref_doi,
                timeout_seconds=20,
                max_bytes=20 * 1024 * 1024,
                max_redirects=2,
            )
        )
        if response.status == "success" and response.payload:
            commit_snapshot(
                run_dir,
                provider_id=response.provider_id,
                request_id=response.request_id,
                claim_ids=response.claim_ids,
                query_ids=response.query_ids,
                requested_url=crossref_doi,
                response=response,
                response_body=response.payload,
                response_headers=response.response_headers,
            )
            result["crossref"] = {"status": "success"}
        else:
            result["crossref"] = {"status": response.status}
    else:
        result["crossref"] = {"status": "skipped"}

    if arxiv_id:
        response = arxiv.fetch(
            FetchRequest(
                request_id="smoke-arxiv",
                run_id=run_id,
                claim_ids=["smoke"],
                query_ids=["smoke-arxiv"],
                url=arxiv_id,
                timeout_seconds=20,
                max_bytes=20 * 1024 * 1024,
                max_redirects=2,
            )
        )
        if response.status == "success" and response.payload:
            result["arxiv"] = {"status": "success"}
        else:
            result["arxiv"] = {"status": response.status}
    else:
        result["arxiv"] = {"status": "skipped"}

    if government_url:
        response = gov.fetch(
            FetchRequest(
                request_id="smoke-government",
                run_id=run_id,
                claim_ids=["smoke"],
                query_ids=["smoke-government"],
                url=government_url,
                timeout_seconds=20,
                max_bytes=20 * 1024 * 1024,
                max_redirects=3,
            )
        )
        result["government_http"] = {"status": response.status}
    else:
        result["government_http"] = {"status": "skipped"}

    return result


def run_benchmark(
    run_dir: Path,
    *,
    lane: str,
    cases_path: Path,
    output_path: Path,
    fail_on_gate: bool = False,
) -> dict[str, Any]:
    output_path = Path(output_path)
    run_dir = Path(run_dir)
    lane = lane.strip().lower()

    case_rows: list[dict[str, Any]] = []
    if cases_path.exists():
        for line in cases_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case_rows.append(json.loads(line))

    failures = 0
    if lane not in {"live", "frozen"}:
        raise ValueError(f"unknown benchmark lane: {lane}")

    # For frozen lane, evaluate schema only and do not execute network.
    if lane == "frozen":
        for row in case_rows:
            if not row.get("claim_id") or not row.get("claim_text"):
                failures += 1
        output = {
            "lane": lane,
            "cases_total": len(case_rows),
            "cases_processed": len(case_rows),
            "cases_failed": failures,
            "passed": failures == 0,
            "metrics": {"network_calls": 0},
        }
    else:
        claims = [
            {
                "claim_id": row.get("claim_id") or row.get("id") or f"case-{idx}",
                "text": row.get("claim_text") or row.get("claim") or "",
            }
            for idx, row in enumerate(case_rows)
        ]
        collect = collect_for_claims(
            run_dir,
            claims,
            profile="keyless_standard",
            run_id=run_dir.name,
            mode="live",
        )
        output = {
            "lane": lane,
            "cases_total": len(case_rows),
            "cases_processed": collect["claims"],
            "cases_failed": 0 if collect["claims"] and collect["searches"] and collect["evidence_added"] else len(case_rows),
            "passed": bool(collect["claims"] and collect["searches"] and collect["evidence_added"]),
            "metrics": collect,
            "checks": {"searches": collect["searches"], "evidence_added": collect["evidence_added"]},
        }

    ensure_layout(run_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")

    if fail_on_gate and not output["passed"]:
        raise RuntimeError("benchmark-gates-failed")
    return output


def verify_run(
    run_dir: Path,
    *,
    require_snapshots: bool = False,
    require_counterevidence_coverage: bool = False,
    require_audit_chain: bool = False,
    require_zero_snippet_evidence: bool = False,
    require_zero_execution_side_effects: bool = False,
) -> dict[str, Any]:
    run_dir = Path(run_dir)
    evidence_path = run_dir / "evidence.jsonl"
    search_rows_path = run_dir / "web_evidence" / "search_results.jsonl"
    provider_calls_path = run_dir / "web_evidence" / "provider_calls.jsonl"
    snapshot_index = run_dir / "web_evidence" / "snapshot_index.jsonl"
    audit_log = run_dir / "audit_log.jsonl"

    evidence_rows = read_jsonl(evidence_path) if evidence_path.exists() else []
    search_rows = read_jsonl(search_rows_path) if search_rows_path.exists() else []
    provider_calls = read_jsonl(provider_calls_path) if provider_calls_path.exists() else []
    snapshot_rows = read_jsonl(snapshot_index) if snapshot_index.exists() else []

    checks = {
        "has_evidence": len(evidence_rows) > 0,
        "search_rows_present": len(search_rows) > 0,
        "provider_calls_present": len(provider_calls) > 0,
    }

    if require_snapshots:
        missing = []
        for row in evidence_rows:
            if row.get("snapshot_id") and not any(
                isinstance(idx, dict) and idx.get("snapshot_id") == row.get("snapshot_id") for idx in snapshot_rows
            ):
                missing.append(row.get("snapshot_id"))
        checks["snapshots_present"] = len(missing) == 0
        checks["missing_snapshots"] = missing[:5]

    if require_counterevidence_coverage:
        query_rows = read_jsonl(run_dir / "web_evidence" / "queries.jsonl")
        claim_ids = {r.get("claim_id") for r in evidence_rows if isinstance(r, dict) and r.get("claim_id")}
        coverage: dict[str, set[str]] = {str(cid): set() for cid in claim_ids}
        for row in query_rows:
            for cid in row.get("claim_ids", []):
                if cid in coverage:
                    coverage[str(cid)].add(str(row.get("lane", "")))
        missing = [cid for cid, lanes in coverage.items() if "counterevidence" not in lanes]
        checks["counterevidence_coverage_ok"] = not missing
        checks["counterevidence_missing_claims"] = missing

    if require_audit_chain:
        checks["audit_chain_present"] = audit_log.exists()
        ok_chain, reason = verify_audit_chain(load_audit_chain(run_dir)) if audit_log.exists() else (False, "missing_audit_log")
        checks["audit_chain_valid"] = ok_chain
        checks["audit_chain_error"] = reason

    if require_zero_snippet_evidence:
        checks["zero_snippet_evidence"] = all(
            row.get("source_type") != "search_result"
            and row.get("verbatim_excerpt_or_value") != ""
            and row.get("segment_id")
            and row.get("snapshot_id")
            for row in evidence_rows
        )

    if require_zero_execution_side_effects:
        forbidden_paths = [
            "mock_ledger.jsonl",
            "mock_portfolio_state.json",
            "pending_order_candidates.jsonl",
            "options_paper_ledger.jsonl",
            "options_paper_state.json",
        ]
        touched = [p for p in forbidden_paths if (run_dir / p).exists()]
        checks["side_effect_free"] = not touched
        checks["side_effect_paths"] = touched

    checks["ok"] = all(v is True for k, v in checks.items() if isinstance(v, bool))
    checks["run_dir"] = str(run_dir)
    checks["recorded_at_utc"] = utcnow()
    return checks


__all__ = [
    "build_registry",
    "check_health",
    "collect_for_claims",
    "run_smoke",
    "run_benchmark",
    "verify_run",
]
