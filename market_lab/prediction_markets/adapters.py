from __future__ import annotations

from pathlib import Path

from market_lab.prediction_markets.models import parse_json_bytes


class FrozenFileAdapter:
    def read(self, path: Path) -> tuple[bytes, dict]:
        data = path.read_bytes()
        return data, parse_json_bytes(data)
