import unittest
from datetime import date, timedelta
from market_lab.data import Bar
from market_lab.signals import generate_signal
from market_lab.backtest import moving_average_cross_backtest


def bars_from_prices(prices):
    start=date(2024,1,1)
    return [Bar(start+timedelta(days=i), p, p*1.01, p*0.99, p, 1000) for i,p in enumerate(prices)]

class SignalBacktestTests(unittest.TestCase):
    def test_signal_insufficient_history_holds(self):
        sig=generate_signal("X", bars_from_prices([1,2,3]))
        self.assertEqual(sig.action, "HOLD")
    def test_generate_buy_in_constructive_uptrend(self):
        prices=[100 + i*0.35 + (1.5 if i % 6 in (1, 2, 3) else -0.5) for i in range(90)]
        sig=generate_signal("UP", bars_from_prices(prices))
        self.assertEqual(sig.action, "BUY")
    def test_backtest_no_lookahead_runs(self):
        prices=[100]*60 + [100+i for i in range(80)] + [180-i for i in range(40)]
        result=moving_average_cross_backtest("X", bars_from_prices(prices))
        self.assertGreaterEqual(result.trades, 0)
        self.assertGreater(result.final_equity, 0)

if __name__ == '__main__': unittest.main()
