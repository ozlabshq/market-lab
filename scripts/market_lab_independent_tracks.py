#!/usr/bin/env python3
"""
Manually run independent research tracks (vt_trend + TSMOM) on demand.

Safety:
  Research/mock-only — never touches live brokers.
  Runs existing per-track scripts as-is; no cron wiring.
  Synthetic data by default; pass --network for yfinance.
  Pass --require-live-data to abort on synthetic fallback.

Usage:
  python scripts/market_lab_independent_tracks.py
  python scripts/market_lab_independent_tracks.py --network
  python scripts/market_lab_independent_tracks.py --network --require-live-data --symbol SPY --days 260
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parents[1]

# Track script paths, relative to project root
TRACKS: dict[str, Path] = {
    "vt_trend": Path("scripts/market_lab_vt_trend.py"),
    "tsmom": Path("scripts/market_lab_tsmom.py"),
}


def _run_track(name: str, script: Path, python: str, network: bool, require_live_data: bool, days: int, symbol: str, track_args: list[str]) -> tuple[int, str, str]:
    """Run a single track script. Returns (exit_code, stdout, stderr)."""
    cmd = [
        python,
        str(script),
        "--days", str(days),
        "--symbol", symbol,
    ]
    if network:
        cmd.append("--network")
    if require_live_data:
        cmd.append("--require-live-data")
    cmd.extend(track_args)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result.returncode, result.stdout, result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manual runner for independent research tracks (vt_trend + TSMOM). "
                    "Not wired into cron. Research/mock-only.",
    )
    parser.add_argument("--network", action="store_true", help="Attempt yfinance before cache/synthetic fallback")
    parser.add_argument("--require-live-data", action="store_true", help="Abort if any symbol falls back to synthetic data")
    parser.add_argument("--days", type=int, default=260)
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter to use for track scripts")
    parser.add_argument("--track", choices=list(TRACKS.keys()), action="append", help="Run specific track only (can specify multiple)")
    parser.add_argument("--vt-trend-args", default="", help="Extra args passed to vt_trend script (quoted string)")
    parser.add_argument("--tsmom-args", default="", help="Extra args passed to TSMOM script (quoted string)")
    args = parser.parse_args()

    tracks_to_run = args.track or list(TRACKS.keys())

    print("=" * 60)
    print(" OzLabs Market Lab — Independent Track Runner ")
    print("=" * 60)
    print(f"Safety: research/mock-only | No live orders | No cron wiring")
    print(f"Symbol: {args.symbol} | Days: {args.days} | Network: {args.network}")
    print(f"Tracks: {', '.join(tracks_to_run)}")
    print("-" * 60)

    all_ok = True
    outputs: dict[str, tuple[str, str]] = {}

    track_extra_args: dict[str, list[str]] = {
        "vt_trend": args.vt_trend_args.split() if args.vt_trend_args else [],
        "tsmom": args.tsmom_args.split() if args.tsmom_args else [],
    }

    for name in tracks_to_run:
        script = TRACKS[name]
        print(f"\n>>> Running {name} ...")
        rc, stdout, stderr = _run_track(
            name, script, args.python, args.network, args.require_live_data,
            args.days, args.symbol, track_extra_args.get(name, []),
        )
        outputs[name] = (stdout, stderr)

        # Print last few lines of stdout for visibility
        if stdout:
            lines = stdout.strip().splitlines()
            for line in lines[-12:]:
                print(f"    {line}")
        if stderr:
            for line in stderr.strip().splitlines():
                print(f"    [stderr] {line}")

        if rc != 0:
            print(f"    *** {name} exited with code {rc} ***")
            all_ok = False
        else:
            print(f"    {name} completed OK")

    print("\n" + "=" * 60)
    print(" Summary ")
    print("=" * 60)
    for name in tracks_to_run:
        rc_tag = "OK" if name in outputs and all_ok else "FAIL"
        # Re-evaluate per-track rc from stored outputs; use a simpler flag
        stdout, stderr = outputs[name]
        rc_flag = "OK" if not stderr.strip().startswith("Traceback") and all_ok else "FAIL"
        print(f"  {name:12s} {rc_flag}")
    print("-" * 60)
    print("No live broker orders were placed.")
    print("=" * 60)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
