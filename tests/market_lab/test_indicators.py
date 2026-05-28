import unittest
from market_lab.indicators import sma, ema, rsi, max_drawdown

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

if __name__ == '__main__': unittest.main()
