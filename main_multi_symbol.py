#!/usr/bin/env python3
"""
Multi-Symbol Trading Bot
Trades multiple symbols with profile-based risk management.
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import ccxt
import pandas as pd
import pandas_ta_classic as ta
from dotenv import load_dotenv

from portfolio_utils import fetch_portfolio_snapshot
from risk_limits import (
    compute_position_size,
    current_day_key,
    evaluate_entry_limits,
    extract_fill,
    new_daily_state,
    rebuild_daily_state_from_events,
    record_realized_pnl,
    record_trade,
    reset_daily_state,
    restore_pending_orders_from_events,
    symbol_loss_limit_hit,
    validate_symbol_configuration,
)
from trading_journal import TradingJournal, utc_now_iso


def parse_symbol_list(raw_value: str) -> List[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def format_price(value: float) -> str:
    if value >= 1000:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:.2f}"
    return f"${value:.8f}"


def reset_position_state(position: Dict, record_exit: bool = False) -> None:
    if record_exit:
        position["last_exit_time"] = time.time()
    position["in_position"] = False
    position["trailing_stop_price"] = 0.0
    position["position_amount"] = 0.0
    position["entry_price"] = 0.0
    position["peak_price"] = 0.0
    position["trailing_profit_target"] = 0.0
    position["breakeven_set"] = False
    position["reconciled_from_balance"] = False
    position["pending_order_id"] = None
    position["pending_order_side"] = None
    position["pending_entry_signal"] = None
    position["pending_order_amount"] = 0.0
    position["pending_order_price"] = 0.0
    position["needs_entry_finalize"] = False


def fetch_data(exchange, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return pd.DataFrame(
            bars,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
    except Exception as exc:
        print(f"Data Error for {symbol}: {exc}")
        return pd.DataFrame()


def analyze_market(df: pd.DataFrame) -> pd.Series:
    working = df.copy()
    working["ema_20"] = ta.ema(working["close"], length=20)
    working["rsi"] = ta.rsi(working["close"], length=14)
    working["atr"] = ta.atr(working["high"], working["low"], working["close"], length=14)
    # Floor ATR at a small fraction of price. On thin books (illiquid alt pairs
    # during low-liquidity hours) a stretch of flat/duplicate candles can otherwise
    # collapse ATR to ~0, which puts the trailing stop essentially at breakeven and
    # whipsaws the position out on the first tick of noise.
    min_atr = working["close"] * 0.001
    working["atr"] = working["atr"].clip(lower=min_atr)
    working["ema_slope"] = working["ema_20"].diff(5)
    working["volume_ma"] = working["volume"].rolling(20).mean()
    # Guard against a zero rolling average (illiquid pairs / dead candles). Dividing
    # by zero would otherwise send volume_ratio to inf, which silently satisfies the
    # volume filter regardless of the profile's configured threshold.
    safe_volume_ma = working["volume_ma"].where(working["volume_ma"] > 0)
    working["volume_ratio"] = (working["volume"] / safe_volume_ma).fillna(0.0)
    # Use the last CLOSED candle (-2) rather than the still-forming candle (-1)
    # so signals do not repaint / flip within the current bar.
    return working.iloc[-2] if len(working) >= 2 else working.iloc[-1]


def analyze_regime(df: pd.DataFrame) -> pd.Series:
    working = df.copy()
    working["ema_50"] = ta.ema(working["close"], length=50)
    working["rsi"] = ta.rsi(working["close"], length=14)
    working["ema_slope"] = working["ema_50"].diff(5)
    return working.iloc[-2] if len(working) >= 2 else working.iloc[-1]


def env_float(name: str, default: str, fallback_name: str = None) -> float:
    raw_value = os.getenv(name)
    if raw_value is None and fallback_name:
        raw_value = os.getenv(fallback_name)
    if raw_value is None:
        raw_value = default
    return float(str(raw_value).strip())


def build_profile_settings() -> Dict[str, Dict]:
    return {
        "core": {
            "label": "core",
            "risk_weight": float(os.getenv("TRADING_CORE_RISK_WEIGHT", "1.00")),
            "profit_target_pct": env_float("TRADING_CORE_PROFIT_TARGET_PCT", "0.030", "TRADING_PROFIT_TARGET_PCT"),
            "spike_reversal_pct": env_float("TRADING_CORE_SPIKE_REVERSAL_PCT", "0.018", "TRADING_SPIKE_REVERSAL_PCT"),
            "min_spike_profit_pct": env_float("TRADING_CORE_MIN_SPIKE_PROFIT", "0.015", "TRADING_MIN_SPIKE_PROFIT"),
            "atr_multiplier": env_float("TRADING_CORE_ATR_MULTIPLIER", "1.60", "TRADING_ATR_MULTIPLIER"),
            "rsi_entry_threshold": env_float("TRADING_CORE_RSI_ENTRY", "54", "TRADING_RSI_ENTRY"),
            "min_trend_strength": env_float("TRADING_CORE_MIN_TREND_STRENGTH", "0.008", "TRADING_MIN_TREND_STRENGTH"),
            "min_volume_ratio": float(os.getenv("TRADING_CORE_MIN_VOLUME_RATIO", "0.95")),
            "breakeven_trigger_pct": float(os.getenv("TRADING_CORE_BREAKEVEN_TRIGGER", "0.012")),
            "breakeven_lock_pct": float(os.getenv("TRADING_CORE_BREAKEVEN_LOCK", "0.003")),
            "trail_capture_ratio": float(os.getenv("TRADING_CORE_TRAIL_CAPTURE_RATIO", "0.55")),
            "high_volatility_atr_pct": float(os.getenv("TRADING_CORE_HIGH_VOL_ATR_PCT", "0.030")),
            "high_volatility_profit_target_scale": float(os.getenv("TRADING_CORE_HIGH_VOL_TARGET_SCALE", "0.90")),
            "high_volatility_spike_scale": float(os.getenv("TRADING_CORE_HIGH_VOL_SPIKE_SCALE", "0.90")),
            "high_volatility_atr_scale": float(os.getenv("TRADING_CORE_HIGH_VOL_ATR_SCALE", "1.10")),
            "profit_locks": [
                (0.015, 0.005),
                (0.030, 0.012),
                (0.050, 0.025),
            ],
            "allowed_regimes": {"risk_on", "mixed"},
        },
        "tactical": {
            "label": "tactical",
            "risk_weight": float(os.getenv("TRADING_TACTICAL_RISK_WEIGHT", "0.90")),
            "profit_target_pct": env_float("TRADING_TACTICAL_PROFIT_TARGET_PCT", "0.025", "TRADING_PROFIT_TARGET_PCT"),
            "spike_reversal_pct": env_float("TRADING_TACTICAL_SPIKE_REVERSAL_PCT", "0.014", "TRADING_SPIKE_REVERSAL_PCT"),
            "min_spike_profit_pct": env_float("TRADING_TACTICAL_MIN_SPIKE_PROFIT", "0.012", "TRADING_MIN_SPIKE_PROFIT"),
            "atr_multiplier": env_float("TRADING_TACTICAL_ATR_MULTIPLIER", "1.80", "TRADING_ATR_MULTIPLIER"),
            "rsi_entry_threshold": env_float("TRADING_TACTICAL_RSI_ENTRY", "56", "TRADING_RSI_ENTRY"),
            "min_trend_strength": env_float("TRADING_TACTICAL_MIN_TREND_STRENGTH", "0.010", "TRADING_MIN_TREND_STRENGTH"),
            "min_volume_ratio": float(os.getenv("TRADING_TACTICAL_MIN_VOLUME_RATIO", "1.00")),
            "breakeven_trigger_pct": float(os.getenv("TRADING_TACTICAL_BREAKEVEN_TRIGGER", "0.010")),
            "breakeven_lock_pct": float(os.getenv("TRADING_TACTICAL_BREAKEVEN_LOCK", "0.004")),
            "trail_capture_ratio": float(os.getenv("TRADING_TACTICAL_TRAIL_CAPTURE_RATIO", "0.65")),
            "high_volatility_atr_pct": float(os.getenv("TRADING_TACTICAL_HIGH_VOL_ATR_PCT", "0.025")),
            "high_volatility_profit_target_scale": float(os.getenv("TRADING_TACTICAL_HIGH_VOL_TARGET_SCALE", "0.90")),
            "high_volatility_spike_scale": float(os.getenv("TRADING_TACTICAL_HIGH_VOL_SPIKE_SCALE", "0.85")),
            "high_volatility_atr_scale": float(os.getenv("TRADING_TACTICAL_HIGH_VOL_ATR_SCALE", "1.10")),
            "profit_locks": [
                (0.010, 0.005),
                (0.020, 0.010),
                (0.035, 0.020),
            ],
            "allowed_regimes": {"risk_on", "mixed"},
        },
        "speculative": {
            "label": "speculative",
            "risk_weight": float(os.getenv("TRADING_SPECULATIVE_RISK_WEIGHT", "1.20")),
            "profit_target_pct": env_float("TRADING_SPECULATIVE_PROFIT_TARGET_PCT", "0.020", "TRADING_PROFIT_TARGET_PCT"),
            "spike_reversal_pct": env_float("TRADING_SPECULATIVE_SPIKE_REVERSAL_PCT", "0.010", "TRADING_SPIKE_REVERSAL_PCT"),
            "min_spike_profit_pct": env_float("TRADING_SPECULATIVE_MIN_SPIKE_PROFIT", "0.010", "TRADING_MIN_SPIKE_PROFIT"),
            "atr_multiplier": env_float("TRADING_SPECULATIVE_ATR_MULTIPLIER", "2.00", "TRADING_ATR_MULTIPLIER"),
            "rsi_entry_threshold": env_float("TRADING_SPECULATIVE_RSI_ENTRY", "60", "TRADING_RSI_ENTRY"),
            "min_trend_strength": env_float("TRADING_SPECULATIVE_MIN_TREND_STRENGTH", "0.015", "TRADING_MIN_TREND_STRENGTH"),
            "min_volume_ratio": float(os.getenv("TRADING_SPECULATIVE_MIN_VOLUME_RATIO", "1.10")),
            "breakeven_trigger_pct": float(os.getenv("TRADING_SPECULATIVE_BREAKEVEN_TRIGGER", "0.008")),
            "breakeven_lock_pct": float(os.getenv("TRADING_SPECULATIVE_BREAKEVEN_LOCK", "0.004")),
            "trail_capture_ratio": float(os.getenv("TRADING_SPECULATIVE_TRAIL_CAPTURE_RATIO", "0.75")),
            "high_volatility_atr_pct": float(os.getenv("TRADING_SPECULATIVE_HIGH_VOL_ATR_PCT", "0.020")),
            "high_volatility_profit_target_scale": float(os.getenv("TRADING_SPECULATIVE_HIGH_VOL_TARGET_SCALE", "0.85")),
            "high_volatility_spike_scale": float(os.getenv("TRADING_SPECULATIVE_HIGH_VOL_SPIKE_SCALE", "0.80")),
            "high_volatility_atr_scale": float(os.getenv("TRADING_SPECULATIVE_HIGH_VOL_ATR_SCALE", "1.15")),
            "profit_locks": [
                (0.008, 0.004),
                (0.015, 0.008),
                (0.025, 0.015),
            ],
            "allowed_regimes": {"risk_on"},
        },
    }


def resolve_symbol_profile(
    symbol: str,
    core_symbols: set,
    tactical_symbols: set,
    speculative_symbols: set,
) -> str:
    if symbol in core_symbols:
        return "core"
    if symbol in tactical_symbols:
        return "tactical"
    if symbol in speculative_symbols:
        return "speculative"
    if symbol in {"ETH/USD", "BTC/USD"}:
        return "core"
    return "tactical"


def place_entry_order(
    exchange,
    symbol: str,
    base_currency: str,
    amount: float,
    cost: float,
    use_limit_orders: bool,
    limit_order_offset_pct: float,
    enable_trading: bool,
) -> Tuple[bool, float, float, Optional[str]]:
    """Returns (filled, amount, price, pending_order_id).

    `pending_order_id` is set only when a limit order was placed but did not
    confirm as filled within the wait -- callers should track it on the position
    and resolve/cancel it (see `sync_pending_order`) rather than abandoning it.
    """
    if use_limit_orders:
        limit_price = exchange.fetch_ticker(symbol)["last"] * (1 - limit_order_offset_pct)
        print(
            f"[{base_currency}] 🚀 ENTER LONG (LIMIT): Buying {amount:.6f} {base_currency} "
            f"at ${limit_price:.2f} (Cost: ${cost:.2f})"
        )
        if not enable_trading:
            print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
            return True, amount, limit_price, None

        try:
            precise_amount = float(exchange.amount_to_precision(symbol, amount))
            precise_price = float(exchange.price_to_precision(symbol, limit_price))
            order = exchange.create_limit_buy_order(symbol, precise_amount, precise_price)
            print(f"[{base_currency}] ✅ Limit order placed: {order.get('id', 'N/A')}")
            time.sleep(5)
            order_status = exchange.fetch_order(order.get("id"), symbol)
            if order_status.get("status") == "closed":
                print(f"[{base_currency}] ✅ Limit order filled")
                filled, average = extract_fill(order_status, precise_amount, precise_price)
                return True, filled, average, None
            print(f"[{base_currency}] ⏳ Limit order still open; tracking it for next cycle")
            return False, 0.0, 0.0, order.get("id")
        except Exception as exc:
            print(f"[{base_currency}] ❌ Limit entry failed: {exc}")
            try:
                order = exchange.create_market_buy_order(symbol, cost)
                print(f"[{base_currency}] ✅ Fallback market order executed: {order.get('id', 'N/A')}")
                filled, average = extract_fill(order, amount, limit_price)
                return True, filled, average, None
            except Exception as fallback_exc:
                print(f"[{base_currency}] ❌ Market entry also failed: {fallback_exc}")
                return False, 0.0, 0.0, None

    print(f"[{base_currency}] 🚀 ENTER LONG: Buying {amount:.6f} {base_currency} (Cost: ${cost:.2f})")
    if not enable_trading:
        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
        return True, amount, 0.0, None

    try:
        order = exchange.create_market_buy_order(symbol, cost)
        print(f"[{base_currency}] ✅ Order executed: {order.get('id', 'N/A')}")
        filled, average = extract_fill(order, amount, 0.0)
        return True, filled, average, None
    except Exception as exc:
        print(f"[{base_currency}] ❌ Order failed: {exc}")
        return False, 0.0, 0.0, None


def place_exit_order(
    exchange,
    symbol: str,
    base_currency: str,
    amount: float,
    reason: str,
    use_limit_orders: bool,
    limit_order_offset_pct: float,
    enable_trading: bool,
    force_market: bool = False,
    is_reconciled_position: bool = False,
) -> Tuple[bool, Optional[str]]:
    """Returns (filled, pending_order_id) -- see `place_entry_order` for the contract."""
    if not enable_trading:
        if is_reconciled_position:
            print(
                f"[{base_currency}]    (Simulated exit of a position reconciled from your REAL "
                "balance -- your actual holdings are unchanged. Use --execute to sell for real.)"
            )
        else:
            print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
        return True, None

    # Never try to sell more than we actually hold. Fees/slippage mean the tracked
    # amount can slightly exceed the free base balance, which would bounce the order.
    try:
        base_balance = exchange.fetch_balance().get(base_currency, {}).get("free", amount)
        if base_balance and base_balance > 0:
            amount = min(amount, float(base_balance))
        amount = float(exchange.amount_to_precision(symbol, amount))
    except Exception as exc:
        print(f"[{base_currency}] ⚠️  Could not verify balance before sell: {exc}")

    if amount <= 0:
        print(f"[{base_currency}] ⚠️  No sellable balance for {reason}; skipping order.")
        return False, None

    if use_limit_orders and not force_market:
        try:
            last_price = exchange.fetch_ticker(symbol)["last"]
            limit_price = last_price * (1 + limit_order_offset_pct)
            precise_price = float(exchange.price_to_precision(symbol, limit_price))
            order = exchange.create_limit_sell_order(symbol, amount, precise_price)
            print(
                f"[{base_currency}] ✅ {reason} limit order placed: "
                f"{order.get('id', 'N/A')} at ${precise_price:.2f}"
            )
            time.sleep(5)
            order_status = exchange.fetch_order(order.get("id"), symbol)
            if order_status.get("status") == "closed":
                print(f"[{base_currency}] ✅ Limit exit filled")
                return True, None
            print(f"[{base_currency}] ⏳ Exit limit order still open; tracking it for next cycle")
            return False, order.get("id")
        except Exception as exc:
            print(f"[{base_currency}] ❌ Limit exit failed: {exc}")

    try:
        order = exchange.create_market_sell_order(symbol, amount)
        print(f"[{base_currency}] ✅ {reason} market sell executed: {order.get('id', 'N/A')}")
        return True, None
    except Exception as exc:
        print(f"[{base_currency}] ❌ {reason} sell failed: {exc}")
        return False, None


def sync_pending_order(
    exchange,
    symbol: str,
    base_currency: str,
    pos: Dict,
    journal,
    daily_state: Optional[Dict] = None,
) -> str:
    """Resolve or cancel a limit order left resting from a previous cycle.

    Returns one of:
      - "none": no pending order
      - "still_pending": order still open/unknown; caller MUST skip new orders
      - "buy_filled": late buy fill applied (risk state updated)
      - "sell_filled": late sell fill applied (P&L recorded, position reset)
      - "cancelled": stale order cancelled (or cleared after terminal status)
      - "partial_buy": cancelled buy that had already partially filled
      - "partial_sell": cancelled sell that had already partially filled
        (position_amount reduced / P&L recorded; fully closed if nothing remains)

    Without this, an unfilled limit entry/exit is silently abandoned: the order
    keeps sitting on the book while the bot's state machine moves on, and the next
    cycle can place *another* order for the same symbol on top of it.
    """
    order_id = pos.get("pending_order_id")
    if not order_id:
        return "none"

    side = pos.get("pending_order_side")
    try:
        order = exchange.fetch_order(order_id, symbol)
    except Exception as exc:
        print(f"[{base_currency}] ⚠️  Could not check pending {side} order {order_id}: {exc}")
        # Keep tracking and block new orders so we never stack on a live resting order.
        return "still_pending"

    status = order.get("status")

    if status == "closed":
        fallback_amount = pos.get("position_amount", 0.0) or pos.get("pending_order_amount", 0.0)
        fallback_price = pos.get("entry_price", 0.0) or pos.get("pending_order_price", 0.0)
        filled, average = extract_fill(order, fallback_amount, fallback_price)
        print(
            f"[{base_currency}] ✅ Pending {side} order {order_id} had filled: "
            f"{filled:.6f} @ {format_price(average)}"
        )
        journal.log_event(
            f"pending_{side}_order_filled",
            symbol=symbol,
            side=side,
            status="executed",
            price=average,
            amount=filled,
            order_id=order_id,
        )
        if side == "buy":
            pos["position_amount"] = filled
            pos["entry_price"] = average
            pos["peak_price"] = average
            pos["in_position"] = True
            pos["breakeven_set"] = False
            pos["needs_entry_finalize"] = True
            signal = pos.get("pending_entry_signal")
            if daily_state is not None:
                record_trade(daily_state, symbol, signal=signal)
            journal.log_event(
                "entry_executed",
                symbol=symbol,
                side="buy",
                status="executed",
                price=average,
                amount=filled,
                cost_usd=average * filled if average and filled else None,
                order_id=order_id,
                payload={
                    "source": "pending_limit_fill",
                    "rsi": (signal or {}).get("rsi"),
                    "trend_strength": (signal or {}).get("trend_strength"),
                    "volume_ratio": (signal or {}).get("volume_ratio"),
                },
            )
            pos["pending_order_id"] = None
            pos["pending_order_side"] = None
            pos["pending_entry_signal"] = None
            pos["pending_order_amount"] = 0.0
            pos["pending_order_price"] = 0.0
            return "buy_filled"

        entry_price = pos.get("entry_price", 0.0) or 0.0
        amount = pos.get("position_amount", 0.0) or filled
        pnl = (average - entry_price) * amount if entry_price and amount else 0.0
        profit_pct = (average - entry_price) / entry_price if entry_price else 0.0
        if daily_state is not None:
            record_realized_pnl(daily_state, symbol, pnl)
        journal.log_event(
            "exit_executed",
            symbol=symbol,
            side="sell",
            reason="pending_limit_fill",
            status="executed",
            price=average,
            amount=amount,
            cost_usd=average * amount if average and amount else None,
            profit_pct=profit_pct,
            order_id=order_id,
            payload={"estimated_pnl_usd": pnl, "source": "pending_limit_fill"},
        )
        reset_position_state(pos, record_exit=True)
        return "sell_filled"

    if status == "open":
        # Capture any partial fill before cancelling so we do not invent a fresh
        # entry on top of residual inventory.
        try:
            partial_filled = float(order.get("filled") or 0)
        except (TypeError, ValueError):
            partial_filled = 0.0
        try:
            partial_avg = float(order.get("average") or order.get("price") or 0)
        except (TypeError, ValueError):
            partial_avg = 0.0

        try:
            exchange.cancel_order(order_id, symbol)
            print(f"[{base_currency}] 🧹 Cancelled stale {side} limit order {order_id}")
            journal.log_event(
                "pending_order_cancelled",
                symbol=symbol,
                side=side,
                status="cancelled",
                order_id=order_id,
                amount=partial_filled if partial_filled > 0 else None,
                price=partial_avg if partial_avg > 0 else None,
            )
        except Exception as exc:
            print(f"[{base_currency}] ⚠️  Could not cancel stale {side} order {order_id}: {exc}")
            # Leave it tracked so we try again next cycle rather than losing the id.
            return "still_pending"

        # Capture before clearing so a partial-fill entry can still journal the
        # original signal (rebuild_daily_state_from_events reads it from entry_executed).
        signal = pos.get("pending_entry_signal")
        original_entry_price = pos.get("entry_price", 0.0) or 0.0
        buy_entry_price = partial_avg if partial_avg > 0 else original_entry_price

        pos["pending_order_id"] = None
        pos["pending_order_side"] = None
        pos["pending_entry_signal"] = None
        pos["pending_order_amount"] = 0.0
        pos["pending_order_price"] = 0.0

        if side == "buy" and partial_filled > 0:
            pos["position_amount"] = partial_filled
            pos["entry_price"] = buy_entry_price
            pos["peak_price"] = pos["entry_price"]
            pos["in_position"] = True
            pos["breakeven_set"] = False
            pos["needs_entry_finalize"] = True
            if daily_state is not None:
                record_trade(daily_state, symbol, signal=signal)
            # Must journal entry_executed so a mid-day restart can rebuild trade
            # counts / last-signal state from the event stream (record_trade alone
            # only updates in-memory daily_state).
            journal.log_event(
                "entry_executed",
                symbol=symbol,
                side="buy",
                status="executed",
                price=buy_entry_price if buy_entry_price else None,
                amount=partial_filled,
                cost_usd=(
                    buy_entry_price * partial_filled
                    if buy_entry_price and partial_filled
                    else None
                ),
                order_id=order_id,
                payload={
                    "source": "pending_limit_partial_fill",
                    "rsi": (signal or {}).get("rsi"),
                    "trend_strength": (signal or {}).get("trend_strength"),
                    "volume_ratio": (signal or {}).get("volume_ratio"),
                },
            )
            print(
                f"[{base_currency}] ⚠️  Cancelled buy had partial fill "
                f"{partial_filled:.6f}; tracking as open position."
            )
            return "partial_buy"

        if side == "sell" and partial_filled > 0:
            # Shrink tracked inventory to match what is left on the exchange after
            # the partial exit; otherwise later sells / P&L / risk tallies stay
            # sized to the pre-cancel amount.
            tracked_amount = pos.get("position_amount", 0.0) or 0.0
            sold_amount = min(partial_filled, tracked_amount) if tracked_amount > 0 else partial_filled
            remaining = max(0.0, tracked_amount - sold_amount)
            sell_price = partial_avg if partial_avg > 0 else original_entry_price
            pnl = (
                (sell_price - original_entry_price) * sold_amount
                if original_entry_price and sold_amount
                else 0.0
            )
            profit_pct = (
                (sell_price - original_entry_price) / original_entry_price
                if original_entry_price
                else 0.0
            )
            if daily_state is not None:
                record_realized_pnl(daily_state, symbol, pnl)
            journal.log_event(
                "exit_executed",
                symbol=symbol,
                side="sell",
                reason="pending_limit_partial_fill",
                status="executed",
                price=sell_price if sell_price else None,
                amount=sold_amount,
                cost_usd=(
                    sell_price * sold_amount if sell_price and sold_amount else None
                ),
                profit_pct=profit_pct,
                order_id=order_id,
                payload={
                    "estimated_pnl_usd": pnl,
                    "source": "pending_limit_partial_fill",
                    "remaining_amount": remaining,
                },
            )
            if remaining <= 0:
                reset_position_state(pos, record_exit=True)
                print(
                    f"[{base_currency}] ⚠️  Cancelled sell had partial fill "
                    f"{sold_amount:.6f}; position fully closed."
                )
            else:
                pos["position_amount"] = remaining
                print(
                    f"[{base_currency}] ⚠️  Cancelled sell had partial fill "
                    f"{sold_amount:.6f}; remaining position {remaining:.6f}."
                )
            return "partial_sell"

        return "cancelled"

    # canceled / rejected / expired / unknown -- stop tracking, nothing left to reconcile.
    pos["pending_order_id"] = None
    pos["pending_order_side"] = None
    pos["pending_entry_signal"] = None
    pos["pending_order_amount"] = 0.0
    pos["pending_order_price"] = 0.0
    return "cancelled"


def get_regime_state(
    exchange, benchmark_symbols: List[str], regime_timeframe: str
) -> Tuple[str, Dict[str, Dict], bool]:
    """Returns (regime_label, snapshots, quorum_ok).

    `quorum_ok` is False whenever one or more benchmarks failed to return usable
    data this cycle (e.g. a transient fetch error). Previously a single missing
    benchmark silently shrank the vote to whichever symbols did respond, so a
    network blip on one of two benchmarks could flip risk_on/risk_off from a single
    symbol's read. On a degraded quorum this now returns the conservative "mixed"
    label instead of guessing from a partial vote; callers should treat that
    distinctly from a normal regime change (see the `regime_degraded_quorum` event).
    """
    snapshots = {}
    bullish = 0
    bearish = 0

    for benchmark_symbol in benchmark_symbols:
        df = fetch_data(exchange, benchmark_symbol, regime_timeframe, limit=120)
        if df.empty or len(df) < 55:
            continue

        row = analyze_regime(df)
        price = row["close"]
        ema_50 = row["ema_50"]
        rsi = row["rsi"]
        ema_slope = row["ema_slope"]

        if pd.isna(price) or pd.isna(ema_50) or pd.isna(rsi) or pd.isna(ema_slope):
            continue

        is_bullish = price > ema_50 and rsi >= 52 and ema_slope > 0
        is_bearish = price < ema_50 and rsi <= 48 and ema_slope < 0

        snapshots[benchmark_symbol] = {
            "price": price,
            "ema_50": ema_50,
            "rsi": rsi,
            "is_bullish": is_bullish,
            "is_bearish": is_bearish,
        }

        if is_bullish:
            bullish += 1
        elif is_bearish:
            bearish += 1

    quorum_ok = len(snapshots) == len(benchmark_symbols) and len(snapshots) > 0
    if not quorum_ok:
        return "mixed", snapshots, False
    if bullish == len(snapshots):
        return "risk_on", snapshots, True
    if bearish == len(snapshots):
        return "risk_off", snapshots, True
    return "mixed", snapshots, True


def get_position_size(exchange, symbol: str, current_price: float, symbol_risk_slice: float, leverage: int) -> Tuple[float, float]:
    try:
        balance = exchange.fetch_balance()
        free_usd = balance.get("USD", {}).get("free", 0) or 0
        if free_usd <= 0:
            free_usd = balance.get("USDC", {}).get("free", 0) or 0
        return compute_position_size(free_usd, current_price, symbol_risk_slice, leverage)
    except Exception as exc:
        print(f"Balance Error for {symbol}: {exc}")
        return 0, 0


def roll_daily_state_if_needed(state: Dict, exchange, journal) -> None:
    today = current_day_key()
    if today == state["day"]:
        return

    journal.log_event(
        "daily_reset",
        status="reset",
        payload={
            "previous_day": state["day"],
            "trades": state["trades"],
            "realized_pnl_usd": state["realized_pnl_usd"],
            "symbol_trades": state["symbol_trades"],
            "symbol_realized_pnl_usd": state["symbol_realized_pnl_usd"],
            "halted_symbols": [s for s, v in state["symbol_halted"].items() if v],
        },
    )
    start_equity = state.get("start_equity_usd", 0.0)
    try:
        snap = fetch_portfolio_snapshot(exchange)
        start_equity = snap["total_estimated_usd"]
    except Exception:
        pass
    reset_daily_state(state, today, start_equity)


def reconcile_open_positions(
    exchange,
    symbols: List[str],
    positions: Dict,
    symbol_profiles: Dict,
    profile_settings: Dict,
    timeframe: str,
    min_value_usd: float,
    journal,
) -> None:
    """Rebuild in-memory position state from existing exchange balances on startup.

    Without this, a restart forgets open positions, so their stops go unmanaged and
    the bot may re-buy coins already held. Entry price is unknown after a restart, so
    the current price is used as a best-effort proxy for stop/target placement.
    """
    try:
        balance = exchange.fetch_balance()
    except Exception as exc:
        print(f"⚠️  Could not fetch balance for reconciliation: {exc}")
        return

    for symbol in symbols:
        base_currency = symbol.split("/")[0]
        info = balance.get(base_currency, {})
        if not isinstance(info, dict):
            continue
        held_amount = info.get("total", 0) or info.get("free", 0) or 0
        if held_amount <= 0:
            continue

        df = fetch_data(exchange, symbol, timeframe)
        if df.empty or len(df) < 30:
            continue

        row = analyze_market(df)
        price = row["close"]
        atr = row["atr"]
        usd_value = held_amount * price
        if usd_value < max(min_value_usd, 1.0):
            continue

        profile_name = symbol_profiles[symbol]
        profile = profile_settings[profile_name]
        pos = positions[symbol]
        pos["in_position"] = True
        pos["position_amount"] = held_amount
        pos["entry_price"] = price
        pos["peak_price"] = price
        pos["trailing_stop_price"] = price - (atr * profile["atr_multiplier"])
        pos["trailing_profit_target"] = price * (1 + profile["profit_target_pct"])
        pos["breakeven_set"] = False
        # Marks this as backed by a real exchange balance, not a bot-opened entry, so
        # a simulated (non --execute) run can say clearly that a later "exit" doesn't
        # touch the actual holdings -- see place_exit_order's simulated-mode message.
        pos["reconciled_from_balance"] = True
        print(
            f"[{base_currency}] ♻️  Reconciled existing position: {held_amount:.6f} "
            f"@ ~{format_price(price)} (${usd_value:.2f})"
        )
        journal.log_event(
            "position_reconciled",
            symbol=symbol,
            profile=profile_name,
            status="reconciled",
            price=price,
            amount=held_amount,
            cost_usd=usd_value,
            payload={"note": "entry_price is a best-effort estimate from current price"},
        )


load_dotenv()

parser = argparse.ArgumentParser(description="Multi-Symbol Coinbase Trading Bot")
parser.add_argument("--test", action="store_true", help="Run in test mode")
parser.add_argument("--sandbox", action="store_true", help="Use sandbox environment")
parser.add_argument("--execute", action="store_true", help="Enable actual trade execution")
args = parser.parse_args()

use_sandbox = args.sandbox or args.test
enable_trading = args.execute

if use_sandbox and os.path.exists(".env.sandbox"):
    load_dotenv(".env.sandbox", override=True)
elif not use_sandbox and os.path.exists(".env.production"):
    load_dotenv(".env.production", override=True)

symbols = parse_symbol_list(
    os.getenv("TRADING_SYMBOLS", "ETH/USD,BTC/USD,LINK/USD,SHIB/USD,ALGO/USD,FET/USD")
)
timeframe = os.getenv("TRADING_TIMEFRAME", "5m")
leverage = int(os.getenv("TRADING_LEVERAGE", "1"))
risk_pct = float(os.getenv("TRADING_RISK_PCT", "0.20"))
check_interval = int(os.getenv("TRADING_CHECK_INTERVAL", "60"))
cooldown_minutes = int(os.getenv("TRADING_COOLDOWN_MINUTES", "5"))
min_order_size = float(os.getenv("TRADING_MIN_ORDER_SIZE", "1.00"))
benchmark_symbols = parse_symbol_list(os.getenv("TRADING_REGIME_SYMBOLS", "BTC/USD,ETH/USD"))
regime_timeframe = os.getenv("TRADING_REGIME_TIMEFRAME", "1h")

use_limit_orders = os.getenv("TRADING_USE_LIMIT_ORDERS", "false").lower() == "true"
limit_order_offset_pct = float(os.getenv("TRADING_LIMIT_ORDER_OFFSET", "0.001"))
log_signal_checks = os.getenv("TRADING_LOG_SIGNAL_CHECKS", "true").lower() == "true"
snapshot_interval_minutes = int(os.getenv("TRADING_PORTFOLIO_SNAPSHOT_MINUTES", "30"))

# Risk guardrails (set any to 0 to disable that specific limit).
# Trade counts and the loss limit are tracked PER COIN.
max_open_positions = int(os.getenv("TRADING_MAX_OPEN_POSITIONS", "3"))
max_trades_per_day = int(os.getenv("TRADING_MAX_TRADES_PER_DAY", "0"))
max_trades_per_symbol_per_day = int(os.getenv("TRADING_MAX_TRADES_PER_SYMBOL_PER_DAY", "6"))
daily_loss_limit_pct = float(os.getenv("TRADING_DAILY_LOSS_LIMIT_PCT", "0.05"))
# Re-entries on a coin must present a signal at least as strong as its previous entry.
require_stronger_reentry = os.getenv("TRADING_REQUIRE_STRONGER_REENTRY", "true").lower() == "true"
min_setup_improvement = float(os.getenv("TRADING_MIN_SETUP_IMPROVEMENT", "0.0"))
reconcile_on_start = os.getenv("TRADING_RECONCILE_ON_START", "true").lower() == "true"
reconcile_min_value_usd = float(
    os.getenv("TRADING_RECONCILE_MIN_USD", os.getenv("MIN_POSITION_VALUE_USD", "5.00"))
)

core_symbols = set(parse_symbol_list(os.getenv("TRADING_CORE_SYMBOLS", "ETH/USD,BTC/USD")))
tactical_symbols = set(parse_symbol_list(os.getenv("TRADING_TACTICAL_SYMBOLS", "LINK/USD,SHIB/USD")))
speculative_symbols = set(parse_symbol_list(os.getenv("TRADING_SPECULATIVE_SYMBOLS", "ALGO/USD,FET/USD")))
profile_settings = build_profile_settings()

symbol_profiles = {
    symbol: resolve_symbol_profile(symbol, core_symbols, tactical_symbols, speculative_symbols)
    for symbol in symbols
}
symbol_weights = {
    symbol: profile_settings[symbol_profiles[symbol]]["risk_weight"]
    for symbol in symbols
}
total_risk_weight = sum(symbol_weights.values()) or float(len(symbols) or 1)

for config_warning in validate_symbol_configuration(
    symbols, core_symbols, tactical_symbols, speculative_symbols
):
    print(f"⚠️  Config warning: {config_warning}")

api_key = os.getenv("COINBASE_API_KEY", "YOUR_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET", "YOUR_SECRET_KEY")
api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")
journal = TradingJournal.from_env()

if api_secret and "\\n" in api_secret:
    api_secret = api_secret.replace("\\n", "\n")

if args.test:
    print("🧪 TEST MODE ENABLED")
    print("=" * 60)

try:
    # Coinbase Advanced Trade is exposed as `ccxt.coinbase` in current ccxt versions.
    # Older aliases (e.g. `coinbaseadvanced`) may not exist, so resolve defensively
    # with getattr instead of attribute access that would raise AttributeError.
    if use_sandbox:
        preferred_exchange_ids = ["coinbaseexchange", "coinbase", "coinbaseadvanced"]
    else:
        preferred_exchange_ids = ["coinbase", "coinbaseadvanced", "coinbaseexchange"]

    ExchangeClass = None
    exchange_id = None
    for candidate_id in preferred_exchange_ids:
        ExchangeClass = getattr(ccxt, candidate_id, None)
        if ExchangeClass is not None:
            exchange_id = candidate_id
            break
    if ExchangeClass is None:
        raise AttributeError(
            "No Coinbase exchange class found in ccxt. Update ccxt: pip install -U ccxt"
        )

    exchange_config = {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "sandbox": use_sandbox,
        "options": {
            "createMarketBuyOrderRequiresPrice": False,
        },
    }

    if use_sandbox:
        exchange_config["password"] = api_passphrase if api_passphrase else ""
    elif api_passphrase:
        exchange_config["password"] = api_passphrase

    exchange = ExchangeClass(exchange_config)
    print(f"🔌 Connecting to {'SANDBOX' if use_sandbox else 'PRODUCTION'} via ccxt.{exchange_id}...")
    exchange.load_markets()
    print("✅ Connected to Coinbase Advanced Trade successfully.")
    print(f"📊 Trading symbols: {', '.join(symbols)}")

    if args.test:
        print(f"📊 Loaded {len(exchange.markets)} markets")
        for symbol in symbols:
            if symbol in exchange.markets:
                print(f"✅ Symbol {symbol} is available")
            else:
                print(f"⚠️  Symbol {symbol} not found")

    for symbol in symbols:
        market = exchange.markets.get(symbol) or {}
        limits = market.get("limits") or {}
        exchange_min_cost = (limits.get("cost") or {}).get("min")
        if exchange_min_cost and exchange_min_cost > min_order_size:
            print(
                f"⚠️  {symbol}: Coinbase's own minimum order cost is ~${exchange_min_cost:.2f}, "
                f"above TRADING_MIN_ORDER_SIZE=${min_order_size:.2f}. Entries will still be "
                "attempted and may be rejected until you raise TRADING_MIN_ORDER_SIZE."
            )
except Exception as exc:
    journal.log_event(
        "runtime_error",
        reason="exchange_connection",
        status="failed",
        payload={"message": str(exc)},
    )
    print(f"❌ Connection Error: {exc}")
    sys.exit()

try:
    for symbol in symbols:
        exchange.set_leverage(leverage, symbol)
    print(f"⚡ Leverage set to {leverage}x for all symbols.")
except Exception as exc:
    journal.log_event(
        "warning",
        reason="set_leverage_not_supported",
        status="warning",
        payload={"message": str(exc)},
    )
    print(f"⚠️  Could not set leverage automatically: {exc}")

if leverage > 1:
    print(
        f"⚠️  TRADING_LEVERAGE={leverage}. Coinbase Advanced Trade spot has no leverage; "
        "set TRADING_LEVERAGE=1 unless you are certain your account supports margin."
    )

positions = {}
for symbol in symbols:
    positions[symbol] = {
        "in_position": False,
        "trailing_stop_price": 0.0,
        "position_amount": 0.0,
        "entry_price": 0.0,
        "breakeven_set": False,
        "peak_price": 0.0,
        "trailing_profit_target": 0.0,
        "last_exit_time": 0,
        "reconciled_from_balance": False,
        "pending_order_id": None,
        "pending_order_side": None,
        "pending_entry_signal": None,
        "pending_order_amount": 0.0,
        "pending_order_price": 0.0,
        "needs_entry_finalize": False,
    }

if reconcile_on_start:
    print("♻️  Reconciling existing exchange positions...")
    reconcile_open_positions(
        exchange,
        symbols,
        positions,
        symbol_profiles,
        profile_settings,
        timeframe,
        reconcile_min_value_usd,
        journal,
    )

print(f"🛡️ Active. Risking {risk_pct * 100:.1f}% total across {len(symbols)} symbols.")
print(f"🧭 Market regime guardrails use {', '.join(benchmark_symbols)} on {regime_timeframe} candles.")
print(
    "🗃️ Journal backend: "
    f"{journal.describe_backend()}"
    + ("" if journal.is_persistent() else " (non-persistent unless you add DATABASE_URL)")
)
if use_limit_orders:
    print("💵 Order Type: LIMIT ORDERS with market fallback")
else:
    print("💵 Order Type: MARKET ORDERS")
for symbol in symbols:
    profile_name = symbol_profiles[symbol]
    profile = profile_settings[profile_name]
    risk_slice = risk_pct * symbol_weights[symbol] / total_risk_weight
    print(
        f"   {symbol:<10} profile={profile_name:<11} "
        f"risk={format_pct(risk_slice)} target={format_pct(profile['profit_target_pct'])} "
        f"spike={format_pct(profile['spike_reversal_pct'])}"
    )
print(f"⏸️  Cooldown Period: {cooldown_minutes} minutes after exit")
print(f"⏱️  Check Interval: {check_interval} seconds")
print(
    "🚧 Daily guardrails (per coin): "
    f"max_open={max_open_positions or 'off'} "
    f"max_trades/coin={max_trades_per_symbol_per_day or 'off'} "
    f"max_trades/day_total={max_trades_per_day or 'off'} "
    f"loss_limit/coin={format_pct(daily_loss_limit_pct) if daily_loss_limit_pct > 0 else 'off'} "
    f"stronger_reentry={'on' if require_stronger_reentry else 'off'}"
)
if enable_trading:
    print("⚠️  TRADING ENABLED - Real orders will be executed!")
else:
    print("ℹ️  Trading disabled - orders are simulated (use --execute to enable)")

journal.log_event(
    "bot_started",
    status="running",
    payload={
        "symbols": symbols,
        "timeframe": timeframe,
        "regime_symbols": benchmark_symbols,
        "risk_pct": risk_pct,
        "leverage": leverage,
        "enable_trading": enable_trading,
        "journal_backend": journal.describe_backend(),
    },
)

today = current_day_key()
day_start_iso = f"{today}T00:00:00+00:00"
# Pending limits can outlive a UTC day boundary (and a crash that lasts hours),
# so pending-order restore looks back further than the daily risk-state window.
pending_order_lookback_days = int(os.getenv("TRADING_PENDING_ORDER_LOOKBACK_DAYS", "7"))
pending_lookback_iso = (
    datetime.now(timezone.utc) - timedelta(days=max(pending_order_lookback_days, 1))
).isoformat()

# Look for today's earliest portfolio snapshot and events *before* touching the
# journal further below, so a restart mid-day can recover the day's actual
# starting equity and risk counters instead of quietly starting over at zero.
day_start_equity_usd = None
todays_events: List[Dict] = []
pending_order_events: List[Dict] = []
if journal.enabled:
    try:
        earliest_snapshot_today = journal.get_first_snapshot_after(day_start_iso)
        if earliest_snapshot_today:
            day_start_equity_usd = earliest_snapshot_today.get("total_estimated_usd")
        # One query covers both: filter to today for daily risk rebuild, keep the
        # full lookback for unresolved resting limit orders.
        pending_order_events = journal.get_events_between(
            pending_lookback_iso, utc_now_iso()
        )
        todays_events = [
            event
            for event in pending_order_events
            if (event.get("created_at") or "") >= day_start_iso
        ]
    except Exception as exc:
        journal.log_event(
            "warning",
            reason="daily_state_rebuild_query_failed",
            status="warning",
            payload={"message": str(exc)},
        )

try:
    initial_snapshot = fetch_portfolio_snapshot(exchange)
    current_equity_usd = initial_snapshot["total_estimated_usd"]
    journal.log_portfolio_snapshot(
        total_estimated_usd=initial_snapshot["total_estimated_usd"],
        free_usd=initial_snapshot["free_usd"],
        invested_usd=initial_snapshot["invested_usd"],
        positions=initial_snapshot["positions"],
    )
except Exception as exc:
    current_equity_usd = 0.0
    journal.log_event(
        "warning",
        reason="initial_snapshot_failed",
        status="warning",
        payload={"message": str(exc)},
    )

if day_start_equity_usd is None:
    day_start_equity_usd = current_equity_usd

if todays_events:
    daily_state = rebuild_daily_state_from_events(
        today, day_start_equity_usd, todays_events, daily_loss_limit_pct
    )
    halted_symbols = [s for s, halted in daily_state["symbol_halted"].items() if halted]
    print(
        f"♻️  Restored today's risk state from the journal: {daily_state['trades']} trade(s) "
        f"so far, halted={halted_symbols or 'none'}"
    )
    journal.log_event(
        "daily_state_restored",
        status="restored",
        payload={
            "trades": daily_state["trades"],
            "symbol_trades": daily_state["symbol_trades"],
            "symbol_realized_pnl_usd": daily_state["symbol_realized_pnl_usd"],
            "halted_symbols": halted_symbols,
            "start_equity_usd": day_start_equity_usd,
        },
    )
else:
    daily_state = new_daily_state(today, day_start_equity_usd)

# Re-attach any resting limit orders the previous process left on the book.
# Without this, pending_order_id resets to None on every boot and the next cycle
# can place a second overlapping order while the first is still open.
if pending_order_events:
    restored_pending = restore_pending_orders_from_events(positions, pending_order_events)
    if restored_pending:
        print(
            f"♻️  Restored {len(restored_pending)} resting limit order(s) from the journal:"
        )
        for symbol, info in restored_pending.items():
            print(
                f"   {symbol}: {info['side']} order {info['order_id']} "
                f"(amount={info['amount']}, price={info['price']})"
            )
        journal.log_event(
            "pending_orders_restored",
            status="restored",
            payload={"orders": restored_pending},
        )

last_regime_label = None
last_snapshot_time = time.time()

while True:
    roll_daily_state_if_needed(daily_state, exchange, journal)
    regime_label, regime_snapshots, regime_quorum_ok = get_regime_state(
        exchange, benchmark_symbols, regime_timeframe
    )
    if not regime_quorum_ok:
        print(
            f"⚠️  Regime quorum incomplete ({len(regime_snapshots)}/{len(benchmark_symbols)} "
            "benchmarks reported) -- treating this cycle as MIXED rather than voting on a "
            "partial read."
        )
        journal.log_event(
            "regime_degraded_quorum",
            regime=regime_label,
            status="degraded",
            payload={"snapshots": regime_snapshots, "expected_benchmarks": benchmark_symbols},
        )
    if regime_label != last_regime_label:
        print(f"🌡️ Market Regime: {regime_label.upper()}")
        for benchmark_symbol, snapshot in regime_snapshots.items():
            print(
                f"   {benchmark_symbol}: price={format_price(snapshot['price'])} "
                f"EMA50={format_price(snapshot['ema_50'])} RSI={snapshot['rsi']:.2f}"
            )
        journal.log_event(
            "regime_changed",
            regime=regime_label,
            status="updated",
            payload={"snapshots": regime_snapshots},
        )
        last_regime_label = regime_label

    for symbol in symbols:
        try:
            base_currency = symbol.split("/")[0]
            pos = positions[symbol]
            sync_status = sync_pending_order(
                exchange, symbol, base_currency, pos, journal, daily_state=daily_state
            )
            has_pending_order = (
                sync_status == "still_pending" or bool(pos.get("pending_order_id"))
            )
            pending_side = pos.get("pending_order_side")
            # A resting sell *is* the exit -- don't stack another. A resting buy (or
            # any pending while flat) only blocks new entries. If we somehow still
            # hold inventory with a non-sell pending order, fall through so stop-loss
            # / profit checks can still run against the live price.
            if has_pending_order and (
                not pos.get("in_position") or pending_side == "sell"
            ):
                print(
                    f"[{base_currency}] ⏳ Waiting on pending {pending_side} "
                    f"order {pos.get('pending_order_id')}; skipping new trades this cycle."
                )
                continue

            profile_name = symbol_profiles[symbol]
            profile = profile_settings[profile_name]

            indicators_ok = False
            price = 0.0
            ema_20 = float("nan")
            atr = float("nan")
            rsi = float("nan")
            ema_slope = 0.0
            volume_ratio = 1.0

            df = fetch_data(exchange, symbol, timeframe)
            if not df.empty and len(df) >= 30:
                row = analyze_market(df)
                price = row["close"]
                ema_20 = row["ema_20"]
                atr = row["atr"]
                rsi = row["rsi"]
                ema_slope = row.get("ema_slope", 0)
                volume_ratio = row.get("volume_ratio", 1.0)
                if not (
                    pd.isna(price) or pd.isna(ema_20) or pd.isna(atr) or pd.isna(rsi)
                ):
                    indicators_ok = True

            if not indicators_ok:
                # Entries need indicators; open-position exits mostly need a live
                # price against already-set stops/targets. Skipping the whole symbol
                # here used to leave positions unmanaged for a full cycle.
                if not pos.get("in_position"):
                    if not df.empty and len(df) >= 30:
                        journal.log_event(
                            "warning",
                            symbol=symbol,
                            reason="indicator_data_incomplete",
                            status="skipped",
                            payload={
                                "note": "insufficient candle history for indicators this cycle"
                            },
                        )
                        print(
                            f"[{base_currency}] ⚠️  Incomplete indicator data this cycle; skipping."
                        )
                    continue

                journal.log_event(
                    "warning",
                    symbol=symbol,
                    reason="indicator_data_incomplete",
                    status="exit_only",
                    payload={
                        "note": (
                            "indicators unavailable; managing open position with live "
                            "price only (no new entries / ATR stop ratchet this cycle)"
                        )
                    },
                )
                try:
                    live_price = exchange.fetch_ticker(symbol)["last"]
                    if not live_price or live_price <= 0:
                        print(
                            f"[{base_currency}] ⚠️  Incomplete indicators and no usable "
                            "live price; skipping."
                        )
                        continue
                    price = live_price
                except Exception as exc:
                    print(
                        f"[{base_currency}] ⚠️  Incomplete indicators and live price "
                        f"fetch failed ({exc}); skipping."
                    )
                    continue
                print(
                    f"[{base_currency}] ⚠️  Incomplete indicator data; still managing "
                    "open position exits off live price."
                )

            trend_strength = (
                abs(price - ema_20) / ema_20 if indicators_ok and ema_20 > 0 else 0
            )
            atr_pct = atr / price if indicators_ok and price > 0 else 0

            dynamic_profit_target = profile["profit_target_pct"]
            dynamic_spike_reversal = profile["spike_reversal_pct"]
            dynamic_min_spike_profit = profile["min_spike_profit_pct"]
            dynamic_atr_multiplier = profile["atr_multiplier"]

            if indicators_ok and atr_pct >= profile["high_volatility_atr_pct"]:
                dynamic_profit_target *= profile["high_volatility_profit_target_scale"]
                dynamic_spike_reversal *= profile["high_volatility_spike_scale"]
                dynamic_atr_multiplier *= profile["high_volatility_atr_scale"]

            # Late limit-buy fills (and partial fills after cancel) need stop/target
            # initialized from the current candle's ATR once indicators are available.
            if (
                indicators_ok
                and pos.get("needs_entry_finalize")
                and pos.get("in_position")
                and pos.get("entry_price")
            ):
                entry_px = pos["entry_price"]
                pos["trailing_stop_price"] = entry_px - (atr * dynamic_atr_multiplier)
                pos["trailing_profit_target"] = entry_px * (1 + dynamic_profit_target)
                pos["needs_entry_finalize"] = False
                print(
                    f"[{base_currency}] 🔧 Finalized late-fill entry: stop="
                    f"{format_price(pos['trailing_stop_price'])} target="
                    f"{format_price(pos['trailing_profit_target'])}"
                )

            if indicators_ok:
                print(
                    f"[{base_currency}] Price: {format_price(price)} | RSI: {rsi:.2f} | "
                    f"Stop: {format_price(pos['trailing_stop_price'])} | "
                    f"Position: {'YES' if pos['in_position'] else 'NO'} | "
                    f"Profile: {profile_name}"
                )
            else:
                print(
                    f"[{base_currency}] Price: {format_price(price)} | RSI: n/a | "
                    f"Stop: {format_price(pos['trailing_stop_price'])} | "
                    f"Position: YES | Profile: {profile_name} (exit-only)"
                )

            if not pos["in_position"]:
                current_time = time.time()
                time_since_exit = (
                current_time - pos["last_exit_time"]
                    if pos["last_exit_time"] > 0
                    else cooldown_minutes * 60 + 1
                )

                price_above_ema = price > ema_20
                rsi_strong = rsi > profile["rsi_entry_threshold"]
                trend_strong_enough = trend_strength >= profile["min_trend_strength"]
                ema_trending_up = ema_slope > 0
                volume_adequate = volume_ratio >= profile["min_volume_ratio"]
                cooldown_active = time_since_exit < cooldown_minutes * 60
                regime_allowed = regime_label in profile["allowed_regimes"]
                blocked_reasons = []

                open_positions_count = sum(
                    1 for state in positions.values() if state["in_position"]
                )

                current_signal = {
                    "rsi": rsi,
                    "trend_strength": trend_strength,
                    "volume_ratio": volume_ratio,
                }
                limit_reasons = evaluate_entry_limits(
                    daily_state,
                    symbol,
                    open_positions_count,
                    max_open_positions,
                    max_trades_per_day,
                    max_trades_per_symbol_per_day,
                    daily_loss_limit_pct,
                    require_stronger_setup=require_stronger_reentry,
                    current_signal=current_signal,
                    min_setup_improvement=min_setup_improvement,
                )
                # Latch the per-coin halt the first time a coin breaches its loss budget.
                if "daily_loss_limit" in limit_reasons and not daily_state["symbol_halted"].get(symbol):
                    daily_state["symbol_halted"][symbol] = True
                    print(
                        f"[{base_currency}] 🛑 Per-coin daily loss limit reached "
                        f"(realized {format_price(daily_state['symbol_realized_pnl_usd'].get(symbol, 0.0))}). "
                        "Pausing new entries for this coin until tomorrow."
                    )
                    journal.log_event(
                        "daily_loss_limit_triggered",
                        symbol=symbol,
                        profile=profile_name,
                        status="halted",
                        payload={
                            "symbol_realized_pnl_usd": daily_state["symbol_realized_pnl_usd"].get(symbol, 0.0),
                            "start_equity_usd": daily_state["start_equity_usd"],
                            "loss_limit_pct": daily_loss_limit_pct,
                        },
                    )
                blocked_reasons.extend(limit_reasons)
                if cooldown_active:
                    blocked_reasons.append("cooldown_active")
                if not regime_allowed:
                    blocked_reasons.append("regime_blocked")
                if not price_above_ema:
                    blocked_reasons.append("price_below_ema")
                if not rsi_strong:
                    blocked_reasons.append("rsi_below_threshold")
                if not trend_strong_enough:
                    blocked_reasons.append("trend_too_weak")
                if not ema_trending_up:
                    blocked_reasons.append("ema_not_rising")
                if not volume_adequate:
                    blocked_reasons.append("volume_below_average")

                if log_signal_checks:
                    journal.log_event(
                        "signal_evaluation",
                        symbol=symbol,
                        profile=profile_name,
                        regime=regime_label,
                        status="entry_ready" if not blocked_reasons else "blocked",
                        price=price,
                        payload={
                            "entry_ready": not blocked_reasons,
                            "blocked_reasons": blocked_reasons,
                            "rsi": rsi,
                            "ema_20": ema_20,
                            "atr": atr,
                            "atr_pct": atr_pct,
                            "trend_strength": trend_strength,
                            "ema_slope": ema_slope,
                            "volume_ratio": volume_ratio,
                            "cooldown_seconds_remaining": max(cooldown_minutes * 60 - time_since_exit, 0),
                        },
                    )

                if blocked_reasons:
                    continue

                if price_above_ema and rsi_strong and trend_strong_enough and ema_trending_up and volume_adequate:
                    risk_slice = risk_pct * symbol_weights[symbol] / total_risk_weight
                    amount, cost = get_position_size(exchange, symbol, price, risk_slice, leverage)

                    if cost < min_order_size:
                        journal.log_event(
                            "entry_skipped",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            reason="order_below_minimum",
                            status="skipped",
                            price=price,
                            amount=amount,
                            cost_usd=cost,
                        )
                        print(
                            f"[{base_currency}] ⚠️  Order too small: "
                            f"${cost:.2f} < ${min_order_size:.2f} minimum. Skipping."
                        )
                        continue

                    if amount <= 0:
                        journal.log_event(
                            "entry_skipped",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            reason="no_position_size",
                            status="skipped",
                            price=price,
                        )
                        continue

                    entry_executed, filled_amount, fill_price, pending_order_id = place_entry_order(
                        exchange,
                        symbol,
                        base_currency,
                        amount,
                        cost,
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                    )

                    if entry_executed:
                        effective_price = fill_price if fill_price and fill_price > 0 else price
                        effective_amount = filled_amount if filled_amount and filled_amount > 0 else amount
                        pos["trailing_stop_price"] = effective_price - (atr * dynamic_atr_multiplier)
                        pos["position_amount"] = effective_amount
                        pos["entry_price"] = effective_price
                        pos["peak_price"] = effective_price
                        pos["trailing_profit_target"] = effective_price * (1 + dynamic_profit_target)
                        pos["in_position"] = True
                        pos["breakeven_set"] = False
                        record_trade(daily_state, symbol, signal=current_signal)
                        journal.log_event(
                            "entry_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="buy",
                            status="executed",
                            price=effective_price,
                            amount=effective_amount,
                            cost_usd=cost,
                            payload={
                                "rsi": rsi,
                                "atr_pct": atr_pct,
                                "trend_strength": trend_strength,
                                "volume_ratio": volume_ratio,
                                "profit_target_pct": dynamic_profit_target,
                                "spike_reversal_pct": dynamic_spike_reversal,
                            },
                        )
                    else:
                        if pending_order_id:
                            pos["pending_order_id"] = pending_order_id
                            pos["pending_order_side"] = "buy"
                            pos["pending_entry_signal"] = current_signal
                            pos["pending_order_amount"] = amount
                            pos["pending_order_price"] = price
                        journal.log_event(
                            "entry_unfilled_or_failed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="buy",
                            status="pending_or_failed",
                            price=price,
                            amount=amount,
                            cost_usd=cost,
                            order_id=pending_order_id,
                            # Persist the signal so a restart can rebuild
                            # pending_entry_signal for late-fill risk accounting.
                            payload={
                                "signal": current_signal if pending_order_id else None,
                            },
                        )
                        continue

            else:
                # Entries above use the last CLOSED candle to avoid repainting, but
                # that means a stop/target decided once per TRADING_CHECK_INTERVAL
                # (default 60s) against a candle close can be reacting to data that's
                # stale by anywhere up to ~one candle. Exit management reacts faster
                # by checking the live price instead -- bounded to at most one extra
                # API call per *open* position per cycle (capped by
                # TRADING_MAX_OPEN_POSITIONS), not one per tracked symbol.
                try:
                    live_price = exchange.fetch_ticker(symbol)["last"]
                    if live_price and live_price > 0:
                        price = live_price
                except Exception as exc:
                    print(f"[{base_currency}] ⚠️  Could not fetch live price, using candle close: {exc}")

                entry_price = pos["entry_price"]
                profit_pct = (price - entry_price) / entry_price if entry_price > 0 else 0

                if price > pos["peak_price"]:
                    pos["peak_price"] = price
                    new_target = entry_price * (1 + dynamic_profit_target) + (
                        (price - entry_price) * profile["trail_capture_ratio"]
                    )
                    if new_target > pos["trailing_profit_target"]:
                        pos["trailing_profit_target"] = new_target

                peak_profit_pct = (
                    (pos["peak_price"] - entry_price) / entry_price if entry_price > 0 else 0
                )
                drop_from_peak_pct = (
                    (pos["peak_price"] - price) / pos["peak_price"] if pos["peak_price"] > 0 else 0
                )

                if (
                    peak_profit_pct >= dynamic_min_spike_profit
                    and drop_from_peak_pct >= dynamic_spike_reversal
                ):
                    print(
                        f"[{base_currency}] 📉 SPIKE REVERSAL DETECTED: "
                        f"Price dropped {drop_from_peak_pct * 100:.2f}% from peak "
                        f"{format_price(pos['peak_price'])}"
                    )
                    print(
                        f"[{base_currency}] 💰 Capturing profit: {profit_pct * 100:.2f}% "
                        f"(Peak was {peak_profit_pct * 100:.2f}%)"
                    )

                    exit_executed, pending_order_id = place_exit_order(
                        exchange,
                        symbol,
                        base_currency,
                        pos["position_amount"],
                        "Spike reversal",
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                        is_reconciled_position=pos.get("reconciled_from_balance", False),
                    )
                    if exit_executed:
                        journal.log_event(
                            "exit_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="spike_reversal",
                            status="executed",
                            price=price,
                            amount=pos["position_amount"],
                            cost_usd=price * pos["position_amount"],
                            profit_pct=profit_pct,
                            payload={
                                "estimated_pnl_usd": (price - entry_price) * pos["position_amount"],
                                "peak_profit_pct": peak_profit_pct,
                                "drop_from_peak_pct": drop_from_peak_pct,
                            },
                        )
                        record_realized_pnl(daily_state, symbol, (price - entry_price) * pos["position_amount"])
                        reset_position_state(pos, record_exit=True)
                        continue
                    if pending_order_id:
                        pos["pending_order_id"] = pending_order_id
                        pos["pending_order_side"] = "sell"
                    journal.log_event(
                        "exit_unfilled_or_failed",
                        symbol=symbol,
                        profile=profile_name,
                        regime=regime_label,
                        side="sell",
                        reason="spike_reversal",
                        status="pending_or_failed",
                        price=price,
                        amount=pos["position_amount"],
                        profit_pct=profit_pct,
                        order_id=pending_order_id,
                    )
                    if pending_order_id:
                        continue

                profit_target_price = entry_price * (1 + dynamic_profit_target)
                if price >= profit_target_price:
                    print(
                        f"[{base_currency}] 💰 PROFIT TARGET REACHED: "
                        f"{profit_pct * 100:.2f}% profit at {format_price(price)}"
                    )
                    exit_executed, pending_order_id = place_exit_order(
                        exchange,
                        symbol,
                        base_currency,
                        pos["position_amount"],
                        "Profit-taking",
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                        is_reconciled_position=pos.get("reconciled_from_balance", False),
                    )
                    if exit_executed:
                        journal.log_event(
                            "exit_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="profit_target",
                            status="executed",
                            price=price,
                            amount=pos["position_amount"],
                            cost_usd=price * pos["position_amount"],
                            profit_pct=profit_pct,
                            payload={
                                "estimated_pnl_usd": (price - entry_price) * pos["position_amount"],
                                "target_price": profit_target_price,
                            },
                        )
                        record_realized_pnl(daily_state, symbol, (price - entry_price) * pos["position_amount"])
                        reset_position_state(pos, record_exit=True)
                        continue
                    if pending_order_id:
                        pos["pending_order_id"] = pending_order_id
                        pos["pending_order_side"] = "sell"
                    journal.log_event(
                        "exit_unfilled_or_failed",
                        symbol=symbol,
                        profile=profile_name,
                        regime=regime_label,
                        side="sell",
                        reason="profit_target",
                        status="pending_or_failed",
                        price=price,
                        amount=pos["position_amount"],
                        profit_pct=profit_pct,
                        order_id=pending_order_id,
                    )
                    if pending_order_id:
                        continue

                if pos["trailing_profit_target"] > 0 and price >= pos["trailing_profit_target"]:
                    print(
                        f"[{base_currency}] 💰 TRAILING PROFIT TARGET REACHED: "
                        f"{profit_pct * 100:.2f}% profit at {format_price(price)}"
                    )
                    exit_executed, pending_order_id = place_exit_order(
                        exchange,
                        symbol,
                        base_currency,
                        pos["position_amount"],
                        "Trailing profit",
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                        is_reconciled_position=pos.get("reconciled_from_balance", False),
                    )
                    if exit_executed:
                        journal.log_event(
                            "exit_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="trailing_profit",
                            status="executed",
                            price=price,
                            amount=pos["position_amount"],
                            cost_usd=price * pos["position_amount"],
                            profit_pct=profit_pct,
                            payload={
                                "estimated_pnl_usd": (price - entry_price) * pos["position_amount"],
                                "trailing_profit_target": pos["trailing_profit_target"],
                            },
                        )
                        record_realized_pnl(daily_state, symbol, (price - entry_price) * pos["position_amount"])
                        reset_position_state(pos, record_exit=True)
                        continue
                    if pending_order_id:
                        pos["pending_order_id"] = pending_order_id
                        pos["pending_order_side"] = "sell"
                    journal.log_event(
                        "exit_unfilled_or_failed",
                        symbol=symbol,
                        profile=profile_name,
                        regime=regime_label,
                        side="sell",
                        reason="trailing_profit",
                        status="pending_or_failed",
                        price=price,
                        amount=pos["position_amount"],
                        profit_pct=profit_pct,
                        order_id=pending_order_id,
                    )
                    if pending_order_id:
                        continue

                potential_stop = None
                if indicators_ok and not pd.isna(atr) and atr > 0:
                    potential_stop = price - (atr * dynamic_atr_multiplier)
                if potential_stop is not None and potential_stop > pos["trailing_stop_price"]:
                    pos["trailing_stop_price"] = potential_stop

                if (
                    not pos["breakeven_set"]
                    and profit_pct >= profile["breakeven_trigger_pct"]
                ):
                    protected_price = entry_price * (1 + profile["breakeven_lock_pct"])
                    pos["trailing_stop_price"] = max(pos["trailing_stop_price"], protected_price)
                    pos["breakeven_set"] = True
                    print(
                        f"[{base_currency}] 🔒 Stop moved above breakeven at "
                        f"{format_price(pos['trailing_stop_price'])}"
                    )

                for trigger_pct, locked_pct in profile["profit_locks"]:
                    if profit_pct >= trigger_pct:
                        locked_price = entry_price * (1 + locked_pct)
                        if pos["trailing_stop_price"] < locked_price:
                            pos["trailing_stop_price"] = locked_price
                            print(
                                f"[{base_currency}] 🔒 Profit locked: {locked_pct * 100:.1f}% "
                                f"at {format_price(pos['trailing_stop_price'])}"
                            )

                if price <= pos["trailing_stop_price"]:
                    print(
                        f"[{base_currency}] 🚨 STOP LOSS TRIGGERED at {format_price(price)} "
                        f"(Entry: {format_price(entry_price)}, P/L: {profit_pct * 100:.2f}%)"
                    )
                    exit_executed, _stop_loss_pending_order_id = place_exit_order(
                        exchange,
                        symbol,
                        base_currency,
                        pos["position_amount"],
                        "Stop-loss",
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                        force_market=True,
                        is_reconciled_position=pos.get("reconciled_from_balance", False),
                    )
                    if exit_executed:
                        journal.log_event(
                            "exit_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="stop_loss",
                            status="executed",
                            price=price,
                            amount=pos["position_amount"],
                            cost_usd=price * pos["position_amount"],
                            profit_pct=profit_pct,
                            payload={
                                "estimated_pnl_usd": (price - entry_price) * pos["position_amount"],
                                "stop_price": pos["trailing_stop_price"],
                            },
                        )
                        record_realized_pnl(daily_state, symbol, (price - entry_price) * pos["position_amount"])
                        reset_position_state(pos, record_exit=True)
                    else:
                        journal.log_event(
                            "exit_unfilled_or_failed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="stop_loss",
                            status="failed",
                            price=price,
                            amount=pos["position_amount"],
                            profit_pct=profit_pct,
                        )

        except Exception as exc:
            journal.log_event(
                "runtime_error",
                symbol=symbol,
                profile=symbol_profiles.get(symbol),
                regime=last_regime_label,
                reason="symbol_loop_exception",
                status="error",
                payload={"message": str(exc)},
            )
            print(f"[{symbol}] Error: {exc}")
            continue

    if snapshot_interval_minutes > 0 and (time.time() - last_snapshot_time) >= snapshot_interval_minutes * 60:
        try:
            snapshot = fetch_portfolio_snapshot(exchange)
            journal.log_portfolio_snapshot(
                total_estimated_usd=snapshot["total_estimated_usd"],
                free_usd=snapshot["free_usd"],
                invested_usd=snapshot["invested_usd"],
                positions=snapshot["positions"],
            )
            last_snapshot_time = time.time()
        except Exception as exc:
            journal.log_event(
                "warning",
                reason="portfolio_snapshot_failed",
                status="warning",
                payload={"message": str(exc)},
            )

    time.sleep(check_interval)
