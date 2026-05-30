from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_lab.alpaca import AlpacaAPIError, AlpacaConfigError, build_alpaca_client, sanitized_account_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Alpaca read-only connectivity without printing secrets")
    parser.add_argument("--env", type=Path, default=Path(".alpaca.env"), help="Path to local Alpaca env file")
    parser.add_argument("--mode", choices=["paper", "live"], default=None)
    parser.add_argument("--symbol", default="SPY", help="Optional symbol for market-data smoke check")
    args = parser.parse_args()

    try:
        client = build_alpaca_client(args.env, args.mode)
        account = sanitized_account_status(client)
        clock = client.clock()
        bars = client.stock_bars(args.symbol, start="2026-01-01", limit=1)
        print(json.dumps({"ok": True, "account": account, "clock": {"is_open": clock.get("is_open"), "timestamp": clock.get("timestamp")}, "market_data_bars": len(bars)}, indent=2, sort_keys=True))
        return 0
    except AlpacaConfigError as exc:
        print(json.dumps({"ok": False, "kind": "config", "error": str(exc)}, sort_keys=True))
        return 2
    except AlpacaAPIError as exc:
        print(json.dumps({"ok": False, "kind": "api", "status": exc.status, "error": str(exc)}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
