import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import json

from market_lab.config import VT_TREND_DIR, TSMOM_DIR


# Assumes tests run from repo root
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "market_lab_independent_tracks.py"
VT_SCRIPT = REPO_ROOT / "scripts" / "market_lab_vt_trend.py"
TSMOM_SCRIPT = REPO_ROOT / "scripts" / "market_lab_tsmom.py"


class IndependentTrackRunnerSafetyTests(unittest.TestCase):
    def test_runner_script_exists(self):
        self.assertTrue(RUNNER.exists(), f"Runner script not found: {RUNNER}")

    def test_runner_is_not_cron_wired(self):
        """The runner must not contain cron definitions or schedule modifications."""
        text = RUNNER.read_text()
        forbidden = ["crontab", "cronjob", "cron job", "@reboot", "@daily", "schedule_job", "sched.add_job", "APScheduler"]
        for phrase in forbidden:
            self.assertNotIn(phrase.lower(), text.lower(), f"Runner contains forbidden scheduling term: {phrase}")

    def test_runner_no_live_trading(self):
        """No live_trading_enabled flip, no broker secret access, no order placement beyond delegation."""
        text = RUNNER.read_text()
        self.assertNotIn("live_trading_enabled = True", text)
        self.assertNotIn("live_trading_enabled=True", text)
        self.assertNotIn("place_order", text)  # real broker
        self.assertNotIn("alpaca", text.lower())
        self.assertNotIn("broker_api", text.lower())

    def test_runner_makes_no_api_calls(self):
        """The runner delegates to track scripts; it should not call data APIs itself."""
        text = RUNNER.read_text()
        # Exclude docstrings/comments from check by looking for actual call patterns
        self.assertNotIn("import yfinance", text)
        self.assertNotIn("from yfinance", text)
        self.assertNotIn("yf.download", text)
        self.assertNotIn("requests.get(", text)
        self.assertNotIn("urllib.request.urlopen", text)

    def test_runner_help_prints(self):
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--help"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("research", result.stdout.lower())
        self.assertIn("mock", result.stdout.lower())
        self.assertIn("trend", result.stdout.lower())
        self.assertIn("tsmom", result.stdout.lower())

    def test_runner_single_track_select(self):
        """--track vt_trend should mention only that track in summary."""
        result = subprocess.run(
            [sys.executable, str(RUNNER), "--track", "vt_trend"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("vt_trend", result.stdout)

    def test_runner_both_tracks_default(self):
        """Default run mentions both tracks and does not crash."""
        result = subprocess.run(
            [sys.executable, str(RUNNER)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("vt_trend", result.stdout)
        self.assertIn("tsmom", result.stdout)
        self.assertIn("No live broker orders were placed", result.stdout)

    def test_runner_vt_trend_produced_report(self):
        """After running, vt_trend latest report exists or is updated."""
        result = subprocess.run(
            [sys.executable, str(RUNNER)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        latest = VT_TREND_DIR / "reports" / "latest.md"
        self.assertTrue(latest.exists() or (VT_TREND_DIR / "reports").exists(),
                        "Expected vt_trend report directory to exist after run")
        if latest.exists():
            content = latest.read_text()
            self.assertIn("vt_trend", content)
            self.assertIn("Research", content)

    def test_runner_tsmom_produced_report(self):
        """After running, TSMOM latest report exists or is updated."""
        result = subprocess.run(
            [sys.executable, str(RUNNER)],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        latest = TSMOM_DIR / "reports" / "latest.md"
        self.assertTrue(latest.exists() or (TSMOM_DIR / "reports").exists(),
                        "Expected tsmom report directory to exist after run")
        if latest.exists():
            content = latest.read_text()
            self.assertIn("TSMOM", content)
            self.assertIn("Research", content)

    def test_runner_no_main_portfolio_mutation(self):
        """Runner should not touch the main mock portfolio state file."""
        # We rely on the runner not referencing STATE_PATH explicitly
        text = RUNNER.read_text()
        self.assertNotIn("mock_portfolio_state.json", text)

    def test_vt_trend_script_self_safety(self):
        """vt_trend script must not enable live trading."""
        text = VT_SCRIPT.read_text()
        self.assertNotIn("live_trading_enabled = True", text)
        self.assertNotIn("live_trading_enabled=True", text)

    def test_tsmom_script_self_safety(self):
        """TSMOM script must not enable live trading."""
        text = TSMOM_SCRIPT.read_text()
        self.assertNotIn("live_trading_enabled = True", text)
        self.assertNotIn("live_trading_enabled=True", text)


if __name__ == "__main__":
    unittest.main()
