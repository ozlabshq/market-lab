import tempfile, unittest
from pathlib import Path
from market_lab.broker import Portfolio, Position, evaluate_order, place_mock_order, load_portfolio
from market_lab.config import RiskConfig

class BrokerTests(unittest.TestCase):
    def test_buy_rejected_when_position_limit_exceeded(self):
        p=Portfolio(cash=100000)
        d=evaluate_order(p, "BUY", "SPY", 1000, 100, {"SPY":100})
        self.assertFalse(d.accepted)
        self.assertIn("max order", d.reason)
    def test_buy_accepts_and_updates_cash_position(self):
        p=Portfolio(cash=100000)
        d=evaluate_order(p, "BUY", "SPY", 10, 100, {"SPY":100})
        self.assertTrue(d.accepted)
        self.assertEqual(p.positions["SPY"].quantity, 10)
        self.assertLess(p.cash, 100000)
    def test_sell_rejected_without_position(self):
        p=Portfolio(cash=100000)
        d=evaluate_order(p, "SELL", "SPY", 10, 100, {"SPY":100})
        self.assertFalse(d.accepted)
        self.assertIn("no shorting", d.reason)
    def test_allow_short_flag_does_not_block_covered_sell(self):
        p=Portfolio(cash=100000, positions={"SPY": Position("SPY", quantity=20, avg_price=90)})
        risk=RiskConfig(allow_short=True)
        d=evaluate_order(p, "SELL", "SPY", 10, 100, {"SPY":100}, risk=risk)
        self.assertTrue(d.accepted)
        self.assertEqual(p.positions["SPY"].quantity, 10)
    def test_short_open_still_rejected_in_mvp_even_with_flag(self):
        p=Portfolio(cash=100000)
        risk=RiskConfig(allow_short=True)
        d=evaluate_order(p, "SELL", "SPY", 10, 100, {"SPY":100}, risk=risk)
        self.assertFalse(d.accepted)
        self.assertIn("shorting is unsupported", d.reason)
    def test_position_limit_values_existing_position_at_market_price(self):
        p=Portfolio(cash=100000, positions={"SPY": Position("SPY", quantity=80, avg_price=10)})
        d=evaluate_order(p, "BUY", "SPY", 30, 100, {"SPY":100})
        self.assertFalse(d.accepted)
        self.assertIn("max position", d.reason)
    def test_place_mock_order_persists_state_and_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td)/"state.json"; ledger=Path(td)/"ledger.jsonl"
            d=place_mock_order("BUY", "SPY", 10, 100, {"SPY":100}, state, ledger)
            self.assertTrue(d.accepted)
            self.assertTrue(state.exists()); self.assertTrue(ledger.exists())
            self.assertEqual(load_portfolio(state).positions["SPY"].quantity, 10)

if __name__ == '__main__': unittest.main()
