#!/usr/bin/env python3
"""
Historical strategy validation utilities.

This module backtests a simplified version of the production trading logic
to measure two outcomes:
1) How well a symbol captures upside during uptrends.
2) How well it limits losses during crashes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
import math
import time

import pandas as pd
import pandas_ta_classic as ta


@dataclass
class StrategyValidationResult:
    symbol: str
    bars: int
    strategy_return: float
    buy_hold_return: float
    max_drawdown: float
    uptrend_capture: float
    crash_protection: Optional[float]
    trades: int
    win_rate: float
    score: float
    recommendation: str
    reason: str


def fetch_ohlcv_history(exchange, symbol: str, timeframe: str = "1h", lookback_days: int = 120) -> pd.DataFrame:
    """
    Fetch OHLCV candles for a lookback window.
    Uses pagination because Coinbase limits candles per request.
    """
    tf_seconds = exchange.parse_timeframe(timeframe)
    tf_ms = tf_seconds * 1000
    now_ms = exchange.milliseconds()
    bars_needed = int((lookback_days * 24 * 3600) / tf_seconds) + 250

    all_rows: List[List[float]] = []
    since = now_ms - bars_needed * tf_ms
    limit = 300

    while since < now_ms and len(all_rows) < bars_needed + limit:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=limit)
        if not batch:
            break

        all_rows.extend(batch)
        since = batch[-1][0] + tf_ms

        # Respect exchange rate limit while paginating.
        if getattr(exchange, "rateLimit", 0):
            time.sleep(exchange.rateLimit / 1000)

        if len(batch) < limit:
            break

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _compute_max_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    rolling_peak = equity_curve.cummax()
    drawdowns = equity_curve / rolling_peak - 1.0
    return float(drawdowns.min())


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema_20"] = ta.ema(df["close"], length=20)
    df["ema_50"] = ta.ema(df["close"], length=50)
    df["rsi"] = ta.rsi(df["close"], length=14)
    df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    df["ema_slope"] = df["ema_20"].diff(5)
    df["volume_ma"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_ma"]
    df["ret_24"] = df["close"].pct_change(24)
    return df


def backtest_symbol(df_raw: pd.DataFrame, symbol: str) -> StrategyValidationResult:
    """
    Backtest a close approximation of the live strategy on historical candles.
    Returns a score used to decide whether the symbol is worth keeping.
    """
    df = _add_indicators(df_raw)
    df = df.dropna().reset_index(drop=True)

    if len(df) < 80:
        return StrategyValidationResult(
            symbol=symbol,
            bars=len(df),
            strategy_return=0.0,
            buy_hold_return=0.0,
            max_drawdown=0.0,
            uptrend_capture=0.0,
            crash_protection=None,
            trades=0,
            win_rate=0.0,
            score=0.0,
            recommendation="KEEP",
            reason="Not enough historical data to score safely.",
        )

    in_position = False
    units = 0.0
    cash = 1.0  # start with 1.0 notional unit

    entry_price = 0.0
    stop_price = 0.0
    peak_price = 0.0
    breakeven_set = False
    fee_rate = 0.004  # maker-fee proxy

    trades = 0
    wins = 0
    trade_entry_value = 0.0

    equity = []
    strategy_returns = []
    prev_equity = cash

    for _, row in df.iterrows():
        price = float(row["close"])
        ema_20 = float(row["ema_20"])
        atr = float(row["atr"])
        rsi = float(row["rsi"])
        ema_slope = float(row["ema_slope"])
        volume_ratio = float(row["volume_ratio"]) if not math.isnan(float(row["volume_ratio"])) else 0.0

        trend_strength = abs(price - ema_20) / ema_20 if ema_20 > 0 else 0.0
        atr_pct = atr / price if price > 0 else 0.0
        is_volatile = atr_pct > 0.02

        if is_volatile:
            dynamic_spike_reversal = 0.012
            dynamic_profit_target = 0.02
            dynamic_atr_mult = 2.0
            dynamic_min_spike_profit = 0.015
        else:
            dynamic_spike_reversal = 0.02
            dynamic_profit_target = 0.035
            dynamic_atr_mult = 1.5
            dynamic_min_spike_profit = 0.02

        if not in_position:
            enter = (
                price > ema_20
                and rsi > 55
                and trend_strength >= 0.01
                and ema_slope > 0
                and volume_ratio >= 1.0
            )
            if enter and cash > 0:
                buy_price = price * (1 + fee_rate)
                units = cash / buy_price
                trade_entry_value = cash
                cash = 0.0
                in_position = True
                entry_price = price
                stop_price = price - (atr * (2.0 if atr_pct > 0.02 else 1.5))
                peak_price = price
                breakeven_set = False
        else:
            if price > peak_price:
                peak_price = price

            profit_pct = (price - entry_price) / entry_price if entry_price > 0 else 0.0
            peak_profit_pct = (peak_price - entry_price) / entry_price if entry_price > 0 else 0.0
            drop_from_peak_pct = (peak_price - price) / peak_price if peak_price > 0 else 0.0

            # Raise trailing stop.
            potential_stop = price - (atr * dynamic_atr_mult)
            if potential_stop > stop_price:
                stop_price = potential_stop

            # Lock some profit once the move is in our favor.
            if not breakeven_set and profit_pct > 0.01:
                stop_price = max(stop_price, entry_price * 1.005)
                breakeven_set = True

            if profit_pct > 0.02:
                stop_price = max(stop_price, entry_price * 1.01)
            if not is_volatile and profit_pct > 0.03:
                stop_price = max(stop_price, entry_price * 1.02)

            hit_spike_reversal = peak_profit_pct >= dynamic_min_spike_profit and drop_from_peak_pct >= dynamic_spike_reversal
            hit_profit_target = price >= entry_price * (1 + dynamic_profit_target)
            hit_stop = price <= stop_price

            if hit_spike_reversal or hit_profit_target or hit_stop:
                sell_price = price * (1 - fee_rate)
                cash = units * sell_price
                units = 0.0
                in_position = False
                trades += 1
                if cash > trade_entry_value:
                    wins += 1

        current_equity = cash + units * price
        equity.append(current_equity)
        if prev_equity > 0:
            strategy_returns.append(current_equity / prev_equity - 1.0)
        else:
            strategy_returns.append(0.0)
        prev_equity = current_equity

    # Liquidate open position at the end for a fair score.
    if in_position and units > 0:
        final_price = float(df.iloc[-1]["close"]) * (1 - fee_rate)
        cash = units * final_price
        units = 0.0
        trades += 1
        if cash > trade_entry_value:
            wins += 1

    close_series = df["close"].astype(float)
    market_returns = close_series.pct_change().fillna(0.0)
    strategy_returns_series = pd.Series(strategy_returns, index=df.index).fillna(0.0)
    equity_curve = pd.Series(equity, index=df.index)

    strategy_return = float(cash - 1.0)
    buy_hold_return = float(close_series.iloc[-1] / close_series.iloc[0] - 1.0)
    max_drawdown = _compute_max_drawdown(equity_curve)
    win_rate = float(wins / trades) if trades > 0 else 0.0

    uptrend_mask = (df["close"] > df["ema_50"]) & (df["ret_24"] > 0.05)
    crash_mask = df["ret_24"] < -0.08

    market_up = float(market_returns[uptrend_mask].sum()) if uptrend_mask.any() else 0.0
    strategy_up = float(strategy_returns_series[uptrend_mask].sum()) if uptrend_mask.any() else 0.0
    uptrend_capture = (strategy_up / market_up) if market_up > 0 else 0.0
    uptrend_capture = _clamp(uptrend_capture, 0.0, 1.5)

    crash_protection: Optional[float] = None
    if crash_mask.any():
        market_crash = float(market_returns[crash_mask].sum())
        strategy_crash = float(strategy_returns_series[crash_mask].sum())
        if market_crash < 0:
            if strategy_crash >= 0:
                crash_protection = 1.0
            else:
                loss_ratio = abs(strategy_crash) / abs(market_crash)
                crash_protection = _clamp(1.0 - loss_ratio, 0.0, 1.0)

    # Score out of 100.
    profit_component = _clamp(strategy_return / 0.25, 0.0, 1.0) * 30.0
    uptrend_component = _clamp(uptrend_capture / 1.0, 0.0, 1.0) * 25.0
    crash_component = ((crash_protection if crash_protection is not None else 0.5)) * 25.0
    drawdown_component = _clamp((0.35 + max_drawdown) / 0.35, 0.0, 1.0) * 15.0
    win_component = ((win_rate if trades > 0 else 0.5)) * 5.0
    score = profit_component + uptrend_component + crash_component + drawdown_component + win_component

    should_sell = (
        score < 60.0
        or strategy_return < -0.08
        or (crash_protection is not None and crash_protection < 0.20 and max_drawdown < -0.20)
    )

    if should_sell:
        recommendation = "SELL"
        reason = (
            f"Weak history: score={score:.1f}, "
            f"uptrend_capture={uptrend_capture:.2f}, "
            f"crash_protection={crash_protection if crash_protection is not None else 0.50:.2f}, "
            f"strategy_return={strategy_return*100:.1f}%"
        )
    else:
        recommendation = "KEEP"
        reason = (
            f"Healthy history: score={score:.1f}, "
            f"uptrend_capture={uptrend_capture:.2f}, "
            f"strategy_return={strategy_return*100:.1f}%"
        )

    return StrategyValidationResult(
        symbol=symbol,
        bars=len(df),
        strategy_return=strategy_return,
        buy_hold_return=buy_hold_return,
        max_drawdown=max_drawdown,
        uptrend_capture=uptrend_capture,
        crash_protection=crash_protection,
        trades=trades,
        win_rate=win_rate,
        score=score,
        recommendation=recommendation,
        reason=reason,
    )


def evaluate_symbol_history(
    exchange,
    symbol: str,
    timeframe: str = "1h",
    lookback_days: int = 120,
    min_bars: int = 200,
) -> StrategyValidationResult:
    """
    Convenience wrapper that fetches history and backtests a symbol.
    """
    df = fetch_ohlcv_history(exchange, symbol=symbol, timeframe=timeframe, lookback_days=lookback_days)
    if df.empty or len(df) < min_bars:
        return StrategyValidationResult(
            symbol=symbol,
            bars=len(df) if not df.empty else 0,
            strategy_return=0.0,
            buy_hold_return=0.0,
            max_drawdown=0.0,
            uptrend_capture=0.0,
            crash_protection=None,
            trades=0,
            win_rate=0.0,
            score=0.0,
            recommendation="KEEP",
            reason=f"Not enough history ({0 if df.empty else len(df)} bars).",
        )
    return backtest_symbol(df, symbol=symbol)

