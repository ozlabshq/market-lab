import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from market_lab import mlab_ingest
from market_lab.data import Bar

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "source_thesis" / "pequity_capture"


class MlabIngestTests(unittest.TestCase):
    def _mock_prices(self, symbol: str, days: int = 260, prefer_network: bool = False):
        bars = [
            Bar(date=date(2026, 1, 2), open=100.0, high=100.0, low=100.0, close=100.0, volume=1000),
            Bar(date=date(2026, 1, 3), open=102.0, high=102.0, low=102.0, close=102.0, volume=1000),
        ]
        return bars, "synthetic"

    def _run_ingest(self, capture_dir: Path, root: Path) -> Path:
        with patch("market_lab.source_thesis.fetch_prices", self._mock_prices), patch(
            "market_lab.source_thesis._safe_factor", return_value=(None, "factor_unavailable")
        ):
            return mlab_ingest.run_ingest_from_capture(capture_dir, run_root=root, owner="test-runner", network=False, days=40)

    def _status(self, run_dir: Path) -> dict:
        return mlab_ingest.read_status(run_dir)

    def _fixture_copy(self, root: Path) -> Path:
        capture_dir = Path(root) / "capture"
        shutil.copytree(FIXTURE_DIR, capture_dir)
        return capture_dir

    def test_lifecycle_advancement_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "runs"
            capture_dir = self._fixture_copy(Path(td))
            run_dir = self._run_ingest(capture_dir, root)
            status = self._status(run_dir)
            self.assertEqual(status["stage"], "claims_extracted")
            self.assertEqual(status["verdict"], "IN_PROGRESS")
            self.assertTrue(len(mlab_ingest.read_claims(run_dir)["claims"]) > 0)

            mlab_ingest.write_research_plan(
                run_dir,
                content="# Plan\n- verify three critical claims\n- map media context",
                owner="qa",
            )
            status = self._status(run_dir)
            self.assertEqual(status["stage"], "research_planned")

            mlab_ingest.set_next_actions(
                run_dir,
                owner="qa",
                actions=[{"owner": "qa", "action": "collect follow up evidence"}],
            )
            review_path = run_dir / "independent_review.md"
            review_path.write_text("Reviewer: qa\nDecision: PENDING\n", encoding="utf-8")
            status = self._status(run_dir)
            self.assertEqual(status["stage"], "research_active")

            plan_before = (run_dir / "research_plan.md").read_text(encoding="utf-8")
            review_before = (run_dir / "independent_review.md").read_text(encoding="utf-8")
            actions_before = (run_dir / "next_actions.json").read_text(encoding="utf-8")

            # Resume should not reinitialize or lose state.
            resumed = self._run_ingest(capture_dir, root)
            resumed_status = self._status(resumed)
            self.assertEqual(run_dir, resumed)
            self.assertEqual(resumed_status["stage"], "research_active")
            self.assertEqual(plan_before, (run_dir / "research_plan.md").read_text(encoding="utf-8"))
            self.assertEqual(review_before, (run_dir / "independent_review.md").read_text(encoding="utf-8"))
            self.assertEqual(actions_before, (run_dir / "next_actions.json").read_text(encoding="utf-8"))

    def test_lifecycle_crash_resume(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "runs"
            capture_dir = self._fixture_copy(Path(td))
            run_dir = self._run_ingest(capture_dir, root)
            status_path = run_dir / "status.json"
            claims_path = run_dir / "claims.json"

            # Simulate a partial/corrupt run state where extraction had not been recorded.
            status = json.loads(status_path.read_text())
            status["stage"] = "created"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            if claims_path.exists():
                claims_path.unlink()

            recovered = self._run_ingest(capture_dir, root)
            recovered_status = self._status(recovered)
            self.assertEqual(recovered_status["stage"], "claims_extracted")
            self.assertGreater(len(mlab_ingest.read_claims(recovered)["claims"]), 0)

    def test_resume_uses_run_snapshot_source_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "runs"
            capture_dir = self._fixture_copy(Path(td))
            run_dir = self._run_ingest(capture_dir, root)
            baseline_claims = mlab_ingest.read_claims(run_dir)["claims"]

            status_path = run_dir / "status.json"
            status = json.loads(status_path.read_text(encoding="utf-8"))
            status["stage"] = "created"
            status_path.write_text(json.dumps(status), encoding="utf-8")
            (run_dir / "claims.json").unlink()

            (capture_dir / "source.json").write_text("{invalid json", encoding="utf-8")

            recovered = self._run_ingest(capture_dir, root)
            recovered_status = self._status(recovered)
            recovered_claims = mlab_ingest.read_claims(recovered)["claims"]

            self.assertEqual(recovered_status["stage"], "claims_extracted")
            self.assertGreater(len(recovered_claims), 0)
            self.assertTrue((run_dir / "analysis.json").exists())
            self.assertTrue((run_dir / "analysis.md").exists())
            self.assertEqual(recovered_claims[0]["claim_id"], baseline_claims[0]["claim_id"])
            self.assertTrue((run_dir / baseline_claims[0]["source_artifact"]).exists())

    def test_append_only_audit_log(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "runs"
            run_dir = self._run_ingest(FIXTURE_DIR, root)
            audit_path = run_dir / "audit_log.jsonl"
            before_lines = audit_path.read_text().splitlines()

            mlab_ingest.write_research_plan(run_dir, content="# Plan\n- evidence review", owner="qa")
            mlab_ingest.set_claim_disposition(
                run_dir,
                claim_id=mlab_ingest.read_claims(run_dir)["claims"][0]["claim_id"],
                disposition="UNRESOLVED",
                rationale="not yet evidenced",
                blocker="source gap",
                actor="qa",
            )

            after_lines = audit_path.read_text().splitlines()
            self.assertGreater(len(after_lines), len(before_lines))
            self.assertTrue(after_lines[: len(before_lines)] == before_lines)

    def test_finalize_blocked_on_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "runs"
            run_dir = self._run_ingest(FIXTURE_DIR, root)
            claims = mlab_ingest.read_claims(run_dir)["claims"]

            for media in self._status(run_dir).get("media_blockers", []):
                mlab_ingest.set_media_interpretation(
                    run_dir,
                    media_id=media["media_id"],
                    status_text="interpreted",
                    actor="qa",
                    blocker="",
                )

            mlab_ingest.write_research_plan(run_dir, content="# Plan\n- resolve claims", owner="qa")
            mlab_ingest.set_next_actions(
                run_dir,
                owner="qa",
                actions=[{"owner": "qa", "action": "complete adjudication"}],
            )

            target = claims[0]["claim_id"]
            mlab_ingest.set_claim_disposition(
                run_dir,
                claim_id=target,
                disposition="VERIFIED",
                rationale="market check confirms",
                actor="qa",
            )
            for stale in claims[1:]:
                mlab_ingest.set_claim_disposition(
                    run_dir,
                    claim_id=stale["claim_id"],
                    disposition="UNRESOLVED",
                    rationale="follow-up needed",
                    blocker="needs independent adjudication",
                    actor="qa",
                )

            mlab_ingest.add_evidence(
                run_dir,
                claim_id=target,
                result="supports",
                source="internal note",
                note="supports",
                actor="qa",
            )
            mlab_ingest.add_evidence(
                run_dir,
                claim_id=target,
                result="refutes",
                source="independent note",
                note="contradiction",
                actor="qa",
            )
            mlab_ingest.write_independent_review(run_dir, reviewer="qa", decision="APPROVE", notes="ready")

            with self.assertRaises(RuntimeError) as exc:
                mlab_ingest.finalize_run(run_dir, actor="qa")
            self.assertIn("contradictory", str(exc.exception).lower())

    def test_premature_finalization_guard(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "runs"
            run_dir = self._run_ingest(FIXTURE_DIR, root)
            with self.assertRaises(RuntimeError) as exc:
                mlab_ingest.finalize_run(run_dir, actor="qa")
            self.assertIn("reviewed", str(exc.exception).lower())


if __name__ == "__main__":
    unittest.main()
