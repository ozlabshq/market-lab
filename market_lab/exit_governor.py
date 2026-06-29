from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .broker import OrderCandidate, Portfolio
from .data import Bar


def check_spy_relative_exit(
    symbol: str,
    asset_current: float,
    entry_price: float,
    spy_current: float,
    spy_entry: float,
    trail: float = -0.03,
) -> tuple[bool, str]:
    """Return (should_exit, reason) for a position based on SPY-relative trail since entry.

    Uses only data available at the close of the current bar (no lookahead).
    If any required price is missing or non-positive, the gate returns ``(False, ...)``
    — it never exits when data is unreliable.
    """
    if asset_current <= 0 or entry_price <= 0 or spy_current <= 0 or spy_entry <= 0:
        return False, "exit governor: invalid prices; skipping"

    asset_return = asset_current / entry_price - 1.0
    spy_return = spy_current / spy_entry - 1.0
    relative_return = asset_return - spy_return

    # Use a small epsilon to avoid floating-point boundary flips at exactly trail.
    if relative_return < trail - 1e-12:
        return (
            True,
            (
                f"SPY-relative exit governor: asset trailing SPY by {abs(relative_return):.2%} "
                f"since entry (asset {asset_return:.2%} vs SPY {spy_return:.2%}); exit at next open"
            ),
        )

    return (
        False,
        (
            f"SPY-relative hold: asset {asset_return:.2%} vs SPY {spy_return:.2%} "
            f"(relative {relative_return:.2%}, trail {trail:.2%})"
        ),
    )


def _spy_close_for_date(spy_bars: list[Bar], dt: date) -> float | None:
    """Return SPY close for the exact date, or the nearest *prior* bar."""
    close = None
    for bar in spy_bars:
        if bar.date <= dt:
            close = bar.close
        else:
            break
    return close


def _last_buy_entries_from_ledger(ledger_path: Path) -> dict[str, tuple[float, date]]:
    """Parse a mock ledger JSONL and return the most recent accepted BUY per symbol.

    Returns a dict: symbol -> (fill_price, execution_date)
    """
    entries: dict[str, tuple[float, date]] = {}
    if not ledger_path.exists():
        return entries

    try:
        with ledger_path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not row.get("accepted"):
                    continue
                if row.get("side") != "BUY":
                    continue
                symbol = row.get("symbol", "").upper()
                fill_price = row.get("fill_price")
                if fill_price is None:
                    fill_price = row.get("requested_price")
                exec_date_str = (
                    row.get("execution_date")
                    or row.get("signal_date")
                    or row.get("timestamp", "")[:10]
                )
                if not symbol or fill_price is None or not exec_date_str:
                    continue
                try:
                    exec_date = date.fromisoformat(exec_date_str)
                except ValueError:
                    continue
                if symbol not in entries or exec_date > entries[symbol][1]:
                    entries[symbol] = (float(fill_price), exec_date)
    except Exception:
        return {}

    return entries


def evaluate_spy_relative_exits(
    portfolio: Portfolio,
    prices: dict[str, float],
    spy_bars: list[Bar] | None,
    ledger_path: Path,
    trail_threshold: float = -0.03,
    signal_date: str | None = None,
) -> list[OrderCandidate]:
    """Generate *next-open* SELL candidates for positions trailing SPY by the trail threshold.

    This is a **research / paper-only** gate. It does not touch broker safety
    checks or strategy code. It reads the mock ledger to reconstruct each
    position's entry date, looks up the SPY close on that date, and compares
    current asset price to current SPY price.

    The gate is deliberately conservative:
    - If ``spy_bars`` are missing or empty, returns **no candidates**.
    - If the ledger is missing, returns **no candidates**.
    - If a position lacks a matching ledger entry, it is **skipped**.
    - If the SPY close for the entry date cannot be found, the position is **skipped**.

    Parameters
    ----------
    portfolio : Portfolio
        Current mock portfolio state (needed for open positions).
    prices : dict[str, float]
        Latest close prices for each held symbol.
    spy_bars : list[Bar] | None
        Chronological SPY price bars (oldest → newest).
    ledger_path : Path
        Path to the mock ledger JSONL.
    trail_threshold : float, default -0.03
        SPY-relative loss that triggers an exit (e.g. -0.03 = -3%).
    signal_date : str | None
        Date to stamp on generated candidates (defaults to the last SPY bar).

    Returns
    -------
    list[OrderCandidate]
        SELL candidates queued for next-open execution.
    """
    candidates: list[OrderCandidate] = []
    if not spy_bars or not portfolio.positions:
        return candidates

    if not ledger_path.exists():
        return candidates

    entries = _last_buy_entries_from_ledger(ledger_path)
    if not entries:
        return candidates

    today = signal_date or (spy_bars[-1].date.isoformat() if spy_bars else None)
    if today is None:
        return candidates

    spy_current = spy_bars[-1].close if spy_bars else None
    if spy_current is None or spy_current <= 0:
        return candidates

    for sym, pos in portfolio.positions.items():
        if pos.quantity <= 0:
            continue

        entry = entries.get(sym.upper())
        if not entry:
            continue

        entry_price, exec_date = entry
        spy_entry = _spy_close_for_date(spy_bars, exec_date)
        if spy_entry is None or spy_entry <= 0:
            continue

        asset_current = prices.get(sym.upper(), entry_price)
        should_exit, reason = check_spy_relative_exit(
            sym,
            asset_current,
            entry_price,
            spy_current,
            spy_entry,
            trail=trail_threshold,
        )

        if should_exit:
            candidates.append(
                OrderCandidate(
                    side="SELL",
                    symbol=sym.upper(),
                    quantity=pos.quantity,
                    strategy="spy_exit_governor",
                    confidence=1.0,
                    reason=reason,
                    signal_date=today,
                    reference_close=asset_current,
                    intended_execution="next_open",
                )
            )

    return candidates
