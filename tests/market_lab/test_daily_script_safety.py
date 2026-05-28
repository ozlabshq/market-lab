import unittest

from market_lab.broker import OrderCandidate
from scripts.market_lab_daily import _dedupe_candidates, _source_is_synthetic


class DailyScriptSafetyTests(unittest.TestCase):
    def test_live_data_guard_treats_cached_synthetic_as_synthetic(self):
        self.assertTrue(_source_is_synthetic("synthetic"))
        self.assertTrue(_source_is_synthetic("cache_synthetic"))
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


if __name__ == "__main__":
    unittest.main()
