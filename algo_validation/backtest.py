from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd
import pandas_ta_classic as ta

ExecutionModel = str  # "close" | "intrabar"


@dataclass(frozen=True)
class StrategyParams:
    # Indicators (match bot defaults)
    ema_len: int = 20
    rsi_len: int = 14
    atr_len: int = 14
    ema_slope_bars: int = 5
    volume_ma_len: int = 20

    # Entry filters (match `main_multi_symbol.py` defaults)
    rsi_entry_threshold: float = 55.0
    min_trend_strength: float = 0.01  # distance from EMA (1%)
    min_volume_ratio: float = 1.0

    # Exits / protection (match `main_multi_symbol.py` defaults)
    atr_multiplier: float = 1.5
    profit_target_pct: float = 0.035
    spike_reversal_pct: float = 0.02
    min_spike_profit_pct: float = 0.02
    cooldown_bars: int = 1  # ~5m default timeframe -> 5 minutes; configurable by caller

    # Volatility-adaptive behavior (match `main_multi_symbol.py`)
    volatile_atr_pct: float = 0.02
    volatile_profit_target_pct: float = 0.02
    volatile_spike_reversal_pct: float = 0.012
    volatile_atr_multiplier: float = 2.0
    volatile_min_spike_profit_pct: float = 0.015

    # Trailing profit target behavior (match code constant)
    trailing_target_factor: float = 0.6

    # Economics
    leverage: float = 1.0
    fee_rate: float = 0.006  # 0.6% taker fee default; use 0.004 for maker

    # Backtest assumption
    execution_model: ExecutionModel = "close"


@dataclass(frozen=True)
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    reason: str
    gross_return: float  # per-trade gross return on equity (includes leverage, excludes fees)
    net_return: float  # per-trade net return on equity (includes leverage and fees)


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    trades: List[Trade]


def _ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"OHLCV dataframe missing columns: {sorted(missing)}")

    out = df.copy()
    if "timestamp" in out.columns:
        if pd.api.types.is_numeric_dtype(out["timestamp"]):
            out["timestamp"] = pd.to_datetime(out["timestamp"], unit="ms", utc=True)
        else:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        out = out.set_index("timestamp")
    else:
        if not isinstance(out.index, pd.DatetimeIndex):
            raise ValueError("OHLCV dataframe must have a `timestamp` column or DatetimeIndex")
        if out.index.tz is None:
            out.index = out.index.tz_localize("UTC")

    out = out.sort_index()
    return out


def add_indicators(df: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    df = _ensure_ohlcv(df)
    out = df.copy()
    out["ema_20"] = ta.ema(out["close"], length=p.ema_len)
    out["rsi"] = ta.rsi(out["close"], length=p.rsi_len)
    out["atr"] = ta.atr(out["high"], out["low"], out["close"], length=p.atr_len)
    out["ema_slope"] = out["ema_20"].diff(p.ema_slope_bars)
    out["volume_ma"] = out["volume"].rolling(p.volume_ma_len).mean()
    out["volume_ratio"] = out["volume"] / out["volume_ma"]
    return out


def run_backtest(df: pd.DataFrame, p: StrategyParams) -> BacktestResult:
    if p.execution_model not in ("close", "intrabar"):
        raise ValueError("execution_model must be 'close' or 'intrabar'")
    df = add_indicators(df, p)

    df_valid = df.dropna(subset=["ema_20", "rsi", "atr", "ema_slope", "volume_ratio"]).copy()
    if len(df_valid) < 10:
        raise ValueError("Not enough candles after indicator warmup to backtest")

    equity_cash = 1.0
    position_entry_equity = 0.0
    in_position = False

    entry_price = 0.0
    entry_time: Optional[pd.Timestamp] = None
    stop_price = 0.0
    peak_price = 0.0  # peak CLOSE (matches bot, which updates on `price` only)
    trailing_profit_target = 0.0
    breakeven_set = False
    last_exit_i = -10**9

    trades: List[Trade] = []

    equity_rows: List[dict] = []

    def is_volatile(atr_value: float, price_value: float) -> bool:
        if price_value <= 0:
            return False
        return (atr_value / price_value) > p.volatile_atr_pct

    def dyn_params(atr_value: float, price_value: float) -> Tuple[float, float, float, float]:
        """
        Returns:
          profit_target_pct, spike_reversal_pct, atr_multiplier, min_spike_profit_pct
        """
        if is_volatile(atr_value, price_value):
            return (
                p.volatile_profit_target_pct,
                p.volatile_spike_reversal_pct,
                p.volatile_atr_multiplier,
                p.volatile_min_spike_profit_pct,
            )
        return (p.profit_target_pct, p.spike_reversal_pct, p.atr_multiplier, p.min_spike_profit_pct)

    for i, (ts, row) in enumerate(df_valid.iterrows()):
        price = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        ema_20 = float(row["ema_20"])
        rsi = float(row["rsi"])
        atr = float(row["atr"])
        ema_slope = float(row["ema_slope"])
        volume_ratio = float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 0.0

        # Mark-to-market equity at this candle close
        if in_position:
            mark_equity = position_entry_equity * (1.0 + p.leverage * ((price / entry_price) - 1.0))
        else:
            mark_equity = equity_cash

        equity_rows.append(
            {
                "timestamp": ts,
                "close": price,
                "equity": float(mark_equity),
                "in_position": bool(in_position),
                "entry_price": float(entry_price) if in_position else 0.0,
                "stop_price": float(stop_price) if in_position else 0.0,
            }
        )

        # --- EXIT LOGIC ---
        if in_position:
            profit_target_pct, spike_reversal_pct, atr_mult, min_spike_profit_pct = dyn_params(atr, price)

            # Conservative intrabar assumption: a stop can happen before any profit-taking.
            if p.execution_model == "intrabar":
                stop_hit = low <= stop_price
                if stop_hit:
                    exit_reason = "stop_loss"
                    exit_price = stop_price
                    gross_mult = 1.0 + p.leverage * ((exit_price / entry_price) - 1.0)
                    net_mult = gross_mult * (1.0 - p.fee_rate)
                    equity_cash = max(0.0, position_entry_equity * net_mult)
                    trades.append(
                        Trade(
                            entry_time=entry_time or ts,
                            exit_time=ts,
                            entry_price=entry_price,
                            exit_price=exit_price,
                            reason=exit_reason,
                            gross_return=gross_mult - 1.0,
                            net_return=(equity_cash / (position_entry_equity) - 1.0) if position_entry_equity else 0.0,
                        )
                    )
                    in_position = False
                    last_exit_i = i
                    entry_price = 0.0
                    entry_time = None
                    stop_price = 0.0
                    peak_price = 0.0
                    trailing_profit_target = 0.0
                    breakeven_set = False
                    continue

            # Update peak close and trailing profit target (bot tracks peak on close)
            if price > peak_price:
                peak_price = price
                new_target = (entry_price * (1.0 + p.profit_target_pct)) + (price - entry_price) * p.trailing_target_factor
                if new_target > trailing_profit_target:
                    trailing_profit_target = new_target

            profit_pct = (price - entry_price) / entry_price if entry_price > 0 else 0.0
            peak_profit_pct = (peak_price - entry_price) / entry_price if entry_price > 0 else 0.0
            drop_from_peak_pct = (peak_price - price) / peak_price if peak_price > 0 else 0.0

            # Spike reversal (close-based; matches bot)
            if peak_profit_pct >= min_spike_profit_pct and drop_from_peak_pct >= spike_reversal_pct:
                exit_reason = "spike_reversal"
                exit_price = price
            else:
                exit_reason = ""
                exit_price = 0.0

            # Profit target (close vs intrabar)
            profit_target_price = entry_price * (1.0 + profit_target_pct)
            if not exit_reason:
                if p.execution_model == "intrabar":
                    if high >= profit_target_price:
                        exit_reason = "profit_target"
                        exit_price = profit_target_price
                else:
                    if price >= profit_target_price:
                        exit_reason = "profit_target"
                        exit_price = price

            # Trailing profit target (close vs intrabar)
            if not exit_reason and trailing_profit_target > 0:
                if p.execution_model == "intrabar":
                    if high >= trailing_profit_target:
                        exit_reason = "trailing_profit_target"
                        exit_price = trailing_profit_target
                else:
                    if price >= trailing_profit_target:
                        exit_reason = "trailing_profit_target"
                        exit_price = price

            # Stop management (bot updates stop then checks trigger)
            potential_stop = price - (atr * atr_mult)
            if potential_stop > stop_price:
                stop_price = potential_stop

            if not breakeven_set and price > entry_price * 1.01:
                stop_price = max(stop_price, entry_price * 1.005)
                breakeven_set = True

            if is_volatile(atr, price):
                if profit_pct > 0.01:
                    stop_price = max(stop_price, entry_price * 1.005)
                if profit_pct > 0.02:
                    stop_price = max(stop_price, entry_price * 1.01)
            else:
                if profit_pct > 0.01:
                    stop_price = max(stop_price, entry_price * 1.005)
                if profit_pct > 0.02:
                    stop_price = max(stop_price, entry_price * 1.01)
                if profit_pct > 0.03:
                    stop_price = max(stop_price, entry_price * 1.02)

            if not exit_reason:
                if p.execution_model == "intrabar":
                    if low <= stop_price:
                        exit_reason = "stop_loss"
                        exit_price = stop_price
                else:
                    if price <= stop_price:
                        exit_reason = "stop_loss"
                        exit_price = price

            if exit_reason:
                gross_mult = 1.0 + p.leverage * ((exit_price / entry_price) - 1.0)
                net_mult = gross_mult * (1.0 - p.fee_rate)
                equity_cash = max(0.0, position_entry_equity * net_mult)
                trades.append(
                    Trade(
                        entry_time=entry_time or ts,
                        exit_time=ts,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        reason=exit_reason,
                        gross_return=gross_mult - 1.0,
                        net_return=(equity_cash / (position_entry_equity) - 1.0) if position_entry_equity else 0.0,
                    )
                )
                in_position = False
                last_exit_i = i
                entry_price = 0.0
                entry_time = None
                stop_price = 0.0
                peak_price = 0.0
                trailing_profit_target = 0.0
                breakeven_set = False
                continue

        # --- ENTRY LOGIC ---
        if not in_position:
            if (i - last_exit_i) <= p.cooldown_bars:
                continue

            trend_strength = abs(price - ema_20) / ema_20 if ema_20 > 0 else 0.0
            price_above_ema = price > ema_20
            rsi_strong = rsi > p.rsi_entry_threshold
            trend_strong_enough = trend_strength >= p.min_trend_strength
            ema_trending_up = ema_slope > 0
            volume_adequate = volume_ratio >= p.min_volume_ratio

            if price_above_ema and rsi_strong and trend_strong_enough and ema_trending_up and volume_adequate:
                # Pay entry fee upfront
                position_entry_equity = equity_cash * (1.0 - p.fee_rate)
                in_position = True
                entry_price = price
                entry_time = ts
                peak_price = price
                trailing_profit_target = entry_price * (1.0 + p.profit_target_pct)
                breakeven_set = False

                # Initial stop (volatility-adjusted, matches bot)
                _, _, atr_mult, _ = dyn_params(atr, price)
                stop_price = price - (atr * atr_mult)

    # Force-close any open position at last close (for consistent metrics)
    if in_position and entry_time is not None:
        ts = df_valid.index[-1]
        exit_price = float(df_valid.iloc[-1]["close"])
        gross_mult = 1.0 + p.leverage * ((exit_price / entry_price) - 1.0)
        net_mult = gross_mult * (1.0 - p.fee_rate)
        equity_cash = max(0.0, position_entry_equity * net_mult)
        trades.append(
            Trade(
                entry_time=entry_time,
                exit_time=ts,
                entry_price=entry_price,
                exit_price=exit_price,
                reason="eod",
                gross_return=gross_mult - 1.0,
                net_return=(equity_cash / (position_entry_equity) - 1.0) if position_entry_equity else 0.0,
            )
        )

    equity_curve = pd.DataFrame(equity_rows).set_index("timestamp")
    return BacktestResult(equity_curve=equity_curve, trades=trades)

