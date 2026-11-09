#!/usr/bin/env python3
"""Keep the bot's in-memory positions in sync with the exchange, and place exits safely.

Background (Nov 2026 incident): a GTC limit sell that did not fill within the bot's
5-second wait was left open on Coinbase. That order kept the ETH "on hold", so every
later sell attempt failed with INSUFFICIENT_FUND, once a minute, while the bot still
believed it owned a sellable position. Nothing ever cancelled the stale order.

This module fixes that class of problem:

* ``cancel_open_orders`` clears any resting orders on a symbol before a new exit, so
  coins/USD locked by an old order become free again.
* ``place_exit_order`` sizes the sell from the FREE balance (never from a default),
  cancels its own limit order if it does not fill, then falls back to a market sell
  for whatever is still held.
* ``reconcile_action`` decides how to correct a tracked position from the real
  balance (clear it, resize it, adopt it, or leave it).
* ``ExitBackoff`` stops a failing exit from hammering the API every cycle.

Everything here takes the exchange as a parameter so it can be tested with a fake.
"""
import time
from typing import Dict, Optional, Tuple


def balance_amounts(balance: Dict, currency: str) -> Tuple[float, float]:
    """Return (free, total) for a currency from a ccxt balance dict; 0.0 when missing."""
    info = balance.get(currency) if isinstance(balance, dict) else None
    if not isinstance(info, dict):
        return 0.0, 0.0
    free = float(info.get("free") or 0.0)
    total = float(info.get("total") or 0.0)
    return free, max(total, free)


def cancel_open_orders(exchange, symbol: str, side: Optional[str] = None) -> int:
    """Cancel resting orders on `symbol` (optionally only one side). Returns the count cancelled."""
    try:
        open_orders = exchange.fetch_open_orders(symbol) or []
    except Exception as exc:
        print(f"[{symbol}] ⚠️  Could not list open orders: {exc}")
        return 0

    cancelled = 0
    for order in open_orders:
        if side and order.get("side") != side:
            continue
        order_id = order.get("id")
        if not order_id:
            continue
        try:
            exchange.cancel_order(order_id, symbol)
            cancelled += 1
            print(
                f"[{symbol}] 🧹 Cancelled stale {order.get('side', '')} order {order_id} "
                f"(amount={order.get('amount')}, price={order.get('price')})"
            )
        except Exception as exc:
            print(f"[{symbol}] ⚠️  Could not cancel order {order_id}: {exc}")
    return cancelled


def min_trade_amount(exchange, symbol: str) -> float:
    """Smallest base amount the exchange accepts for `symbol` (0 when unknown)."""
    try:
        market = exchange.markets.get(symbol, {}) if getattr(exchange, "markets", None) else {}
        return float(((market.get("limits") or {}).get("amount") or {}).get("min") or 0.0)
    except Exception:
        return 0.0


def _free_base(exchange, base_currency: str) -> Optional[float]:
    try:
        free, _ = balance_amounts(exchange.fetch_balance(), base_currency)
        return free
    except Exception as exc:
        print(f"[{base_currency}] ⚠️  Could not fetch balance: {exc}")
        return None


def _to_precision(exchange, symbol: str, amount: float) -> float:
    try:
        return float(exchange.amount_to_precision(symbol, amount))
    except Exception:
        return amount


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
    fill_wait_seconds: float = 5.0,
    sleep=time.sleep,
) -> bool:
    """Sell up to `amount` of `symbol`. Returns True when the position is closed.

    "Closed" also covers the case where only dust below the exchange minimum is left,
    so the bot does not retry an unsellable remainder forever.
    """
    if not enable_trading:
        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
        return True

    # 1. Free anything an old order is holding.
    cancel_open_orders(exchange, symbol)

    # 2. Size from the FREE balance. A missing/zero balance means there is nothing to sell;
    #    never fall back to the tracked amount (that is what produced INSUFFICIENT_FUND).
    free = _free_base(exchange, base_currency)
    if free is None:
        return False
    sell_amount = _to_precision(exchange, symbol, min(amount, free))
    dust = min_trade_amount(exchange, symbol)

    if sell_amount <= 0 or (dust and sell_amount < dust):
        print(
            f"[{base_currency}] ⚠️  Nothing sellable for {reason} "
            f"(free={free}, tracked={amount}). Treating position as closed."
        )
        return True

    # 3. Optional limit exit; cancel it if it does not fill so it cannot lock the coins.
    if use_limit_orders and not force_market:
        order_id = None
        try:
            last_price = exchange.fetch_ticker(symbol)["last"]
            limit_price = last_price * (1 + limit_order_offset_pct)
            order = exchange.create_limit_sell_order(symbol, sell_amount, limit_price)
            order_id = order.get("id")
            print(f"[{base_currency}] ✅ {reason} limit order placed: {order_id} at ${limit_price:.6f}")
            sleep(fill_wait_seconds)
            status = exchange.fetch_order(order_id, symbol) if order_id else {}
            if status.get("status") == "closed":
                print(f"[{base_currency}] ✅ Limit exit filled")
                return True
        except Exception as exc:
            print(f"[{base_currency}] ❌ Limit exit failed: {exc}")
        if order_id:
            try:
                exchange.cancel_order(order_id, symbol)
                print(f"[{base_currency}] 🧹 Cancelled unfilled limit exit {order_id}; falling back to market")
            except Exception as exc:
                # It may have filled between the check and the cancel; the balance re-check handles it.
                print(f"[{base_currency}] ⚠️  Could not cancel limit exit {order_id}: {exc}")

        free = _free_base(exchange, base_currency)
        if free is None:
            return False
        sell_amount = _to_precision(exchange, symbol, min(amount, free))
        if sell_amount <= 0 or (dust and sell_amount < dust):
            print(f"[{base_currency}] ✅ Limit exit filled before cancel; position closed")
            return True

    # 4. Market sell whatever is still free.
    try:
        order = exchange.create_market_sell_order(symbol, sell_amount)
        print(f"[{base_currency}] ✅ {reason} market sell executed: {order.get('id', 'N/A')}")
        return True
    except Exception as exc:
        print(f"[{base_currency}] ❌ {reason} sell failed: {exc}")
        return False


def reconcile_action(
    in_position: bool,
    tracked_amount: float,
    held_total: float,
    price: float,
    min_value_usd: float,
    adopt_untracked: bool = False,
    tolerance: float = 0.02,
) -> str:
    """Decide how to correct one symbol's tracked position from the exchange balance.

    Returns one of:
      "clear"  - tracked as open, but the account holds less than `min_value_usd` of it
      "resize" - tracked as open, but the held amount differs by more than `tolerance`
      "adopt"  - not tracked, the account holds a meaningful amount, and adoption is on
      "none"   - nothing to change
    """
    held_value = held_total * price if price > 0 else 0.0
    meaningful = held_value >= max(min_value_usd, 0.0) and held_total > 0

    if in_position:
        if not meaningful:
            return "clear"
        if tracked_amount <= 0:
            return "resize"
        if abs(held_total - tracked_amount) / tracked_amount > tolerance:
            return "resize"
        return "none"

    if adopt_untracked and meaningful:
        return "adopt"
    return "none"


class ExitBackoff:
    """Throttle repeated exit attempts for a symbol after consecutive failures.

    The first `free_retries` failures retry on the next cycle. After that, the wait
    doubles from `base_seconds` up to `max_seconds`. A success resets the symbol.
    """

    def __init__(self, free_retries: int = 2, base_seconds: float = 120.0, max_seconds: float = 1800.0):
        self.free_retries = free_retries
        self.base_seconds = base_seconds
        self.max_seconds = max_seconds
        self._failures: Dict[str, int] = {}
        self._next_attempt: Dict[str, float] = {}

    def failures(self, symbol: str) -> int:
        return self._failures.get(symbol, 0)

    def should_attempt(self, symbol: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return now >= self._next_attempt.get(symbol, 0.0)

    def seconds_until_retry(self, symbol: str, now: Optional[float] = None) -> float:
        now = time.time() if now is None else now
        return max(self._next_attempt.get(symbol, 0.0) - now, 0.0)

    def record_failure(self, symbol: str, now: Optional[float] = None) -> float:
        """Record a failed exit; returns the delay before the next attempt (0 = next cycle)."""
        now = time.time() if now is None else now
        count = self._failures.get(symbol, 0) + 1
        self._failures[symbol] = count
        if count <= self.free_retries:
            delay = 0.0
        else:
            delay = min(self.base_seconds * (2 ** (count - self.free_retries - 1)), self.max_seconds)
        self._next_attempt[symbol] = now + delay
        return delay

    def record_success(self, symbol: str) -> None:
        self._failures.pop(symbol, None)
        self._next_attempt.pop(symbol, None)
