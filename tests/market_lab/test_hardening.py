import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from market_lab.backtest import moving_average_cross_backtest
from market_lab.broker import load_order_candidates, load_portfolio
from market_lab.data import Bar
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


if __name__ == "__main__":
    unittest.main()
