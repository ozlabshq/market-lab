import json
from pathlib import Path
from unittest.mock import patch

from market_lab.web_evidence import FetchResponse, ProviderHealth, SearchHit, SearchResponse, utcnow
from market_lab.web_evidence_runner import collect_for_claims, verify_run
from market_lab.web_evidence_store import read_jsonl


class _DDGS:
    provider_id = "ddgs"

    def health(self):
        return ProviderHealth("ddgs", utcnow(), "ready", ["search"])

    def search(self, request):
        return SearchResponse(
            request_id=request.request_id,
            query_id=request.query_id,
            provider_id="ddgs",
            status="success",
            hits=[SearchHit("ddgs", "hit-1", 1, "https://example.com/report", "Report", "snippet")],
            result_count=1,
            latency_ms=1,
        )


class _Direct:
    provider_id = "direct_http"

    def health(self):
        return ProviderHealth("direct_http", utcnow(), "ready", ["fetch"])

    def fetch(self, request):
        body = b"Example Corp revenue increased in the filed report."
        return FetchResponse(
            request_id=request.request_id,
            run_id=request.run_id,
            claim_ids=request.claim_ids,
            query_ids=request.query_ids,
            provider_id="direct_http",
            provider_call_id=f"call-{request.request_id}",
            status="success",
            canonical_url=request.url,
            redirect_chain=[request.url],
            content_type="text/plain",
            byte_length=len(body),
            payload=body,
            response_headers={"content-type": "text/plain"},
        )


class _Official:
    def __init__(self, calls: list[str]) -> None:
        self.provider_id = "crossref"
        self.calls = calls

    def health(self):
        return ProviderHealth("crossref", utcnow(), "ready", ["fetch"])

    def fetch(self, request):
        self.calls.append(request.request_id)
        body = b"The DOI 10.1038/nphys1170 resolves to scholarly metadata context."
        return FetchResponse(
            request_id=request.request_id,
            run_id=request.run_id,
            claim_ids=request.claim_ids,
            query_ids=request.query_ids,
            provider_id="crossref",
            provider_call_id=f"crossref-{request.request_id}",
            status="success",
            canonical_url="https://api.crossref.org/works/10.1038/nphys1170",
            redirect_chain=["https://api.crossref.org/works/10.1038/nphys1170"],
            content_type="text/plain",
            byte_length=len(body),
            payload=body,
            response_headers={"content-type": "text/plain"},
        )


def _providers():
    return [_DDGS(), _Direct()]


def test_successful_live_fetch_has_provider_snapshot_and_extraction_audit(tmp_path: Path) -> None:
    with patch("market_lab.web_evidence_runner.build_registry", lambda profile, include_optional: _providers()):
        collect_for_claims(tmp_path, [{"claim_id": "claim-1", "text": "Example Corp revenue increased"}], mode="live", run_id="run")

    evidence = read_jsonl(tmp_path / "evidence.jsonl")
    calls = read_jsonl(tmp_path / "web_evidence" / "provider_calls.jsonl")
    audit = read_jsonl(tmp_path / "audit_log.jsonl")
    event_types = {row["event_type"] for row in audit}

    assert evidence
    assert all(row["provider_call_id"] in {call.get("provider_call_id") for call in calls} for row in evidence)
    assert "snapshot.committed" in event_types
    assert "extraction.completed" in event_types


def test_counterevidence_gate_reports_typed_freshness_and_context_only(tmp_path: Path) -> None:
    with patch("market_lab.web_evidence_runner.build_registry", lambda profile, include_optional: _providers()):
        collect_for_claims(tmp_path, [{"claim_id": "claim-1", "text": "Example Corp revenue increased"}], mode="live", run_id="run")
    queries = tmp_path / "web_evidence" / "queries.jsonl"
    rows = [row for row in read_jsonl(queries) if row.get("lane") == "primary_source"]
    queries.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    checks = verify_run(tmp_path, require_counterevidence_coverage=True)

    assert not checks["ok"]
    assert {"type": "counterevidence_missing", "claim_id": "claim-1", "lane": "counterevidence"} in checks[
        "coverage_blockers"
    ]
    assert {"type": "freshness_supersession_missing", "claim_id": "claim-1", "lane": "freshness_supersession"} in checks[
        "coverage_blockers"
    ]
    assert checks["automated_evidence_context_only"] is True


def _rewrite_search_row(tmp_path: Path, lane: str, mutate) -> str:
    query_rows = read_jsonl(tmp_path / "web_evidence" / "queries.jsonl")
    query_id = next(row["query_id"] for row in query_rows if row.get("lane") == lane)
    path = tmp_path / "web_evidence" / "search_results.jsonl"
    rows = read_jsonl(path)
    rewritten = []
    for row in rows:
        if row.get("query_id") == query_id:
            changed = mutate(dict(row))
            if changed is not None:
                rewritten.append(changed)
        else:
            rewritten.append(row)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rewritten) + "\n", encoding="utf-8")
    return query_id


def test_counterevidence_gate_requires_executed_search_result_for_planned_query(tmp_path: Path) -> None:
    with patch("market_lab.web_evidence_runner.build_registry", lambda profile, include_optional: _providers()):
        collect_for_claims(tmp_path, [{"claim_id": "claim-1", "text": "Example Corp revenue increased"}], mode="live", run_id="run")
    query_id = _rewrite_search_row(tmp_path, "counterevidence", lambda row: None)

    checks = verify_run(tmp_path, require_counterevidence_coverage=True)

    assert not checks["ok"]
    assert {
        "type": "counterevidence_not_executed",
        "claim_id": "claim-1",
        "lane": "counterevidence",
        "query_id": query_id,
    } in checks["coverage_blockers"]


def test_counterevidence_gate_reports_typed_failed_search_result(tmp_path: Path) -> None:
    with patch("market_lab.web_evidence_runner.build_registry", lambda profile, include_optional: _providers()):
        collect_for_claims(tmp_path, [{"claim_id": "claim-1", "text": "Example Corp revenue increased"}], mode="live", run_id="run")

    def fail(row):
        row.update({"status": "transport_error", "typed_error": "timeout", "result_count": 0})
        return row

    query_id = _rewrite_search_row(tmp_path, "freshness_supersession", fail)
    checks = verify_run(tmp_path, require_counterevidence_coverage=True)

    assert not checks["ok"]
    assert {
        "type": "freshness_supersession_failed",
        "claim_id": "claim-1",
        "lane": "freshness_supersession",
        "query_id": query_id,
        "provider_id": "ddgs",
        "status": "transport_error",
        "typed_error": "timeout",
    } in checks["coverage_blockers"]


def test_counterevidence_gate_reports_zero_search_results(tmp_path: Path) -> None:
    with patch("market_lab.web_evidence_runner.build_registry", lambda profile, include_optional: _providers()):
        collect_for_claims(tmp_path, [{"claim_id": "claim-1", "text": "Example Corp revenue increased"}], mode="live", run_id="run")

    def zero(row):
        row.update({"status": "success", "typed_error": "", "result_count": 0, "hits": []})
        return row

    query_id = _rewrite_search_row(tmp_path, "counterevidence", zero)
    checks = verify_run(tmp_path, require_counterevidence_coverage=True)

    assert not checks["ok"]
    assert {
        "type": "counterevidence_no_results",
        "claim_id": "claim-1",
        "lane": "counterevidence",
        "query_id": query_id,
        "provider_id": "ddgs",
    } in checks["coverage_blockers"]


def test_official_exact_resume_skips_provider_fetch_and_artifact_appends(tmp_path: Path) -> None:
    calls: list[str] = []

    def providers():
        return [_DDGS(), _Direct(), _Official(calls)]

    with patch("market_lab.web_evidence_runner.build_registry", lambda profile, include_optional: providers()):
        collect_for_claims(
            tmp_path,
            [{"claim_id": "claim-doi", "text": "The DOI 10.1038/nphys1170 resolves to scholarly metadata context"}],
            mode="live",
            run_id="run",
        )
        counts = {
            str(path.relative_to(tmp_path)): len(path.read_text(encoding="utf-8").splitlines())
            for path in [
                tmp_path / "evidence.jsonl",
                tmp_path / "audit_log.jsonl",
                tmp_path / "web_evidence" / "queries.jsonl",
                tmp_path / "web_evidence" / "provider_calls.jsonl",
                tmp_path / "web_evidence" / "snapshot_index.jsonl",
                tmp_path / "web_evidence" / "segments.jsonl",
            ]
        }
        first_call_count = len(calls)
        collect_for_claims(
            tmp_path,
            [{"claim_id": "claim-doi", "text": "The DOI 10.1038/nphys1170 resolves to scholarly metadata context"}],
            mode="live",
            run_id="run",
        )
        counts_after = {
            str(path.relative_to(tmp_path)): len(path.read_text(encoding="utf-8").splitlines())
            for path in [
                tmp_path / "evidence.jsonl",
                tmp_path / "audit_log.jsonl",
                tmp_path / "web_evidence" / "queries.jsonl",
                tmp_path / "web_evidence" / "provider_calls.jsonl",
                tmp_path / "web_evidence" / "snapshot_index.jsonl",
                tmp_path / "web_evidence" / "segments.jsonl",
            ]
        }

    assert first_call_count == 1
    assert len(calls) == first_call_count
    assert counts_after == counts


def test_require_snapshots_fails_missing_snapshot_index(tmp_path: Path) -> None:
    with patch("market_lab.web_evidence_runner.build_registry", lambda profile, include_optional: _providers()):
        collect_for_claims(tmp_path, [{"claim_id": "claim-1", "text": "Example Corp revenue increased"}], mode="live", run_id="run")
    (tmp_path / "web_evidence" / "snapshot_index.jsonl").write_text("", encoding="utf-8")

    checks = verify_run(tmp_path, require_snapshots=True)

    assert not checks["ok"]
    assert checks["missing_snapshots"]


def test_frozen_collection_zero_provider_calls_and_idempotent_artifacts(tmp_path: Path) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("provider construction or network path was called")

    with patch("market_lab.web_evidence_runner.build_registry", explode), patch(
        "market_lab.web_evidence_providers.DDGSProvider.health", explode
    ), patch("market_lab.web_evidence_providers.DDGSProvider.search", explode), patch(
        "market_lab.web_evidence_providers.DirectHTTPProvider.health", explode
    ), patch(
        "market_lab.web_evidence_providers.DirectHTTPProvider.fetch", explode
    ):
        first = collect_for_claims(tmp_path, [{"claim_id": "claim-frozen", "text": "Frozen claim context"}], mode="frozen", run_id="run")
        counts = {
            path.name: len(path.read_text(encoding="utf-8").splitlines())
            for path in [
                tmp_path / "evidence.jsonl",
                tmp_path / "audit_log.jsonl",
                tmp_path / "web_evidence" / "queries.jsonl",
                tmp_path / "web_evidence" / "provider_calls.jsonl",
                tmp_path / "web_evidence" / "snapshot_index.jsonl",
                tmp_path / "web_evidence" / "segments.jsonl",
            ]
        }
        second = collect_for_claims(tmp_path, [{"claim_id": "claim-frozen", "text": "Frozen claim context"}], mode="frozen", run_id="run")
        counts_after = {path.name: len(path.read_text(encoding="utf-8").splitlines()) for path in [
            tmp_path / "evidence.jsonl",
            tmp_path / "audit_log.jsonl",
            tmp_path / "web_evidence" / "queries.jsonl",
            tmp_path / "web_evidence" / "provider_calls.jsonl",
            tmp_path / "web_evidence" / "snapshot_index.jsonl",
            tmp_path / "web_evidence" / "segments.jsonl",
        ]}

    assert first["fetches"] == 1
    assert second["fetches"] == 0
    assert counts_after == counts
