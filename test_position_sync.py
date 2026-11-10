#!/usr/bin/env python3
"""Unit tests for position_sync (stale-order cleanup, safe exits, reconciliation, backoff).

Run with:  python -m unittest test_position_sync    (no network, no extra dependencies)
"""
import unittest

from position_sync import (
    EXIT_FAILED,
    EXIT_NOTHING_TO_SELL,
    EXIT_SOLD,
    ExitBackoff,
    balance_amounts,
    cancel_open_orders,
    coinbase_exchange_options,
    place_exit_order,
    reconcile_action,
)


class InsufficientFunds(Exception):
    pass


class FakeExchange:
    """Tiny Coinbase-like spot exchange: resting sell orders put the base coin on hold."""

    def __init__(self, base="ETH", total=1.0, price=2000.0, min_amount=0.0001, limit_fills=False,
                 external_hold=0.0):
        self.base = base
        self.total = total
        # Coins Coinbase holds for reasons the bot cannot cancel (staking, transfers, locks).
        self.external_hold = external_hold
        self.price = price
        self.limit_fills = limit_fills
        self.orders = {}
        self.next_id = 1
        self.market_sells = []
        self.cancelled = []
        self.markets = {f"{base}/USD": {"limits": {"amount": {"min": min_amount}}}}

    # --- helpers -------------------------------------------------------------
    def _held(self):
        orders = sum(o["amount"] for o in self.orders.values() if o["status"] == "open" and o["side"] == "sell")
        return orders + self.external_hold

    def add_resting_sell(self, amount, price):
        order_id = f"old-{self.next_id}"
        self.next_id += 1
        self.orders[order_id] = {"id": order_id, "side": "sell", "amount": amount, "price": price, "status": "open"}
        return order_id

    # --- ccxt surface ----------------------------------------------------------
    def fetch_balance(self):
        free = self.total - self._held()
        return {self.base: {"free": free, "used": self._held(), "total": self.total}}

    def fetch_open_orders(self, symbol):
        return [dict(o) for o in self.orders.values() if o["status"] == "open"]

    def cancel_order(self, order_id, symbol):
        self.orders[order_id]["status"] = "canceled"
        self.cancelled.append(order_id)

    def amount_to_precision(self, symbol, amount):
        return f"{amount:.8f}"

    def fetch_ticker(self, symbol):
        return {"last": self.price}

    def create_limit_sell_order(self, symbol, amount, price):
        if amount > self.total - self._held() + 1e-12:
            raise InsufficientFunds("INSUFFICIENT_FUND")
        order_id = f"new-{self.next_id}"
        self.next_id += 1
        status = "closed" if self.limit_fills else "open"
        self.orders[order_id] = {"id": order_id, "side": "sell", "amount": amount, "price": price, "status": status}
        if self.limit_fills:
            self.total -= amount
        return {"id": order_id}

    def fetch_order(self, order_id, symbol):
        return dict(self.orders[order_id])

    def create_market_sell_order(self, symbol, amount):
        if amount > self.total - self._held() + 1e-12:
            raise InsufficientFunds("INSUFFICIENT_FUND")
        self.total -= amount
        self.market_sells.append(amount)
        return {"id": f"mkt-{len(self.market_sells)}"}


def no_sleep(_seconds):
    return None


class StuckOrderRegressionTests(unittest.TestCase):
    """Reproduces the Nov 2026 incident: an old GTC limit sell holds all the ETH."""

    def test_old_resting_order_no_longer_blocks_the_exit(self):
        ex = FakeExchange(total=1.03215358, price=2089.80)
        ex.add_resting_sell(1.03215358, price=2800.0)  # stale order far above market
        self.assertEqual(ex.fetch_balance()["ETH"]["free"], 0.0)

        result = place_exit_order(
            ex, "ETH/USD", "ETH", 1.02999464, "Stop-loss",
            use_limit_orders=True, limit_order_offset_pct=0.001,
            enable_trading=True, force_market=True, sleep=no_sleep,
        )

        self.assertEqual(result, EXIT_SOLD)
        self.assertIn("old-1", ex.cancelled)
        self.assertEqual(len(ex.market_sells), 1)
        self.assertAlmostEqual(ex.market_sells[0], 1.02999464, places=8)

    def test_unfilled_limit_exit_is_cancelled_then_sold_at_market(self):
        ex = FakeExchange(total=0.5, limit_fills=False)
        result = place_exit_order(
            ex, "ETH/USD", "ETH", 0.5, "Profit-taking",
            use_limit_orders=True, limit_order_offset_pct=0.001,
            enable_trading=True, sleep=no_sleep,
        )
        self.assertEqual(result, EXIT_SOLD)
        # The bot's own limit order must not be left resting on the book.
        self.assertEqual([o for o in ex.orders.values() if o["status"] == "open"], [])
        self.assertEqual(ex.market_sells, [0.5])

    def test_filled_limit_exit_does_not_also_market_sell(self):
        ex = FakeExchange(total=0.5, limit_fills=True)
        result = place_exit_order(
            ex, "ETH/USD", "ETH", 0.5, "Profit-taking",
            use_limit_orders=True, limit_order_offset_pct=0.001,
            enable_trading=True, sleep=no_sleep,
        )
        self.assertEqual(result, EXIT_SOLD)
        self.assertEqual(ex.market_sells, [])

    def test_limit_exit_that_cannot_be_cancelled_is_a_failure(self):
        ex = FakeExchange(total=0.5, limit_fills=False)

        def refuse(order_id, symbol):
            raise RuntimeError("cancel rejected")

        ex.cancel_order = refuse
        result = place_exit_order(
            ex, "ETH/USD", "ETH", 0.5, "Profit-taking",
            use_limit_orders=True, limit_order_offset_pct=0.001,
            enable_trading=True, sleep=no_sleep,
        )
        # The order is still resting and holding the ETH: not sold, not closed.
        self.assertEqual(result, EXIT_FAILED)
        self.assertEqual(ex.market_sells, [])


class PlaceExitOrderTests(unittest.TestCase):
    def test_never_sells_more_than_free_balance(self):
        ex = FakeExchange(total=0.9)
        place_exit_order(ex, "ETH/USD", "ETH", 1.0, "Stop-loss", False, 0.0, True, sleep=no_sleep)
        self.assertEqual(ex.market_sells, [0.9])

    def test_zero_balance_closes_without_a_sale(self):
        ex = FakeExchange(total=0.0)
        result = place_exit_order(ex, "ETH/USD", "ETH", 1.0, "Stop-loss", False, 0.0, True, sleep=no_sleep)
        self.assertEqual(result, EXIT_NOTHING_TO_SELL)
        self.assertEqual(ex.market_sells, [])

    def test_dust_below_exchange_minimum_closes_without_a_sale(self):
        ex = FakeExchange(total=0.00001, min_amount=0.0001)
        result = place_exit_order(ex, "ETH/USD", "ETH", 0.5, "Stop-loss", False, 0.0, True, sleep=no_sleep)
        self.assertEqual(result, EXIT_NOTHING_TO_SELL)
        self.assertEqual(ex.market_sells, [])

    def test_simulated_mode_places_nothing(self):
        ex = FakeExchange(total=1.0)
        result = place_exit_order(ex, "ETH/USD", "ETH", 1.0, "Stop-loss", True, 0.0, False, sleep=no_sleep)
        self.assertEqual(result, EXIT_SOLD)
        self.assertEqual(ex.market_sells, [])
        self.assertEqual(ex.orders, {})

    def test_balance_fetch_failure_returns_false(self):
        ex = FakeExchange(total=1.0)

        def boom():
            raise RuntimeError("network down")

        ex.fetch_balance = boom
        result = place_exit_order(ex, "ETH/USD", "ETH", 1.0, "Stop-loss", False, 0.0, True, sleep=no_sleep)
        self.assertEqual(result, EXIT_FAILED)


class HoldsAndBalanceSourceTests(unittest.TestCase):
    """Nov 10 2026 follow-up: ETH on hold outside the bot's own orders."""

    def test_exchange_options_read_balances_from_v3(self):
        options = coinbase_exchange_options()
        self.assertEqual(options["fetchBalance"], "v3PrivateGetBrokerageAccounts")
        self.assertFalse(options["createMarketBuyOrderRequiresPrice"])
        options["fetchBalance"] = "changed"  # callers get a copy, not the shared dict
        self.assertEqual(coinbase_exchange_options()["fetchBalance"], "v3PrivateGetBrokerageAccounts")

    def test_coins_fully_on_hold_keep_the_position_and_fail(self):
        ex = FakeExchange(total=1.03215357, external_hold=1.03215357)
        result = place_exit_order(ex, "ETH/USD", "ETH", 1.03215357, "Stop-loss", False, 0.0, True,
                                  force_market=True, sleep=no_sleep)
        # Not closed without a sale (the coins are still there) and no doomed order sent.
        self.assertEqual(result, EXIT_FAILED)
        self.assertEqual(ex.market_sells, [])

    def test_partial_hold_sells_only_the_free_part(self):
        ex = FakeExchange(total=1.0, external_hold=0.4)
        result = place_exit_order(ex, "ETH/USD", "ETH", 1.0, "Stop-loss", False, 0.0, True, sleep=no_sleep)
        self.assertEqual(result, EXIT_SOLD)
        self.assertEqual(len(ex.market_sells), 1)
        self.assertAlmostEqual(ex.market_sells[0], 0.6, places=8)

    def test_hold_found_after_cancelling_limit_exit_keeps_position(self):
        ex = FakeExchange(total=0.5, limit_fills=False)

        def cancel_then_lock(order_id, symbol):
            FakeExchange.cancel_order(ex, order_id, symbol)
            ex.external_hold = 0.5  # e.g. the coins were moved into staking meanwhile

        ex.cancel_order = cancel_then_lock
        result = place_exit_order(ex, "ETH/USD", "ETH", 0.5, "Profit-taking",
                                  use_limit_orders=True, limit_order_offset_pct=0.001,
                                  enable_trading=True, sleep=no_sleep)
        self.assertEqual(result, EXIT_FAILED)
        self.assertEqual(ex.market_sells, [])

    def test_v2_style_balance_that_overstates_free_still_fails_safely(self):
        """If balances ever come from v2 again (free == total), the rejection is a failure, not a close."""
        ex = FakeExchange(total=1.0, external_hold=1.0)
        ex.fetch_balance = lambda: {"ETH": {"free": 1.0, "used": 0.0, "total": 1.0}}
        result = place_exit_order(ex, "ETH/USD", "ETH", 1.0, "Stop-loss", False, 0.0, True, sleep=no_sleep)
        self.assertEqual(result, EXIT_FAILED)
        self.assertEqual(ex.market_sells, [])


class CancelOpenOrdersTests(unittest.TestCase):
    def test_cancels_only_requested_side(self):
        ex = FakeExchange(total=1.0)
        ex.add_resting_sell(0.2, 2500.0)
        ex.orders["buy-1"] = {"id": "buy-1", "side": "buy", "amount": 0.1, "price": 1500.0, "status": "open"}
        self.assertEqual(cancel_open_orders(ex, "ETH/USD", side="sell"), 1)
        self.assertEqual(ex.orders["buy-1"]["status"], "open")

    def test_skips_orders_for_other_symbols(self):
        ex = FakeExchange(total=1.0)
        ex.orders["btc-1"] = {"id": "btc-1", "symbol": "BTC/USD", "side": "sell",
                              "amount": 0.01, "price": 90000.0, "status": "open"}
        self.assertEqual(cancel_open_orders(ex, "ETH/USD"), 0)
        self.assertEqual(ex.orders["btc-1"]["status"], "open")

    def test_listing_failure_is_non_fatal(self):
        ex = FakeExchange()

        def boom(_symbol):
            raise RuntimeError("nope")

        ex.fetch_open_orders = boom
        self.assertEqual(cancel_open_orders(ex, "ETH/USD"), 0)


class BalanceAmountsTests(unittest.TestCase):
    def test_missing_currency_is_zero(self):
        self.assertEqual(balance_amounts({}, "ETH"), (0.0, 0.0))

    def test_total_never_below_free(self):
        self.assertEqual(balance_amounts({"ETH": {"free": 1.0, "total": None}}, "ETH"), (1.0, 1.0))


class ReconcileActionTests(unittest.TestCase):
    def test_tracked_position_sold_elsewhere_is_cleared(self):
        self.assertEqual(reconcile_action(True, 1.0, 0.0, 2000.0, 5.0), "clear")

    def test_tracked_position_down_to_dust_is_cleared(self):
        self.assertEqual(reconcile_action(True, 1.0, 0.001, 2000.0, 5.0), "clear")

    def test_small_fee_difference_is_ignored(self):
        self.assertEqual(reconcile_action(True, 1.02999464, 1.03215358, 2089.8, 5.0), "none")

    def test_large_difference_is_resized(self):
        self.assertEqual(reconcile_action(True, 1.0, 0.5, 2000.0, 5.0), "resize")

    def test_untracked_holding_is_left_alone_by_default(self):
        self.assertEqual(reconcile_action(False, 0.0, 66.65, 10.25, 5.0), "none")

    def test_untracked_holding_adopted_when_enabled(self):
        self.assertEqual(reconcile_action(False, 0.0, 66.65, 10.25, 5.0, adopt_untracked=True), "adopt")


class ExitBackoffTests(unittest.TestCase):
    def test_first_failures_retry_next_cycle_then_back_off(self):
        backoff = ExitBackoff(free_retries=2, base_seconds=120, max_seconds=1800)
        self.assertEqual(backoff.record_failure("ETH/USD", now=0), 0.0)
        self.assertEqual(backoff.record_failure("ETH/USD", now=0), 0.0)
        self.assertEqual(backoff.record_failure("ETH/USD", now=0), 120.0)
        self.assertFalse(backoff.should_attempt("ETH/USD", now=60))
        self.assertTrue(backoff.should_attempt("ETH/USD", now=120))
        self.assertEqual(backoff.record_failure("ETH/USD", now=120), 240.0)

    def test_delay_is_capped(self):
        backoff = ExitBackoff(free_retries=0, base_seconds=120, max_seconds=1800)
        for _ in range(10):
            delay = backoff.record_failure("ETH/USD", now=0)
        self.assertEqual(delay, 1800)

    def test_success_resets(self):
        backoff = ExitBackoff(free_retries=0)
        backoff.record_failure("ETH/USD", now=0)
        backoff.record_success("ETH/USD")
        self.assertTrue(backoff.should_attempt("ETH/USD", now=0))
        self.assertEqual(backoff.failures("ETH/USD"), 0)


if __name__ == "__main__":
    unittest.main()
