from __future__ import annotations

import math
from statistics import mean, pstdev

def sma(values: list[float], window: int) -> list[float | None]:
    if window <= 0: raise ValueError("window must be positive")
    out=[]
    for i in range(len(values)):
        out.append(mean(values[i-window+1:i+1]) if i + 1 >= window else None)
    return out

def ema(values: list[float], window: int) -> list[float | None]:
    if window <= 0: raise ValueError("window must be positive")
    if not values: return []
    alpha=2/(window+1)
    out=[]; current=None
    for i,v in enumerate(values):
        current = v if current is None else alpha*v + (1-alpha)*current
        out.append(current if i + 1 >= window else None)
    return out

def returns(values: list[float]) -> list[float | None]:
    out=[None]
    for prev, cur in zip(values, values[1:]):
        out.append(None if prev == 0 else cur/prev - 1)
    return out

def rsi(values: list[float], window: int = 14) -> list[float | None]:
    if window <= 0: raise ValueError("window must be positive")
    out=[None]*len(values)
    if len(values) <= window: return out
    gains=[]; losses=[]
    for prev, cur in zip(values, values[1:window+1]):
        change=cur-prev; gains.append(max(change,0)); losses.append(max(-change,0))
    avg_gain=mean(gains); avg_loss=mean(losses)
    out[window] = 100.0 if avg_loss == 0 else 100 - 100/(1 + avg_gain/avg_loss)
    for i in range(window+1, len(values)):
        change=values[i]-values[i-1]
        gain=max(change,0); loss=max(-change,0)
        avg_gain=(avg_gain*(window-1)+gain)/window
        avg_loss=(avg_loss*(window-1)+loss)/window
        out[i]=100.0 if avg_loss == 0 else 100 - 100/(1 + avg_gain/avg_loss)
    return out

def rolling_volatility(values: list[float], window: int = 20, annualization: int = 252) -> list[float | None]:
    rets=returns(values)
    out=[]
    for i in range(len(rets)):
        sample=[x for x in rets[i-window+1:i+1] if x is not None] if i + 1 >= window else []
        out.append(pstdev(sample) * math.sqrt(annualization) if len(sample) >= 2 else None)
    return out

def rolling_peak(values: list[float], window: int) -> list[float | None]:
    if window <= 0: raise ValueError("window must be positive")
    out: list[float | None] = []
    for i in range(len(values)):
        if i + 1 >= window:
            out.append(max(values[i - window + 1 : i + 1]))
        else:
            out.append(None)
    return out

def max_drawdown(values: list[float]) -> float:
    peak=-float('inf'); mdd=0.0
    for v in values:
        peak=max(peak,v)
        if peak > 0:
            mdd=min(mdd, v/peak - 1)
    return mdd
