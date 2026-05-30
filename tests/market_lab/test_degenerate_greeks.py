"""Focused regression tests for degenerate-greeks quality gating (finding #3)."""

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from market_lab.broker import Portfolio, Position
from market_lab.config import OptionsRiskConfig
from market_lab.options_data import (
    OptionChainSnapshot,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    _approx_delta,
    load_option_chain_snapshot,
    save_option_chain_snapshot,
)
from market_lab.options_paper import (
    OptionPaperOrder,
    OptionPaperPortfolio,
    evaluate_option_paper_order,
)
from market_lab.options_screeners import screen_cash_secured_puts, screen_covered_calls


def _make_contract(strike: float, option_type: str, greeks: OptionGreeks) -> OptionContract:
    today = date.today()
    expiry = today + timedelta(days=35)
    return OptionContract(
        underlying="SPY",
        expiration=expiry.isoformat(),
        strike=strike,
        option_type=option_type,
        quote=OptionQuote(1.9, 2.1, 2.0, 150, 1200),
        greeks=greeks,
    )


class DegenerateGreeksRegressionTests(unittest.TestCase):
    """Contracts whose deltas come from the degenerate fallback must be tagged
    low-quality and excluded from risk gates/screeners.
    """

    def test_approx_delta_returns_degenerate_true_for_invalid_inputs(self):
        cases = [
            # (underlying_price, strike, dte, iv, option_type)
            (0, 100, 30, 0.25, "CALL"),
            (100, 0, 30, 0.25, "CALL"),
            (100, 100, 0, 0.25, "PUT"),
            (100, 100, 30, 0, "PUT"),
            (100, 100, -5, 0.25, "CALL"),
            (100, 100, 30, -0.1, "PUT"),
        ]
        for up, strike, dte, iv, opt_type in cases:
            with self.subTest(up=up, strike=strike, dte=dte, iv=iv, type=opt_type):
                delta, degenerate = _approx_delta(opt_type, up, strike, dte, iv)
                self.assertTrue(degenerate, "expected degenerate=True for invalid inputs")
                self.assertIsInstance(delta, float)

    def test_approx_delta_returns_degenerate_false_for_valid_inputs(self):
        delta, degenerate = _approx_delta("CALL", 100, 105, 30, 0.25)
        self.assertFalse(degenerate)
        self.assertGreater(delta, 0)
        self.assertLess(delta, 1.0)

        delta, degenerate = _approx_delta("PUT", 100, 95, 30, 0.25)
        self.assertFalse(degenerate)
        self.assertLess(delta, 0)
        self.assertGreater(delta, -1.0)

    def test_covered_call_screener_excludes_degenerate_greeks(self):
        snapshot = OptionChainSnapshot(
            underlying="SPY",
            underlying_price=100.0,
            as_of=date.today().isoformat(),
            source="fixture",
            contracts=[
                # This contract has valid greeks
                _make_contract(105.0, "CALL", OptionGreeks(0.35, 0.04, -0.03, 0.12, 0.28, degenerate=False)),
                # This contract has degenerate greeks (should be filtered)
                _make_contract(110.0, "CALL", OptionGreeks(0.50, 0.0, 0.0, 0.0, 0.0, degenerate=True)),
            ],
        )
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_assignment_notional_pct=0.60)
        portfolio = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 200, 90.0)})

        calls = screen_covered_calls(snapshot, portfolio, risk)

        strikes = [c.contract.strike for c in calls]
        self.assertIn(105.0, strikes)
        self.assertNotIn(110.0, strikes)

    def test_cash_secured_put_screener_excludes_degenerate_greeks(self):
        snapshot = OptionChainSnapshot(
            underlying="SPY",
            underlying_price=100.0,
            as_of=date.today().isoformat(),
            source="fixture",
            contracts=[
                _make_contract(95.0, "PUT", OptionGreeks(-0.30, 0.03, -0.025, 0.10, 0.31, degenerate=False)),
                _make_contract(90.0, "PUT", OptionGreeks(-0.40, 0.0, 0.0, 0.0, 0.0, degenerate=True)),
            ],
        )
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_assignment_notional_pct=0.60)
        portfolio = Portfolio(cash=100_000)

        puts = screen_cash_secured_puts(snapshot, portfolio, risk)

        strikes = [p.contract.strike for p in puts]
        self.assertIn(95.0, strikes)
        self.assertNotIn(90.0, strikes)

    def test_paper_order_rejects_sell_to_open_for_degenerate_greeks(self):
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_contracts_per_symbol=2)
        paper = OptionPaperPortfolio(cash=100_000)
        equity = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 200, 90.0)})

        # Valid greeks — should be accepted
        valid_call = _make_contract(105.0, "CALL", OptionGreeks(0.35, 0.04, -0.03, 0.12, 0.28, degenerate=False))
        decision = evaluate_option_paper_order(
            paper, equity, OptionPaperOrder("SELL_TO_OPEN", valid_call, 1, valid_call.quote.mid, "covered_call"), risk
        )
        self.assertTrue(decision.accepted, decision.reason)

        # Degenerate greeks — should be rejected even if all other gates pass
        degenerate_call = _make_contract(110.0, "CALL", OptionGreeks(0.50, 0.0, 0.0, 0.0, 0.0, degenerate=True))
        decision = evaluate_option_paper_order(
            paper, equity, OptionPaperOrder("SELL_TO_OPEN", degenerate_call, 1, degenerate_call.quote.mid, "covered_call"), risk
        )
        self.assertFalse(decision.accepted)
        self.assertIn("degenerate", decision.reason.lower())

    def test_paper_order_rejects_buy_to_open_for_degenerate_greeks(self):
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True)
        paper = OptionPaperPortfolio(cash=100_000)
        equity = Portfolio(cash=100_000)

        degenerate_put = _make_contract(95.0, "PUT", OptionGreeks(-0.30, 0.0, 0.0, 0.0, 0.0, degenerate=True))
        decision = evaluate_option_paper_order(
            paper, equity, OptionPaperOrder("BUY_TO_OPEN", degenerate_put, 1, degenerate_put.quote.mid, "long_put"), risk
        )
        self.assertFalse(decision.accepted)
        self.assertIn("degenerate", decision.reason.lower())

    def test_chain_snapshot_round_trip_preserves_degenerate_flag(self):
        contract = _make_contract(105.0, "CALL", OptionGreeks(0.35, 0.04, -0.03, 0.12, 0.28, degenerate=False))
        degenerate_contract = _make_contract(110.0, "CALL", OptionGreeks(0.50, 0.0, 0.0, 0.0, 0.0, degenerate=True))
        snapshot = OptionChainSnapshot(
            underlying="SPY",
            underlying_price=100.0,
            as_of=date.today().isoformat(),
            source="fixture",
            contracts=[contract, degenerate_contract],
        )
        with tempfile.TemporaryDirectory() as td:
            path = save_option_chain_snapshot(snapshot, Path(td))
            loaded = load_option_chain_snapshot("SPY", Path(td))

        self.assertFalse(loaded.contracts[0].greeks.degenerate)
        self.assertTrue(loaded.contracts[1].greeks.degenerate)

    def test_load_old_snapshot_without_degenerates_defaults_to_false(self):
        """Backward compat: JSON saved before the field exists loads as degenerate=False."""
        old_json = {
            "underlying": "SPY",
            "underlying_price": 100.0,
            "as_of": date.today().isoformat(),
            "source": "fixture",
            "contracts": [
                {
                    "underlying": "SPY",
                    "expiration": (date.today() + timedelta(days=35)).isoformat(),
                    "strike": 105.0,
                    "option_type": "CALL",
                    "quote": {"bid": 1.9, "ask": 2.1, "mid": 2.0, "volume": 150, "open_interest": 1200},
                    "greeks": {"delta": 0.35, "gamma": 0.04, "theta": -0.03, "vega": 0.12, "implied_volatility": 0.28},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "SPY.json"
            path.write_text(json.dumps(old_json))
            loaded = load_option_chain_snapshot("SPY", Path(td))

        self.assertEqual(len(loaded.contracts), 1)
        self.assertFalse(loaded.contracts[0].greeks.degenerate)


if __name__ == "__main__":
    unittest.main()
