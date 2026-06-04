import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from market_lab.broker import OrderCandidate, OrderDecision, Portfolio, Position, save_order_candidates, save_portfolio
from market_lab.config import RiskConfig
from market_lab.data import Bar, save_prices
from market_lab.evidence import append_evidence_record
from market_lab.webapp import MarketLabDashboardHandler, build_dashboard_snapshot, render_dashboard_html
from scripts import market_lab_webapp


def bars(symbol_base: float = 100.0, count: int = 170) -> list[Bar]:
    start = date(2025, 1, 1)
    out = []
    price = symbol_base
    for i in range(count):
        price = price * (1.001 + (0.0005 if i % 7 == 0 else 0))
        out.append(Bar(start + timedelta(days=i), price * 0.99, price * 1.01, price * 0.98, price, 1_000_000 + i))
    return out


class ReadOnlyWebappTests(unittest.TestCase):
    def test_dashboard_snapshot_uses_local_artifacts_and_no_live_trading(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            with patch("market_lab.config.DATA_DIR", data_dir), patch("market_lab.data.PRICE_DIR", data_dir / "prices"), patch("market_lab.data.SYNTHETIC_PRICE_DIR", data_dir / "synthetic"), patch("market_lab.config.PRICE_DIR", data_dir / "prices"), patch("market_lab.config.SYNTHETIC_PRICE_DIR", data_dir / "synthetic"), patch("market_lab.config.REPORT_DIR", data_dir / "reports"), patch("market_lab.config.FACTOR_DIR", data_dir / "factors"), patch("market_lab.config.EVIDENCE_DIR", data_dir / "evidence"), patch("market_lab.config.LEDGER_PATH", data_dir / "ledger.jsonl"), patch("market_lab.config.PENDING_CANDIDATES_PATH", data_dir / "candidates.jsonl"), patch("market_lab.config.STATE_PATH", data_dir / "portfolio.json"), patch("market_lab.webapp.REPORT_DIR", data_dir / "reports"), patch("market_lab.webapp.EVIDENCE_DIR", data_dir / "evidence"), patch("market_lab.webapp.LEDGER_PATH", data_dir / "ledger.jsonl"), patch("market_lab.webapp.PENDING_CANDIDATES_PATH", data_dir / "candidates.jsonl"), patch("market_lab.webapp.STATE_PATH", data_dir / "portfolio.json"), patch("market_lab.webapp.RISK", RiskConfig()):
                save_prices("SPY", bars(100))
                save_prices("QQQ", bars(120))
                save_portfolio(Portfolio(cash=90_000, positions={"SPY": Position("SPY", 10, 100)}), data_dir / "portfolio.json")
                save_order_candidates([OrderCandidate("BUY", "QQQ", 3, "tsmom", 0.7, "test", "2025-06-01", 120.0)], data_dir / "candidates.jsonl")
                (data_dir / "ledger.jsonl").write_text(json.dumps(OrderDecision(True, "BUY", "SPY", 10, 100, 100.05, "accepted", "2025-06-01T00:00:00Z", "tsmom", "2025-05-31", "2025-06-01").__dict__) + "\n")
                append_evidence_record({
                    "decision_id": "abc",
                    "symbol": "SPY",
                    "strategy": "tsmom",
                    "side": "BUY",
                    "entry_date": "2025-06-01",
                    "exit_date": "2025-06-10",
                    "holding_bars": 7,
                    "entry_price": 100.0,
                    "exit_price": 105.0,
                    "pnl_pct": 0.05,
                    "pnl_vs_benchmark": 0.02,
                    "regime_label": "trending_up",
                    "hypothesis": "trend",
                    "evidence_snapshot": {},
                    "failure_mode": None,
                    "confidence_at_entry": 0.7,
                    "data_quality": "cache",
                }, data_dir / "evidence" / "trades.jsonl")
                snapshot = build_dashboard_snapshot(["SPY", "QQQ"])

        self.assertEqual(snapshot["mode"], "READ_ONLY_VIEW")
        self.assertFalse(snapshot["guardrails"]["live_trading_enabled"])
        self.assertEqual(snapshot["portfolio"]["open_positions"], 1)
        self.assertEqual(len(snapshot["mock_trading"]["queued_candidates"]), 1)
        self.assertGreaterEqual(snapshot["mock_trading"]["accepted_orders"], 1)
        self.assertTrue(snapshot["signals"]["cards"])
        self.assertTrue(snapshot["backtests"])
        self.assertTrue(any(h["strategy"] == "tsmom" for h in snapshot["council"]["health"]))

    def test_rendered_html_has_visual_sections_and_read_only_api_pointer(self):
        snapshot = {
            "generated_at": "2026-01-01T00:00:00Z",
            "portfolio": {"equity": 101000.0, "cash": 99000.0, "open_positions": 1},
            "signals": {"buy": 1, "hold": 1, "sell": 0, "cards": [{"symbol": "SPY", "action": "BUY", "confidence": 0.75, "close": 500.0, "change_1m": 0.03, "reason": "trend", "sparkline": "0,50 180,1"}]},
            "backtests": [{"symbol": "SPY", "strategy": "tsmom", "total_return": 0.1, "benchmark_return": 0.08, "max_drawdown": -0.05, "sharpe": 1.2, "trades": 4}],
            "momentum": [{"rank": 1, "symbol": "SPY", "percentile": 1.0, "score": 0.2}],
            "mock_trading": {"queued_candidates": [], "accepted_orders": 1, "rejected_orders": 0},
            "council": {"health": [{"strategy": "tsmom", "recommended_action": "continue", "total_trades": 1, "win_rate": 1, "avg_pnl": 0.05}], "trade_diagnoses": []},
            "data_sources": {"SPY": "cache"},
            "report_excerpt": "# latest",
        }
        html = render_dashboard_html(snapshot)
        self.assertIn("Market Lab · Visual Read-Only Cockpit", html)
        self.assertIn("Signal board", html)
        self.assertIn("Backtest sanity checks", html)
        self.assertIn("READ ONLY · NO BROKER ACTIONS", html)
        self.assertIn("/api/snapshot", html)
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertNotIn("https://", html)

    def test_handler_rejects_write_methods(self):
        self.assertIs(MarketLabDashboardHandler.do_PUT, MarketLabDashboardHandler.do_POST)
        self.assertIs(MarketLabDashboardHandler.do_PATCH, MarketLabDashboardHandler.do_POST)
        self.assertIs(MarketLabDashboardHandler.do_DELETE, MarketLabDashboardHandler.do_POST)

    def test_script_imports_webapp_main(self):
        self.assertTrue(callable(market_lab_webapp.main))

    def test_dashboard_snapshot_includes_tsmom_when_state_exists(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            tsmom_state = data_dir / "tsmom" / "portfolio_state.json"
            tsmom_ledger = data_dir / "tsmom" / "ledger.jsonl"
            with patch("market_lab.data.PRICE_DIR", data_dir / "prices"), patch("market_lab.data.SYNTHETIC_PRICE_DIR", data_dir / "synthetic"), patch("market_lab.webapp.EVIDENCE_DIR", data_dir / "evidence"), patch("market_lab.webapp.LEDGER_PATH", data_dir / "ledger.jsonl"), patch("market_lab.webapp.PENDING_CANDIDATES_PATH", data_dir / "candidates.jsonl"), patch("market_lab.webapp.STATE_PATH", data_dir / "portfolio.json"), patch("market_lab.webapp.REPORT_DIR", data_dir / "reports"), patch("market_lab.webapp.TSMOM_STATE", tsmom_state), patch("market_lab.webapp.TSMOM_LEDGER", tsmom_ledger):
                save_prices("SPY", bars(100))
                from market_lab.broker import Portfolio, save_portfolio
                save_portfolio(Portfolio(cash=25000.0), tsmom_state)
                snapshot = build_dashboard_snapshot(["SPY"])

        self.assertIn("tsmom", snapshot)
        self.assertTrue(snapshot["tsmom"]["active"])
        self.assertIn("portfolio", snapshot["tsmom"])
        self.assertIn("signal", snapshot["tsmom"])
        self.assertEqual(snapshot["tsmom"]["symbol"], "SPY")

    def test_dashboard_snapshot_tsmom_inactive_when_state_missing(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            missing_state = data_dir / "tsmom" / "portfolio_state.json"
            missing_ledger = data_dir / "tsmom" / "ledger.jsonl"
            with patch("market_lab.data.PRICE_DIR", data_dir / "prices"), patch("market_lab.data.SYNTHETIC_PRICE_DIR", data_dir / "synthetic"), patch("market_lab.webapp.EVIDENCE_DIR", data_dir / "evidence"), patch("market_lab.webapp.LEDGER_PATH", data_dir / "ledger.jsonl"), patch("market_lab.webapp.PENDING_CANDIDATES_PATH", data_dir / "candidates.jsonl"), patch("market_lab.webapp.STATE_PATH", data_dir / "portfolio.json"), patch("market_lab.webapp.REPORT_DIR", data_dir / "reports"), patch("market_lab.webapp.TSMOM_STATE", missing_state), patch("market_lab.webapp.TSMOM_LEDGER", missing_ledger):
                snapshot = build_dashboard_snapshot(["SPY"])

        self.assertIn("tsmom", snapshot)
        self.assertFalse(snapshot["tsmom"]["active"])
        self.assertIn("message", snapshot["tsmom"])

    def test_rendered_html_includes_tsmom_panel(self):
        snapshot = {
            "generated_at": "2026-01-01T00:00:00Z",
            "portfolio": {"equity": 101000.0, "cash": 99000.0, "open_positions": 1, "positions": []},
            "signals": {"buy": 1, "hold": 1, "sell": 0, "cards": [{"symbol": "SPY", "action": "BUY", "confidence": 0.75, "close": 500.0, "change_1m": 0.03, "reason": "trend", "sparkline": "0,50 180,1", "source": "cache"}]},
            "backtests": [{"symbol": "SPY", "strategy": "tsmom", "total_return": 0.1, "benchmark_return": 0.08, "max_drawdown": -0.05, "sharpe": 1.2, "trades": 4}],
            "momentum": [{"rank": 1, "symbol": "SPY", "percentile": 1.0, "score": 0.2}],
            "mock_trading": {"queued_candidates": [], "accepted_orders": 1, "rejected_orders": 0},
            "council": {"health": [], "trade_diagnoses": []},
            "data_sources": {"SPY": "cache"},
            "report_excerpt": "# latest",
            "options": {"covered_calls": [], "cash_secured_puts": [], "warnings": [], "mode": "DISABLED", "chain_count": 0, "paper_portfolio": {"cash": 0, "available_cash": 0, "reserved_cash": 0, "reserved_shares": {}, "open_positions": 0, "positions": []}},
            "tsmom": {
                "active": True,
                "symbol": "SPY",
                "mode": "READ_ONLY_VIEW",
                "source": "cache",
                "portfolio": {"cash": 25000.0, "equity": 25000.0, "position_qty": 0, "position_avg_price": 0.0, "position_weight": 0.0},
                "signal": {"action": "HOLD", "confidence": 0.5, "target_weight": 0.0, "reason": "flat", "evidence": {}},
                "cumulative_fills": 0,
            },
        }
        html = render_dashboard_html(snapshot)
        self.assertIn("TSMOM Independent Mock Tracking", html)
        self.assertIn("Active", html)

        # Also verify inactive rendering when tsmom.active is False
        inactive_snapshot = dict(snapshot)
        inactive_snapshot["tsmom"] = {"active": False, "message": "tsmom tracking not started yet"}
        inactive_html = render_dashboard_html(inactive_snapshot)
        self.assertIn("TSMOM Independent Mock Tracking", inactive_html)
        self.assertIn("Inactive", inactive_html)

    def test_snapshot_tolerates_malformed_trade_evidence_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            with patch("market_lab.data.PRICE_DIR", data_dir / "prices"), patch("market_lab.data.SYNTHETIC_PRICE_DIR", data_dir / "synthetic"), patch("market_lab.webapp.EVIDENCE_DIR", data_dir / "evidence"), patch("market_lab.webapp.LEDGER_PATH", data_dir / "ledger.jsonl"), patch("market_lab.webapp.PENDING_CANDIDATES_PATH", data_dir / "candidates.jsonl"), patch("market_lab.webapp.STATE_PATH", data_dir / "portfolio.json"):
                save_prices("SPY", bars(100))
                path = data_dir / "evidence" / "trades.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{"decision_id":"ok","symbol":"SPY","strategy":"tsmom","side":"BUY","entry_date":"2025-06-01","exit_date":null,"holding_bars":2,"entry_price":100,"exit_price":101,"pnl_pct":0.01,"pnl_vs_benchmark":0,"regime_label":"unknown","hypothesis":"test","evidence_snapshot":{},"failure_mode":null,"confidence_at_entry":0.5,"data_quality":"cache"}\n{broken json\n')

                snapshot = build_dashboard_snapshot(["SPY"])

        self.assertEqual(len(snapshot["council"]["trade_diagnoses"]), 1)
        self.assertEqual(snapshot["council"]["trade_diagnoses"][0]["symbol"], "SPY")
    def test_dashboard_includes_non_default_held_symbols_for_valuation(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            custom = bars(200, count=170)
            latest = custom[-1].close
            with patch("market_lab.data.PRICE_DIR", data_dir / "prices"), patch("market_lab.data.SYNTHETIC_PRICE_DIR", data_dir / "synthetic"), patch("market_lab.webapp.EVIDENCE_DIR", data_dir / "evidence"), patch("market_lab.webapp.LEDGER_PATH", data_dir / "ledger.jsonl"), patch("market_lab.webapp.PENDING_CANDIDATES_PATH", data_dir / "candidates.jsonl"), patch("market_lab.webapp.STATE_PATH", data_dir / "portfolio.json"):
                save_prices("NFLX", custom)
                save_portfolio(Portfolio(cash=1_000, positions={"NFLX": Position("NFLX", 2, 100)}), data_dir / "portfolio.json")

                snapshot = build_dashboard_snapshot(["SPY"])

        self.assertEqual(snapshot["portfolio"]["positions"][0]["symbol"], "NFLX")
        self.assertAlmostEqual(snapshot["portfolio"]["positions"][0]["market_value"], 2 * latest, places=3)
        self.assertAlmostEqual(snapshot["portfolio"]["equity"], 1_000 + 2 * latest, places=3)
    def test_snapshot_does_not_create_directories_for_empty_readonly_view(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            missing_prices = data_dir / "missing-prices"
            with patch("market_lab.data.PRICE_DIR", missing_prices), patch("market_lab.data.SYNTHETIC_PRICE_DIR", data_dir / "missing-synthetic"), patch("market_lab.webapp.EVIDENCE_DIR", data_dir / "missing-evidence"), patch("market_lab.webapp.LEDGER_PATH", data_dir / "missing-ledger.jsonl"), patch("market_lab.webapp.PENDING_CANDIDATES_PATH", data_dir / "missing-candidates.jsonl"), patch("market_lab.webapp.STATE_PATH", data_dir / "missing-portfolio.json"):
                snapshot = build_dashboard_snapshot(["SPY"])

        self.assertEqual(snapshot["data_sources"]["SPY"], "missing")
        self.assertFalse(missing_prices.exists())


if __name__ == "__main__":
    unittest.main()
