#!/usr/bin/env python3
"""
Order placement helpers shared by trading entrypoints.
"""
import time


def place_entry_order(
    exchange,
    symbol: str,
    base_currency: str,
    amount: float,
    cost: float,
    use_limit_orders: bool,
    limit_order_offset_pct: float,
    enable_trading: bool,
    order_check_delay: int = 5,
) -> bool:
    if use_limit_orders:
        limit_price = exchange.fetch_ticker(symbol)["last"] * (1 - limit_order_offset_pct)
        print(
            f"[{base_currency}] 🚀 ENTER LONG (LIMIT): Buying {amount:.6f} {base_currency} "
            f"at ${limit_price:.2f} (Cost: ${cost:.2f})"
        )
        if not enable_trading:
            print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
            return True

        try:
            order = exchange.create_limit_buy_order(symbol, amount, limit_price)
        except Exception as exc:
            print(f"[{base_currency}] ❌ Limit entry failed before order placement: {exc}")
            try:
                order = exchange.create_market_buy_order(symbol, cost)
                print(f"[{base_currency}] ✅ Fallback market order executed: {order.get('id', 'N/A')}")
                return True
            except Exception as fallback_exc:
                print(f"[{base_currency}] ❌ Market entry also failed: {fallback_exc}")
                return False

        order_id = order.get("id")
        print(f"[{base_currency}] ✅ Limit order placed: {order_id or 'N/A'}")
        if order_check_delay > 0:
            time.sleep(order_check_delay)

        try:
            order_status = exchange.fetch_order(order_id, symbol)
        except Exception as exc:
            print(
                f"[{base_currency}] ⚠️  Could not verify limit order status; "
                f"tracking it to avoid duplicate entries: {exc}"
            )
            return True

        status = order_status.get("status")
        if status == "closed":
            print(f"[{base_currency}] ✅ Limit order filled")
            return True

        if status in {"open", "pending"}:
            try:
                exchange.cancel_order(order_id, symbol)
                print(f"[{base_currency}] ⏳ Limit order unfilled; canceled before next cycle")
                return False
            except Exception as exc:
                print(
                    f"[{base_currency}] ⚠️  Limit order still open and cancel failed; "
                    f"tracking it to avoid duplicate entries: {exc}"
                )
                return True

        print(f"[{base_currency}] ⏳ Limit order finished with status={status}; waiting for the next cycle")
        return False

    print(f"[{base_currency}] 🚀 ENTER LONG: Buying {amount:.6f} {base_currency} (Cost: ${cost:.2f})")
    if not enable_trading:
        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
        return True

    try:
        order = exchange.create_market_buy_order(symbol, cost)
        print(f"[{base_currency}] ✅ Order executed: {order.get('id', 'N/A')}")
        return True
    except Exception as exc:
        print(f"[{base_currency}] ❌ Order failed: {exc}")
        return False
