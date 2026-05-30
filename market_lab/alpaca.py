from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_LIVE_BASE_URL = "https://api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"

AlpacaMode = Literal["paper", "live"]


class AlpacaConfigError(RuntimeError):
    pass


class AlpacaAPIError(RuntimeError):
    def __init__(self, status: int | None, message: str):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class AlpacaCredentials:
    api_key_id: str
    api_secret_key: str
    mode: AlpacaMode = "paper"
    trading_base_url: str = ALPACA_PAPER_BASE_URL
    data_base_url: str = ALPACA_DATA_BASE_URL

    @property
    def headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key_id,
            "APCA-API-SECRET-KEY": self.api_secret_key,
            "Accept": "application/json",
        }


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    raw_lines: list[str] = []
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        if "=" not in stripped:
            raw_lines.append(stripped.strip().strip('"').strip("'"))
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    # Allow Ronak's quick two-line local file format without ever printing values:
    # line 1 = key id, line 2 = secret. Prefer named env vars if present.
    if raw_lines and "APCA_API_KEY_ID" not in values and "ALPACA_API_KEY_ID" not in values:
        values["APCA_API_KEY_ID"] = raw_lines[0]
    if len(raw_lines) > 1 and "APCA_API_SECRET_KEY" not in values and "ALPACA_API_SECRET_KEY" not in values:
        values["APCA_API_SECRET_KEY"] = raw_lines[1]
    return values


def load_alpaca_credentials(env_path: Path | None = None, mode: AlpacaMode | None = None) -> AlpacaCredentials:
    candidate_paths = [
        Path.home() / ".hermes" / ".alpaca.env",
        Path.cwd() / ".alpaca.env",
        env_path,
    ]
    file_values: dict[str, str] = {}
    for path in candidate_paths:
        if path is None:
            continue
        file_values.update(_parse_env_file(path.expanduser()))

    def get(*names: str) -> str:
        for name in names:
            value = file_values.get(name) or os.environ.get(name)
            if value:
                return value
        return ""

    resolved_mode = (mode or get("ALPACA_MODE", "APCA_API_MODE") or "paper").lower()
    if resolved_mode not in ("paper", "live"):
        raise AlpacaConfigError("ALPACA_MODE must be 'paper' or 'live'")
    key = get("APCA_API_KEY_ID", "ALPACA_API_KEY_ID", "ALPACA_KEY_ID")
    secret = get("APCA_API_SECRET_KEY", "ALPACA_API_SECRET_KEY", "ALPACA_SECRET_KEY")
    if not key or not secret:
        raise AlpacaConfigError("Alpaca credentials missing: set APCA_API_KEY_ID and APCA_API_SECRET_KEY")
    trading_base = get("ALPACA_TRADING_BASE_URL") or (ALPACA_PAPER_BASE_URL if resolved_mode == "paper" else ALPACA_LIVE_BASE_URL)
    data_base = get("ALPACA_DATA_BASE_URL") or ALPACA_DATA_BASE_URL
    return AlpacaCredentials(key, secret, resolved_mode, trading_base.rstrip("/"), data_base.rstrip("/"))  # type: ignore[arg-type]


@dataclass(frozen=True)
class AlpacaReadOnlyClient:
    credentials: AlpacaCredentials
    timeout: float = 15.0

    def _request(self, base_url: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = ""
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            query = "?" + urllib.parse.urlencode(clean)
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}{query}"
        request = urllib.request.Request(url, headers=self.credentials.headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="ignore")
            message = body.strip() or str(exc.reason) or "Alpaca HTTP error"
            if body.strip():
                try:
                    parsed = json.loads(body)
                    if isinstance(parsed, dict) and parsed.get("message"):
                        message = str(parsed["message"])
                except json.JSONDecodeError:
                    pass
            raise AlpacaAPIError(exc.code, message) from exc
        except urllib.error.URLError as exc:
            raise AlpacaAPIError(None, str(exc.reason)) from exc
        except json.JSONDecodeError as exc:
            raise AlpacaAPIError(None, "Alpaca returned non-JSON response") from exc

    def account(self) -> dict[str, Any]:
        return self._request(self.credentials.trading_base_url, "/v2/account")

    def clock(self) -> dict[str, Any]:
        return self._request(self.credentials.trading_base_url, "/v2/clock")

    def assets(self, status: str = "active", asset_class: str = "us_equity") -> list[dict[str, Any]]:
        data = self._request(self.credentials.trading_base_url, "/v2/assets", {"status": status, "asset_class": asset_class})
        return data if isinstance(data, list) else []

    def stock_bars(self, symbol: str, start: date | str, end: date | str | None = None, timeframe: str = "1Day", limit: int = 1000) -> list[dict[str, Any]]:
        params = {
            "symbols": symbol.upper(),
            "timeframe": timeframe,
            "start": start.isoformat() if isinstance(start, date) else start,
            "end": end.isoformat() if isinstance(end, date) else end,
            "limit": limit,
            "adjustment": "split",
            "feed": "iex",
        }
        data = self._request(self.credentials.data_base_url, "/v2/stocks/bars", params)
        bars = data.get("bars", {}) if isinstance(data, dict) else {}
        return bars.get(symbol.upper(), []) if isinstance(bars, dict) else []


def build_alpaca_client(env_path: Path | None = None, mode: AlpacaMode | None = None) -> AlpacaReadOnlyClient:
    return AlpacaReadOnlyClient(load_alpaca_credentials(env_path, mode))


def sanitized_account_status(client: AlpacaReadOnlyClient) -> dict[str, Any]:
    account = client.account()
    return {
        "mode": client.credentials.mode,
        "status": account.get("status"),
        "currency": account.get("currency"),
        "trading_blocked": account.get("trading_blocked"),
        "account_blocked": account.get("account_blocked"),
        "pattern_day_trader": account.get("pattern_day_trader"),
        "multiplier": account.get("multiplier"),
    }
