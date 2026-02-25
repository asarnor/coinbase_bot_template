from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PerformanceSummary:
    total_return: float
    cagr: float
    max_drawdown: float
    annualized_vol: float
    sharpe: float
    sortino: float
    worst_bar_return: float
    tail_mean_5pct: float
    num_trades: int
    win_rate: float
    profit_factor: float
    exposure: float
    downside_capture: Optional[float]  # vs underlying on down bars (<= crash_threshold)


def _to_returns(series: pd.Series) -> pd.Series:
    r = series.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return r


def max_drawdown(equity: pd.Series) -> float:
    running_max = equity.cummax()
    dd = (equity / running_max) - 1.0
    return float(dd.min())


def annualization_factor(timeframe: str) -> float:
    """
    Approximate periods-per-year for common candle timeframes.
    """
    tf = timeframe.strip().lower()
    mapping = {
        "1m": 365.0 * 24.0 * 60.0,
        "5m": 365.0 * 24.0 * 12.0,
        "15m": 365.0 * 24.0 * 4.0,
        "30m": 365.0 * 24.0 * 2.0,
        "1h": 365.0 * 24.0,
        "2h": 365.0 * 12.0,
        "4h": 365.0 * 6.0,
        "6h": 365.0 * 4.0,
        "12h": 365.0 * 2.0,
        "1d": 365.0,
    }
    return float(mapping.get(tf, 365.0))


def downside_capture_ratio(
    strategy_returns: pd.Series, underlying_returns: pd.Series, crash_threshold: float = -0.03
) -> Optional[float]:
    """
    On bars where the underlying return is <= crash_threshold, how much did the strategy lose
    relative to the underlying? Lower is better. Returns None if no crash bars exist.
    """
    mask = underlying_returns <= crash_threshold
    if mask.sum() == 0:
        return None

    strat = strategy_returns[mask]
    under = underlying_returns[mask]
    under_loss = float(under.mean())
    strat_loss = float(strat.mean())
    if under_loss == 0:
        return None
    return float(strat_loss / under_loss)  # e.g. 0.5 means half the loss on average


def summarize_performance(
    equity_curve: pd.DataFrame,
    trades: list,
    timeframe: str,
    underlying_close: Optional[pd.Series] = None,
    crash_threshold: float = -0.03,
) -> PerformanceSummary:
    if "equity" not in equity_curve.columns:
        raise ValueError("equity_curve must include an `equity` column")

    equity = equity_curve["equity"].astype(float)
    rets = _to_returns(equity)
    ppy = annualization_factor(timeframe)

    total_ret = float(equity.iloc[-1] / equity.iloc[0] - 1.0)

    # CAGR: approximate by using bar count and periods/year
    years = max(1e-9, len(equity) / ppy)
    cagr = float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)

    vol = float(rets.std(ddof=0) * np.sqrt(ppy))
    mean = float(rets.mean() * ppy)
    sharpe = float(mean / vol) if vol > 0 else 0.0

    downside = rets[rets < 0]
    downside_dev = float(downside.std(ddof=0) * np.sqrt(ppy)) if len(downside) else 0.0
    sortino = float(mean / downside_dev) if downside_dev > 0 else 0.0

    mdd = max_drawdown(equity)
    worst_bar = float(rets.min())
    tail_cut = max(1, int(0.05 * len(rets)))
    tail_mean = float(rets.nsmallest(tail_cut).mean()) if len(rets) else 0.0

    # Trade stats
    trade_rets = np.array([float(getattr(t, "net_return", 0.0)) for t in trades], dtype=float)
    num_trades = int(len(trade_rets))
    wins = int((trade_rets > 0).sum())
    win_rate = float(wins / num_trades) if num_trades else 0.0
    gross_wins = float(trade_rets[trade_rets > 0].sum()) if num_trades else 0.0
    gross_losses = float(-trade_rets[trade_rets < 0].sum()) if num_trades else 0.0
    profit_factor = float(gross_wins / gross_losses) if gross_losses > 0 else float("inf") if gross_wins > 0 else 0.0

    # Exposure (time in market)
    exposure = float(equity_curve["in_position"].mean()) if "in_position" in equity_curve.columns else 0.0

    dcr = None
    if underlying_close is not None:
        underlying_rets = _to_returns(underlying_close.astype(float))
        dcr = downside_capture_ratio(rets, underlying_rets, crash_threshold=crash_threshold)

    return PerformanceSummary(
        total_return=total_ret,
        cagr=cagr,
        max_drawdown=mdd,
        annualized_vol=vol,
        sharpe=sharpe,
        sortino=sortino,
        worst_bar_return=worst_bar,
        tail_mean_5pct=tail_mean,
        num_trades=num_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        exposure=exposure,
        downside_capture=dcr,
    )

