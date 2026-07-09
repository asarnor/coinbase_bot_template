#!/usr/bin/env python3
"""Pure, testable helpers for position sizing, order fills, and per-coin daily risk limits.

These functions intentionally have no side effects and never touch the exchange or
network, so they can be imported and unit-tested in isolation. The trading bot
(`main_multi_symbol.py`) wires them together with live data.

Daily limits are tracked PER COIN: each symbol gets its own trade counter, realized
P&L tally, and loss-limit halt. A losing or maxed-out coin is paused for the rest of
the UTC day while the other coins keep trading normally.
"""
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple


def current_day_key(now: Optional[datetime] = None) -> str:
    """Return the current UTC day as an YYYY-MM-DD string (used to reset counters)."""
    moment = now or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%d")


def daily_utc_bounds(day: str) -> Tuple[str, str]:
    """Return inclusive/exclusive UTC ISO bounds for a YYYY-MM-DD day key."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start.isoformat(), end.isoformat()


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


def _event_payload(event: Dict) -> Dict:
    payload = event.get("payload")
    if isinstance(payload, dict):
        return payload

    raw_payload = event.get("payload_json")
    if isinstance(raw_payload, dict):
        return raw_payload
    if isinstance(raw_payload, str) and raw_payload:
        try:
            parsed = json.loads(raw_payload)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _as_float(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def restore_daily_state_from_events(
    day: str, events: Iterable[Dict], start_equity_usd: float = 0.0
) -> Dict:
    """Rebuild daily risk counters from persisted journal events for one UTC day."""
    state = new_daily_state(day, start_equity_usd)

    for event in events:
        symbol = event.get("symbol")
        event_type = event.get("event_type")
        status = event.get("status")
        payload = _event_payload(event)

        if event_type == "entry_executed" and symbol and status == "executed":
            signal = {
                key: payload[key]
                for key in ("rsi", "trend_strength", "volume_ratio")
                if key in payload
            }
            record_trade(state, symbol, signal=signal or None)
        elif event_type == "exit_executed" and symbol and status == "executed":
            pnl = _as_float(payload.get("estimated_pnl_usd"))
            if pnl is not None:
                record_realized_pnl(state, symbol, pnl)
        elif event_type == "daily_loss_limit_triggered" and symbol:
            state["symbol_halted"][symbol] = True

    return state


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


def resolve_effective_leverage(requested_leverage: float, setup_succeeded: bool) -> float:
    """Use requested leverage only after the exchange confirms leverage is active."""
    if not setup_succeeded:
        return 1.0
    return max(requested_leverage, 1.0)


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

    if daily_loss_limit_pct > 0 and state.get("start_equity_usd", 0) <= 0:
        reasons.append("daily_loss_equity_unavailable")
    elif state["symbol_halted"].get(symbol) or symbol_loss_limit_hit(
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
