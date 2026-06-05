import unittest
from pathlib import Path


class IndependentTrackRunnerTests(unittest.TestCase):
    def test_runner_importable_without_dependencies(self):
        # Ensure the runner script parses and basic structures exist
        import scripts.market_lab_independent_tracks as runner
        self.assertIn("vt_trend", runner.TRACKS)
        self.assertIn("tsmom", runner.TRACKS)

    def test_source_is_synthetic_rejects_cache(self):
        from scripts.market_lab_vt_trend import _source_is_synthetic as vt_synthetic
        from scripts.market_lab_tsmom import _source_is_synthetic as tsmom_synthetic
        self.assertTrue(vt_synthetic("cache"))
        self.assertTrue(vt_synthetic("synthetic"))
        self.assertTrue(vt_synthetic("cache_synthetic"))
        self.assertFalse(vt_synthetic("yfinance"))
        self.assertTrue(tsmom_synthetic("cache"))
        self.assertTrue(tsmom_synthetic("synthetic"))
        self.assertTrue(tsmom_synthetic("cache_synthetic"))
        self.assertFalse(tsmom_synthetic("yfinance"))

    def test_source_is_live_only_yfinance(self):
        from scripts.market_lab_vt_trend import _source_is_live as vt_live
        from scripts.market_lab_tsmom import _source_is_live as tsmom_live
        self.assertTrue(vt_live("yfinance"))
        self.assertFalse(vt_live("cache"))
        self.assertFalse(vt_live("synthetic"))
        self.assertTrue(tsmom_live("yfinance"))
        self.assertFalse(tsmom_live("cache"))
        self.assertFalse(tsmom_live("synthetic"))

    def test_runner_detects_non_live_source_in_output(self):
        # Simulate runner-level detection logic without external process
        stdout_cache = "Some report\n| Data source | cache |\n"
        stdout_synthetic = "Some report\n| Data source | synthetic |\n"
        stdout_live = "Some report\n| Data source | yfinance |\n"

        def _detects_non_live(output: str) -> bool:
            return "Data source | cache" in output or "Data source | synthetic" in output

        self.assertTrue(_detects_non_live(stdout_cache))
        self.assertTrue(_detects_non_live(stdout_synthetic))
        self.assertFalse(_detects_non_live(stdout_live))


if __name__ == "__main__":
    unittest.main()
