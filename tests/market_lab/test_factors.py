import tempfile
import unittest
from datetime import date
from pathlib import Path

from market_lab.factors import FactorSnapshot, factor_score, load_cached_factors, save_factors, synthetic_factors
from market_lab.signals import Signal, apply_factor_overlay


class FactorTests(unittest.TestCase):
    def test_synthetic_factors_are_deterministic(self):
        first = synthetic_factors("NVDA", as_of=date(2026, 1, 1))
        second = synthetic_factors("NVDA", as_of=date(2026, 1, 1))
        self.assertEqual(first, second)
        self.assertGreater(first.ai_impact_score, 0.9)

    def test_factor_score_rewards_value_growth_and_ai_exposure(self):
        snapshot = FactorSnapshot("AI", date.today(), 16.0, 3.0, 0.22, 0.65, 0.06, 0.88, 0.30, "test")
        score, reasons = factor_score(snapshot)
        self.assertGreater(score, 0.15)
        self.assertTrue(any("AI" in reason for reason in reasons))

    def test_factor_overlay_nudges_confidence_and_records_evidence(self):
        signal = Signal("AI", "BUY", 0.50, "technical setup", 100.0, None, None, None, None, "ensemble")
        snapshot = FactorSnapshot("AI", date.today(), 16.0, 3.0, 0.22, 0.65, 0.06, 0.88, 0.30, "test")
        adjusted = apply_factor_overlay(signal, snapshot)
        self.assertGreater(adjusted.confidence, signal.confidence)
        self.assertIn("factor lens", adjusted.reason)
        self.assertEqual(adjusted.evidence["factor_source"], "test")

    def test_factor_cache_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            import market_lab.factors as factors
            original_dir = factors.FACTOR_DIR
            factors.FACTOR_DIR = Path(d)
            try:
                snapshot = synthetic_factors("TEST", as_of=date.today())
                save_factors(snapshot)
                loaded = load_cached_factors("TEST")
                self.assertEqual(loaded, snapshot)
            finally:
                factors.FACTOR_DIR = original_dir


if __name__ == "__main__":
    unittest.main()
