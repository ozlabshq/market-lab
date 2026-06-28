import unittest
from datetime import date, timedelta

from market_lab.broker import OrderCandidate, Portfolio, Position
from market_lab.data import Bar
from market_lab.signals import Signal
from scripts.market_lab_daily import _candidate_from_signal, _dedupe_candidates, _source_is_synthetic, _spy_guarded_tsmom


class DailyScriptSafetyTests(unittest.TestCase):
    def test_live_data_guard_treats_cached_synthetic_as_synthetic(self):
        self.assertTrue(_source_is_synthetic("synthetic"))
        self.assertTrue(_source_is_synthetic("cache_synthetic"))
        self.assertTrue(_source_is_synthetic("cache"))
        self.assertFalse(_source_is_synthetic("yfinance"))
        self.assertFalse(_source_is_synthetic("yfinance_info"))

    def test_dedupe_candidates_keeps_latest_unique_key(self):
        first = OrderCandidate("BUY", "SPY", 1, "ensemble", 0.5, "old", "2026-01-02", 100.0)
        second = OrderCandidate("BUY", "SPY", 2, "ensemble", 0.8, "new", "2026-01-02", 101.0)
        other = OrderCandidate("BUY", "QQQ", 1, "ensemble", 0.5, "other", "2026-01-02", 100.0)
        deduped = _dedupe_candidates([first, second, other])
        self.assertEqual(len(deduped), 2)
        spy = [c for c in deduped if c.symbol == "SPY"][0]
        self.assertEqual(spy.quantity, 2)
        self.assertEqual(spy.reason, "new")

    def test_sell_signal_queues_position_exit_candidate_without_shorting(self):
        portfolio = Portfolio(cash=95_000.0, positions={"AAPL": Position("AAPL", quantity=80, avg_price=150.0)})
        sig = Signal("AAPL", "SELL", 0.8, "SPY-relative exit", 200.0, None, None, None, None, "ensemble", 0.0)
        candidate = _candidate_from_signal(sig, "2026-01-02", portfolio_equity=111_000.0, portfolio=portfolio)
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.side, "SELL")
        self.assertEqual(candidate.symbol, "AAPL")
        self.assertEqual(candidate.quantity, 25)  # $5k risk chunk at $200, no shorting/new exposure

    def test_sell_signal_without_position_does_not_queue_candidate(self):
        sig = Signal("AAPL", "SELL", 0.8, "exit", 200.0, None, None, None, None, "ensemble", 0.0)
        candidate = _candidate_from_signal(sig, "2026-01-02", portfolio_equity=100_000.0, portfolio=Portfolio())
        self.assertIsNone(candidate)

    def test_spy_guarded_tsmom_backtest_helper_does_not_use_future_spy_bars(self):
        start = date(2024, 1, 1)
        def bars(prices):
            return [Bar(start + timedelta(days=i), p, p * 1.01, p * 0.99, p, 1_000_000) for i, p in enumerate(prices)]

        asset_history = bars([100 + i * 0.45 for i in range(160)])
        benign_spy = [100 + i * 0.10 for i in range(160)]
        future_spike_spy = benign_spy + [1000 + i * 50 for i in range(40)]

        baseline = _spy_guarded_tsmom(bars(benign_spy))("A", asset_history)
        mutated = _spy_guarded_tsmom(bars(future_spike_spy))("A", asset_history)

        self.assertEqual(baseline.action, mutated.action)
        self.assertEqual(baseline.evidence.get("spy_momentum"), mutated.evidence.get("spy_momentum"))


if __name__ == "__main__":
    unittest.main()
