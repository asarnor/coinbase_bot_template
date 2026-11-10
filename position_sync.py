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

Follow-up (Nov 10 2026): ccxt's Coinbase class reads balances from the v2 /accounts
endpoint by default, and its v2 parser sets ``free = total``. Coins Coinbase holds
(open orders, pending transfers, staking or other locks) therefore still looked free,
so the sizing above did not help and the ETH stop-loss kept failing with
INSUFFICIENT_FUND. ``COINBASE_EXCHANGE_OPTIONS`` switches ccxt to the Advanced Trade
v3 accounts endpoint, which reports ``available_balance`` (free) and ``hold`` (used)
separately. ``place_exit_order`` also no longer closes a position whose coins are
merely on hold; it reports the hold and retries later.
"""
import time
from typing import Dict, Optional, Tuple

# Outcomes of place_exit_order. Only EXIT_SOLD means a sell actually executed (or was
# simulated); EXIT_NOTHING_TO_SELL means the position is gone but nothing was sold, so
# callers must not record realized P&L for it.
EXIT_SOLD = "sold"
EXIT_NOTHING_TO_SELL = "nothing_to_sell"
EXIT_FAILED = "failed"

# ccxt options for the Coinbase exchange. ``fetchBalance`` must use the v3 Advanced Trade
# accounts endpoint: the ccxt default (v2) reports every coin as free, holds included.
COINBASE_EXCHANGE_OPTIONS = {
    "createMarketBuyOrderRequiresPrice": False,
    "fetchBalance": "v3PrivateGetBrokerageAccounts",
}


def coinbase_exchange_options() -> Dict:
    """A fresh copy of the ccxt options this bot uses for Coinbase (e.g. main_multi_symbol.py, portfolio_utils.py)."""
    return dict(COINBASE_EXCHANGE_OPTIONS)


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
        if order.get("symbol") and order.get("symbol") != symbol:
            continue
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


def _base_balance(exchange, base_currency: str) -> Optional[Tuple[float, float]]:
    """(free, total) of the base coin, or None when the balance cannot be fetched."""
    try:
        return balance_amounts(exchange.fetch_balance(), base_currency)
    except Exception as exc:
        print(f"[{base_currency}] ⚠️  Could not fetch balance: {exc}")
        return None


def _nothing_free_result(base_currency: str, reason: str, free: float, total: float,
                         amount: float, dust: float, context: str) -> str:
    """Decide what an exit with no sellable balance means.

    Coins that are still in the account but on hold (an order or lock the bot could not
    cancel, a pending transfer, staking) are not gone: keep the position and retry later.
    Only a real zero or dust balance closes the position without a sale.
    """
    on_hold = max(total - free, 0.0)
    if on_hold > 0 and (not dust or on_hold >= dust):
        print(
            f"[{base_currency}] ⛔ {reason} blocked: {on_hold:.8f} {base_currency} is on hold at "
            f"Coinbase (free={free:.8f}, total={total:.8f}, tracked={amount:.8f}). Release the hold "
            f"(open order, transfer or staking) in Coinbase; the bot will retry."
        )
        return EXIT_FAILED
    print(
        f"[{base_currency}] ⚠️  {context} for {reason} "
        f"(free={free}, tracked={amount}). Closing the position without a sale."
    )
    return EXIT_NOTHING_TO_SELL


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
) -> str:
    """Sell up to `amount` of `symbol` and return EXIT_SOLD, EXIT_NOTHING_TO_SELL or EXIT_FAILED.

    EXIT_NOTHING_TO_SELL covers a zero balance or dust below the exchange minimum: the
    position should be closed (so the bot stops retrying), but no sale happened.
    """
    if not enable_trading:
        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
        return EXIT_SOLD

    # 1. Free anything an old order is holding.
    cancel_open_orders(exchange, symbol)

    # 2. Size from the FREE balance. A missing/zero balance means there is nothing to sell;
    #    never fall back to the tracked amount (that is what produced INSUFFICIENT_FUND).
    bal = _base_balance(exchange, base_currency)
    if bal is None:
        return EXIT_FAILED
    free, total = bal
    sell_amount = _to_precision(exchange, symbol, min(amount, free))
    dust = min_trade_amount(exchange, symbol)

    if sell_amount <= 0 or (dust and sell_amount < dust):
        return _nothing_free_result(base_currency, reason, free, total, amount, dust, "Nothing sellable")

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
                return EXIT_SOLD
        except Exception as exc:
            print(f"[{base_currency}] ❌ Limit exit failed: {exc}")
        limit_filled = 0.0
        if order_id:
            try:
                exchange.cancel_order(order_id, symbol)
                print(f"[{base_currency}] 🧹 Cancelled unfilled limit exit {order_id}; falling back to market")
            except Exception as exc:
                # It may have filled between the check and the cancel; the status check decides.
                print(f"[{base_currency}] ⚠️  Could not cancel limit exit {order_id}: {exc}")
            try:
                final = exchange.fetch_order(order_id, symbol) or {}
            except Exception as exc:
                print(f"[{base_currency}] ⚠️  Could not confirm limit exit {order_id}: {exc}")
                return EXIT_FAILED
            if final.get("status") == "closed":
                print(f"[{base_currency}] ✅ Limit exit filled before cancel; position closed")
                return EXIT_SOLD
            if final.get("status") == "open":
                # Cancel failed and the order is still resting, holding the coins. Retry later.
                return EXIT_FAILED
            limit_filled = float(final.get("filled") or 0.0)

        bal = _base_balance(exchange, base_currency)
        if bal is None:
            return EXIT_FAILED
        free, total = bal
        sell_amount = _to_precision(exchange, symbol, min(amount, free))
        if sell_amount <= 0 or (dust and sell_amount < dust):
            if limit_filled > 0:
                print(f"[{base_currency}] ✅ Limit exit partially filled; remainder is dust. Position closed")
                return EXIT_SOLD
            return _nothing_free_result(
                base_currency, reason, free, total, amount, dust,
                "Nothing left to sell after cancelling the limit exit",
            )

    # 4. Market sell whatever is still free.
    try:
        order = exchange.create_market_sell_order(symbol, sell_amount)
        print(f"[{base_currency}] ✅ {reason} market sell executed: {order.get('id', 'N/A')}")
        return EXIT_SOLD
    except Exception as exc:
        print(f"[{base_currency}] ❌ {reason} sell failed: {exc}")
        if "INSUFFICIENT_FUND" in str(exc):
            # Log what Coinbase reports right now, so a mismatch is visible in the logs.
            after = _base_balance(exchange, base_currency)
            if after is not None:
                print(
                    f"[{base_currency}]    Balance after rejection: free={after[0]:.8f}, "
                    f"total={after[1]:.8f}, attempted={sell_amount:.8f}"
                )
        return EXIT_FAILED


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
