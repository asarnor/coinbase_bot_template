#!/usr/bin/env python3
"""Pure, testable helpers for position sizing, order fills, per-coin daily risk
limits, restart-safe state recovery (daily risk counters and resting limit
orders), and startup config validation.

These functions intentionally have no side effects and never touch the exchange or
network, so they can be imported and unit-tested in isolation. The trading bot
(`main_multi_symbol.py`) wires them together with live data.

Daily limits are tracked PER COIN: each symbol gets its own trade counter, realized
P&L tally, and loss-limit halt. A losing or maxed-out coin is paused for the rest of
the UTC day while the other coins keep trading normally.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


def current_day_key(now: Optional[datetime] = None) -> str:
    """Return the current UTC day as an YYYY-MM-DD string (used to reset counters)."""
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%d")


def new_daily_state(day: str, start_equity_usd: float = 0.0) -> Dict:
    """Create a fresh per-day risk-tracking structure."""
    return {
        "day": day,
        "trades": 0,
        "symbol_trades": {},
        "realized_pnl_usd": 0.0,
        "symbol_realized_pnl_usd": {},
        "start_equity_usd": start_equity_usd,
        "symbol_halted": {},
        # Signal snapshot ({"rsi", "trend_strength", "volume_ratio"}) of each coin's
        # most recent entry today, used to require the next trade to be stronger.
        "symbol_last_entry_signal": {},
    }


def reset_daily_state(state: Dict, day: str, start_equity_usd: float = 0.0) -> Dict:
    """Reset an existing state dict in place for a new day (keeps the same object)."""
    state.clear()
    state.update(new_daily_state(day, start_equity_usd))
    return state


def record_trade(state: Dict, symbol: str, signal: Optional[Dict] = None) -> None:
    """Increment the global and per-coin trade counters for a newly opened position.

    When `signal` (a dict with rsi/trend_strength/volume_ratio) is provided, it is
    stored as the baseline the next entry on this coin must beat.
    """
    state["trades"] += 1
    state["symbol_trades"][symbol] = state["symbol_trades"].get(symbol, 0) + 1
    if signal is not None:
        state["symbol_last_entry_signal"][symbol] = dict(signal)


def record_realized_pnl(state: Dict, symbol: str, pnl_usd: float) -> None:
    """Add a closed-trade P&L to the global and per-coin realized tallies."""
    state["realized_pnl_usd"] += pnl_usd
    state["symbol_realized_pnl_usd"][symbol] = (
        state["symbol_realized_pnl_usd"].get(symbol, 0.0) + pnl_usd
    )


def symbol_trade_count(state: Dict, symbol: str) -> int:
    return state["symbol_trades"].get(symbol, 0)


def symbol_realized_pnl(state: Dict, symbol: str) -> float:
    return state["symbol_realized_pnl_usd"].get(symbol, 0.0)


def symbol_loss_limit_hit(state: Dict, symbol: str, limit_pct: float) -> bool:
    """True when a single coin's realized loss for the day breaches its own budget.

    The threshold is `limit_pct` of the start-of-day total equity, applied
    independently to each coin, so one coin hitting its limit never blocks the rest.
    """
    if limit_pct <= 0 or state.get("start_equity_usd", 0) <= 0:
        return False
    threshold = -(limit_pct * state["start_equity_usd"])
    return symbol_realized_pnl(state, symbol) <= threshold


def compute_position_size(
    free_usd: float, price: float, risk_slice: float, leverage: float
) -> Tuple[float, float]:
    """Return (amount, cost) where amount == cost / price so tracked size matches fills.

    On spot there is no borrowing, so the USD spent (`cost`) is capped at the free
    balance regardless of leverage. `leverage` only scales how much USD is deployed.
    """
    if free_usd <= 0 or price <= 0:
        return 0.0, 0.0
    cost = free_usd * risk_slice * max(leverage, 1)
    spendable_cap = free_usd * 0.995
    if cost > spendable_cap:
        cost = spendable_cap
    amount = cost / price
    return amount, cost


def extract_fill(
    order: Optional[Dict], fallback_amount: float, fallback_price: float
) -> Tuple[float, float]:
    """Read the actually filled base amount and average price from an order response.

    Falls back to the requested values when the exchange omits the fields so the bot
    never tracks a position size larger than what it truly holds.
    """
    filled = None
    average = None
    if isinstance(order, dict):
        filled = order.get("filled") or order.get("amount")
        average = order.get("average") or order.get("price")

    try:
        filled = float(filled)
    except (TypeError, ValueError):
        filled = fallback_amount
    if not filled or filled <= 0:
        filled = fallback_amount

    try:
        average = float(average)
    except (TypeError, ValueError):
        average = fallback_price
    if not average or average <= 0:
        average = fallback_price

    return filled, average


def setup_is_stronger(
    state: Dict,
    symbol: str,
    rsi: float,
    trend_strength: float,
    volume_ratio: float,
    min_improvement: float = 0.0,
) -> bool:
    """Return True if the current signal is at least as strong as the coin's last entry.

    Strength is the average of the per-metric ratios (current / previous) across RSI,
    trend strength, and volume ratio, so all three contribute regardless of scale. The
    first trade of the day on a coin has no baseline and is always allowed. Requires the
    average ratio to be >= 1 + `min_improvement`.
    """
    last = state["symbol_last_entry_signal"].get(symbol)
    if not last:
        return True

    ratios: List[float] = []
    for current, previous in (
        (rsi, last.get("rsi")),
        (trend_strength, last.get("trend_strength")),
        (volume_ratio, last.get("volume_ratio")),
    ):
        if previous and previous > 0 and current is not None:
            ratios.append(current / previous)

    if not ratios:
        return True

    average_ratio = sum(ratios) / len(ratios)
    return average_ratio >= 1.0 + min_improvement


def _decode_event_payload(event: Dict) -> Dict[str, Any]:
    """Best-effort decode of a journaled event's payload back into a dict.

    `TradingJournal` stores payloads as a JSON string (`payload_json`); some callers
    may also pass an already-decoded `payload` dict directly (e.g. in tests).
    """
    payload = event.get("payload")
    if isinstance(payload, dict):
        return payload
    raw = event.get("payload_json")
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
        return decoded if isinstance(decoded, dict) else {}
    except (TypeError, ValueError):
        return {}


def restore_pending_orders_from_events(
    positions: Dict[str, Dict],
    events: List[Dict],
) -> Dict[str, Dict]:
    """Replay journal events to recover resting limit-order IDs after a restart.

    Pending limit orders are tracked in process memory (`pending_order_id` on each
    position). A redeploy / crash clears that state while the order can still rest
    on the exchange, so the next cycle may place a second overlapping order for the
    same symbol. The journal already records `order_id` on
    `entry_unfilled_or_failed` / `exit_unfilled_or_failed` and on the resolve events
    (`pending_order_cancelled`, `pending_*_order_filled`, and matching
    `entry_executed` / `exit_executed`). Replaying those chronologically restores
    whichever order is still unresolved per symbol so `sync_pending_order` can
    cancel or apply the fill instead of abandoning it.

    Returns a dict of symbol -> restored pending summary (for startup logging).
    Mutates `positions` in place.
    """
    # Working copy while replaying; only applied to `positions` at the end so a
    # mid-replay clear does not leave a half-applied id on a live position dict.
    pending_by_symbol: Dict[str, Optional[Dict]] = {symbol: None for symbol in positions}

    open_event_types = {"entry_unfilled_or_failed", "exit_unfilled_or_failed"}
    clear_event_types = {
        "pending_order_cancelled",
        "pending_buy_order_filled",
        "pending_sell_order_filled",
        "entry_executed",
        "exit_executed",
    }

    for event in events:
        symbol = event.get("symbol")
        if not symbol or symbol not in pending_by_symbol:
            continue

        event_type = event.get("event_type")
        order_id = event.get("order_id") or None
        current = pending_by_symbol[symbol]

        if event_type in open_event_types and order_id:
            side = event.get("side")
            if not side:
                side = "buy" if event_type.startswith("entry_") else "sell"
            try:
                amount = float(event.get("amount") or 0.0)
            except (TypeError, ValueError):
                amount = 0.0
            try:
                price = float(event.get("price") or 0.0)
            except (TypeError, ValueError):
                price = 0.0

            payload = _decode_event_payload(event)
            signal = None
            if side == "buy":
                # Prefer an explicit nested signal dict; fall back to flat payload
                # keys written by older journal rows.
                nested = payload.get("signal")
                if isinstance(nested, dict):
                    signal = {
                        "rsi": nested.get("rsi"),
                        "trend_strength": nested.get("trend_strength"),
                        "volume_ratio": nested.get("volume_ratio"),
                    }
                elif any(k in payload for k in ("rsi", "trend_strength", "volume_ratio")):
                    signal = {
                        "rsi": payload.get("rsi"),
                        "trend_strength": payload.get("trend_strength"),
                        "volume_ratio": payload.get("volume_ratio"),
                    }

            pending_by_symbol[symbol] = {
                "pending_order_id": str(order_id),
                "pending_order_side": side,
                "pending_order_amount": amount,
                "pending_order_price": price,
                "pending_entry_signal": signal,
            }
            continue

        if event_type not in clear_event_types or current is None:
            continue

        tracked_id = current.get("pending_order_id")
        tracked_side = current.get("pending_order_side")

        if order_id and str(order_id) != str(tracked_id):
            # A fill/cancel for a *different* order must not drop tracking of the
            # still-resting limit -- that is exactly the overlapping-order bug.
            continue

        if not order_id and event_type in ("entry_executed", "exit_executed"):
            # Market (or otherwise untagged) fill for this symbol: only clear when
            # the side matches, so a buy fill does not erase a resting sell limit.
            if event_type == "entry_executed" and tracked_side != "buy":
                continue
            if event_type == "exit_executed" and tracked_side != "sell":
                continue

        pending_by_symbol[symbol] = None

    restored: Dict[str, Dict] = {}
    for symbol, pending in pending_by_symbol.items():
        if not pending:
            continue
        pos = positions[symbol]
        pos["pending_order_id"] = pending["pending_order_id"]
        pos["pending_order_side"] = pending["pending_order_side"]
        pos["pending_order_amount"] = pending["pending_order_amount"]
        pos["pending_order_price"] = pending["pending_order_price"]
        pos["pending_entry_signal"] = pending["pending_entry_signal"]
        restored[symbol] = {
            "order_id": pending["pending_order_id"],
            "side": pending["pending_order_side"],
            "amount": pending["pending_order_amount"],
            "price": pending["pending_order_price"],
        }
    return restored


def rebuild_daily_state_from_events(
    day: str,
    start_equity_usd: float,
    events: List[Dict],
    daily_loss_limit_pct: float = 0.0,
) -> Dict:
    """Reconstruct a day's risk-tracking state by replaying journaled events.

    Without this, `daily_state` lives only in process memory: a restart (a Railway
    redeploy, a host recycle, a transient crash) silently resets every trade count,
    realized P&L tally, and per-coin loss halt back to zero mid-day, letting a coin
    that already blew its daily loss budget trade again immediately. `events` should
    be every `bot_events` row for `day` in ascending `created_at` order, as returned
    by `TradingJournal.get_events_between`.

    `daily_loss_limit_pct` is optional belt-and-suspenders: beyond replaying explicit
    `daily_loss_limit_triggered` events, it also re-applies the halt to any coin whose
    replayed realized loss already breaches the budget, in case that one event was
    missed (e.g. a transient journal write failure right as the halt was recorded).
    """
    state = new_daily_state(day, start_equity_usd)

    for event in events:
        symbol = event.get("symbol")
        if not symbol:
            continue
        event_type = event.get("event_type")

        if event_type == "entry_executed":
            payload = _decode_event_payload(event)
            signal = {
                "rsi": payload.get("rsi"),
                "trend_strength": payload.get("trend_strength"),
                "volume_ratio": payload.get("volume_ratio"),
            }
            record_trade(state, symbol, signal=signal)
        elif event_type == "exit_executed":
            payload = _decode_event_payload(event)
            pnl = payload.get("estimated_pnl_usd")
            if pnl is not None:
                try:
                    record_realized_pnl(state, symbol, float(pnl))
                except (TypeError, ValueError):
                    pass
        elif event_type == "daily_loss_limit_triggered":
            state["symbol_halted"][symbol] = True

    if daily_loss_limit_pct > 0:
        for symbol in state["symbol_realized_pnl_usd"]:
            if symbol_loss_limit_hit(state, symbol, daily_loss_limit_pct):
                state["symbol_halted"][symbol] = True

    return state


def validate_symbol_configuration(
    symbols: List[str],
    core_symbols: "set",
    tactical_symbols: "set",
    speculative_symbols: "set",
) -> List[str]:
    """Return human-readable warnings for symbol/profile misconfiguration.

    Two mistakes this catches: a symbol listed in a profile bucket
    (`TRADING_CORE_SYMBOLS` etc.) but missing from `TRADING_SYMBOLS`, so it silently
    never trades; and a symbol listed in more than one bucket, so it silently trades
    under whichever bucket wins the core > tactical > speculative priority order.
    """
    warnings: List[str] = []
    symbol_set = set(symbols)
    buckets = (
        ("core", core_symbols),
        ("tactical", tactical_symbols),
        ("speculative", speculative_symbols),
    )

    for label, bucket in buckets:
        for extra_symbol in sorted(bucket - symbol_set):
            warnings.append(
                f"{extra_symbol} is listed in TRADING_{label.upper()}_SYMBOLS but not "
                "in TRADING_SYMBOLS, so it will never be traded."
            )

    for symbol in symbols:
        containing = [label for label, bucket in buckets if symbol in bucket]
        if len(containing) > 1:
            warnings.append(
                f"{symbol} is listed in multiple profile buckets ({', '.join(containing)}); "
                f"it will be treated as '{containing[0]}' (core > tactical > speculative)."
            )

    return warnings


def evaluate_entry_limits(
    state: Dict,
    symbol: str,
    open_positions_count: int,
    max_open_positions: int,
    max_trades_per_day: int,
    max_trades_per_symbol_per_day: int,
    daily_loss_limit_pct: float,
    *,
    require_stronger_setup: bool = False,
    current_signal: Optional[Dict] = None,
    min_setup_improvement: float = 0.0,
) -> List[str]:
    """Return the list of blocking reasons (empty means the trade is allowed).

    All numeric limits are opt-out: pass 0 to disable. When `require_stronger_setup`
    is set and a `current_signal` is supplied, re-entries on a coin must be at least as
    strong as that coin's previous entry today.
    """
    reasons: List[str] = []

    if state["symbol_halted"].get(symbol) or symbol_loss_limit_hit(
        state, symbol, daily_loss_limit_pct
    ):
        reasons.append("daily_loss_limit")
    if max_open_positions > 0 and open_positions_count >= max_open_positions:
        reasons.append("max_open_positions")
    if max_trades_per_day > 0 and state["trades"] >= max_trades_per_day:
        reasons.append("max_trades_per_day")
    if (
        max_trades_per_symbol_per_day > 0
        and symbol_trade_count(state, symbol) >= max_trades_per_symbol_per_day
    ):
        reasons.append("max_symbol_trades_per_day")
    if require_stronger_setup and current_signal is not None:
        if not setup_is_stronger(
            state,
            symbol,
            current_signal.get("rsi"),
            current_signal.get("trend_strength"),
            current_signal.get("volume_ratio"),
            min_setup_improvement,
        ):
            reasons.append("setup_not_stronger")

    return reasons
