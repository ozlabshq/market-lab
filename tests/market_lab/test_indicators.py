import math
import unittest
from market_lab.indicators import sma, ema, rsi, max_drawdown, returns, rolling_volatility

class IndicatorTests(unittest.TestCase):
    def test_sma_returns_none_until_window_ready(self):
        self.assertEqual(sma([1,2,3,4], 3), [None, None, 2, 3])
    def test_ema_length_and_warmup(self):
        out=ema([1,2,3,4,5], 3)
        self.assertEqual(len(out), 5)
        self.assertIsNone(out[1])
        self.assertIsNotNone(out[-1])
    def test_rsi_uptrend_high(self):
        out=rsi(list(range(1,30)), 14)
        self.assertEqual(out[-1], 100.0)
    def test_max_drawdown(self):
        self.assertAlmostEqual(max_drawdown([100,120,90,110]), -0.25)
    def test_returns_skip_nonfinite_live_vendor_values(self):
        out = returns([100.0, float('nan'), 102.0, 0.0, 103.0])
        self.assertEqual(out, [None, None, None, -1.0, None])
    def test_rolling_volatility_handles_nonfinite_values_without_crashing(self):
        out = rolling_volatility([100.0, 101.0, float('nan'), 103.0, 104.0], window=3)
        self.assertEqual(len(out), 5)
        self.assertTrue(all(v is None or math.isfinite(v) for v in out))

if __name__ == '__main__': unittest.main()
