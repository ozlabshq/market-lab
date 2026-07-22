import unittest
from datetime import date, timedelta

from market_lab.broker import OrderCandidate
from market_lab.data import Bar
from market_lab.signals import Signal
from market_lab.verifier import SpyBeatResult, apply_verifier_guard, verify_spy_beat


def _bars(prices, opens=None, start=None):
    start = start or date(2024, 1, 1)
    opens = opens or prices
    return [
        Bar(start + timedelta(days=i), opens[i], max(opens[i], prices[i]) * 1.01, min(opens[i], prices[i]) * 0.99, prices[i], 1_000_000)
        for i in range(len(prices))
    ]


def _always_buy(symbol, bars):
    return Signal(symbol, "BUY", 1.0, "always", bars[-1].close, None, None, None, None, "always_buy")


def _always_hold(symbol, bars):
    return Signal(symbol, "HOLD", 0.0, "never", bars[-1].close, None, None, None, None, "always_hold")


class SpyBeatVerifierTests(unittest.TestCase):
    def test_passes_when_strategy_outperforms_spy_oos(self):
        # 150 train flat, 50 OOS: symbol up 50%, SPY up ~17%
        train = [100.0] * 150
        oos_symbol = [100 + i * 1.0 for i in range(50)]
        oos_spy = [100 + i * 0.33 for i in range(50)]
        bars = _bars(train + oos_symbol)
        spy = _bars(train + oos_spy)
        result = verify_spy_beat("FOO", bars, _always_buy, spy_bars=spy, train_pct=0.70, min_oos_bars=5, min_total_bars=20)
        self.assertTrue(result.passed)
        self.assertGreater(result.strategy_oos_return, result.spy_oos_return)
        self.assertGreater(result.oos_bars, 0)

    def test_fails_when_strategy_underperforms_spy_oos(self):
        # 150 train flat, 50 OOS: symbol flat, SPY up ~17%
        train = [100.0] * 150
        oos_symbol = [100.0] * 50
        oos_spy = [100 + i * 0.33 for i in range(50)]
        bars = _bars(train + oos_symbol)
        spy = _bars(train + oos_spy)
        result = verify_spy_beat("FOO", bars, _always_buy, spy_bars=spy, train_pct=0.70, min_oos_bars=5, min_total_bars=20)
        self.assertFalse(result.passed)
        self.assertLess(result.strategy_oos_return, result.spy_oos_return)

    def test_no_lookahead_train_split_is_fixed(self):
        # Same inputs should yield identical train_n and returns
        train = [100.0] * 100
        oos_symbol = [150.0] * 100
        oos_spy = [110.0] * 100
        bars = _bars(train + oos_symbol)
        spy = _bars(train + oos_spy)
        result1 = verify_spy_beat("FOO", bars, _always_buy, spy_bars=spy, train_pct=0.50, min_oos_bars=5, min_total_bars=20)
        result2 = verify_spy_beat("FOO", bars, _always_buy, spy_bars=spy, train_pct=0.50, min_oos_bars=5, min_total_bars=20)
        self.assertEqual(result1.train_bars, result2.train_bars)
        self.assertEqual(result1.strategy_oos_return, result2.strategy_oos_return)
        self.assertEqual(result1.spy_oos_return, result2.spy_oos_return)

    def test_insufficient_bars_defaults_to_pass(self):
        bars = _bars([100.0, 101.0, 102.0])
        result = verify_spy_beat("FOO", bars, _always_buy, spy_bars=None, min_total_bars=10)
        self.assertTrue(result.passed)
        self.assertIn("insufficient", result.reason)

    def test_sell_candidates_allowed_without_verifier(self):
        sell = OrderCandidate("SELL", "FOO", 10, "ensemble", 1.0, "sell", "2024-01-01", 100.0)
        allowed, result = apply_verifier_guard(sell, [], None, spy_bars=None)
        self.assertTrue(allowed)
        self.assertIn("allowed without verifier", result.reason)

    def test_daily_queue_rejects_buy_and_allows_sell(self):
        # Simulate the verifier gate used in the daily loop
        train = [100.0] * 150
        oos_symbol = [100.0] * 50
        oos_spy = [100 + i * 0.33 for i in range(50)]
        bars = _bars(train + oos_symbol)
        spy = _bars(train + oos_spy)

        buy_candidate = OrderCandidate("BUY", "FOO", 10, "ensemble", 1.0, "buy", "2024-01-01", 100.0)
        sell_candidate = OrderCandidate("SELL", "FOO", 10, "ensemble", 1.0, "sell", "2024-01-01", 100.0)

        allowed_buy, v_buy = apply_verifier_guard(buy_candidate, bars, _always_buy, spy_bars=spy)
        allowed_sell, v_sell = apply_verifier_guard(sell_candidate, bars, _always_buy, spy_bars=spy)

        self.assertFalse(allowed_buy)
        self.assertTrue(v_buy.strategy_oos_return < v_buy.spy_oos_return)
        self.assertTrue(allowed_sell)
        self.assertIn("allowed without verifier", v_sell.reason)

    def test_verifier_passes_when_spy_returns_negative_and_strategy_flat(self):
        # symbol flat (0%) vs SPY down (~5%) should pass
        train = [100.0] * 150
        oos_symbol = [100.0] * 50
        oos_spy = [100.0 - i * 0.10 for i in range(50)]
        bars = _bars(train + oos_symbol)
        spy = _bars(train + oos_spy)
        result = verify_spy_beat("FOO", bars, _always_buy, spy_bars=spy, train_pct=0.70, min_oos_bars=5, min_total_bars=20)
        self.assertTrue(result.passed)
        self.assertGreater(result.strategy_oos_return, result.spy_oos_return)


if __name__ == "__main__":
    unittest.main()
