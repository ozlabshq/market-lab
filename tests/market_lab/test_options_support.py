import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from market_lab.broker import Portfolio, Position, save_portfolio
from market_lab.config import OptionsRiskConfig
from market_lab.options_data import (
    OptionChainSnapshot,
    OptionContract,
    OptionGreeks,
    OptionQuote,
    load_option_chain_snapshot,
    save_option_chain_snapshot,
)
from market_lab.options_paper import (
    OptionPaperOrder,
    OptionPaperPortfolio,
    evaluate_option_paper_order,
    load_option_paper_portfolio,
    save_option_paper_portfolio,
)
from market_lab.options_screeners import screen_cash_secured_puts, screen_covered_calls
from market_lab.report import render_report
from market_lab.webapp import build_dashboard_snapshot, render_dashboard_html


def sample_snapshot(symbol="SPY"):
    today = date(2026, 1, 2)
    expiry = today + timedelta(days=35)
    return OptionChainSnapshot(
        underlying=symbol,
        underlying_price=100.0,
        as_of=today.isoformat() + "T21:00:00Z",
        source="fixture",
        contracts=[
            OptionContract(symbol, expiry.isoformat(), 105.0, "CALL", OptionQuote(1.9, 2.1, 2.0, 150, 1200), OptionGreeks(0.35, 0.04, -0.03, 0.12, 0.28)),
            OptionContract(symbol, expiry.isoformat(), 95.0, "PUT", OptionQuote(1.4, 1.6, 1.5, 180, 1400), OptionGreeks(-0.30, 0.03, -0.025, 0.10, 0.31)),
            OptionContract(symbol, expiry.isoformat(), 120.0, "CALL", OptionQuote(0.1, 0.5, 0.3, 1, 3), OptionGreeks(0.05, 0.01, -0.01, 0.03, 0.55)),
        ],
    )


class OptionsSupportTests(unittest.TestCase):
    def test_option_chain_snapshot_round_trips_without_losing_greeks(self):
        with tempfile.TemporaryDirectory() as td:
            path = save_option_chain_snapshot(sample_snapshot(), Path(td))
            loaded = load_option_chain_snapshot("SPY", Path(td))

        self.assertEqual(path.name, "SPY.json")
        self.assertEqual(loaded.underlying, "SPY")
        self.assertEqual(len(loaded.contracts), 3)
        self.assertAlmostEqual(loaded.contracts[0].greeks.delta, 0.35)
        self.assertEqual(loaded.contracts[1].option_type, "PUT")

    def test_screeners_enforce_liquidity_and_collateral_requirements(self):
        risk = OptionsRiskConfig(paper_options_enabled=True, max_bid_ask_spread_pct=0.20, min_open_interest=100, min_volume=50, max_assignment_notional_pct=0.60)
        portfolio = Portfolio(cash=20_000, positions={"SPY": Position("SPY", 100, 90.0)})
        snapshot = sample_snapshot()

        calls = screen_covered_calls(snapshot, portfolio, risk)
        puts = screen_cash_secured_puts(snapshot, portfolio, risk)

        self.assertEqual([c.contract.strike for c in calls], [105.0])
        self.assertEqual([p.contract.strike for p in puts], [95.0])
        self.assertGreater(calls[0].annualized_yield, 0)
        self.assertLessEqual(abs(puts[0].contract.greeks.delta), risk.max_abs_short_put_delta)

    def test_screeners_block_options_when_paper_switch_is_off(self):
        risk = OptionsRiskConfig(paper_options_enabled=False)
        portfolio = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 100, 90.0)})

        self.assertEqual(screen_covered_calls(sample_snapshot(), portfolio, risk), [])
        self.assertEqual(screen_cash_secured_puts(sample_snapshot(), portfolio, risk), [])

    def test_paper_options_portfolio_reserves_cash_and_shares_for_defined_risk_shorts(self):
        risk = OptionsRiskConfig(paper_options_enabled=True)
        equity_portfolio = Portfolio(cash=20_000, positions={"SPY": Position("SPY", 100, 90.0)})
        paper = OptionPaperPortfolio(cash=20_000)
        snapshot = sample_snapshot()
        call = snapshot.contracts[0]
        put = snapshot.contracts[1]

        call_decision = evaluate_option_paper_order(paper, equity_portfolio, OptionPaperOrder("SELL_TO_OPEN", call, 1, call.quote.mid, "covered_call"), risk)
        put_decision = evaluate_option_paper_order(paper, equity_portfolio, OptionPaperOrder("SELL_TO_OPEN", put, 1, put.quote.mid, "cash_secured_put"), risk)

        self.assertTrue(call_decision.accepted, call_decision.reason)
        self.assertTrue(put_decision.accepted, put_decision.reason)
        self.assertEqual(paper.reserved_shares["SPY"], 100)
        self.assertEqual(paper.reserved_cash, 9500.0)
        self.assertGreater(paper.cash, 20_000)  # premiums received

    def test_paper_options_rejects_naked_call_and_excess_cash_secured_put(self):
        risk = OptionsRiskConfig(paper_options_enabled=True)
        snapshot = sample_snapshot()
        call = snapshot.contracts[0]
        put = snapshot.contracts[1]

        no_shares = OptionPaperPortfolio(cash=20_000)
        decision = evaluate_option_paper_order(no_shares, Portfolio(cash=20_000), OptionPaperOrder("SELL_TO_OPEN", call, 1, call.quote.mid, "covered_call"), risk)
        self.assertFalse(decision.accepted)
        self.assertIn("covered shares", decision.reason)

        low_cash = OptionPaperPortfolio(cash=1_000)
        decision = evaluate_option_paper_order(low_cash, Portfolio(cash=1_000), OptionPaperOrder("SELL_TO_OPEN", put, 1, put.quote.mid, "cash_secured_put"), risk)
        self.assertFalse(decision.accepted)
        self.assertIn("reserved cash", decision.reason)

    def test_paper_options_portfolio_persists_positions_and_reserves(self):
        paper = OptionPaperPortfolio(cash=21_000, reserved_cash=9_500, reserved_shares={"SPY": 100})
        paper.positions["SPY-2026-02-06-C-105.00"] = 1
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "paper_options.json"
            save_option_paper_portfolio(paper, path)
            loaded = load_option_paper_portfolio(path)

        self.assertEqual(loaded.cash, 21_000)
        self.assertEqual(loaded.reserved_cash, 9_500)
        self.assertEqual(loaded.reserved_shares["SPY"], 100)
        self.assertEqual(loaded.positions["SPY-2026-02-06-C-105.00"], 1)

    def test_report_and_dashboard_surface_options_research_read_only(self):
        snapshot = sample_snapshot()
        risk = OptionsRiskConfig(paper_options_enabled=True)
        portfolio = Portfolio(cash=20_000, positions={"SPY": Position("SPY", 100, 90.0)})
        calls = screen_covered_calls(snapshot, portfolio, risk)
        puts = screen_cash_secured_puts(snapshot, portfolio, risk)
        text = render_report([], [], [], portfolio, {"SPY": 100}, {"SPY": "cache"}, options_research={"covered_calls": calls, "cash_secured_puts": puts, "warnings": []})

        self.assertIn("## Options Research — Paper Only", text)
        self.assertIn("Covered Call Candidates", text)
        self.assertIn("Cash-Secured Put Candidates", text)

        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            save_option_chain_snapshot(snapshot, data_dir / "options" / "chains")
            save_portfolio(portfolio, data_dir / "mock_portfolio_state.json")
            with patch("market_lab.webapp.OPTIONS_CHAIN_DIR", data_dir / "options" / "chains"), patch("market_lab.webapp.STATE_PATH", data_dir / "mock_portfolio_state.json"), patch("market_lab.webapp.OPTIONS_RISK", risk):
                dash = build_dashboard_snapshot(["SPY"])
                html = render_dashboard_html(dash)

        self.assertIn("options", dash)
        self.assertGreaterEqual(dash["options"]["covered_call_count"], 1)
        self.assertIn("Options Research", html)
        self.assertIn("PAPER ONLY", html)
    def test_paper_short_put_can_close_using_released_collateral(self):
        risk = OptionsRiskConfig(paper_options_enabled=True, max_total_options_assignment_pct=1.0)
        put = sample_snapshot().contracts[1]
        paper = OptionPaperPortfolio(cash=10_150, positions={put.contract_id: -1}, avg_price={put.contract_id: 1.5}, reserved_cash=9_500)

        decision = evaluate_option_paper_order(paper, Portfolio(cash=10_150), OptionPaperOrder("BUY_TO_CLOSE", put, 1, 7.0, "risk_exit"), risk)

        self.assertTrue(decision.accepted, decision.reason)
        self.assertEqual(paper.reserved_cash, 0)
        self.assertNotIn(put.contract_id, paper.positions)

    def test_cash_secured_put_screener_caps_multi_contract_assignment_notional(self):
        snapshot = sample_snapshot()
        risk = OptionsRiskConfig(paper_options_enabled=True, max_contracts_per_symbol=3, max_assignment_notional_pct=0.20)
        portfolio = Portfolio(cash=100_000)

        puts = screen_cash_secured_puts(snapshot, portfolio, risk)

        self.assertEqual(len(puts), 1)
        self.assertLessEqual(puts[0].cash_reserved, portfolio.equity({"SPY": 100}) * risk.max_assignment_notional_pct)
        self.assertEqual(puts[0].contracts, 2)


if __name__ == "__main__":
    unittest.main()
