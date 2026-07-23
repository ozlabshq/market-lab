from __future__ import annotations

import json
import socket
from pathlib import Path
import shutil

import pytest

from market_lab.agency_contracts import canonical_bytes, sha256_hex
from market_lab.agency_policy import snapshot_protected_state
from market_lab.valuation_runner import build_valuation_run, review_valuation_run, verify_valuation_run

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "market_lab" / "fixtures" / "valuation" / "mature_us_issuer_run"
CUTOFF = "2025-12-31T23:59:59Z"


def _refresh_manifest_for_artifact(output: Path, artifact_name: str) -> None:
    artifact_path = output / artifact_name
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for row in manifest["artifacts"]:
        if row["path"] == artifact_name:
            row["sha256"] = sha256_hex(artifact_path.read_bytes())
            row["bytes"] = artifact_path.stat().st_size
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_digest"}
    manifest["manifest_digest"] = sha256_hex(canonical_bytes(unsigned))
    manifest_path.write_bytes(canonical_bytes(manifest))


def test_frozen_pipeline_builds_sourced_scenarios_reverse_dcf_and_memo_without_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network forbidden")))
    data_root = tmp_path / "protected-data"
    before = snapshot_protected_state(data_root)
    output = tmp_path / "valuation"

    result = build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )

    assert result["status"] == "REVIEW_REQUIRED"
    assert snapshot_protected_state(data_root) == before
    assert result["artifact_count"] >= 10
    memo = json.loads((output / "memo.json").read_text(encoding="utf-8"))
    markdown = (output / "memo.md").read_text(encoding="utf-8")
    scenarios = memo["scenario_valuations"]
    assert [row["name"] for row in scenarios] == ["bear", "base", "bull"]
    values = [row["per_share_value_range"][0] for row in scenarios]
    assert float(values[0]) < float(values[1]) < float(values[2])
    assert memo["reverse_dcf"]["status"] == "calculated"
    assert memo["reverse_dcf"]["result_scope"] == "market_implied"
    assert memo["method_reconciliation"]["status"] == "material_method_disagreement"
    assert memo["catalysts"][0]["mechanism"]
    assert memo["invalidations"][0]["action_on_trigger"] == "mark_rejected"
    assert memo["provenance_summary"]["source_resolved"] == 5
    assert memo["uncertainty_summary"]["label"] == "HIGH"
    assert "target_price" not in json.dumps(memo)
    assert "RESEARCH ONLY" in markdown
    assert "## Bull / Base / Bear" in markdown
    assert "## Catalysts" in markdown
    for rendered_range in memo["render_trace"]["per_share_ranges"].values():
        assert rendered_range in markdown

    verification = verify_valuation_run(output, require_independent_review=False)
    assert verification["ok"] is True
    assert verification["checks"]["no_false_precision"] is True
    assert verification["checks"]["zero_execution_side_effects"] is True


def test_live_smoke_consumes_accepted_m2_and_ready_m3_without_raw_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("raw network forbidden")))
    output = tmp_path / "live-smoke"
    review_authority = tmp_path / "review-authority"
    built = build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="live",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    assert built["status"] == "REVIEW_REQUIRED"
    assert built["input_mode"] == "live"

    with pytest.raises(ValueError, match="reviewer must differ"):
        review_valuation_run(output, reviewer_id="valuation-builder", decision="APPROVE")
    approved = review_valuation_run(
        output,
        reviewer_id="independent-reviewer",
        decision="APPROVE",
        review_authority_dir=review_authority,
    )
    assert approved["status"] == "APPROVED_RESEARCH"
    verification = verify_valuation_run(
        output,
        require_independent_review=True,
        review_authority_dir=review_authority,
    )
    assert verification["ok"] is True
    assert verification["checks"]["independent_review"] is True
    assert list(review_authority.rglob("receipt.json"))


def test_live_mode_rejects_material_evidence_not_verified_by_accepted_m2_refs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    shutil.copytree(FIXTURE, run_dir)
    refs_path = run_dir / "input_refs.json"
    refs = json.loads(refs_path.read_text(encoding="utf-8"))
    refs["verified_evidence_ids"].remove("evidence-filing")
    refs_path.write_text(json.dumps(refs), encoding="utf-8")

    with pytest.raises(ValueError, match="live mode evidence is not accepted"):
        build_valuation_run(
            run_dir=run_dir,
            output_dir=tmp_path / "valuation",
            candidate_id="fixture-candidate",
            analysis_cutoff_utc=CUTOFF,
            mode="live",
            forecast_years=5,
            builder_id="valuation-builder",
        )


def test_frozen_build_is_idempotent_and_review_refuses_tampered_manifest(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    first = build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    second = build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    assert second["manifest_digest"] == first["manifest_digest"]

    memo_path = output / "memo.json"
    memo_path.write_bytes(memo_path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="manifest integrity check failed"):
        review_valuation_run(output, reviewer_id="independent-reviewer", decision="APPROVE")


def test_verify_requires_markdown_to_be_pure_render_of_canonical_memo(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    markdown_path = output / "memo.md"
    markdown_path.write_text(markdown_path.read_text(encoding="utf-8").replace("## Catalysts", "## Hidden Catalysts"), encoding="utf-8")

    _refresh_manifest_for_artifact(output, "memo.md")

    verification = verify_valuation_run(output, require_independent_review=False)
    assert verification["ok"] is False
    assert verification["checks"]["manifest"] is True
    assert verification["checks"]["memo_fidelity"] is False


def test_verify_rejects_cross_scenario_method_references_even_with_valid_hashes(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    memo_path = output / "memo.json"
    memo = json.loads(memo_path.read_text(encoding="utf-8"))
    bear, base = memo["scenario_valuations"][:2]
    bear["method_result_ids"], base["method_result_ids"] = base["method_result_ids"], bear["method_result_ids"]
    memo_path.write_bytes(canonical_bytes(memo))
    _refresh_manifest_for_artifact(output, "memo.json")

    verification = verify_valuation_run(output, require_independent_review=False)
    assert verification["ok"] is False
    assert verification["checks"]["scenario_identity"] is False


def test_review_cannot_approve_a_point_target_hidden_in_validly_hashed_memo(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    memo_path = output / "memo.json"
    memo = json.loads(memo_path.read_text(encoding="utf-8"))
    memo["price_target"] = "123.456789"
    memo_path.write_bytes(canonical_bytes(memo))
    _refresh_manifest_for_artifact(output, "memo.json")

    with pytest.raises(ValueError, match="valuation hard gates failed"):
        review_valuation_run(output, reviewer_id="independent-reviewer", decision="APPROVE")


def test_review_cannot_approve_renamed_point_target_semantics(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    memo_path = output / "memo.json"
    memo = json.loads(memo_path.read_text(encoding="utf-8"))
    memo["fair_value_estimate"] = "123.456789"
    memo_path.write_bytes(canonical_bytes(memo))
    _refresh_manifest_for_artifact(output, "memo.json")

    with pytest.raises(ValueError, match="valuation hard gates failed"):
        review_valuation_run(output, reviewer_id="independent-reviewer", decision="APPROVE")


def test_frozen_build_replays_to_identical_manifest_in_fresh_output_directories(tmp_path: Path) -> None:
    results = [
        build_valuation_run(
            run_dir=FIXTURE,
            output_dir=tmp_path / name,
            candidate_id="fixture-candidate",
            analysis_cutoff_utc=CUTOFF,
            mode="frozen",
            forecast_years=5,
            builder_id="valuation-builder",
        )
        for name in ("first", "second")
    ]

    assert results[0]["valuation_id"] == results[1]["valuation_id"]
    assert results[0]["manifest_digest"] == results[1]["manifest_digest"]
    assert (tmp_path / "first" / "request.json").read_bytes() == (tmp_path / "second" / "request.json").read_bytes()


def test_verify_revalidates_fact_provenance_instead_of_trusting_summary_counts(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    memo_path = output / "memo.json"
    memo = json.loads(memo_path.read_text(encoding="utf-8"))
    memo["reported_financial_summary"][0]["value"] = "999999999"
    memo["reported_financial_summary"][0]["evidence_id"] = "forged-evidence"
    memo_path.write_bytes(canonical_bytes(memo))
    _refresh_manifest_for_artifact(output, "memo.json")
    input_facts_path = output / "input_facts.json"
    input_facts = json.loads(input_facts_path.read_text(encoding="utf-8"))
    input_facts["facts"][0]["value"] = "999999999"
    input_facts["facts"][0]["evidence_id"] = "forged-evidence"
    input_facts_path.write_bytes(canonical_bytes(input_facts))
    _refresh_manifest_for_artifact(output, "input_facts.json")

    verification = verify_valuation_run(output, require_independent_review=False)
    assert verification["ok"] is False
    assert verification["checks"]["provenance"] is False


def test_forged_unmanifested_review_sidecars_cannot_satisfy_independent_review(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    request = json.loads((output / "request.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    review = {
        "schema_version": "mlab-valuation-review.v1",
        "valuation_id": request["valuation_id"],
        "builder_id": request["builder_id"],
        "reviewer_id": "forged-reviewer",
        "decision": "APPROVE",
        "reviewed_manifest_digest": manifest["manifest_digest"],
        "reviewed_at_utc": CUTOFF,
    }
    review["review_digest"] = sha256_hex(canonical_bytes(review))
    approval = {
        "schema_version": "mlab-valuation-approval.v1",
        "valuation_id": request["valuation_id"],
        "status": "APPROVED_RESEARCH",
        "review_digest": review["review_digest"],
        "research_only": True,
    }
    (output / "independent_review.json").write_bytes(canonical_bytes(review))
    (output / "approval.json").write_bytes(canonical_bytes(approval))

    verification = verify_valuation_run(output, require_independent_review=True)
    assert verification["ok"] is False
    assert verification["checks"]["independent_review"] is False


def test_forged_complete_review_sidecar_set_cannot_replace_external_authority_receipt(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    request = json.loads((output / "request.json").read_text(encoding="utf-8"))
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    review = {
        "schema_version": "mlab-valuation-review.v1",
        "valuation_id": request["valuation_id"],
        "builder_id": request["builder_id"],
        "reviewer_id": "forged-reviewer",
        "decision": "APPROVE",
        "reviewed_manifest_digest": manifest["manifest_digest"],
        "reviewed_at_utc": CUTOFF,
    }
    review["review_digest"] = sha256_hex(canonical_bytes(review))
    approval = {
        "schema_version": "mlab-valuation-approval.v1",
        "valuation_id": request["valuation_id"],
        "status": "APPROVED_RESEARCH",
        "review_digest": review["review_digest"],
        "research_only": True,
    }
    (output / "independent_review.json").write_bytes(canonical_bytes(review))
    (output / "approval.json").write_bytes(canonical_bytes(approval))
    review_manifest = {
        "schema_version": "mlab-valuation-review-manifest.v1",
        "valuation_id": request["valuation_id"],
        "base_manifest_digest": manifest["manifest_digest"],
        "artifacts": [
            {
                "path": name,
                "sha256": sha256_hex((output / name).read_bytes()),
                "bytes": (output / name).stat().st_size,
            }
            for name in ("approval.json", "independent_review.json")
        ],
    }
    review_manifest["review_manifest_digest"] = sha256_hex(canonical_bytes(review_manifest))
    (output / "review_manifest.json").write_bytes(canonical_bytes(review_manifest))

    verification = verify_valuation_run(
        output,
        require_independent_review=True,
        review_authority_dir=tmp_path / "empty-authority",
    )
    assert verification["ok"] is False
    assert verification["checks"]["independent_review"] is False


def test_review_authority_receipt_directory_cannot_overlap_builder_output(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    built = build_valuation_run(
        run_dir=FIXTURE,
        output_dir=staging,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    authority = tmp_path / "authority"
    overlap = authority / built["valuation_id"] / built["manifest_digest"]
    overlap.parent.mkdir(parents=True)
    shutil.copytree(staging, overlap)

    with pytest.raises(ValueError, match="outside valuation output"):
        review_valuation_run(
            overlap,
            reviewer_id="independent-reviewer",
            decision="APPROVE",
            review_authority_dir=authority,
        )
    assert not (overlap / "independent_review.json").exists()
    assert not (overlap / "approval.json").exists()


def test_verify_recomputes_method_sidecars_from_bound_sources(tmp_path: Path) -> None:
    output = tmp_path / "valuation"
    build_valuation_run(
        run_dir=FIXTURE,
        output_dir=output,
        candidate_id="fixture-candidate",
        analysis_cutoff_utc=CUTOFF,
        mode="frozen",
        forecast_years=5,
        builder_id="valuation-builder",
    )
    method_path = output / "method_dcf.json"
    method = json.loads(method_path.read_text(encoding="utf-8"))
    method["results"][0]["per_share_value_range"] = ["999", "999"]
    method_path.write_bytes(canonical_bytes(method))
    _refresh_manifest_for_artifact(output, "method_dcf.json")

    verification = verify_valuation_run(output, require_independent_review=False)
    assert verification["ok"] is False
    assert verification["checks"]["derived_outputs"] is False


def test_build_rejects_output_nested_inside_access_controlled_source_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "source-run"
    shutil.copytree(FIXTURE, run_dir)

    with pytest.raises(ValueError, match="must not overlap"):
        build_valuation_run(
            run_dir=run_dir,
            output_dir=run_dir / "valuation-output",
            candidate_id="fixture-candidate",
            analysis_cutoff_utc=CUTOFF,
            mode="frozen",
            forecast_years=5,
            builder_id="valuation-builder",
        )
