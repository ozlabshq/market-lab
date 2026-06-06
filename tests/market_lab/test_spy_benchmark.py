import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from market_lab.broker import OrderDecision, Portfolio, append_ledger
from market_lab.data import Bar, compute_spy_benchmark
from market_lab.report import render_report


def bars_from_prices(prices, opens=None, start_date=None):
    start = start_date or date(2024, 1, 1)
    opens = opens or prices
    return [
        Bar(start + timedelta(days=i), opens[i], max(opens[i], p) * 1.01, min(opens[i], p) * 0.99, p, 1_000_000)
        for i, p in enumerate(prices)
    ]


class ComputeSpyBenchmarkTests(unittest.TestCase):
    def test_benchmark_with_explicit_start_date(self):
        prices = [100.0, 102.0, 104.0, 103.0]
        bars = bars_from_prices(prices)
        # Patch fetch_prices to return these bars
        from unittest.mock import patch
        with patch("market_lab.data.fetch_prices", return_value=(bars, "synthetic")):
            result = compute_spy_benchmark(starting_cash=100_000.0, start_date=bars[0].date)
        self.assertEqual(result["start_price"], 100.0)
        self.assertEqual(result["current_price"], 103.0)
        self.assertEqual(result["benchmark_equity"], 103_000.0)
        bm_ret = result["benchmark_return"]
        self.assertIsInstance(bm_ret, float)
        self.assertTrue(abs(bm_ret - 0.03) < 1e-9)
        self.assertEqual(result["start_date_str"], bars[0].date.isoformat())
        self.assertEqual(result["data_source"], "synthetic")

    def test_benchmark_without_start_date_uses_first_bar(self):
        prices = [100.0, 102.0, 104.0]
        bars = bars_from_prices(prices)
        from unittest.mock import patch
        with patch("market_lab.data.fetch_prices", return_value=(bars, "cache")):
            result = compute_spy_benchmark(starting_cash=50_000.0)
        self.assertEqual(result["start_price"], 100.0)
        self.assertEqual(result["current_price"], 104.0)
        self.assertEqual(result["benchmark_equity"], 52_000.0)
        bm_ret = result["benchmark_return"]
        self.assertIsInstance(bm_ret, float)
        self.assertTrue(abs(bm_ret - 0.04) < 1e-9)

    def test_benchmark_with_no_bars_returns_defaults(self):
        from unittest.mock import patch
        with patch("market_lab.data.fetch_prices", return_value=([], "synthetic")):
            result = compute_spy_benchmark(starting_cash=100_000.0)
        self.assertEqual(result["benchmark_equity"], 100_000.0)
        self.assertEqual(result["benchmark_return"], 0.0)
        self.assertIsNone(result["start_price"])
        self.assertIsNone(result["current_price"])
        self.assertIsNone(result["start_date_str"])

    def test_benchmark_start_date_after_first_bar(self):
        prices = [100.0, 102.0, 104.0, 106.0]
        bars = bars_from_prices(prices)
        from unittest.mock import patch
        with patch("market_lab.data.fetch_prices", return_value=(bars, "yfinance")):
            result = compute_spy_benchmark(starting_cash=100_000.0, start_date=bars[2].date)
        self.assertEqual(result["start_price"], 104.0)
        self.assertEqual(result["current_price"], 106.0)
        bm_equity = result["benchmark_equity"]
        bm_ret = result["benchmark_return"]
        self.assertIsInstance(bm_equity, float)
        self.assertIsInstance(bm_ret, float)
        self.assertTrue(abs(bm_equity - 100_000.0 * 106.0 / 104.0) < 1e-9)
        self.assertTrue(abs(bm_ret - (106.0 / 104.0 - 1)) < 1e-9)


class RenderReportBenchmarkTests(unittest.TestCase):
    def test_render_report_includes_spy_benchmark_when_provided(self):
        from market_lab.broker import Portfolio
        spy_benchmark = {
            "benchmark_equity": 97_500.0,
            "benchmark_return": -0.025,
            "start_price": 754.0,
            "current_price": 737.55,
            "start_date_str": "2026-05-29",
            "data_source": "cache",
        }
        text = render_report(
            [], [], [], Portfolio(cash=100_000, positions={}), {}, {},
            spy_benchmark=spy_benchmark,
        )
        self.assertIn("SPY Buy/Hold Benchmark", text)
        self.assertIn("Benchmark start: 2026-05-29 (SPY @ $754.00)", text)
        self.assertIn("SPY current: $737.55", text)
        self.assertIn("Benchmark equity: $97,500.00 (-2.50%)", text)
        self.assertIn("Portfolio vs benchmark:", text)
        self.assertIn("Benchmark data source: cache", text)

    def test_render_report_shows_unavailable_when_benchmark_missing(self):
        from market_lab.broker import Portfolio
        text = render_report([], [], [], Portfolio(cash=100_000, positions={}), {}, {})
        self.assertIn("SPY Buy/Hold Benchmark", text)
        self.assertIn("SPY benchmark unavailable", text)

    def test_render_report_portfolio_vs_benchmark_positive(self):
        from market_lab.broker import Portfolio, Position
        spy_benchmark = {
            "benchmark_equity": 90_000.0,
            "benchmark_return": -0.10,
            "start_price": 100.0,
            "current_price": 90.0,
            "start_date_str": "2026-01-01",
            "data_source": "yfinance",
        }
        portfolio = Portfolio(cash=10_000, positions={"SPY": Position("SPY", 1000, 100.0)})
        prices = {"SPY": 100.0}
        text = render_report([], [], [], portfolio, prices, {}, spy_benchmark=spy_benchmark)
        # Portfolio equity = 10_000 + 1000*100 = 110_000
        # vs benchmark = 110_000 / 90_000 - 1 = +22.22%
        self.assertIn("Portfolio vs benchmark: +22.22%", text)


class DailyScriptBenchmarkTests(unittest.TestCase):
    def test_earliest_ledger_date_from_execution_date(self):
        from scripts.market_lab_daily import _earliest_ledger_date
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "mock_ledger.jsonl"
            d1 = OrderDecision(True, "BUY", "SPY", 10, 100.0, 100.0, "test", "2026-05-29T12:00:00+00:00", execution_date="2026-05-29")
            d2 = OrderDecision(True, "BUY", "QQQ", 10, 100.0, 100.0, "test", "2026-06-01T12:00:00+00:00", execution_date="2026-06-01")
            append_ledger(d1, ledger)
            append_ledger(d2, ledger)
            earliest = _earliest_ledger_date(ledger)
            self.assertEqual(earliest, date(2026, 5, 29))

    def test_earliest_ledger_date_from_signal_date_fallback(self):
        from scripts.market_lab_daily import _earliest_ledger_date
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "mock_ledger.jsonl"
            d = OrderDecision(True, "BUY", "SPY", 10, 100.0, 100.0, "test", "2026-05-30T12:00:00+00:00", signal_date="2026-05-28")
            append_ledger(d, ledger)
            earliest = _earliest_ledger_date(ledger)
            self.assertEqual(earliest, date(2026, 5, 28))

    def test_earliest_ledger_date_missing_file_returns_none(self):
        from scripts.market_lab_daily import _earliest_ledger_date
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / "nonexistent.jsonl"
            self.assertIsNone(_earliest_ledger_date(ledger))


class IndependentTrackBenchmarkTests(unittest.TestCase):
    def test_vt_trend_report_includes_benchmark_when_provided(self):
        from scripts.market_lab_vt_trend import _render_vt_trend_report
        from market_lab.broker import Portfolio
        from market_lab.signals import Signal
        sig = Signal("SPY", "BUY", 0.7, "test", 100.0, 50.0, 95.0, 100.0, 0.15, target_weight=1.0, evidence={"vol20": 0.15, "drawdown": 0.05, "drawdown_level": 0, "trend_up": True, "reentry_ok": True})
        spy_benchmark = {
            "benchmark_equity": 24_500.0,
            "benchmark_return": -0.02,
            "start_price": 100.0,
            "current_price": 98.0,
            "start_date_str": "2026-05-29",
            "data_source": "cache",
        }
        report = _render_vt_trend_report(
            Portfolio(cash=25_000), 100.0, sig, [], [], 1, 0, "cache",
            spy_benchmark=spy_benchmark,
        )
        self.assertIn("SPY benchmark equity", report)
        self.assertIn("$24,500.00", report)
        self.assertIn("-2.00%", report)

    def test_vt_trend_report_omits_benchmark_when_not_provided(self):
        from scripts.market_lab_vt_trend import _render_vt_trend_report
        from market_lab.broker import Portfolio
        from market_lab.signals import Signal
        sig = Signal("SPY", "BUY", 0.7, "test", 100.0, 50.0, 95.0, 100.0, 0.15, target_weight=1.0, evidence={"vol20": 0.15, "drawdown": 0.05, "drawdown_level": 0, "trend_up": True, "reentry_ok": True})
        report = _render_vt_trend_report(
            Portfolio(cash=25_000), 100.0, sig, [], [], 1, 0, "cache",
        )
        self.assertNotIn("SPY benchmark equity", report)

    def test_tsmom_report_includes_benchmark_when_provided(self):
        from scripts.market_lab_tsmom import _render_tsmom_report
        from market_lab.broker import Portfolio
        from market_lab.signals import Signal
        sig = Signal("SPY", "BUY", 0.7, "test", 100.0, 50.0, 95.0, 100.0, 0.15, target_weight=1.0, evidence={"vol20": 0.15, "raw_momentum": 0.05, "drawdown_from_peak": 0.02})
        spy_benchmark = {
            "benchmark_equity": 24_500.0,
            "benchmark_return": -0.02,
            "start_price": 100.0,
            "current_price": 98.0,
            "start_date_str": "2026-05-29",
            "data_source": "cache",
        }
        report = _render_tsmom_report(
            Portfolio(cash=25_000), 100.0, sig, [], [], 1, 0, "cache",
            spy_benchmark=spy_benchmark,
        )
        self.assertIn("SPY benchmark equity", report)
        self.assertIn("$24,500.00", report)
        self.assertIn("-2.00%", report)

    def test_tsmom_report_omits_benchmark_when_not_provided(self):
        from scripts.market_lab_tsmom import _render_tsmom_report
        from market_lab.broker import Portfolio
        from market_lab.signals import Signal
        sig = Signal("SPY", "BUY", 0.7, "test", 100.0, 50.0, 95.0, 100.0, 0.15, target_weight=1.0, evidence={"vol20": 0.15, "raw_momentum": 0.05, "drawdown_from_peak": 0.02})
        report = _render_tsmom_report(
            Portfolio(cash=25_000), 100.0, sig, [], [], 1, 0, "cache",
        )
        self.assertNotIn("SPY benchmark equity", report)


if __name__ == "__main__":
    unittest.main()
