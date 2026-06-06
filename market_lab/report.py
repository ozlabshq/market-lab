from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .backtest import BacktestResult
from .broker import OrderCandidate, OrderDecision, Portfolio
from .config import OPTIONS_CHAIN_DIR, REPORT_DIR, TSMOM_LEDGER, TSMOM_REPORT_DIR, TSMOM_STATE, VT_TREND_LEDGER, VT_TREND_REPORT_DIR, VT_TREND_STATE, ensure_dirs
from .factors import FactorSnapshot
from .options_paper import OptionPaperPortfolio, build_option_positions_view, load_option_paper_portfolio
from .options_screeners import CashSecuredPutCandidate, CoveredCallCandidate
from .signals import CrossSectionalRank, Signal, rank_signals


def _parse_report_table(report_text: str) -> dict[str, str]:
    """Extract key-value pairs from a markdown table in an independent track report."""
    result: dict[str, str] = {}
    in_table = False
    for line in report_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("| Metric | Value |"):
            in_table = True
            continue
        if in_table and stripped.startswith("|") and "---" not in stripped:
            parts = [p.strip() for p in stripped.split("|")]
            # parts = ['', 'Metric', 'Value', '']
            if len(parts) >= 3 and parts[1] and parts[2]:
                result[parts[1]] = parts[2]
        if in_table and not stripped.startswith("|"):
            in_table = False
    return result


def _vt_trend_section_from_report() -> list[str]:
    """Read the latest vt_trend report and surface its summary in the ensemble report."""
    latest = VT_TREND_REPORT_DIR / "latest.md"
    if not latest.exists():
        return []
    try:
        text = latest.read_text()
    except Exception:
        return []
    metrics = _parse_report_table(text)
    if not metrics:
        return []
    lines = [
        "",
        "## vt_trend Independent Mock Tracking",
        "",
        "**Status:** Research tracking — not wired into ensemble. Evidence collected daily.",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]
    for key in (
        "Cash", "Position", "Equity", "Position weight", "Target weight",
        "Vol20 (ann.)", "Drawdown from 90d peak", "Drawdown level",
        "Trend regime", "Re-entry allowed", "Cumulative fills", "Pending candidates",
        "Data source",
    ):
        if key in metrics:
            lines.append(f"| {key} | {metrics[key]} |")
    return lines


def _tsmom_section_from_report() -> list[str]:
    """Read the latest TSMOM report and surface its summary in the ensemble report."""
    latest = TSMOM_REPORT_DIR / "latest.md"
    if not latest.exists():
        return []
    try:
        text = latest.read_text()
    except Exception:
        return []
    metrics = _parse_report_table(text)
    if not metrics:
        return []
    lines = [
        "",
        "## TSMOM Independent Mock Tracking",
        "",
        "**Status:** Research tracking — not wired into ensemble. Evidence collected daily.",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]
    for key in (
        "Cash", "Position", "Equity", "Position weight", "Target weight",
        "Vol20 (ann.)", "Raw momentum", "Drawdown from 120d peak",
        "Cumulative fills", "Pending candidates", "Data source",
    ):
        if key in metrics:
            lines.append(f"| {key} | {metrics[key]} |")
    return lines


def _independent_tracks_summary(include_independent_tracks: bool = True) -> list[str]:
    if not include_independent_tracks:
        return []
    lines: list[str] = []
    vt_lines = _vt_trend_section_from_report()
    tsmom_lines = _tsmom_section_from_report()
    if vt_lines or tsmom_lines:
        lines += [
            "",
            "---",
            "",
            "## Independent Track Summaries — Research Only",
            "",
            "These tracks run in isolated mock portfolios (not the ensemble). "
            "They are surfaced here for visibility only; no live orders, no broker integration.",
        ]
    if vt_lines:
        lines.extend(vt_lines)
    if tsmom_lines:
        lines.extend(tsmom_lines)
    if vt_lines or tsmom_lines:
        lines += [
            "",
            "*Track reports are read-only snapshots. No ensemble wiring. No live trading.*",
        ]
    return lines


def render_report(
    signals: list[Signal],
    backtests: list[BacktestResult],
    decisions: list[OrderDecision],
    portfolio: Portfolio,
    prices: dict[str, float],
    data_sources: dict[str, str],
    candidates: list[OrderCandidate] | None = None,
    family_signals: dict[str, list[Signal]] | None = None,
    cross_sectional: list[CrossSectionalRank] | None = None,
    factor_snapshots: dict[str, FactorSnapshot] | None = None,
    options_research: dict[str, list[CoveredCallCandidate] | list[CashSecuredPutCandidate] | list[str]] | None = None,
    paper: OptionPaperPortfolio | None = None,
    include_independent_tracks: bool = True,
    spy_benchmark: dict[str, float | str | None] | None = None,
) -> str:
    ensure_dirs()
    candidates = candidates or []
    family_signals = family_signals or {}
    cross_sectional = cross_sectional or []
    factor_snapshots = factor_snapshots or {}
    options_research = options_research or {"covered_calls": [], "cash_secured_puts": [], "warnings": []}
    spy_benchmark = spy_benchmark or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M %Z")
    buys = [s for s in rank_signals(signals) if s.action == "BUY"][:8]
    holds = [s for s in rank_signals(signals) if s.action == "HOLD"][:8]
    sells = [s for s in rank_signals(signals) if s.action == "SELL"][:8]
    lines = [
        f"# OzLabs Market Lab Daily Research Report — {now}",
        "",
        "Status: DRY RUN / RESEARCH ONLY. No live orders. No investment advice. Ronak remains final decision maker.",
        "",
        "## Guardrails",
        "- Live trading disabled",
        "- Broker integration disabled",
        "- Options paper research enabled; live options/broker execution disabled",
        "- Margin/shorting disabled",
        "- After-close signals become next-session candidates only; no same-close fills",
        "- Mock fills use next available open through explicit candidate ledger",
        "",
        "## Portfolio",
        f"- Cash: ${portfolio.cash:,.2f}",
        f"- Estimated equity: ${portfolio.equity(prices):,.2f}",
        f"- Open positions: {len(portfolio.positions)}",
        "",
    ]
    # SPY buy/hold benchmark section
    bm_equity = spy_benchmark.get("benchmark_equity")
    bm_return = spy_benchmark.get("benchmark_return")
    bm_start_price = spy_benchmark.get("start_price")
    bm_current_price = spy_benchmark.get("current_price")
    bm_start_date = spy_benchmark.get("start_date_str")
    bm_source = spy_benchmark.get("data_source")
    if isinstance(bm_equity, (int, float)) and isinstance(bm_start_price, (int, float)) and isinstance(bm_current_price, (int, float)):
        equity = portfolio.equity(prices)
        vs_bm = (equity / bm_equity - 1) if bm_equity > 0 else 0.0
        vs_bm_str = f"{vs_bm:+.2%}"
        bm_ret_str = f"{bm_return:+.2%}" if isinstance(bm_return, (int, float)) else "n/a"
        lines += [
            "## SPY Buy/Hold Benchmark",
            f"- Benchmark start: {bm_start_date} (SPY @ ${bm_start_price:,.2f})",
            f"- SPY current: ${bm_current_price:,.2f}",
            f"- Benchmark equity: ${bm_equity:,.2f} ({bm_ret_str})",
            f"- Portfolio equity: ${equity:,.2f}",
            f"- Portfolio vs benchmark: {vs_bm_str}",
            f"- Benchmark data source: {bm_source}",
            "",
        ]
    else:
        lines += [
            "## SPY Buy/Hold Benchmark",
            "- SPY benchmark unavailable (no price data)",
            "",
        ]
    lines += [
        "## Factor Lens — valuation / quality / growth / AI exposure",
    ]
    if not factor_snapshots:
        lines.append("- No factor snapshots available")
    else:
        for sym, f in sorted(factor_snapshots.items()):
            pe = "n/a" if f.pe_ratio is None else f"{f.pe_ratio:.1f}"
            pb = "n/a" if f.pb_ratio is None else f"{f.pb_ratio:.1f}"
            growth = "n/a" if f.revenue_growth_yoy is None else f"{f.revenue_growth_yoy:.1%}"
            fcf = "n/a" if f.free_cash_flow_yield is None else f"{f.free_cash_flow_yield:.1%}"
            lines.append(f"- {sym}: P/E {pe}, P/B {pb}, rev growth {growth}, FCF yield {fcf}, AI {f.ai_impact_score:.2f}, sentiment {f.sentiment_proxy:.2f}; source {f.source}")
    lines += [
        "",
        "## Ensemble BUY candidates",
    ]
    if not buys:
        lines.append("- None today")
    for s in buys:
        lines.append(f"- {s.symbol}: close ${s.close:.2f}, confidence {s.confidence:.2f}, target {s.target_weight:.0%}; {s.reason}")
    lines += ["", "## HOLD watchlist"]
    if not holds:
        lines.append("- None")
    for s in holds[:5]:
        lines.append(f"- {s.symbol}: ${s.close:.2f}; {s.reason}")
    lines += ["", "## SELL / avoid signals"]
    if not sells:
        lines.append("- None")
    for s in sells[:5]:
        lines.append(f"- {s.symbol}: ${s.close:.2f}; {s.reason}")

    lines += ["", "## Strategy family diagnostics"]
    if not family_signals:
        lines.append("- No family diagnostics generated")
    else:
        for symbol in sorted(family_signals)[:8]:
            summary = "; ".join(f"{sig.strategy}:{sig.action}/{sig.confidence:.2f}" for sig in family_signals[symbol])
            lines.append(f"- {symbol}: {summary}")

    lines += ["", "## Cross-sectional momentum ranks — 6m formation / 1m skip"]
    if not cross_sectional:
        lines.append("- Not enough universe/history for ranking")
    for rank in cross_sectional[:10]:
        lines.append(f"- #{rank.rank} {rank.symbol}: score {rank.score:.1%}, percentile {rank.percentile:.0%}; {rank.reason}")

    lines += ["", "## Backtest sanity checks — not edge claims"]
    for b in sorted(backtests, key=lambda x: x.total_return, reverse=True)[:12]:
        lines.append(f"- {b.symbol} / {b.strategy}: strategy {b.total_return:.1%}, buy/hold {b.benchmark_return:.1%}, MDD {b.max_drawdown:.1%}, Sharpe {b.sharpe:.2f}, trades {b.trades}")

    lines += ["", "## Options Research — Paper Only"]
    lines.append("- Status: options live trading disabled; candidates are research/paper only")
    cc = options_research.get("covered_calls", [])
    csp = options_research.get("cash_secured_puts", [])
    warnings = options_research.get("warnings", [])
    lines += ["", "### Covered Call Candidates"]
    if not cc:
        lines.append("- None passed guardrails")
    for c in cc[:8]:
        lines.append(f"- {c.contract.underlying} {c.contract.expiration} ${c.contract.strike:.2f} CALL x{c.contracts}: premium ${c.premium:,.2f}, annualized {c.annualized_yield:.1%}, OTM {c.otm_pct:.1%}, delta {c.contract.greeks.delta:.2f}; {c.reason}")
    lines += ["", "### Cash-Secured Put Candidates"]
    if not csp:
        lines.append("- None passed guardrails")
    for p in csp[:8]:
        lines.append(f"- {p.contract.underlying} {p.contract.expiration} ${p.contract.strike:.2f} PUT x{p.contracts}: reserve ${p.cash_reserved:,.2f}, premium ${p.premium:,.2f}, annualized {p.annualized_yield:.1%}, OTM {p.otm_pct:.1%}, delta {p.contract.greeks.delta:.2f}; {p.reason}")
    lines += ["", "### Liquidity / Guardrail Warnings"]
    if not warnings:
        lines.append("- None")
    for w in warnings[:10]:
        lines.append(f"- {w}")

    # Paper option positions & reserves
    if paper is not None:
        paper_positions = build_option_positions_view(paper, OPTIONS_CHAIN_DIR)
        lines += ["", "### Active Paper Option Positions"]
        if not paper_positions:
            lines.append("- No open paper option positions")
        else:
            for v in paper_positions:
                pnl_str = f"P&L ${v.unrealized_pnl:,.2f}" if v.unrealized_pnl != 0.0 else "P&L —"
                lines.append(f"- {v.side} {v.contracts} {v.underlying} {v.option_type} ${v.strike:.2f} exp {v.expiration}: mark ${v.mark:.2f}, avg ${v.avg_price:.2f}, {pnl_str}")
        lines += ["", "### Paper Collateral Reserves"]
        lines.append(f"- Reserved cash: ${paper.reserved_cash:,.2f}")
        if paper.reserved_shares:
            for sym, qty in sorted(paper.reserved_shares.items()):
                lines.append(f"- Reserved shares {sym}: {qty}")
        else:
            lines.append("- No reserved shares")

    lines += ["", "## Next-session order candidates queued"]
    if not candidates:
        lines.append("- None queued")
    for c in candidates:
        lines.append(f"- {c.side} {c.quantity} {c.symbol} via {c.strategy}, confidence {c.confidence:.2f}, reference close ${c.reference_close:.2f}, intended fill {c.intended_execution}: {c.reason}")

    lines += ["", "## Mock broker decisions logged today"]
    if not decisions:
        lines.append("- No mock orders placed")
    for d in decisions:
        status = "ACCEPTED" if d.accepted else "REJECTED"
        fill = f" fill ${d.fill_price:.2f}" if d.fill_price else ""
        lines.append(f"- {status} {d.side} {d.quantity} {d.symbol} @ ${d.requested_price:.2f}{fill}: {d.reason}")
    lines += ["", "## Data sources"]
    for sym, src in sorted(data_sources.items()):
        lines.append(f"- {sym}: {src}")
    lines += _independent_tracks_summary(include_independent_tracks)
    lines += [
        "",
        "## Research basis",
        "- Time-series momentum: Moskowitz/Ooi/Pedersen; Hurst/Ooi/Pedersen trend following evidence",
        "- Cross-sectional momentum: Jegadeesh/Titman; Asness/Moskowitz/Pedersen value+momentum framing",
        "- RSI pullback: Wilder RSI, practitioner mean-reversion patterns; only inside regime filters",
        "- MA baseline: Brock/Lakonishok/LeBaron technical trading rules; treated as baseline only",
        "- Factor lens: valuation/quality/growth principles from Fama-French, quality-minus-junk, and practitioner fundamental screens; treated as overlay, not standalone proof",
        "",
        "## Next operator action",
        "- Review whether queued candidates make economic sense. Promote only after backtest + mock evidence, never from one report.",
    ]
    return "\n".join(lines) + "\n"


def save_report(text: str, report_dir: Path = REPORT_DIR) -> Path:
    ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = report_dir / f"market-lab-{stamp}.md"
    path.write_text(text)
    latest = report_dir / "latest.md"
    latest.write_text(text)
    return path
