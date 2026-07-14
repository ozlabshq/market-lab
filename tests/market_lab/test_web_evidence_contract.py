from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_lab import mlab_ingest
from market_lab.web_evidence import FetchRequest, FetchResponse, ProviderHealth, SearchHit, SearchResponse, utcnow
from market_lab.web_evidence_providers import DirectHTTPProvider, OptionalProvider
from market_lab.web_evidence_runner import collect_for_claims, run_benchmark, verify_run
from market_lab.web_evidence_store import append_audit_chain, commit_snapshot, load_audit_chain, read_snapshot_manifest, verify_audit_chain


def _fetch_response(payload: bytes, *, content_type: str = "text/html; charset=utf-8") -> FetchResponse:
    return FetchResponse(
        request_id="fetch-1",
        run_id="run-1",
        claim_ids=["claim-1"],
        query_ids=["query-1"],
        provider_id="direct_http",
        provider_call_id="call-1",
        status="success",
        canonical_url="https://example.com/report",
        redirect_chain=["https://example.com/report"],
        content_type=content_type,
        byte_length=len(payload),
        payload=payload,
        response_headers={"content-type": content_type},
    )


class _FakeDDGS:
    provider_id = "ddgs"

    def health(self):
        return ProviderHealth("ddgs", utcnow(), "ready", ["search"])

    def search(self, request):
        return SearchResponse(
            request_id=request.request_id,
            query_id=request.query_id,
            provider_id="ddgs",
            status="success",
            hits=[
                SearchHit("ddgs", "r1", 1, "https://example.com/report?utm_source=x", "Search title", "SEARCH SNIPPET ONLY"),
                SearchHit("ddgs", "r2", 2, "https://example.com/report", "Duplicate", "SEARCH SNIPPET ONLY"),
            ],
            result_count=2,
            latency_ms=1,
        )


class _FakeDirect:
    provider_id = "direct_http"

    def health(self):
        return ProviderHealth("direct_http", utcnow(), "ready", ["fetch"])

    def fetch(self, request):
        body = b"<html><body><p>Example Corp revenue increased in the filed report.</p></body></html>"
        return FetchResponse(
            request_id=request.request_id,
            run_id=request.run_id,
            claim_ids=request.claim_ids,
            query_ids=request.query_ids,
            provider_id="direct_http",
            provider_call_id="call",
            status="success",
            canonical_url="https://example.com/report",
            redirect_chain=["https://example.com/report"],
            content_type="text/html",
            byte_length=len(body),
            payload=body,
            response_headers={"content-type": "text/html"},
        )


class WebEvidenceContractTests(unittest.TestCase):
    def test_audit_chain_uses_one_canonical_hash_and_detects_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            append_audit_chain(run_dir, {"event_type": "first", "run_id": "run"})
            append_audit_chain(run_dir, {"event_type": "second", "run_id": "run"})

            self.assertEqual(verify_audit_chain(load_audit_chain(run_dir)), (True, ""))

            rows = load_audit_chain(run_dir)
            rows[0]["event_type"] = "tampered"
            self.assertEqual(verify_audit_chain(rows), (False, "event hash mismatch"))

    def test_direct_http_returns_typed_unsafe_for_private_and_redirect(self) -> None:
        provider = DirectHTTPProvider()
        response = provider.fetch(FetchRequest(request_id="r", run_id="run", claim_ids=["c"], query_ids=["q"], url="http://127.0.0.1/"))
        self.assertEqual(response.status, "unsafe_url")

        def fake_fetch(url: str, *, timeout_seconds: int, max_bytes: int):
            return 302, b"", {"location": "http://127.0.0.1/secret"}

        with patch("market_lab.web_evidence_providers._single_pinned_fetch", fake_fetch):
            redirected = provider.fetch(
                FetchRequest(request_id="r2", run_id="run", claim_ids=["c"], query_ids=["q"], url="https://example.com/")
            )
        self.assertEqual(redirected.status, "unsafe_url")

    def test_snapshot_commit_is_immutable_and_extraction_is_typed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            payload = b"<html><head><title>Title</title></head><body><p>Revenue increased in the filed report.</p></body></html>"
            response = _fetch_response(payload)

            snapshot_id, manifest_path = commit_snapshot(
                run_dir,
                provider_id="direct_http",
                request_id="fetch-1",
                claim_ids=["claim-1"],
                query_ids=["query-1"],
                requested_url="https://example.com/report",
                response=response,
                response_body=payload,
                response_headers=response.response_headers,
            )
            extracted_path = manifest_path.parent / "extracted.txt"
            first_mtime = (manifest_path.stat().st_mtime_ns, extracted_path.stat().st_mtime_ns)

            snapshot_id_2, manifest_path_2 = commit_snapshot(
                run_dir,
                provider_id="direct_http",
                request_id="fetch-1",
                claim_ids=["claim-1"],
                query_ids=["query-1"],
                requested_url="https://example.com/report",
                response=response,
                response_body=payload,
                response_headers=response.response_headers,
            )
            self.assertEqual(snapshot_id_2, snapshot_id)
            self.assertEqual(manifest_path_2, manifest_path)
            self.assertEqual(first_mtime, (manifest_path.stat().st_mtime_ns, extracted_path.stat().st_mtime_ns))
            self.assertEqual(read_snapshot_manifest(run_dir, snapshot_id)["extraction_status"], "success")

            media = b"\x89PNG\r\n"
            media_response = _fetch_response(media, content_type="image/png")
            media_id, _ = commit_snapshot(
                run_dir,
                provider_id="direct_http",
                request_id="fetch-2",
                claim_ids=["claim-1"],
                query_ids=["query-1"],
                requested_url="https://example.com/image.png",
                response=media_response,
                response_body=media,
                response_headers=media_response.response_headers,
            )
            self.assertEqual(read_snapshot_manifest(run_dir, media_id)["extraction_status"], "unsupported_media")

    def test_pipeline_links_only_extracted_segments_and_records_dedupe_counterevidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            with patch("market_lab.web_evidence_runner.build_registry", lambda profile, include_optional: [_FakeDDGS(), _FakeDirect()]):
                result = collect_for_claims(
                    run_dir,
                    [{"claim_id": "claim-1", "text": "Example Corp revenue increased"}],
                    mode="live",
                    run_id="run-1",
                )

            self.assertGreaterEqual(result["evidence_added"], 1)
            evidence = [json.loads(line) for line in (run_dir / "evidence.jsonl").read_text().splitlines()]
            self.assertTrue(all(row["source_type"] != "search_result" for row in evidence))
            self.assertNotIn("SEARCH SNIPPET ONLY", {row["verbatim_excerpt_or_value"] for row in evidence})
            self.assertTrue(all(row["snapshot_id"].startswith("sha256:") and row["segment_id"].startswith("seg-") for row in evidence))
            queries = [json.loads(line) for line in (run_dir / "web_evidence" / "queries.jsonl").read_text().splitlines()]
            self.assertTrue({"primary_source", "counterevidence", "freshness_supersession"}.issubset({row["lane"] for row in queries}))
            calls = [json.loads(line) for line in (run_dir / "web_evidence" / "provider_calls.jsonl").read_text().splitlines()]
            self.assertTrue(any(row.get("event") == "dedupe_skip" for row in calls))

            checks = verify_run(
                run_dir,
                require_snapshots=True,
                require_counterevidence_coverage=True,
                require_audit_chain=True,
                require_zero_snippet_evidence=True,
                require_zero_execution_side_effects=True,
            )
            self.assertTrue(checks["ok"], checks)

    def test_optional_provider_unconfigured_and_benchmark_fail_control(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            health = OptionalProvider("tavily", "TAVILY_API_KEY_DOES_NOT_EXIST").health()
            self.assertEqual(health.status, "unconfigured")
            self.assertEqual(health.missing_configuration, ["TAVILY_API_KEY_DOES_NOT_EXIST"])

            cases = run_dir / "cases.jsonl"
            cases.write_text(json.dumps({"claim_id": "bad"}) + "\n", encoding="utf-8")
            output = run_benchmark(run_dir / "bench", lane="frozen", cases_path=cases, output_path=run_dir / "out.json")
            self.assertFalse(output["passed"])
            self.assertEqual(output["cases_failed"], 1)

    def test_mlab_ingest_web_evidence_hook_advances_without_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            run_dir.mkdir()
            (run_dir / "status.json").write_text(
                json.dumps({"run_id": "run", "stage": "claims_extracted", "verdict": "IN_PROGRESS", "owner": "qa", "next_owner": "qa"}),
                encoding="utf-8",
            )
            (run_dir / "claims.json").write_text(
                json.dumps({"run_id": "run", "claims": [{"claim_id": "claim-1", "text": "Example claim"}]}),
                encoding="utf-8",
            )

            result = mlab_ingest.run_web_evidence_research(run_dir, mode="off", owner="qa")
            status = mlab_ingest.read_status(run_dir)
            claims = mlab_ingest.read_claims(run_dir)["claims"]

            self.assertEqual(result["status"], "off")
            self.assertEqual(status["stage"], "research_active")
            self.assertEqual(status["verdict"], "IN_PROGRESS")
            self.assertIsNone(claims[0].get("disposition"))


if __name__ == "__main__":
    unittest.main()
