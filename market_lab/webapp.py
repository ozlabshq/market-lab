from __future__ import annotations

import argparse
import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .backtest import moving_average_cross_backtest
from .broker import load_order_candidates, load_portfolio
from .config import DEFAULT_UNIVERSE, EVIDENCE_DIR, LEDGER_PATH, OPTIONS_CHAIN_DIR, OPTIONS_RISK, PENDING_CANDIDATES_PATH, REPORT_DIR, RISK, STATE_PATH
from .data import Bar, load_cached_prices, load_cached_synthetic_prices
from .diagnosis import TradeDiagnosis, generate_strategy_health_report
from .options_data import load_available_option_chains
from .options_screeners import screen_cash_secured_puts, screen_covered_calls
from .signals import cross_sectional_momentum_ranks, generate_ensemble_signal, generate_strategy_signals, rank_signals


APP_TITLE = "OzLabs Market Lab"


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.0f}"


def _load_best_bars(symbol: str) -> tuple[list[Bar], str]:
    bars = load_cached_prices(symbol)
    if bars:
        return bars, "cache"
    synthetic = load_cached_synthetic_prices(symbol)
    if synthetic:
        return synthetic, "cache_synthetic"
    return [], "missing"


def _sparkline_points(bars: list[Bar], width: int = 180, height: int = 54) -> str:
    closes = [bar.close for bar in bars[-60:] if bar.close > 0]
    if len(closes) < 2:
        return ""
    lo = min(closes)
    hi = max(closes)
    span = hi - lo or 1.0
    points: list[str] = []
    for idx, close in enumerate(closes):
        x = idx / (len(closes) - 1) * width
        y = height - ((close - lo) / span * height)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def _load_ledger_records() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    records: list[dict] = []
    with LEDGER_PATH.open() as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def _latest_report_excerpt() -> str:
    latest = REPORT_DIR / "latest.md"
    if not latest.exists():
        return "No daily report generated yet."
    text = latest.read_text()
    return text[:4000]


def _trade_diagnoses() -> list[TradeDiagnosis]:
    path = EVIDENCE_DIR / "trades.jsonl"
    records: list[dict] = []
    if path.exists():
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    diagnoses: list[TradeDiagnosis] = []
    for record in records:
        try:
            diagnoses.append(TradeDiagnosis(**record))
        except TypeError:
            continue
    return diagnoses


def build_dashboard_snapshot(symbols: list[str] | None = None) -> dict:
    """Build a read-only visual snapshot from local Market Lab artifacts only.

    The webapp deliberately avoids network fetches and broker writes. It visualizes cached
    market data, the mock portfolio, queued candidates, local backtest sanity checks,
    and evidence-council health records.
    """
    symbols = symbols or DEFAULT_UNIVERSE
    portfolio = load_portfolio(STATE_PATH)
    candidates = load_order_candidates(PENDING_CANDIDATES_PATH)
    symbols = list(dict.fromkeys([*symbols, *portfolio.positions.keys(), *(candidate.symbol for candidate in candidates)]))
    bars_by_symbol: dict[str, list[Bar]] = {}
    sources: dict[str, str] = {}
    for symbol in symbols:
        bars, source = _load_best_bars(symbol)
        bars_by_symbol[symbol] = bars
        sources[symbol] = source

    prices = {symbol: bars[-1].close for symbol, bars in bars_by_symbol.items() if bars}
    ledger = _load_ledger_records()
    diagnoses = _trade_diagnoses()
    strategies = sorted({d.strategy for d in diagnoses} | {"tsmom", "rsi_pullback", "baseline_scoring", "dual_momentum"})
    health = [generate_strategy_health_report(strategy, diagnoses).as_record() for strategy in strategies]

    signals = [generate_ensemble_signal(symbol, bars) for symbol, bars in bars_by_symbol.items() if bars]
    ranked_signals = rank_signals(signals)
    family = {symbol: generate_strategy_signals(symbol, bars) for symbol, bars in bars_by_symbol.items() if bars}
    ranks = cross_sectional_momentum_ranks(bars_by_symbol)
    backtests = []
    for symbol, bars in bars_by_symbol.items():
        if len(bars) >= 80:
            # Keep the dashboard responsive: use the fast MA sanity check here.
            # Deeper TSMOM/walk-forward results belong in research reports/CI artifacts.
            backtests.append(moving_average_cross_backtest(symbol, bars))

    buy_count = len([s for s in ranked_signals if s.action == "BUY"])
    sell_count = len([s for s in ranked_signals if s.action == "SELL"])
    hold_count = len([s for s in ranked_signals if s.action == "HOLD"])
    accepted_orders = len([r for r in ledger if r.get("accepted")])
    rejected_orders = len([r for r in ledger if r.get("accepted") is False])
    equity = portfolio.equity(prices)

    cards = []
    for signal in ranked_signals[:12]:
        bars = bars_by_symbol.get(signal.symbol, [])
        first = bars[-21].close if len(bars) >= 21 else bars[0].close if bars else signal.close
        change_1m = signal.close / first - 1 if first else 0.0
        cards.append({
            "symbol": signal.symbol,
            "action": signal.action,
            "confidence": signal.confidence,
            "close": signal.close,
            "change_1m": change_1m,
            "strategy": signal.strategy,
            "reason": signal.reason,
            "sparkline": _sparkline_points(bars),
            "source": sources.get(signal.symbol, "missing"),
        })

    option_chains = load_available_option_chains(OPTIONS_CHAIN_DIR)
    covered_calls = []
    cash_secured_puts = []
    options_warnings = []
    for chain in option_chains:
        covered_calls.extend(screen_covered_calls(chain, portfolio, OPTIONS_RISK))
        cash_secured_puts.extend(screen_cash_secured_puts(chain, portfolio, OPTIONS_RISK))
        stale_source = "synthetic" in chain.source.lower()
        if stale_source:
            options_warnings.append(f"{chain.underlying}: synthetic/sample chain source")
    options_payload = {
        "mode": "PAPER_ONLY" if OPTIONS_RISK.paper_options_enabled else "DISABLED",
        "chain_count": len(option_chains),
        "covered_call_count": len(covered_calls),
        "cash_secured_put_count": len(cash_secured_puts),
        "covered_calls": [asdict(c) for c in covered_calls[:8]],
        "cash_secured_puts": [asdict(p) for p in cash_secured_puts[:8]],
        "warnings": options_warnings,
        "guardrails": asdict(OPTIONS_RISK),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_VIEW",
        "guardrails": {
            "live_trading_enabled": RISK.live_trading_enabled,
            "allow_options": RISK.allow_options,
            "paper_options_enabled": OPTIONS_RISK.paper_options_enabled,
            "live_options_enabled": OPTIONS_RISK.live_options_enabled,
            "allow_short": RISK.allow_short,
            "allow_margin": RISK.allow_margin,
        },
        "portfolio": {
            "cash": portfolio.cash,
            "equity": equity,
            "open_positions": len(portfolio.positions),
            "positions": [asdict(position) | {"market_value": position.quantity * prices.get(symbol, position.avg_price)} for symbol, position in sorted(portfolio.positions.items())],
        },
        "signals": {
            "buy": buy_count,
            "hold": hold_count,
            "sell": sell_count,
            "top": [asdict(s) for s in ranked_signals[:16]],
            "cards": cards,
            "family": {symbol: [asdict(sig) for sig in sigs] for symbol, sigs in list(family.items())[:12]},
        },
        "momentum": [asdict(rank) for rank in ranks[:12]],
        "backtests": [asdict(result) for result in sorted(backtests, key=lambda b: b.sharpe, reverse=True)[:16]],
        "mock_trading": {
            "queued_candidates": [asdict(c) for c in candidates],
            "accepted_orders": accepted_orders,
            "rejected_orders": rejected_orders,
            "recent_ledger": ledger[-12:],
        },
        "council": {
            "trade_diagnoses": [d.as_record() for d in diagnoses[-20:]],
            "health": health,
        },
        "options": options_payload,
        "data_sources": sources,
        "report_excerpt": _latest_report_excerpt(),
    }


def _json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def render_dashboard_html(snapshot: dict) -> str:
    cards = snapshot["signals"]["cards"]
    backtests = snapshot["backtests"]
    momentum = snapshot["momentum"]
    candidates = snapshot["mock_trading"]["queued_candidates"]
    health = snapshot["council"]["health"]
    diagnoses = snapshot["council"]["trade_diagnoses"]
    sources = snapshot["data_sources"]
    options = snapshot.get("options", {"covered_calls": [], "cash_secured_puts": [], "warnings": [], "mode": "DISABLED", "chain_count": 0})
    synthetic_count = len([s for s in sources.values() if "synthetic" in s])
    missing_count = len([s for s in sources.values() if s == "missing"])

    def esc(value: object) -> str:
        return html.escape(str(value))

    signal_cards = "\n".join(
        f"""
        <article class=\"asset-card {esc(card['action']).lower()}\">
          <div class=\"card-top\"><span class=\"ticker\">{esc(card['symbol'])}</span><span class=\"pill {esc(card['action']).lower()}\">{esc(card['action'])}</span></div>
          <svg class=\"spark\" viewBox=\"0 0 180 54\" preserveAspectRatio=\"none\"><polyline points=\"{esc(card['sparkline'])}\" /></svg>
          <div class=\"metric-row\"><span>Close</span><strong>{_money(card['close'])}</strong></div>
          <div class=\"metric-row\"><span>1M</span><strong class=\"{'pos' if card['change_1m'] >= 0 else 'neg'}\">{_pct(card['change_1m'])}</strong></div>
          <div class=\"confidence\"><i style=\"width:{max(3, min(100, card['confidence'] * 100)):.0f}%\"></i></div>
          <p>{esc(card['reason'])}</p>
        </article>
        """ for card in cards
    ) or "<p class='muted'>No cached signals yet. Run the daily script to populate data.</p>"

    backtest_rows = "\n".join(
        f"<tr><td>{esc(b['symbol'])}</td><td>{esc(b['strategy'])}</td><td class=\"{'pos' if b['total_return'] >= 0 else 'neg'}\">{_pct(b['total_return'])}</td><td>{_pct(b['benchmark_return'])}</td><td>{_pct(b['max_drawdown'])}</td><td>{b['sharpe']:.2f}</td><td>{b['trades']}</td></tr>"
        for b in backtests[:10]
    ) or "<tr><td colspan='7'>No backtest rows available yet.</td></tr>"

    momentum_rows = "\n".join(
        f"<div class=\"rank-row\"><span>#{rank['rank']} {esc(rank['symbol'])}</span><div><b style=\"width:{max(2, min(100, rank['percentile'] * 100)):.0f}%\"></b></div><strong>{_pct(rank['score'])}</strong></div>"
        for rank in momentum[:10]
    ) or "<p class='muted'>Not enough cached history for cross-sectional ranks.</p>"

    candidate_rows = "\n".join(
        f"<li><b>{esc(c['side'])} {esc(c['quantity'])} {esc(c['symbol'])}</b><span>{esc(c['strategy'])} · confidence {float(c['confidence']):.2f} · {esc(c['intended_execution'])}</span></li>"
        for c in candidates[:8]
    ) or "<li><b>No queued candidates</b><span>Mock trading remains visual/read-only here.</span></li>"

    health_rows = "\n".join(
        f"<div class=\"health-card\"><span>{esc(h['strategy'])}</span><strong>{esc(h['recommended_action']).upper()}</strong><p>{h['total_trades']} trades · win {_pct(h['win_rate'])} · avg {_pct(h['avg_pnl'])}</p></div>"
        for h in health
    )

    diagnosis_rows = "\n".join(
        f"<li><b>{esc(d['symbol'])}</b><span>{esc(d['strategy'])} · {esc(d['regime_label'])} · pnl {_pct(d['pnl_pct'])} · {esc(d.get('failure_mode') or 'no failure')}</span></li>"
        for d in diagnoses[-8:]
    ) or "<li><b>No diagnoses yet</b><span>They appear after mock trades have post-entry bars.</span></li>"

    option_call_rows = "\n".join(
        f"<li><b>CC {esc(c['contract']['underlying'])} {esc(c['contract']['expiration'])} ${float(c['contract']['strike']):.0f}</b><span>premium {_money(c['premium'])} · annualized {_pct(c['annualized_yield'])} · delta {float(c['contract']['greeks']['delta']):.2f}</span></li>"
        for c in options.get("covered_calls", [])[:5]
    ) or "<li><b>No covered-call candidates</b><span>Need cached chains, 100-share lots, and liquidity pass.</span></li>"
    option_put_rows = "\n".join(
        f"<li><b>CSP {esc(p['contract']['underlying'])} {esc(p['contract']['expiration'])} ${float(p['contract']['strike']):.0f}</b><span>reserve {_money(p['cash_reserved'])} · premium {_money(p['premium'])} · annualized {_pct(p['annualized_yield'])}</span></li>"
        for p in options.get("cash_secured_puts", [])[:5]
    ) or "<li><b>No cash-secured put candidates</b><span>Need cash, cached chains, and liquidity pass.</span></li>"
    option_warning_rows = "\n".join(f"<li><b>Warning</b><span>{esc(w)}</span></li>" for w in options.get("warnings", [])[:5]) or "<li><b>Guardrails clean</b><span>No options data warnings in current snapshot.</span></li>"

    report_excerpt = esc(snapshot.get("report_excerpt", ""))
    generated = esc(snapshot["generated_at"])
    equity = snapshot["portfolio"]["equity"]
    cash = snapshot["portfolio"]["cash"]
    open_positions = snapshot["portfolio"]["open_positions"]
    buy = snapshot["signals"]["buy"]
    hold = snapshot["signals"]["hold"]
    sell = snapshot["signals"]["sell"]
    accepted = snapshot["mock_trading"]["accepted_orders"]
    rejected = snapshot["mock_trading"]["rejected_orders"]

    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{APP_TITLE}</title>
  <style>
    :root {{ --bg:#08090a; --panel:#0f1011; --surface:rgba(255,255,255,.035); --surface2:rgba(255,255,255,.055); --border:rgba(255,255,255,.08); --muted:#8a8f98; --text:#f7f8f8; --soft:#d0d6e0; --accent:#7170ff; --brand:#5e6ad2; --green:#10b981; --red:#f87171; --amber:#f59e0b; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:radial-gradient(circle at top left, rgba(113,112,255,.18), transparent 32rem), radial-gradient(circle at 70% 20%, rgba(16,185,129,.08), transparent 28rem), var(--bg); color:var(--text); font-family:'Inter',system-ui,sans-serif; font-feature-settings:'cv01','ss03'; }}
    .shell {{ max-width:1420px; margin:0 auto; padding:28px; }}
    header {{ display:flex; justify-content:space-between; align-items:flex-start; gap:20px; margin-bottom:26px; }}
    .eyebrow {{ color:var(--accent); font-family:'JetBrains Mono',monospace; font-size:12px; letter-spacing:.08em; text-transform:uppercase; }}
    h1 {{ font-size:54px; line-height:1; letter-spacing:-1.2px; margin:8px 0 12px; font-weight:510; max-width:830px; }}
    .sub {{ color:var(--muted); font-size:17px; line-height:1.6; max-width:760px; }}
    .read-only {{ border:1px solid var(--border); background:rgba(16,185,129,.08); color:#a7f3d0; padding:9px 12px; border-radius:999px; font-family:'JetBrains Mono',monospace; font-size:12px; white-space:nowrap; }}
    .grid {{ display:grid; gap:16px; }}
    .kpis {{ grid-template-columns:repeat(6, minmax(0,1fr)); margin-bottom:18px; }}
    .kpi, .panel, .asset-card {{ border:1px solid var(--border); background:linear-gradient(180deg, var(--surface2), var(--surface)); border-radius:18px; box-shadow:0 0 0 1px rgba(0,0,0,.2), inset 0 1px 0 rgba(255,255,255,.03); }}
    .kpi {{ padding:16px; min-height:112px; }}
    .kpi span {{ color:var(--muted); font-size:12px; }}
    .kpi strong {{ display:block; margin-top:14px; font-size:25px; letter-spacing:-.4px; }}
    .kpi small {{ color:var(--soft); }}
    .main {{ grid-template-columns:1.5fr .9fr; align-items:start; }}
    .panel {{ padding:18px; overflow:hidden; }}
    .panel h2 {{ margin:0 0 14px; font-size:20px; letter-spacing:-.24px; }}
    .asset-grid {{ grid-template-columns:repeat(3, minmax(0,1fr)); }}
    .asset-card {{ padding:14px; min-height:230px; }}
    .card-top, .metric-row {{ display:flex; justify-content:space-between; align-items:center; gap:10px; }}
    .ticker {{ font-size:20px; font-weight:590; }}
    .pill {{ border:1px solid var(--border); border-radius:999px; padding:4px 8px; font-size:11px; font-family:'JetBrains Mono',monospace; }}
    .pill.buy {{ color:#a7f3d0; background:rgba(16,185,129,.09); }} .pill.sell {{ color:#fecaca; background:rgba(248,113,113,.09); }} .pill.hold {{ color:#d0d6e0; background:rgba(255,255,255,.04); }}
    .spark {{ width:100%; height:58px; margin:16px 0; overflow:visible; }} .spark polyline {{ fill:none; stroke:var(--accent); stroke-width:2.5; vector-effect:non-scaling-stroke; filter:drop-shadow(0 0 8px rgba(113,112,255,.45)); }}
    .metric-row {{ color:var(--muted); font-size:13px; margin:7px 0; }} .metric-row strong {{ color:var(--text); }}
    .pos {{ color:var(--green)!important; }} .neg {{ color:var(--red)!important; }}
    .confidence {{ height:7px; background:rgba(255,255,255,.06); border-radius:999px; overflow:hidden; margin:14px 0; }} .confidence i {{ display:block; height:100%; background:linear-gradient(90deg,var(--brand),var(--green)); border-radius:999px; }}
    p {{ color:var(--muted); line-height:1.5; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }} td, th {{ padding:10px 8px; border-bottom:1px solid rgba(255,255,255,.06); text-align:left; }} th {{ color:var(--muted); font-weight:510; }}
    .rank-row {{ display:grid; grid-template-columns:86px 1fr 64px; gap:10px; align-items:center; margin:11px 0; font-size:13px; }} .rank-row div {{ height:8px; background:rgba(255,255,255,.06); border-radius:999px; overflow:hidden; }} .rank-row b {{ display:block; height:100%; background:linear-gradient(90deg,var(--accent),var(--green)); }}
    ul.feed {{ list-style:none; padding:0; margin:0; }} ul.feed li {{ border-top:1px solid rgba(255,255,255,.06); padding:12px 0; }} ul.feed b {{ display:block; }} ul.feed span {{ color:var(--muted); font-size:13px; line-height:1.45; }}
    .health-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .health-card {{ border:1px solid rgba(255,255,255,.06); border-radius:12px; padding:12px; background:rgba(255,255,255,.025); }} .health-card span {{ color:var(--muted); font-size:12px; }} .health-card strong {{ display:block; margin-top:5px; color:var(--soft); }} .health-card p {{ margin:6px 0 0; font-size:12px; }}
    pre {{ white-space:pre-wrap; max-height:330px; overflow:auto; border:1px solid var(--border); background:rgba(0,0,0,.25); padding:14px; border-radius:14px; color:#cbd5e1; font-family:'JetBrains Mono',monospace; font-size:12px; }}
    .muted {{ color:var(--muted); }} .footer {{ color:var(--muted); font-size:12px; margin:20px 0; font-family:'JetBrains Mono',monospace; }}
    @media (max-width:1100px) {{ .kpis {{ grid-template-columns:repeat(3,1fr); }} .main {{ grid-template-columns:1fr; }} .asset-grid {{ grid-template-columns:repeat(2,1fr); }} }}
    @media (max-width:720px) {{ .shell {{ padding:18px; }} header {{ flex-direction:column; }} h1 {{ font-size:38px; }} .kpis,.asset-grid,.health-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class=\"shell\">
    <header>
      <div><div class=\"eyebrow\">Market Lab · Visual Read-Only Cockpit</div><h1>Research, mock trading, and agent evidence — visible at a glance.</h1><div class=\"sub\">This page does not place trades. It only renders local Market Lab artifacts: cached prices, signals, backtests, queued mock candidates, ledger summaries, and council diagnostics.</div></div>
      <div class=\"read-only\">READ ONLY · NO BROKER ACTIONS</div>
    </header>

    <section class=\"grid kpis\">
      <div class=\"kpi\"><span>Mock equity</span><strong>{_money(equity)}</strong><small>Cash {_money(cash)}</small></div>
      <div class=\"kpi\"><span>Open positions</span><strong>{open_positions}</strong><small>Local mock portfolio</small></div>
      <div class=\"kpi\"><span>Signal mix</span><strong>{buy}/{hold}/{sell}</strong><small>BUY / HOLD / SELL</small></div>
      <div class=\"kpi\"><span>Queued mock orders</span><strong>{len(candidates)}</strong><small>Next-open candidates</small></div>
      <div class=\"kpi\"><span>Ledger decisions</span><strong>{accepted}/{rejected}</strong><small>Accepted / rejected</small></div>
      <div class=\"kpi\"><span>Options chains</span><strong>{options.get('chain_count', 0)}</strong><small>{esc(options.get('mode', 'DISABLED'))}</small></div>
    </section>

    <main class=\"grid main\">
      <section class=\"panel\"><h2>Signal board</h2><div class=\"grid asset-grid\">{signal_cards}</div></section>
      <aside class=\"grid\">
        <section class=\"panel\"><h2>Momentum rotation</h2>{momentum_rows}</section>
        <section class=\"panel\"><h2>Mock trade queue</h2><ul class=\"feed\">{candidate_rows}</ul></section>
        <section class=\"panel\"><h2>Strategy health council</h2><div class=\"grid health-grid\">{health_rows}</div></section>
      </aside>
    </main>

    <section class=\"panel\" style=\"margin-top:16px\"><h2>Options Research — PAPER ONLY</h2><div class=\"grid health-grid\"><div><h3>Covered calls</h3><ul class=\"feed\">{option_call_rows}</ul></div><div><h3>Cash-secured puts</h3><ul class=\"feed\">{option_put_rows}</ul></div></div><h3>Options guardrails</h3><ul class=\"feed\">{option_warning_rows}</ul></section>
    <section class=\"panel\" style=\"margin-top:16px\"><h2>Backtest sanity checks</h2><table><thead><tr><th>Symbol</th><th>Strategy</th><th>Return</th><th>Benchmark</th><th>Max DD</th><th>Sharpe</th><th>Trades</th></tr></thead><tbody>{backtest_rows}</tbody></table></section>
    <section class=\"grid main\" style=\"margin-top:16px\"><div class=\"panel\"><h2>Trade diagnoses</h2><ul class=\"feed\">{diagnosis_rows}</ul></div><div class=\"panel\"><h2>Latest report excerpt</h2><pre>{report_excerpt}</pre></div></section>
    <div class=\"footer\">Generated {generated} · API: /api/snapshot · Source: local Market Lab artifacts only</div>
  </div>
</body>
</html>"""


class MarketLabDashboardHandler(BaseHTTPRequestHandler):
    server_version = "MarketLabDashboard/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/snapshot":
            _json_response(self, build_dashboard_snapshot())
            return
        if parsed.path in ("/", "/index.html"):
            body = render_dashboard_html(build_dashboard_snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        _json_response(self, {"error": "not_found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        _json_response(self, {"error": "read_only_dashboard", "message": "Market Lab webapp exposes viewing endpoints only."}, 405)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def log_message(self, format: str, *args: object) -> None:
        return


def run_server(host: str = "127.0.0.1", port: int = 8766) -> None:
    server = ThreadingHTTPServer((host, port), MarketLabDashboardHandler)
    print(f"Market Lab read-only webapp: http://{host}:{port}")
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the read-only OzLabs Market Lab webapp")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    run_server(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
