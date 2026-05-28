import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from market_lab.data import Bar
from market_lab.signals import (
    Signal,
    cross_sectional_momentum_ranks,
    generate_strategy_signals,
    generate_tsmom_signal,
)
from market_lab.backtest import run_signal_backtest
from market_lab.broker import OrderCandidate, candidate_to_order_at_open


def bars_from_prices(prices, opens=None):
    start = date(2024, 1, 1)
    opens = opens or prices
    return [Bar(start + timedelta(days=i), opens[i], max(opens[i], p) * 1.01, min(opens[i], p) * 0.99, p, 1_000_000) for i, p in enumerate(prices)]


class ResearchStrategyTests(unittest.TestCase):
    def test_tsmom_buys_persistent_positive_multi_horizon_momentum(self):
        prices = [100 + i * 0.28 for i in range(180)]
        sig = generate_tsmom_signal("TREND", bars_from_prices(prices))
        self.assertEqual(sig.action, "BUY")
        self.assertIn("TSMOM", sig.reason)
        self.assertGreater(sig.confidence, 0.30)

    def test_tsmom_sells_when_multi_horizon_momentum_breaks_negative(self):
        prices = [180 - i * 0.35 for i in range(180)]
        sig = generate_tsmom_signal("DOWN", bars_from_prices(prices))
        self.assertEqual(sig.action, "SELL")
        self.assertIn("negative", sig.reason.lower())

    def test_cross_sectional_momentum_uses_one_month_skip(self):
        steady_winner = [100 + i * 0.40 for i in range(180)]
        recent_spike_loser = [120 - i * 0.25 for i in range(160)] + [90 + i * 2.0 for i in range(20)]
        ranks = cross_sectional_momentum_ranks({
            "WIN": bars_from_prices(steady_winner),
            "SPIKE": bars_from_prices(recent_spike_loser),
        }, formation_days=126, skip_days=21)
        self.assertEqual(ranks[0].symbol, "WIN")
        self.assertGreater(ranks[0].score, ranks[1].score)

    def test_strategy_family_outputs_multiple_researched_models(self):
        prices = [100 + i * 0.18 for i in range(180)]
        signals = generate_strategy_signals("FAM", bars_from_prices(prices))
        names = {s.strategy for s in signals}
        self.assertIn("tsmom", names)
        self.assertIn("rsi_pullback", names)
        self.assertIn("baseline_scoring", names)

    def test_backtest_executes_signal_at_next_open_not_same_close(self):
        prices = [100] * 60 + [101 + i for i in range(80)]
        opens = list(prices)
        # Exaggerate next open after first BUY; if engine used same close this would not matter.
        opens[61] = 250

        def always_buy(symbol, bars):
            return Signal(symbol, "BUY", 1.0, "test", bars[-1].close, None, None, None, None, "test")

        result = run_signal_backtest("X", bars_from_prices(prices, opens=opens), always_buy, min_history=60)
        self.assertGreaterEqual(result.trades, 1)
        self.assertLess(result.final_equity, 10_000)  # expensive next-open fill hurts; proves lag is modeled

    def test_order_candidate_converts_to_order_using_next_open_only(self):
        candidate = OrderCandidate("BUY", "ABC", 5, "tsmom", 0.7, "next session", "2024-01-02", 101.0)
        with tempfile.TemporaryDirectory() as td:
            state_path = Path(td) / "state.json"
            ledger_path = Path(td) / "ledger.jsonl"
            decision = candidate_to_order_at_open(
                candidate,
                next_open=105.0,
                prices={"ABC": 105.0},
                portfolio_path=state_path,
                ledger_path=ledger_path,
            )
            self.assertEqual(decision.requested_price, 105.0)
            self.assertTrue(decision.accepted)
            self.assertTrue(state_path.exists())
            self.assertTrue(ledger_path.exists())


if __name__ == "__main__":
    unittest.main()
