from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from .config import OPTIONS_CHAIN_DIR, ensure_dirs

OptionType = Literal["CALL", "PUT"]


@dataclass(frozen=True)
class OptionQuote:
    bid: float
    ask: float
    mid: float
    volume: int
    open_interest: int

    @property
    def spread_pct(self) -> float:
        if self.mid <= 0:
            return 1.0
        return (self.ask - self.bid) / self.mid


@dataclass(frozen=True)
class OptionGreeks:
    delta: float
    gamma: float
    theta: float
    vega: float
    implied_volatility: float


@dataclass(frozen=True)
class OptionContract:
    underlying: str
    expiration: str
    strike: float
    option_type: OptionType
    quote: OptionQuote
    greeks: OptionGreeks

    @property
    def contract_id(self) -> str:
        cp = "C" if self.option_type == "CALL" else "P"
        return f"{self.underlying.upper()}-{self.expiration}-{cp}-{self.strike:.2f}"

    def dte(self, as_of: str) -> int:
        as_date = datetime.fromisoformat(as_of.replace("Z", "+00:00")).date() if "T" in as_of else date.fromisoformat(as_of)
        return (date.fromisoformat(self.expiration) - as_date).days


@dataclass(frozen=True)
class OptionChainSnapshot:
    underlying: str
    underlying_price: float
    as_of: str
    source: str
    contracts: list[OptionContract]


def _snapshot_path(symbol: str, chain_dir: Path = OPTIONS_CHAIN_DIR) -> Path:
    safe = symbol.upper().replace("/", "_").replace("-", "_")
    return chain_dir / f"{safe}.json"


def save_option_chain_snapshot(snapshot: OptionChainSnapshot, chain_dir: Path = OPTIONS_CHAIN_DIR) -> Path:
    ensure_dirs()
    path = _snapshot_path(snapshot.underlying, chain_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(snapshot), indent=2, sort_keys=True))
    return path


def load_option_chain_snapshot(symbol: str, chain_dir: Path = OPTIONS_CHAIN_DIR) -> OptionChainSnapshot:
    path = _snapshot_path(symbol, chain_dir)
    data = json.loads(path.read_text())
    contracts = [
        OptionContract(
            underlying=c["underlying"],
            expiration=c["expiration"],
            strike=float(c["strike"]),
            option_type=c["option_type"],
            quote=OptionQuote(**c["quote"]),
            greeks=OptionGreeks(**c["greeks"]),
        )
        for c in data.get("contracts", [])
    ]
    return OptionChainSnapshot(
        underlying=data["underlying"],
        underlying_price=float(data["underlying_price"]),
        as_of=data["as_of"],
        source=data.get("source", "unknown"),
        contracts=contracts,
    )


def load_available_option_chains(chain_dir: Path = OPTIONS_CHAIN_DIR) -> list[OptionChainSnapshot]:
    if not chain_dir.exists():
        return []
    snapshots: list[OptionChainSnapshot] = []
    for path in sorted(chain_dir.glob("*.json")):
        try:
            snapshots.append(load_option_chain_snapshot(path.stem, chain_dir))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return snapshots
