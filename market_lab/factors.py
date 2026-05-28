from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from .config import FACTOR_DIR, ensure_dirs


@dataclass(frozen=True)
class FactorSnapshot:
    symbol: str
    as_of_date: date
    pe_ratio: float | None
    pb_ratio: float | None
    revenue_growth_yoy: float | None
    gross_margin: float | None
    free_cash_flow_yield: float | None
    ai_impact_score: float
    sentiment_proxy: float
    source: str

    def as_row(self) -> dict[str, str]:
        def fmt(value: float | None) -> str:
            return "" if value is None else f"{value:.6f}"
        return {
            "symbol": self.symbol,
            "as_of_date": self.as_of_date.isoformat(),
            "pe_ratio": fmt(self.pe_ratio),
            "pb_ratio": fmt(self.pb_ratio),
            "revenue_growth_yoy": fmt(self.revenue_growth_yoy),
            "gross_margin": fmt(self.gross_margin),
            "free_cash_flow_yield": fmt(self.free_cash_flow_yield),
            "ai_impact_score": f"{self.ai_impact_score:.6f}",
            "sentiment_proxy": f"{self.sentiment_proxy:.6f}",
            "source": self.source,
        }


AI_EXPOSURE_KEYWORDS = {
    "NVDA": 0.98, "AMD": 0.80, "AVGO": 0.75, "SMCI": 0.78, "MSFT": 0.86,
    "GOOGL": 0.84, "AMZN": 0.78, "META": 0.74, "TSLA": 0.62, "AAPL": 0.48,
    "COIN": 0.30, "MSTR": 0.28, "QQQ": 0.60, "SPY": 0.35, "IWM": 0.22,
}

FIELDNAMES = [
    "symbol", "as_of_date", "pe_ratio", "pb_ratio", "revenue_growth_yoy", "gross_margin",
    "free_cash_flow_yield", "ai_impact_score", "sentiment_proxy", "source",
]


def factor_path(symbol: str) -> Path:
    safe = symbol.upper().replace("/", "_").replace("-", "_")
    return FACTOR_DIR / f"{safe}.csv"


def _float_or_none(value: str | float | int | None) -> float | None:
    if value in (None, "", "None", "nan"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _from_row(row: dict[str, str]) -> FactorSnapshot:
    return FactorSnapshot(
        symbol=row["symbol"].upper(),
        as_of_date=datetime.strptime(row["as_of_date"], "%Y-%m-%d").date(),
        pe_ratio=_float_or_none(row.get("pe_ratio")),
        pb_ratio=_float_or_none(row.get("pb_ratio")),
        revenue_growth_yoy=_float_or_none(row.get("revenue_growth_yoy")),
        gross_margin=_float_or_none(row.get("gross_margin")),
        free_cash_flow_yield=_float_or_none(row.get("free_cash_flow_yield")),
        ai_impact_score=float(row.get("ai_impact_score") or 0.0),
        sentiment_proxy=float(row.get("sentiment_proxy") or 0.0),
        source=row.get("source") or "cache",
    )


def load_cached_factors(symbol: str, max_age_days: int = 14) -> FactorSnapshot | None:
    path = factor_path(symbol)
    if not path.exists():
        return None
    try:
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return None
        snapshot = _from_row(rows[-1])
        if snapshot.as_of_date < date.today() - timedelta(days=max_age_days):
            return None
        return snapshot
    except (OSError, ValueError, KeyError):
        return None


def save_factors(snapshot: FactorSnapshot) -> Path:
    ensure_dirs()
    path = factor_path(snapshot.symbol)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerow(snapshot.as_row())
    return path


def synthetic_factors(symbol: str, as_of: date | None = None) -> FactorSnapshot:
    symbol = symbol.upper()
    rng = random.Random(sum(ord(c) for c in symbol) + 13_337)
    ai_score = AI_EXPOSURE_KEYWORDS.get(symbol, rng.uniform(0.05, 0.45))
    # Plausible placeholders. Synthetic factors are for pipeline continuity only, not evidence.
    return FactorSnapshot(
        symbol=symbol,
        as_of_date=as_of or date.today(),
        pe_ratio=round(rng.uniform(8, 55), 2),
        pb_ratio=round(rng.uniform(0.8, 14), 2),
        revenue_growth_yoy=round(rng.uniform(-0.12, 0.35), 4),
        gross_margin=round(rng.uniform(0.20, 0.78), 4),
        free_cash_flow_yield=round(rng.uniform(-0.03, 0.09), 4),
        ai_impact_score=round(ai_score, 4),
        sentiment_proxy=round(rng.uniform(-0.35, 0.45), 4),
        source="synthetic",
    )


def _yfinance_factors(symbol: str) -> FactorSnapshot | None:
    try:
        import yfinance as yf  # type: ignore
        info = yf.Ticker(symbol).get_info()
        if not info:
            return None
        market_cap = _float_or_none(info.get("marketCap"))
        fcf = _float_or_none(info.get("freeCashflow"))
        fcf_yield = (fcf / market_cap) if fcf is not None and market_cap and market_cap > 0 else None
        ai_score = AI_EXPOSURE_KEYWORDS.get(symbol.upper(), 0.10)
        long_summary = str(info.get("longBusinessSummary") or "").lower()
        ai_mentions = sum(1 for term in ("artificial intelligence", " ai ", "machine learning", "accelerator", "data center", "gpu") if term in long_summary)
        ai_score = min(1.0, ai_score + 0.08 * ai_mentions)
        snapshot = FactorSnapshot(
            symbol=symbol.upper(),
            as_of_date=date.today(),
            pe_ratio=_float_or_none(info.get("trailingPE") or info.get("forwardPE")),
            pb_ratio=_float_or_none(info.get("priceToBook")),
            revenue_growth_yoy=_float_or_none(info.get("revenueGrowth")),
            gross_margin=_float_or_none(info.get("grossMargins")),
            free_cash_flow_yield=fcf_yield,
            ai_impact_score=round(ai_score, 4),
            sentiment_proxy=0.0,
            source="yfinance_info",
        )
        if all(getattr(snapshot, field) is None for field in ("pe_ratio", "pb_ratio", "revenue_growth_yoy", "gross_margin", "free_cash_flow_yield")):
            return None
        return snapshot
    except Exception:
        return None


def fetch_factors(symbol: str, prefer_network: bool = False, max_cache_age_days: int = 14) -> tuple[FactorSnapshot, str]:
    ensure_dirs()
    cached = load_cached_factors(symbol, max_age_days=max_cache_age_days)
    if cached:
        return cached, cached.source if cached.source != "synthetic" else "cache_synthetic"
    if prefer_network:
        snapshot = _yfinance_factors(symbol)
        if snapshot:
            save_factors(snapshot)
            return snapshot, snapshot.source
    snapshot = synthetic_factors(symbol)
    save_factors(snapshot)
    return snapshot, "synthetic"


def factor_score(snapshot: FactorSnapshot) -> tuple[float, list[str]]:
    """Small, interpretable factor overlay score. Not an edge claim."""
    score = 0.0
    reasons: list[str] = []
    if snapshot.pe_ratio is not None:
        if snapshot.pe_ratio < 18:
            score += 0.08; reasons.append(f"reasonable P/E {snapshot.pe_ratio:.1f}")
        elif snapshot.pe_ratio > 55:
            score -= 0.08; reasons.append(f"stretched P/E {snapshot.pe_ratio:.1f}")
    if snapshot.free_cash_flow_yield is not None:
        if snapshot.free_cash_flow_yield > 0.04:
            score += 0.08; reasons.append(f"FCF yield {snapshot.free_cash_flow_yield:.1%}")
        elif snapshot.free_cash_flow_yield < -0.01:
            score -= 0.06; reasons.append(f"negative FCF yield {snapshot.free_cash_flow_yield:.1%}")
    if snapshot.revenue_growth_yoy is not None:
        if snapshot.revenue_growth_yoy > 0.15:
            score += 0.07; reasons.append(f"revenue growth {snapshot.revenue_growth_yoy:.1%}")
        elif snapshot.revenue_growth_yoy < -0.03:
            score -= 0.05; reasons.append(f"revenue decline {snapshot.revenue_growth_yoy:.1%}")
    if snapshot.gross_margin is not None and snapshot.gross_margin > 0.55:
        score += 0.03; reasons.append(f"high gross margin {snapshot.gross_margin:.1%}")
    if snapshot.ai_impact_score > 0.70:
        score += 0.08; reasons.append(f"high AI exposure {snapshot.ai_impact_score:.2f}")
    elif snapshot.ai_impact_score < 0.15:
        score -= 0.02; reasons.append(f"low AI exposure {snapshot.ai_impact_score:.2f}")
    if snapshot.sentiment_proxy > 0.25:
        score += 0.03; reasons.append(f"positive sentiment proxy {snapshot.sentiment_proxy:.2f}")
    elif snapshot.sentiment_proxy < -0.25:
        score -= 0.03; reasons.append(f"negative sentiment proxy {snapshot.sentiment_proxy:.2f}")
    return max(-0.25, min(0.25, score)), reasons or ["neutral factor lens"]
