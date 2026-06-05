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


class IndependentTrackReportWiringTests(unittest.TestCase):
    """Tests for read-only/report-only surfacing of independent tracks in the ensemble daily report."""

    def test_parse_report_table_extracts_metrics(self):
        from market_lab.report import _parse_report_table
        text = """
# Some Report
| Metric | Value |
|--------|-------|
| Cash | $25,000.00 |
| Position | 1 shares SPY @ $100.00 avg |
| Data source | yfinance |

## Decisions today
- No fills
"""
        metrics = _parse_report_table(text)
        self.assertEqual(metrics["Cash"], "$25,000.00")
        self.assertEqual(metrics["Position"], "1 shares SPY @ $100.00 avg")
        self.assertEqual(metrics["Data source"], "yfinance")

    def test_parse_report_table_returns_empty_for_no_table(self):
        from market_lab.report import _parse_report_table
        self.assertEqual(_parse_report_table("no table here"), {})

    def test_vt_trend_section_from_report_reads_latest_md(self):
        from market_lab.report import _vt_trend_section_from_report
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            report_dir = Path(d) / "vt_trend" / "reports"
            report_dir.mkdir(parents=True)
            latest = report_dir / "latest.md"
            latest.write_text(
                "| Metric | Value |\n|--------|-------|\n| Cash | $24,000.00 |\n| Trend regime | up |\n"
            )
            # Patch the module-level path directly (already imported at module load)
            from unittest.mock import patch
            import market_lab.report as report_module
            with patch.object(report_module, "VT_TREND_REPORT_DIR", report_dir):
                lines = _vt_trend_section_from_report()
            self.assertIn("## vt_trend Independent Mock Tracking", lines)
            self.assertTrue(any("$24,000.00" in line for line in lines))
            self.assertTrue(any("up" in line for line in lines))

    def test_tsmom_section_from_report_reads_latest_md(self):
        from market_lab.report import _tsmom_section_from_report
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            report_dir = Path(d) / "tsmom" / "reports"
            report_dir.mkdir(parents=True)
            latest = report_dir / "latest.md"
            latest.write_text(
                "| Metric | Value |\n|--------|-------|\n| Cash | $25,000.00 |\n| Raw momentum | 5.0% |\n"
            )
            from unittest.mock import patch
            import market_lab.report as report_module
            with patch.object(report_module, "TSMOM_REPORT_DIR", report_dir):
                lines = _tsmom_section_from_report()
            self.assertIn("## TSMOM Independent Mock Tracking", lines)
            self.assertTrue(any("$25,000.00" in line for line in lines))
            self.assertTrue(any("5.0%" in line for line in lines))

    def test_independent_tracks_summary_disabled_returns_empty(self):
        from market_lab.report import _independent_tracks_summary
        self.assertEqual(_independent_tracks_summary(include_independent_tracks=False), [])

    def test_independent_tracks_summary_missing_reports_returns_empty(self):
        from market_lab.report import _independent_tracks_summary
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            from unittest.mock import patch
            import market_lab.report as report_module
            vt_dir = Path(d) / "vt_trend" / "reports"
            tsmom_dir = Path(d) / "tsmom" / "reports"
            vt_dir.mkdir(parents=True)
            tsmom_dir.mkdir(parents=True)
            with patch.object(report_module, "VT_TREND_REPORT_DIR", vt_dir), patch.object(report_module, "TSMOM_REPORT_DIR", tsmom_dir):
                lines = _independent_tracks_summary()
            self.assertEqual(lines, [])

    def test_render_report_includes_tracks_by_default(self):
        from market_lab.report import render_report
        from market_lab.broker import Portfolio
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            from unittest.mock import patch
            import market_lab.report as report_module
            vt_dir = Path(d) / "vt_trend" / "reports"
            tsmom_dir = Path(d) / "tsmom" / "reports"
            vt_dir.mkdir(parents=True)
            tsmom_dir.mkdir(parents=True)
            (vt_dir / "latest.md").write_text(
                "| Metric | Value |\n|--------|-------|\n| Cash | $24,000.00 |\n"
            )
            with patch.object(report_module, "VT_TREND_REPORT_DIR", vt_dir), patch.object(report_module, "TSMOM_REPORT_DIR", tsmom_dir):
                text = render_report([], [], [], Portfolio(cash=100_000, positions={}), {}, {})
            self.assertIn("Independent Track Summaries", text)
            self.assertIn("vt_trend Independent Mock Tracking", text)
            self.assertIn("$24,000.00", text)
            self.assertIn("read-only snapshots", text)

    def test_render_report_can_exclude_tracks(self):
        from market_lab.report import render_report
        from market_lab.broker import Portfolio
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            from unittest.mock import patch
            import market_lab.report as report_module
            vt_dir = Path(d) / "vt_trend" / "reports"
            tsmom_dir = Path(d) / "tsmom" / "reports"
            vt_dir.mkdir(parents=True)
            tsmom_dir.mkdir(parents=True)
            (vt_dir / "latest.md").write_text(
                "| Metric | Value |\n|--------|-------|\n| Cash | $24,000.00 |\n"
            )
            with patch.object(report_module, "VT_TREND_REPORT_DIR", vt_dir), patch.object(report_module, "TSMOM_REPORT_DIR", tsmom_dir):
                text = render_report([], [], [], Portfolio(cash=100_000, positions={}), {}, {}, include_independent_tracks=False)
            self.assertNotIn("Independent Track Summaries", text)
            self.assertNotIn("vt_trend Independent Mock Tracking", text)

    def test_report_wiring_is_read_only_no_state_modification(self):
        """Surfacing tracks in the report must not modify any state files."""
        from market_lab.report import _vt_trend_section_from_report, _tsmom_section_from_report, _independent_tracks_summary
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            from unittest.mock import patch
            import market_lab.report as report_module
            vt_dir = Path(d) / "vt_trend" / "reports"
            tsmom_dir = Path(d) / "tsmom" / "reports"
            vt_dir.mkdir(parents=True)
            tsmom_dir.mkdir(parents=True)
            (vt_dir / "latest.md").write_text(
                "| Metric | Value |\n|--------|-------|\n| Cash | $24,000.00 |\n"
            )
            (tsmom_dir / "latest.md").write_text(
                "| Metric | Value |\n|--------|-------|\n| Cash | $25,000.00 |\n"
            )
            with patch.object(report_module, "VT_TREND_REPORT_DIR", vt_dir), patch.object(report_module, "TSMOM_REPORT_DIR", tsmom_dir):
                _ = _vt_trend_section_from_report()
                _ = _tsmom_section_from_report()
                _ = _independent_tracks_summary()
            # Verify no new files were created beyond latest.md
            self.assertEqual(sorted(p.name for p in vt_dir.iterdir()), ["latest.md"])
            self.assertEqual(sorted(p.name for p in tsmom_dir.iterdir()), ["latest.md"])


if __name__ == "__main__":
    unittest.main()
