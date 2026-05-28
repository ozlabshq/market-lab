import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from market_lab.backtest import moving_average_cross_backtest
from market_lab.broker import load_order_candidates, load_portfolio
from market_lab.data import Bar, fetch_prices, load_cached_prices, price_path
from market_lab.report import render_report
from market_lab.signals import generate_ensemble_signal, generate_rsi_pullback_signal


def bars_from_prices(prices):
    start = date(2024, 1, 1)
    return [Bar(start + timedelta(days=i), p, p * 1.01, p * 0.99, p, 1_000_000) for i, p in enumerate(prices)]


class MarketLabHardeningTests(unittest.TestCase):
    def test_ma_cross_does_not_count_zero_cash_trade(self):
        prices = [100] * 60 + [100 + i for i in range(80)]
        result = moving_average_cross_backtest("X", bars_from_prices(prices), initial_cash=0.0)
        self.assertEqual(result.trades, 0)
        self.assertEqual(result.final_equity, 0.0)

    def test_corrupt_portfolio_state_loads_default_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            path.write_text("{not json")
            portfolio = load_portfolio(path)
            self.assertGreater(portfolio.cash, 0)
            self.assertEqual(portfolio.positions, {})

    def test_corrupt_pending_candidates_loads_empty_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pending.jsonl"
            path.write_text("{bad json}\n")
            self.assertEqual(load_order_candidates(path), [])

    def test_rsi_pullback_buys_oversold_pullback_inside_uptrend(self):
        prices = [100 + i * 0.5 for i in range(150)] + [174, 171, 168, 165, 162, 159]
        sig = generate_rsi_pullback_signal("PULL", bars_from_prices(prices))
        self.assertEqual(sig.action, "BUY")
        self.assertEqual(sig.strategy, "rsi_pullback")

    def test_ensemble_and_report_render_strategy_sections(self):
        prices = [100 + i * 0.3 for i in range(180)]
        bars = bars_from_prices(prices)
        sig = generate_ensemble_signal("ENS", bars)
        text = render_report([sig], [], [], load_portfolio(Path("/tmp/nonexistent-market-lab-state.json")), {"ENS": bars[-1].close}, {"ENS": "test"}, [], {"ENS": []}, [])
        self.assertIn("Strategy family diagnostics", text)
        self.assertIn("Research basis", text)
        self.assertIn("next-session", text.lower())

    def test_synthetic_prices_do_not_poison_real_price_cache(self):
        with tempfile.TemporaryDirectory() as d:
            price_dir = Path(d) / "prices"
            synthetic_dir = Path(d) / "synthetic_prices"
            with patch("market_lab.data.PRICE_DIR", price_dir), patch("market_lab.data.SYNTHETIC_PRICE_DIR", synthetic_dir):
                bars, source = fetch_prices("FAKE", days=45, prefer_network=False)
                self.assertEqual(source, "synthetic")
                self.assertGreaterEqual(len(bars), 45)
                self.assertFalse(price_path("FAKE").exists())
                cached = load_cached_prices("FAKE")
                self.assertEqual(cached, [])
                self.assertTrue((synthetic_dir / "FAKE.csv").exists())

    def test_market_lab_data_dir_env_overrides_all_default_paths_before_import(self):
        with tempfile.TemporaryDirectory() as d:
            code = """
import json
from market_lab import config
print(json.dumps({
    'data': str(config.DATA_DIR),
    'prices': str(config.PRICE_DIR),
    'reports': str(config.REPORT_DIR),
    'factors': str(config.FACTOR_DIR),
    'ledger': str(config.LEDGER_PATH),
    'pending': str(config.PENDING_CANDIDATES_PATH),
    'state': str(config.STATE_PATH),
}))
"""
            env = dict(os.environ, MARKET_LAB_DATA_DIR=d)
            result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2], env=env, text=True, capture_output=True, check=True)
            paths = __import__("json").loads(result.stdout)
            expected = str(Path(d).resolve())
            self.assertEqual(paths["data"], expected)
            self.assertTrue(paths["prices"].startswith(expected))
            self.assertTrue(paths["reports"].startswith(expected))
            self.assertTrue(paths["factors"].startswith(expected))
            self.assertTrue(paths["ledger"].startswith(expected))
            self.assertTrue(paths["pending"].startswith(expected))
            self.assertTrue(paths["state"].startswith(expected))


if __name__ == "__main__":
    unittest.main()
