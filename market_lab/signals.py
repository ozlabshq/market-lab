from __future__ import annotations

from dataclasses import dataclass, field, replace
from statistics import mean

from .data import Bar
from .factors import FactorSnapshot, factor_score
from .indicators import ema, returns, rolling_peak, rolling_volatility, rsi, sma


@dataclass(frozen=True)
class Signal:
    symbol: str
    action: str  # BUY, SELL, HOLD
    confidence: float
    reason: str
    close: float
    rsi14: float | None
    sma20: float | None
    sma50: float | None
    volatility20: float | None
    strategy: str = "baseline_scoring"
    target_weight: float = 0.0
    evidence: dict[str, float | str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class CrossSectionalRank:
    symbol: str
    score: float
    rank: int
    percentile: float
    reason: str


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _close(bars: list[Bar]) -> float:
    return bars[-1].close if bars else 0.0


def _insufficient(symbol: str, bars: list[Bar], strategy: str, needed: int) -> Signal:
    return Signal(symbol, "HOLD", 0.0, f"{strategy}: insufficient history; need {needed} bars", _close(bars), None, None, None, None, strategy)


def _momentum_over_lookback(bars: list[Bar], lookback: int) -> float | None:
    """Lookahead-free trailing return ending at the latest provided bar."""
    if lookback <= 0 or len(bars) < lookback:
        return None
    start = bars[-lookback].close
    end = bars[-1].close
    if start <= 0 or end <= 0:
        return None
    return end / start - 1.0


def generate_signal(symbol: str, bars: list[Bar]) -> Signal:
    """Legacy baseline technical score: useful as a sanity-check, not an edge claim."""
    if len(bars) < 60:
        close = bars[-1].close if bars else 0.0
        return Signal(symbol, "HOLD", 0.0, "insufficient history", close, None, None, None, None)
    closes = [b.close for b in bars]
    s20 = sma(closes, 20)[-1]
    s50 = sma(closes, 50)[-1]
    e12 = ema(closes, 12)[-1]
    e26 = ema(closes, 26)[-1]
    r14 = rsi(closes, 14)[-1]
    vol20 = rolling_volatility(closes, 20)[-1]
    close = closes[-1]
    reasons = []
    score = 0.0
    if s20 and s50 and close > s20 > s50:
        score += 0.45
        reasons.append("uptrend: close > SMA20 > SMA50")
    if e12 and e26 and e12 > e26:
        score += 0.20
        reasons.append("short EMA above long EMA")
    if r14 is not None and 45 <= r14 <= 70:
        score += 0.20
        reasons.append(f"RSI constructive ({r14:.1f})")
    elif r14 is not None and r14 > 78:
        score -= 0.35
        reasons.append(f"RSI overheated ({r14:.1f})")
    elif r14 is not None and r14 < 30:
        score += 0.10
        reasons.append(f"RSI washed out ({r14:.1f})")
    if vol20 is not None and vol20 < 0.75:
        score += 0.10
        reasons.append(f"vol manageable ({vol20:.0%})")
    elif vol20 is not None:
        score -= 0.20
        reasons.append(f"high vol ({vol20:.0%})")
    if score >= 0.55:
        action = "BUY"
    elif score <= -0.20:
        action = "SELL"
    else:
        action = "HOLD"
    return Signal(symbol, action, _clamp(score), "; ".join(reasons) or "no clear edge", close, r14, s20, s50, vol20)


def generate_tsmom_signal(symbol: str, bars: list[Bar], lookbacks: tuple[int, ...] = (20, 60, 120), target_vol: float = 0.15, spy_bars: list[Bar] | None = None) -> Signal:
    """Time-series momentum / trend-following signal.

    Literature basis: Moskowitz/Ooi/Pedersen TSMOM, Hurst/Ooi/Pedersen trend following,
    and classic practitioner trend filters. EOD signal only; execution must happen next bar.
    Optional SPY bars add a benchmark-relative dual-momentum guard: buy only when the
    asset's trailing momentum beats SPY and SPY itself is in a positive regime.
    """
    needed = max(lookbacks) + 21
    if len(bars) < needed:
        return _insufficient(symbol, bars, "tsmom", needed)
    closes = [b.close for b in bars]
    close = closes[-1]
    components = [(close / closes[-lb] - 1.0) for lb in lookbacks if closes[-lb] > 0]
    raw_momentum = mean(components) if components else 0.0
    vol20 = rolling_volatility(closes, 20)[-1] or 0.0
    s20 = sma(closes, 20)[-1]
    s50 = sma(closes, 50)[-1]
    s100 = sma(closes, 100)[-1]
    r14 = rsi(closes, 14)[-1]
    trailing_peak = max(closes[-120:])
    drawdown_from_peak = close / trailing_peak - 1 if trailing_peak > 0 else 0.0
    trend_confirmed = bool(s20 and s50 and close > s20 > s50)
    regime_ok = bool(s100 and close > s100 and vol20 < 1.00)
    vol_scaled = raw_momentum / max(vol20, 0.05)
    confidence = _clamp(abs(vol_scaled) * 0.55)
    evidence: dict[str, float | str | None] = {"raw_momentum": raw_momentum, "vol20": vol20, "vol_scaled": vol_scaled, "target_vol": target_vol, "drawdown_from_peak": drawdown_from_peak}
    spy_momentum = None
    relative_momentum = None
    if spy_bars is not None:
        aligned_spy_bars = spy_bars[-len(bars):] if len(spy_bars) > len(bars) else spy_bars
        spy_momentum = _momentum_over_lookback(aligned_spy_bars, max(lookbacks))
        if spy_momentum is not None:
            relative_momentum = raw_momentum - spy_momentum
            evidence.update({"spy_momentum": spy_momentum, "spy_relative_momentum": relative_momentum})
    if drawdown_from_peak <= -0.15:
        return Signal(symbol, "SELL", max(0.45, confidence), f"TSMOM negative/drawdown guard: {drawdown_from_peak:.1%} below trailing peak; reduce/avoid", close, r14, s20, s50, vol20, "tsmom", 0.0, evidence)
    if spy_momentum is not None and spy_momentum <= 0:
        return Signal(symbol, "SELL", max(0.35, confidence), f"TSMOM SPY regime guard: SPY momentum {spy_momentum:.1%}; reduce/avoid beta exposure", close, r14, s20, s50, vol20, "tsmom", 0.0, evidence)
    if raw_momentum > 0.03 and trend_confirmed and regime_ok:
        if spy_momentum is not None and raw_momentum <= spy_momentum:
            return Signal(symbol, "HOLD", 0.0, f"TSMOM relative-momentum guard: asset {raw_momentum:.1%} <= SPY {spy_momentum:.1%}; no entry", close, r14, s20, s50, vol20, "tsmom", 0.0, evidence)
        target_weight = _clamp(target_vol / max(vol20, 0.05), 0.02, 0.20)
        rel_reason = f"; beats SPY by {relative_momentum:.1%}" if relative_momentum is not None else ""
        return Signal(symbol, "BUY", max(0.35, confidence), f"TSMOM positive {raw_momentum:.1%}; trend confirmed; vol {vol20:.0%}{rel_reason}; next-open candidate only", close, r14, s20, s50, vol20, "tsmom", target_weight, evidence)
    if raw_momentum < -0.03 or (s100 and close < s100):
        return Signal(symbol, "SELL", max(0.30, confidence), f"TSMOM negative/broken regime: momentum {raw_momentum:.1%}, close vs SMA100 {(close / s100 - 1) if s100 else 0:.1%}; reduce/avoid", close, r14, s20, s50, vol20, "tsmom", 0.0, evidence)
    return Signal(symbol, "HOLD", confidence, f"TSMOM neutral: momentum {raw_momentum:.1%}, vol {vol20:.0%}; no forced trade", close, r14, s20, s50, vol20, "tsmom", 0.0, evidence)


def generate_rsi_pullback_signal(symbol: str, bars: list[Bar]) -> Signal:
    """Regime-filtered RSI pullback: buy weakness only inside an uptrend.

    Literature/practitioner basis: Wilder RSI, Chan/Connors-style short-term mean reversion.
    """
    if len(bars) < 120:
        return _insufficient(symbol, bars, "rsi_pullback", 120)
    closes = [b.close for b in bars]
    close = closes[-1]
    s20 = sma(closes, 20)[-1]
    s50 = sma(closes, 50)[-1]
    s100 = sma(closes, 100)[-1]
    r14 = rsi(closes, 14)[-1]
    vol20 = rolling_volatility(closes, 20)[-1]
    five_day_ret = close / closes[-6] - 1 if closes[-6] > 0 else 0.0
    up_regime = bool(s100 and close > s100 and s50 and s50 > s100)
    if up_regime and r14 is not None and r14 < 35 and five_day_ret < -0.02 and (vol20 or 0) < 0.90:
        confidence = _clamp((35 - r14) / 35 + abs(five_day_ret) * 2, 0.25, 0.75)
        return Signal(symbol, "BUY", confidence, f"RSI pullback in uptrend: RSI {r14:.1f}, 5d {five_day_ret:.1%}; time-stop/next-open only", close, r14, s20, s50, vol20, "rsi_pullback", 0.05, {"five_day_return": five_day_ret})
    if s100 and close < s100:
        return Signal(symbol, "SELL", 0.35, "RSI pullback model off: close below SMA100 regime filter", close, r14, s20, s50, vol20, "rsi_pullback", 0.0, {"five_day_return": five_day_ret})
    return Signal(symbol, "HOLD", 0.0, f"RSI pullback inactive: RSI {r14:.1f} in {'up' if up_regime else 'non-up'} regime" if r14 is not None else "RSI unavailable", close, r14, s20, s50, vol20, "rsi_pullback", 0.0, {"five_day_return": five_day_ret})


def generate_vt_trend_signal(symbol: str, bars: list[Bar], target_vol: float = 0.15, max_leverage: float = 1.0, vol_floor: float = 0.05) -> Signal:
    """Volatility-targeted trend following with drawdown guard.

    Literature basis: Moreira & Muir (2017) volatility-managed portfolios;
    Moskowitz, Ooi & Pedersen (2012) TSMOM vol scaling.
    """
    needed = 120
    if len(bars) < needed:
        return _insufficient(symbol, bars, "vt_trend", needed)
    closes = [b.close for b in bars]
    close = closes[-1]
    vol20 = rolling_volatility(closes, 20)[-1] or 0.0
    s100 = sma(closes, 100)[-1]
    s20 = sma(closes, 20)[-1]
    s50 = sma(closes, 50)[-1]
    r14 = rsi(closes, 14)[-1]
    peak_90d = max(closes[-90:]) if len(closes) >= 90 else close
    drawdown = close / peak_90d - 1 if peak_90d > 0 else 0.0
    trend_up = bool(s100 and close > s100)
    exposure = target_vol / max(vol20, vol_floor)
    full_target_weight = _clamp(exposure, 0.10, max_leverage)
    drawdown_level = 0
    reentry_ok = trend_up and close > 0.90 * peak_90d
    if exposure < 0.10:
        action = "SELL"
        target_weight = 0.0
        reason = f"vt_trend exposure floor: raw exposure {exposure:.2f}; go flat"
        confidence = 0.45
    elif vol20 > 1.00:
        action = "SELL"
        target_weight = 0.0
        reason = f"vt_trend vol spike guard: vol20 {vol20:.0%}; go flat"
        confidence = _clamp(0.3 + vol20 * 0.1)
    elif drawdown <= -0.20 + 1e-12:
        action = "SELL"
        target_weight = 0.0
        drawdown_level = 2
        reason = f"vt_trend drawdown level 2: {drawdown:.1%} below 90d peak; go flat"
        confidence = _clamp(0.4 + abs(drawdown))
    elif drawdown <= -0.15:
        action = "SELL"
        target_weight = full_target_weight * 0.5
        drawdown_level = 1
        reason = f"vt_trend drawdown level 1: {drawdown:.1%} below 90d peak; reduce to 50%"
        confidence = _clamp(0.3 + abs(drawdown))
    elif not trend_up:
        action = "SELL"
        target_weight = 0.0
        reason = f"vt_trend trend break: close {close:.2f} below SMA100 {s100:.2f}"
        confidence = _clamp(0.3 + abs(close / s100 - 1) if s100 else 0.0)
    else:
        action = "BUY"
        target_weight = full_target_weight
        reason = f"vt_trend trend up: exposure {exposure:.2f}, vol {vol20:.0%}, weight {target_weight:.2f}"
        confidence = _clamp(full_target_weight * 0.5)
    evidence = {
        "target_vol": target_vol,
        "vol20": vol20,
        "exposure": exposure,
        "full_target_weight": full_target_weight,
        "peak_90d": peak_90d,
        "drawdown": drawdown,
        "drawdown_level": drawdown_level,
        "reentry_ok": reentry_ok,
        "trend_up": trend_up,
    }
    return Signal(symbol, action, confidence, reason, close, r14, s20, s50, vol20, "vt_trend", target_weight, evidence)


def generate_strategy_signals(symbol: str, bars: list[Bar], spy_bars: list[Bar] | None = None) -> list[Signal]:
    return [generate_tsmom_signal(symbol, bars, spy_bars=spy_bars), generate_rsi_pullback_signal(symbol, bars), generate_signal(symbol, bars)]


def generate_ensemble_signal(symbol: str, bars: list[Bar], spy_bars: list[Bar] | None = None) -> Signal:
    family = generate_strategy_signals(symbol, bars, spy_bars=spy_bars)
    close = _close(bars)
    buy_score = sum(s.confidence for s in family if s.action == "BUY")
    sell_score = sum(s.confidence for s in family if s.action == "SELL")
    primary = max(family, key=lambda s: s.confidence) if family else _insufficient(symbol, bars, "ensemble", 120)
    spy_momentum = None
    raw_momentum = None
    if spy_bars is not None:
        spy_momentum = _momentum_over_lookback(spy_bars[-len(bars):] if len(spy_bars) > len(bars) else spy_bars, 120)
        raw_momentum = _momentum_over_lookback(bars, 120)
        if spy_momentum is not None and spy_momentum <= 0:
            sell_score = max(sell_score, 0.60)
            buy_score *= 0.35
        elif spy_momentum is not None and raw_momentum is not None and raw_momentum <= spy_momentum:
            buy_score *= 0.50
    if buy_score >= 0.70 and buy_score > sell_score:
        action = "BUY"
        confidence = _clamp(buy_score / max(len(family), 1) + 0.35)
    elif sell_score >= 0.45 and sell_score >= buy_score:
        action = "SELL"
        confidence = _clamp(sell_score / max(len(family), 1) + 0.25)
    else:
        action = "HOLD"
        confidence = _clamp(max(buy_score, sell_score) / max(len(family), 1))
    reason = "ensemble: " + " | ".join(f"{s.strategy}={s.action}/{s.confidence:.2f}" for s in family)
    evidence: dict[str, float | str | None] = {"buy_score": buy_score, "sell_score": sell_score}
    if spy_momentum is not None:
        evidence.update({"spy_momentum": spy_momentum, "asset_120d_momentum": raw_momentum, "spy_relative_momentum": (raw_momentum - spy_momentum) if raw_momentum is not None else None})
        reason += f" | SPY guard: asset {raw_momentum:.1%} vs SPY {spy_momentum:.1%}" if raw_momentum is not None else f" | SPY guard: SPY {spy_momentum:.1%}"
    return Signal(symbol, action, confidence, reason, close, primary.rsi14, primary.sma20, primary.sma50, primary.volatility20, "ensemble", max((s.target_weight for s in family if s.action == "BUY"), default=0.0) if action == "BUY" else 0.0, evidence)


def cross_sectional_momentum_ranks(bars_by_symbol: dict[str, list[Bar]], formation_days: int = 126, skip_days: int = 21, spy_bars: list[Bar] | None = None) -> list[CrossSectionalRank]:
    scores: list[tuple[str, float]] = []
    needed = formation_days + skip_days + 1
    spy_score = None
    if spy_bars and len(spy_bars) >= needed:
        spy_closes = [b.close for b in spy_bars]
        spy_end_idx = len(spy_closes) - skip_days - 1
        spy_start_idx = spy_end_idx - formation_days
        if spy_start_idx >= 0 and spy_closes[spy_start_idx] > 0:
            spy_score = spy_closes[spy_end_idx] / spy_closes[spy_start_idx] - 1.0
    for symbol, bars in bars_by_symbol.items():
        if len(bars) < needed:
            continue
        closes = [b.close for b in bars]
        end_idx = len(closes) - skip_days - 1
        start_idx = end_idx - formation_days
        if start_idx < 0 or closes[start_idx] <= 0:
            continue
        score = closes[end_idx] / closes[start_idx] - 1.0
        if spy_score is not None and symbol.upper() != "SPY":
            score -= spy_score
        scores.append((symbol, score))
    scores.sort(key=lambda item: item[1], reverse=True)
    n = len(scores)
    ranks: list[CrossSectionalRank] = []
    for idx, (symbol, score) in enumerate(scores, start=1):
        percentile = 1.0 - ((idx - 1) / max(n - 1, 1)) if n > 1 else 1.0
        reason = f"6m excess momentum vs SPY with 1m skip: {score:.1%}" if spy_score is not None and symbol.upper() != "SPY" else f"6m momentum with 1m skip: {score:.1%}"
        ranks.append(CrossSectionalRank(symbol, score, idx, percentile, reason))
    return ranks


def apply_factor_overlay(signal: Signal, factor: FactorSnapshot | None) -> Signal:
    """Blend non-price factor evidence into a technical signal without overclaiming.

    The overlay is deliberately capped: fundamentals/narrative can nudge confidence,
    but they do not turn a SELL into a BUY by themselves in MVP.
    """
    if factor is None:
        return signal
    delta, reasons = factor_score(factor)
    adjusted = _clamp(signal.confidence + delta)
    if signal.action == "BUY" and delta < -0.12 and adjusted < 0.55:
        action = "HOLD"
    elif signal.action == "SELL" and delta > 0.12 and adjusted < 0.55:
        action = "HOLD"
    else:
        action = signal.action
    evidence = dict(signal.evidence)
    evidence.update({
        "factor_delta": delta,
        "factor_source": factor.source,
        "pe_ratio": factor.pe_ratio,
        "pb_ratio": factor.pb_ratio,
        "revenue_growth_yoy": factor.revenue_growth_yoy,
        "free_cash_flow_yield": factor.free_cash_flow_yield,
        "ai_impact_score": factor.ai_impact_score,
        "sentiment_proxy": factor.sentiment_proxy,
    })
    reason = signal.reason + "; factor lens: " + ", ".join(reasons)
    return replace(signal, action=action, confidence=adjusted, reason=reason, evidence=evidence)


def rank_signals(signals: list[Signal]) -> list[Signal]:
    action_rank = {"BUY": 2, "HOLD": 1, "SELL": 0}
    return sorted(signals, key=lambda s: (action_rank.get(s.action, 1), s.confidence), reverse=True)
