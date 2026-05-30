import builtins
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
    fetch_option_chain_snapshot,
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
    today = date.today()
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
        risk = OptionsRiskConfig(paper_options_enabled=True, max_contracts_per_symbol=2, max_assignment_notional_pct=0.60)
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
    def test_paper_options_rejects_global_kill_switch_and_oversized_long_premium(self):
        call = sample_snapshot().contracts[0]
        paper = OptionPaperPortfolio(cash=100_000)
        killed = OptionsRiskConfig(allow_options=False, paper_options_enabled=True)
        decision = evaluate_option_paper_order(paper, Portfolio(cash=100_000), OptionPaperOrder("BUY_TO_OPEN", call, 1, call.quote.mid, "long_call"), killed)
        self.assertFalse(decision.accepted)

        expensive = OptionContract(call.underlying, call.expiration, call.strike, "CALL", OptionQuote(49.0, 51.0, 50.0, 100, 1000), call.greeks)
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_option_premium_pct=0.02)
        decision = evaluate_option_paper_order(paper, Portfolio(cash=100_000), OptionPaperOrder("BUY_TO_OPEN", expensive, 1, expensive.quote.mid, "long_call"), risk)
        self.assertFalse(decision.accepted)
        self.assertIn("premium", decision.reason)

    def test_daily_report_script_builds_options_research_from_cached_chains(self):
        import scripts.market_lab_daily as daily
        snapshot = sample_snapshot()
        portfolio = Portfolio(cash=20_000, positions={"SPY": Position("SPY", 100, 90.0)})
        with tempfile.TemporaryDirectory() as td:
            chain_dir = Path(td) / "chains"
            save_option_chain_snapshot(snapshot, chain_dir)
            with patch.object(daily, "OPTIONS_CHAIN_DIR", chain_dir), patch.object(daily, "OPTIONS_RISK", OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_assignment_notional_pct=0.60)):
                chains = daily.load_available_option_chains(daily.OPTIONS_CHAIN_DIR)
                calls = []
                puts = []
                for chain in chains:
                    calls.extend(daily.screen_covered_calls(chain, portfolio, daily.OPTIONS_RISK))
                    puts.extend(daily.screen_cash_secured_puts(chain, portfolio, daily.OPTIONS_RISK))

        text = render_report([], [], [], portfolio, {"SPY": 100}, {"SPY": "cache"}, options_research={"covered_calls": calls, "cash_secured_puts": puts, "warnings": []})
        self.assertIn("SPY", text)
        self.assertIn("CALL", text)
        self.assertIn("PUT", text)
    def test_paper_order_gate_rejects_repeated_opens_and_bad_contract_quality(self):
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_contracts_per_symbol=1)
        call = sample_snapshot().contracts[0]
        paper = OptionPaperPortfolio(cash=100_000)
        equity = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 200, 90.0)})

        first = evaluate_option_paper_order(paper, equity, OptionPaperOrder("SELL_TO_OPEN", call, 1, call.quote.mid, "covered_call", sample_snapshot().as_of), risk)
        second = evaluate_option_paper_order(paper, equity, OptionPaperOrder("SELL_TO_OPEN", call, 1, call.quote.mid, "covered_call", sample_snapshot().as_of), risk)
        self.assertTrue(first.accepted, first.reason)
        self.assertFalse(second.accepted)
        self.assertIn("per-symbol", second.reason)

        bad_quote = OptionContract(call.underlying, call.expiration, call.strike, "CALL", OptionQuote(0.1, 1.0, 0.55, 0, 0), call.greeks)
        rejected = evaluate_option_paper_order(OptionPaperPortfolio(cash=100_000), equity, OptionPaperOrder("BUY_TO_OPEN", bad_quote, 1, bad_quote.quote.mid, "long_call", sample_snapshot().as_of), risk)
        self.assertFalse(rejected.accepted)
        self.assertIn("liquidity", rejected.reason)
    def test_global_risk_and_options_risk_defaults_enable_paper_but_not_live_options(self):
        from market_lab.config import RISK, OPTIONS_RISK
        self.assertTrue(RISK.allow_options)
        self.assertTrue(OPTIONS_RISK.allow_options)
        self.assertTrue(OPTIONS_RISK.paper_options_enabled)
        self.assertFalse(RISK.live_trading_enabled)
        self.assertFalse(OPTIONS_RISK.live_options_enabled)
    def test_direct_cash_secured_put_order_enforces_per_trade_assignment_cap(self):
        put = sample_snapshot().contracts[1]
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_contracts_per_symbol=5, max_assignment_notional_pct=0.20, max_total_options_assignment_pct=0.50)
        paper = OptionPaperPortfolio(cash=100_000)
        equity = Portfolio(cash=100_000)
        oversized = OptionPaperOrder("SELL_TO_OPEN", put, 3, put.quote.mid, "cash_secured_put", sample_snapshot().as_of)

        decision = evaluate_option_paper_order(paper, equity, oversized, risk)

        self.assertFalse(decision.accepted)
        self.assertIn("per-trade assignment", decision.reason)
        self.assertEqual(paper.reserved_cash, 0)
    def test_opening_order_cannot_offset_existing_opposite_option_position(self):
        call = sample_snapshot().contracts[0]
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_contracts_per_symbol=2)
        paper = OptionPaperPortfolio(cash=100_000, positions={call.contract_id: 1}, avg_price={call.contract_id: call.quote.mid})
        equity = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 100, 90.0)})

        decision = evaluate_option_paper_order(paper, equity, OptionPaperOrder("SELL_TO_OPEN", call, 1, call.quote.mid, "covered_call", sample_snapshot().as_of), risk)

        self.assertFalse(decision.accepted)
        self.assertIn("SELL_TO_CLOSE", decision.reason)
        self.assertEqual(paper.positions[call.contract_id], 1)
        self.assertEqual(paper.reserved_shares, {})
    def test_cash_secured_put_screener_respects_total_assignment_cap(self):
        snapshot = sample_snapshot()
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_contracts_per_symbol=5, max_assignment_notional_pct=0.60, max_total_options_assignment_pct=0.20)
        portfolio = Portfolio(cash=100_000)

        puts = screen_cash_secured_puts(snapshot, portfolio, risk)

        self.assertEqual(len(puts), 1)
        self.assertEqual(puts[0].contracts, 2)
        self.assertLessEqual(puts[0].cash_reserved, portfolio.equity({"SPY": 100}) * risk.max_total_options_assignment_pct)

    def test_screeners_reject_stale_cached_chains_and_expired_contracts(self):
        stale_as_of = date.today() - timedelta(days=45)
        expired = date.today() - timedelta(days=10)
        snapshot = OptionChainSnapshot(
            underlying="SPY",
            underlying_price=100.0,
            as_of=stale_as_of.isoformat() + "T21:00:00Z",
            source="fixture",
            contracts=[
                OptionContract("SPY", expired.isoformat(), 105.0, "CALL", OptionQuote(1.9, 2.1, 2.0, 150, 1200), OptionGreeks(0.35, 0.04, -0.03, 0.12, 0.28)),
                OptionContract("SPY", expired.isoformat(), 95.0, "PUT", OptionQuote(1.4, 1.6, 1.5, 180, 1400), OptionGreeks(-0.30, 0.03, -0.025, 0.10, 0.31)),
            ],
        )
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_chain_age_days=2)
        portfolio = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 100, 90.0)})

        self.assertEqual(screen_covered_calls(snapshot, portfolio, risk), [])
        self.assertEqual(screen_cash_secured_puts(snapshot, portfolio, risk), [])

    def test_screeners_accept_fresh_utc_snapshot_when_local_date_lags(self):
        tomorrow_utc = date.today() + timedelta(days=1)
        expiry = tomorrow_utc + timedelta(days=35)
        snapshot = OptionChainSnapshot(
            underlying="SPY",
            underlying_price=100.0,
            as_of=tomorrow_utc.isoformat() + "T01:00:00+00:00",
            source="fixture",
            contracts=[
                OptionContract("SPY", expiry.isoformat(), 105.0, "CALL", OptionQuote(1.9, 2.1, 2.0, 150, 1200), OptionGreeks(0.35, 0.04, -0.03, 0.12, 0.28)),
                OptionContract("SPY", expiry.isoformat(), 95.0, "PUT", OptionQuote(1.4, 1.6, 1.5, 180, 1400), OptionGreeks(-0.30, 0.03, -0.025, 0.10, 0.31)),
            ],
        )
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_chain_age_days=2, max_assignment_notional_pct=0.60)
        portfolio = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 100, 90.0)})

        self.assertEqual(len(screen_covered_calls(snapshot, portfolio, risk, as_of=date.today())), 1)
        self.assertEqual(len(screen_cash_secured_puts(snapshot, portfolio, risk, as_of=date.today())), 1)

    def test_screeners_account_for_existing_paper_option_reservations(self):
        snapshot = sample_snapshot()
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_contracts_per_symbol=5, max_assignment_notional_pct=0.60, max_total_options_assignment_pct=0.20)
        portfolio = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 100, 90.0)})
        paper = OptionPaperPortfolio(cash=100_000, reserved_cash=19_000, reserved_shares={"SPY": 100})

        self.assertEqual(screen_covered_calls(snapshot, portfolio, risk, paper=paper), [])
        self.assertEqual(screen_cash_secured_puts(snapshot, portfolio, risk, paper=paper), [])

    def test_screeners_size_against_paper_cash_and_existing_contract_limits(self):
        snapshot = sample_snapshot()
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_contracts_per_symbol=1, max_assignment_notional_pct=0.60, max_total_options_assignment_pct=0.60)
        portfolio = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 200, 90.0)})
        existing = OptionPaperPortfolio(cash=100_000, positions={snapshot.contracts[0].contract_id: -1})
        low_paper_cash = OptionPaperPortfolio(cash=5_000)

        self.assertEqual(screen_covered_calls(snapshot, portfolio, risk, paper=existing), [])
        self.assertEqual(screen_cash_secured_puts(snapshot, portfolio, risk, paper=existing), [])
        self.assertEqual(screen_cash_secured_puts(snapshot, portfolio, risk, paper=low_paper_cash), [])

    def test_cash_secured_put_screener_uses_funded_paper_account_equity_base(self):
        snapshot = sample_snapshot()
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, max_contracts_per_symbol=1, max_assignment_notional_pct=0.20, max_total_options_assignment_pct=0.35)
        portfolio = Portfolio(cash=5_000)
        paper = OptionPaperPortfolio(cash=100_000)

        puts = screen_cash_secured_puts(snapshot, portfolio, risk, paper=paper)

        self.assertEqual(len(puts), 1)
        self.assertLessEqual(puts[0].cash_reserved, paper.cash * risk.max_assignment_notional_pct)
    def test_screeners_reject_when_live_options_kill_switch_is_on(self):
        snapshot = sample_snapshot()
        risk = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, live_options_enabled=True)
        portfolio = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 100, 90.0)})

        self.assertEqual(screen_covered_calls(snapshot, portfolio, risk), [])
        self.assertEqual(screen_cash_secured_puts(snapshot, portfolio, risk), [])

    def test_dashboard_reports_disabled_mode_when_options_kill_switches_are_active(self):
        snapshot = sample_snapshot()
        portfolio = Portfolio(cash=100_000, positions={"SPY": Position("SPY", 100, 90.0)})
        disabled = OptionsRiskConfig(allow_options=False, paper_options_enabled=True, live_options_enabled=False)
        live_enabled = OptionsRiskConfig(allow_options=True, paper_options_enabled=True, live_options_enabled=True)
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            save_option_chain_snapshot(snapshot, data_dir / "options" / "chains")
            save_portfolio(portfolio, data_dir / "mock_portfolio_state.json")
            with patch("market_lab.webapp.OPTIONS_CHAIN_DIR", data_dir / "options" / "chains"), patch("market_lab.webapp.STATE_PATH", data_dir / "mock_portfolio_state.json"), patch("market_lab.webapp.OPTIONS_RISK", disabled):
                disabled_dash = build_dashboard_snapshot(["SPY"])
            with patch("market_lab.webapp.OPTIONS_CHAIN_DIR", data_dir / "options" / "chains"), patch("market_lab.webapp.STATE_PATH", data_dir / "mock_portfolio_state.json"), patch("market_lab.webapp.OPTIONS_RISK", live_enabled):
                live_dash = build_dashboard_snapshot(["SPY"])

        self.assertEqual(disabled_dash["options"]["mode"], "DISABLED")
        self.assertEqual(live_dash["options"]["mode"], "DISABLED")
        self.assertEqual(disabled_dash["options"]["covered_call_count"], 0)
        self.assertEqual(live_dash["options"]["cash_secured_put_count"], 0)

    def test_fetch_option_chain_snapshot_from_yfinance_normalizes_calls_and_puts(self):
        import pandas as pd

        class FakeTicker:
            options = [(date.today() + timedelta(days=35)).isoformat()]

            def __init__(self, symbol):
                self.symbol = symbol
                self.fast_info = {"last_price": 100.0}

            def option_chain(self, expiration):
                self.requested_expiration = expiration
                calls = pd.DataFrame([
                    {"strike": 105.0, "bid": 1.9, "ask": 2.1, "lastPrice": 2.0, "volume": 150, "openInterest": 1200, "impliedVolatility": 0.28},
                ])
                puts = pd.DataFrame([
                    {"strike": 95.0, "bid": 1.4, "ask": 1.6, "lastPrice": 1.5, "volume": 180, "openInterest": 1400, "impliedVolatility": 0.31},
                ])
                return type("Chain", (), {"calls": calls, "puts": puts})()

        with patch("market_lab.options_data.yf.Ticker", FakeTicker):
            snapshot = fetch_option_chain_snapshot("SPY", min_dte=14, max_dte=60)

        self.assertEqual(snapshot.underlying, "SPY")
        self.assertEqual(snapshot.source, "yfinance")
        self.assertEqual(len(snapshot.contracts), 2)
        self.assertEqual({c.option_type for c in snapshot.contracts}, {"CALL", "PUT"})
        self.assertGreater(snapshot.contracts[0].quote.open_interest, 0)
        self.assertGreaterEqual(abs(snapshot.contracts[0].greeks.delta), 0.0)

    def test_fetch_option_chain_snapshot_computes_delta_after_underlying_price_fallback(self):
        import pandas as pd

        class FakeTickerNoFastPrice:
            options = [(date.today() + timedelta(days=35)).isoformat()]
            fast_info = {}

            def __init__(self, symbol):
                self.symbol = symbol

            def option_chain(self, expiration):
                calls = pd.DataFrame([
                    {"strike": 105.0, "bid": 1.9, "ask": 2.1, "lastPrice": 2.0, "volume": 150, "openInterest": 1200, "impliedVolatility": 0.28},
                ])
                puts = pd.DataFrame([
                    {"strike": 95.0, "bid": 1.4, "ask": 1.6, "lastPrice": 1.5, "volume": 180, "openInterest": 1400, "impliedVolatility": 0.31},
                ])
                return type("Chain", (), {"calls": calls, "puts": puts})()

        with patch("market_lab.options_data.yf.Ticker", FakeTickerNoFastPrice):
            snapshot = fetch_option_chain_snapshot("SPY", min_dte=14, max_dte=60)

        put = [c for c in snapshot.contracts if c.option_type == "PUT"][0]
        self.assertGreater(snapshot.underlying_price, 0)
        self.assertGreater(put.greeks.delta, -0.95)

    def test_corrupt_options_paper_state_loads_default_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "paper_options_state.json"
            path.write_text("{not json")
            portfolio = load_option_paper_portfolio(path)
            self.assertEqual(portfolio.cash, 100_000.0)
            self.assertEqual(portfolio.positions, {})
            self.assertEqual(portfolio.reserved_cash, 0.0)
            self.assertEqual(portfolio.reserved_shares, {})

    def test_options_paper_save_uses_atomic_write_under_lock(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            paper = OptionPaperPortfolio(cash=50_000, positions={"SPY-CALL": 5}, reserved_shares={"SPY": 100})
            save_option_paper_portfolio(paper, path)
            self.assertTrue(path.exists())
            loaded = load_option_paper_portfolio(path)
            self.assertEqual(loaded.cash, 50_000)
            self.assertEqual(loaded.positions["SPY-CALL"], 5)
            self.assertEqual(loaded.reserved_shares["SPY"], 100)
            lock_path = path.with_suffix(path.suffix + ".lock")
            self.assertTrue(lock_path.exists())

    def test_options_paper_save_gracefully_degrades_without_fcntl(self):
        original_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "fcntl":
                raise ModuleNotFoundError("No module named 'fcntl'")
            return original_import(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as td, patch("builtins.__import__", side_effect=fake_import):
            path = Path(td) / "state.json"
            paper = OptionPaperPortfolio(cash=30_000)
            save_option_paper_portfolio(paper, path)
            self.assertTrue(path.exists())
            self.assertEqual(load_option_paper_portfolio(path).cash, 30_000)

    def test_options_paper_ledger_appends_with_fsync(self):
        from market_lab.options_paper import append_option_paper_ledger, OptionPaperDecision
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.jsonl"
            decision = OptionPaperDecision(
                accepted=True,
                action="BUY_TO_OPEN",
                contract_id="SPY-2025-01-01-C-100",
                contracts=1,
                price=2.0,
                premium=200.0,
                reason="test",
                timestamp=date.today().isoformat() + "T00:00:00Z",
                strategy="test",
            )
            append_option_paper_ledger(decision, path)
            self.assertTrue(path.exists())
            lines = path.read_text().strip().split("\n")
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["contract_id"], "SPY-2025-01-01-C-100")


if __name__ == "__main__":
    unittest.main()
