import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from market_lab.data import Bar
from market_lab import source_thesis
from market_lab import source_thesis_cli


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "source_thesis" / "pequity_capture"


class SourceThesisTests(unittest.TestCase):
    def _mock_prices(self, symbol: str, days: int = 260, prefer_network: bool = False):
        bars = [
            Bar(date=date(2026, 1, 2), open=100.0, high=100.0, low=100.0, close=100.0, volume=1000),
            Bar(date=date(2026, 1, 3), open=102.0, high=102.0, low=102.0, close=102.0, volume=1000),
        ]
        return bars, "synthetic"

    def _same_day_prices(self, symbol: str, days: int = 260, prefer_network: bool = False):
        bars = [
            Bar(date=date(2026, 7, 13), open=100.0, high=100.0, low=100.0, close=100.0, volume=1000),
        ]
        return bars, "synthetic"

    def _run_from_capture(self, capture_dir: Path) -> source_thesis.ThesisRun:
        with patch("market_lab.source_thesis.fetch_prices", self._mock_prices), patch(
            "market_lab.source_thesis._safe_factor", return_value=(None, "factor_unavailable")
        ):
            return source_thesis.extract_source_thesis_from_capture_dir(str(capture_dir), prefer_network=False, days=40)

    def test_extracts_key_claims_with_provenance(self):
        run = self._run_from_capture(FIXTURE_DIR)
        claims = [claim.text for claim in run.thesis.claims]
        claim_blob = "\n".join(claims)

        self.assertIn("~300x growth in the robot bearings market", claim_blob)
        self.assertIn("OpenAI listed precision bearings as 1 of 6 critical components", claim_blob)
        self.assertIn("Small quadcopter drone: Requires 8–12 bearings.", claim_blob)
        self.assertIn("Humanoid robot: Requires 70 or more bearings.", claim_blob)
        self.assertIn("top 6 global manufacturers control over 50%", claim_blob)
        self.assertIn("Roughly 40% of the overall market goes to industrial equipment OEMs, 30% to automotive, and 30 to distribution channels", claim_blob)

        for claim in run.thesis.claims:
            self.assertTrue(claim.source_url)
            self.assertTrue(claim.source_artifact)
            self.assertTrue(claim.captured_at)
            self.assertTrue(claim.author)

        first_claim = run.thesis.claims[0]
        self.assertIn("/tests/market_lab/fixtures/source_thesis/pequity_capture", first_claim.source_artifact)

    def test_preserves_media_provenance_and_dimensions(self):
        run = self._run_from_capture(FIXTURE_DIR)
        media = run.thesis.media_assets
        self.assertEqual(len(media), 3)
        dimensions = {asset.media_id: (asset.width, asset.height) for asset in media}
        self.assertIn((894, 526), dimensions.values())
        self.assertIn((770, 644), dimensions.values())
        self.assertIn((1512, 822), dimensions.values())

        for asset in media:
            self.assertTrue(asset.local_path)
            self.assertTrue(asset.interpretation_status)
            self.assertTrue(asset.source_artifact)

    def test_no_source_derived_candidate_inference(self):
        run = self._run_from_capture(FIXTURE_DIR)
        self.assertEqual(run.thesis.candidate_tickers, [])
        self.assertFalse(any(member.role == "candidate" for member in run.basket))
        self.assertTrue(any(member.role == "control" for member in run.evaluations))
        self.assertTrue(any("No explicit source candidate tickers found" in warning for warning in run.warnings))

    def test_market_window_blocks_same_day_evidence(self):
        with patch("market_lab.source_thesis.fetch_prices", self._same_day_prices), patch(
            "market_lab.source_thesis._safe_factor", return_value=(None, "factor_unavailable")
        ):
            run = source_thesis.extract_source_thesis_from_capture_dir(str(FIXTURE_DIR), prefer_network=False, days=40)

        self.assertTrue(any("No post-source market window" in warning for warning in run.warnings))

    def test_contradiction_guard_for_claim_fidelity(self):
        with tempfile.TemporaryDirectory() as td:
            mutated = Path(td) / "capture"
            shutil.copytree(FIXTURE_DIR, mutated)
            source_path = mutated / "source.json"
            payload = json.loads(source_path.read_text())
            text = payload["tweet"]["text"]
            replacements = {
                "~300x growth": "30x growth",
                "OpenAI listed precision bearings as 1 of 6 critical components": "OpenAI listed precision bearings as 2 of 6 critical components",
                "control over 50%": "control over 40%",
                "Roughly 40% of the overall market goes to industrial equipment OEMs, 30% to automotive, and 30 to distribution channels": "Roughly 30% of the overall market goes to industrial equipment OEMs, 30% to automotive, and 40 to distribution channels",
                "Small quadcopter drone: Requires 8–12 bearings.": "Small quadcopter drone: Requires 1 bearing.",
                "Humanoid robot: Requires 70 or more bearings.": "Humanoid robot: Requires 7 or more bearings.",
            }
            for src, dst in replacements.items():
                text = text.replace(src, dst)
            payload["tweet"]["text"] = text
            source_path.write_text(json.dumps(payload))

            run = self._run_from_capture(mutated)
            claim_blob = "\n".join(claim.text for claim in run.thesis.claims)

            self.assertNotIn("~300x growth", claim_blob)
            self.assertIn("30x growth", claim_blob)
            self.assertNotIn("1 of 6 critical components", claim_blob)
            self.assertIn("2 of 6 critical components", claim_blob)
            self.assertNotIn("control over 50%", claim_blob)
            self.assertIn("control over 40%", claim_blob)
            self.assertNotIn("Roughly 40% of the overall market goes to industrial equipment OEMs, 30% to automotive, and 30 to distribution channels", claim_blob)
            self.assertIn("Roughly 30% of the overall market goes to industrial equipment OEMs, 30% to automotive, and 40 to distribution channels", claim_blob)
            self.assertNotIn("Small quadcopter drone: Requires 8–12 bearings.", claim_blob)
            self.assertIn("Small quadcopter drone: Requires 1 bearing.", claim_blob)
            self.assertNotIn("Humanoid robot: Requires 70 or more bearings.", claim_blob)
            self.assertIn("Humanoid robot: Requires 7 or more bearings.", claim_blob)

    def test_cli_writes_json_markdown_and_run_log(self):
        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td)
            json_out = out_root / "thesis_run_log.json"

            with patch.object(source_thesis, "SOURCE_THESIS_DIR", out_root / "runs"), \
                patch.object(
                    source_thesis,
                    "SOURCE_THESIS_REPORT_DIR",
                    out_root / "runs" / "reports",
                ), \
                patch.object(
                    source_thesis,
                    "ensure_dirs",
                    lambda: (
                        (out_root / "runs").mkdir(parents=True, exist_ok=True),
                        (out_root / "runs" / "reports").mkdir(parents=True, exist_ok=True),
                    ),
                ), \
                patch("market_lab.source_thesis.fetch_prices", self._mock_prices), \
                patch("market_lab.source_thesis._safe_factor", return_value=(None, "factor_unavailable")), \
                patch(
                    "sys.argv",
                    [
                        "source_thesis_cli",
                        str(FIXTURE_DIR),
                        "--run-log",
                        str(json_out),
                        "--slug",
                        "pequity-fixture",
                    ],
                ):
                self.assertEqual(source_thesis_cli.main(), 0)

            run_log = json.loads(json_out.read_text())
            self.assertIn("outputs", run_log)
            output_json = Path(run_log["outputs"]["json"])
            output_markdown = Path(run_log["outputs"]["markdown"])
            output_latest = Path(run_log["outputs"]["latest"])

            self.assertTrue(output_json.exists())
            self.assertTrue(output_markdown.exists())
            self.assertTrue(output_latest.exists())

            artifact = json.loads(output_json.read_text())
            self.assertIn("thesis", artifact)
            self.assertGreaterEqual(len(artifact["thesis"]["claims"]), 1)
            self.assertEqual(run_log["outputs"]["run_log"], str(json_out))


if __name__ == "__main__":
    unittest.main()
