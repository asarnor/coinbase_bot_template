#!/usr/bin/env python3
"""Unit tests for risk_limits (position sizing, order fills, per-coin daily limits).

Run with:  python -m unittest test_risk_limits    (no extra dependencies required)
"""
import json
import unittest
from datetime import datetime, timezone

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
    setup_is_stronger,
    symbol_loss_limit_hit,
    symbol_realized_pnl,
    symbol_trade_count,
    validate_symbol_configuration,
)


STRONG = {"rsi": 60.0, "trend_strength": 0.02, "volume_ratio": 1.5}
WEAKER = {"rsi": 55.0, "trend_strength": 0.01, "volume_ratio": 1.0}
STRONGER = {"rsi": 66.0, "trend_strength": 0.03, "volume_ratio": 2.0}


class ComputePositionSizeTests(unittest.TestCase):
    def test_amount_matches_cost_at_leverage_one(self):
        amount, cost = compute_position_size(free_usd=1000, price=100, risk_slice=0.2, leverage=1)
        self.assertAlmostEqual(cost, 200.0)
        self.assertAlmostEqual(amount, 2.0)
        # The core invariant that fixes the oversell bug: amount * price == cost.
        self.assertAlmostEqual(amount * price_for(cost, amount), cost)

    def test_cost_never_exceeds_free_balance(self):
        # leverage 5 would ask for 5x the balance; spot must clamp to ~free balance.
        amount, cost = compute_position_size(free_usd=1000, price=50, risk_slice=0.5, leverage=5)
        self.assertLessEqual(cost, 1000 * 0.995 + 1e-9)
        self.assertAlmostEqual(amount, cost / 50)

    def test_leverage_scales_within_cap(self):
        amount, cost = compute_position_size(free_usd=1000, price=10, risk_slice=0.05, leverage=3)
        # 1000 * 0.05 * 3 = 150, well under the cap.
        self.assertAlmostEqual(cost, 150.0)
        self.assertAlmostEqual(amount, 15.0)

    def test_zero_inputs_return_zero(self):
        self.assertEqual(compute_position_size(0, 100, 0.2, 1), (0.0, 0.0))
        self.assertEqual(compute_position_size(1000, 0, 0.2, 1), (0.0, 0.0))

    def test_leverage_below_one_treated_as_one(self):
        amount, cost = compute_position_size(free_usd=1000, price=100, risk_slice=0.1, leverage=0)
        self.assertAlmostEqual(cost, 100.0)
        self.assertAlmostEqual(amount, 1.0)


class ExtractFillTests(unittest.TestCase):
    def test_reads_filled_and_average(self):
        order = {"filled": 1.2345, "average": 101.5}
        filled, avg = extract_fill(order, fallback_amount=1.0, fallback_price=100.0)
        self.assertAlmostEqual(filled, 1.2345)
        self.assertAlmostEqual(avg, 101.5)

    def test_falls_back_when_fields_missing(self):
        filled, avg = extract_fill({}, fallback_amount=2.0, fallback_price=50.0)
        self.assertAlmostEqual(filled, 2.0)
        self.assertAlmostEqual(avg, 50.0)

    def test_uses_amount_and_price_when_no_filled_average(self):
        order = {"amount": 3.0, "price": 20.0}
        filled, avg = extract_fill(order, fallback_amount=1.0, fallback_price=10.0)
        self.assertAlmostEqual(filled, 3.0)
        self.assertAlmostEqual(avg, 20.0)

    def test_zero_or_bad_values_fall_back(self):
        filled, avg = extract_fill({"filled": 0, "average": "nan-ish"}, 1.5, 99.0)
        self.assertAlmostEqual(filled, 1.5)
        self.assertAlmostEqual(avg, 99.0)

    def test_none_order_falls_back(self):
        filled, avg = extract_fill(None, 4.0, 8.0)
        self.assertAlmostEqual(filled, 4.0)
        self.assertAlmostEqual(avg, 8.0)


class DailyStateTests(unittest.TestCase):
    def test_current_day_key_uses_utc(self):
        moment = datetime(2026, 7, 3, 23, 59, tzinfo=timezone.utc)
        self.assertEqual(current_day_key(moment), "2026-07-03")

    def test_record_trade_tracks_per_coin(self):
        state = new_daily_state("2026-07-03", start_equity_usd=1000)
        record_trade(state, "BTC/USD")
        record_trade(state, "BTC/USD")
        record_trade(state, "ETH/USD")
        self.assertEqual(symbol_trade_count(state, "BTC/USD"), 2)
        self.assertEqual(symbol_trade_count(state, "ETH/USD"), 1)
        self.assertEqual(state["trades"], 3)

    def test_record_realized_pnl_tracks_per_coin_and_global(self):
        state = new_daily_state("2026-07-03", start_equity_usd=1000)
        record_realized_pnl(state, "BTC/USD", -30)
        record_realized_pnl(state, "ETH/USD", 10)
        self.assertAlmostEqual(symbol_realized_pnl(state, "BTC/USD"), -30)
        self.assertAlmostEqual(symbol_realized_pnl(state, "ETH/USD"), 10)
        self.assertAlmostEqual(state["realized_pnl_usd"], -20)

    def test_reset_clears_counters_and_sets_new_day(self):
        state = new_daily_state("2026-07-03", start_equity_usd=1000)
        record_trade(state, "BTC/USD")
        record_realized_pnl(state, "BTC/USD", -50)
        reset_daily_state(state, "2026-07-04", start_equity_usd=1200)
        self.assertEqual(state["day"], "2026-07-04")
        self.assertEqual(state["trades"], 0)
        self.assertEqual(state["symbol_trades"], {})
        self.assertEqual(state["symbol_realized_pnl_usd"], {})
        self.assertEqual(state["symbol_halted"], {})
        self.assertAlmostEqual(state["start_equity_usd"], 1200)


class SymbolLossLimitTests(unittest.TestCase):
    def test_hit_when_symbol_loss_exceeds_budget(self):
        state = new_daily_state("2026-07-03", start_equity_usd=1000)
        record_realized_pnl(state, "BTC/USD", -60)  # -6% of 1000 > 5% limit
        self.assertTrue(symbol_loss_limit_hit(state, "BTC/USD", 0.05))

    def test_not_hit_below_budget(self):
        state = new_daily_state("2026-07-03", start_equity_usd=1000)
        record_realized_pnl(state, "BTC/USD", -40)  # -4% < 5% limit
        self.assertFalse(symbol_loss_limit_hit(state, "BTC/USD", 0.05))

    def test_is_isolated_per_coin(self):
        state = new_daily_state("2026-07-03", start_equity_usd=1000)
        record_realized_pnl(state, "BTC/USD", -80)
        # ETH untouched -> not limited even though BTC blew its budget.
        self.assertTrue(symbol_loss_limit_hit(state, "BTC/USD", 0.05))
        self.assertFalse(symbol_loss_limit_hit(state, "ETH/USD", 0.05))

    def test_disabled_when_pct_zero_or_no_equity(self):
        state = new_daily_state("2026-07-03", start_equity_usd=1000)
        record_realized_pnl(state, "BTC/USD", -500)
        self.assertFalse(symbol_loss_limit_hit(state, "BTC/USD", 0))
        state2 = new_daily_state("2026-07-03", start_equity_usd=0)
        record_realized_pnl(state2, "BTC/USD", -500)
        self.assertFalse(symbol_loss_limit_hit(state2, "BTC/USD", 0.05))


class EvaluateEntryLimitsTests(unittest.TestCase):
    def _state(self):
        return new_daily_state("2026-07-03", start_equity_usd=1000)

    def test_allows_trade_when_under_all_limits(self):
        state = self._state()
        reasons = evaluate_entry_limits(state, "BTC/USD", 0, 3, 0, 6, 0.05)
        self.assertEqual(reasons, [])

    def test_blocks_after_six_trades_per_coin(self):
        state = self._state()
        for _ in range(6):
            record_trade(state, "BTC/USD")
        reasons = evaluate_entry_limits(state, "BTC/USD", 1, 3, 0, 6, 0.05)
        self.assertIn("max_symbol_trades_per_day", reasons)
        # A different coin with no trades is still allowed.
        other = evaluate_entry_limits(state, "ETH/USD", 1, 3, 0, 6, 0.05)
        self.assertNotIn("max_symbol_trades_per_day", other)

    def test_allows_up_to_six_trades_per_coin(self):
        state = self._state()
        for _ in range(5):
            record_trade(state, "BTC/USD")
        # 6th entry (5 already taken) should still be permitted.
        reasons = evaluate_entry_limits(state, "BTC/USD", 1, 3, 0, 6, 0.05)
        self.assertNotIn("max_symbol_trades_per_day", reasons)

    def test_blocks_on_max_open_positions(self):
        state = self._state()
        reasons = evaluate_entry_limits(state, "BTC/USD", 3, 3, 0, 6, 0.05)
        self.assertIn("max_open_positions", reasons)

    def test_blocks_on_per_coin_loss_limit(self):
        state = self._state()
        record_realized_pnl(state, "BTC/USD", -60)
        reasons = evaluate_entry_limits(state, "BTC/USD", 0, 3, 0, 6, 0.05)
        self.assertIn("daily_loss_limit", reasons)
        # ETH is unaffected.
        self.assertEqual(
            evaluate_entry_limits(state, "ETH/USD", 0, 3, 0, 6, 0.05), []
        )

    def test_respects_latched_symbol_halt(self):
        state = self._state()
        state["symbol_halted"]["BTC/USD"] = True
        reasons = evaluate_entry_limits(state, "BTC/USD", 0, 3, 0, 6, 0.05)
        self.assertIn("daily_loss_limit", reasons)

    def test_optional_global_daily_cap(self):
        state = self._state()
        for symbol in ("BTC/USD", "ETH/USD", "SOL/USD", "LINK/USD"):
            record_trade(state, symbol)
        # Global cap of 4 reached -> blocked regardless of per-coin room.
        reasons = evaluate_entry_limits(state, "FET/USD", 0, 3, 4, 6, 0.05)
        self.assertIn("max_trades_per_day", reasons)


class StrongerSetupTests(unittest.TestCase):
    def _state_with_entry(self, signal):
        state = new_daily_state("2026-07-03", start_equity_usd=1000)
        record_trade(state, "BTC/USD", signal=signal)
        return state

    def test_first_trade_always_allowed(self):
        state = new_daily_state("2026-07-03", start_equity_usd=1000)
        self.assertTrue(setup_is_stronger(state, "BTC/USD", 40, 0.001, 0.5))

    def test_stronger_signal_allowed(self):
        state = self._state_with_entry(STRONG)
        self.assertTrue(
            setup_is_stronger(
                state, "BTC/USD",
                STRONGER["rsi"], STRONGER["trend_strength"], STRONGER["volume_ratio"],
            )
        )

    def test_weaker_signal_blocked(self):
        state = self._state_with_entry(STRONG)
        self.assertFalse(
            setup_is_stronger(
                state, "BTC/USD",
                WEAKER["rsi"], WEAKER["trend_strength"], WEAKER["volume_ratio"],
            )
        )

    def test_equal_signal_allowed_at_zero_improvement(self):
        state = self._state_with_entry(STRONG)
        self.assertTrue(
            setup_is_stronger(
                state, "BTC/USD",
                STRONG["rsi"], STRONG["trend_strength"], STRONG["volume_ratio"],
            )
        )

    def test_min_improvement_requires_strict_gain(self):
        state = self._state_with_entry(STRONG)
        # Same signal fails once we demand a 5% average improvement.
        self.assertFalse(
            setup_is_stronger(
                state, "BTC/USD",
                STRONG["rsi"], STRONG["trend_strength"], STRONG["volume_ratio"],
                min_improvement=0.05,
            )
        )

    def test_gate_isolated_per_coin(self):
        state = self._state_with_entry(STRONG)
        # ETH has no prior entry, so it is unaffected by BTC's baseline.
        self.assertTrue(
            setup_is_stronger(
                state, "ETH/USD",
                WEAKER["rsi"], WEAKER["trend_strength"], WEAKER["volume_ratio"],
            )
        )

    def test_evaluate_entry_limits_blocks_weaker_reentry(self):
        state = self._state_with_entry(STRONG)
        reasons = evaluate_entry_limits(
            state, "BTC/USD", 1, 3, 0, 6, 0.05,
            require_stronger_setup=True, current_signal=WEAKER,
        )
        self.assertIn("setup_not_stronger", reasons)

    def test_evaluate_entry_limits_allows_stronger_reentry(self):
        state = self._state_with_entry(STRONG)
        reasons = evaluate_entry_limits(
            state, "BTC/USD", 1, 3, 0, 6, 0.05,
            require_stronger_setup=True, current_signal=STRONGER,
        )
        self.assertNotIn("setup_not_stronger", reasons)

    def test_gate_disabled_by_default(self):
        state = self._state_with_entry(STRONG)
        reasons = evaluate_entry_limits(state, "BTC/USD", 1, 3, 0, 6, 0.05)
        self.assertNotIn("setup_not_stronger", reasons)


def price_for(cost, amount):
    """Helper: recover the implied price so we can assert amount * price == cost."""
    return cost / amount if amount else 0.0


def entry_event(symbol, rsi=60.0, trend_strength=0.02, volume_ratio=1.5, created_at="2026-07-03T10:00:00+00:00"):
    return {
        "event_type": "entry_executed",
        "symbol": symbol,
        "created_at": created_at,
        "payload_json": json.dumps(
            {"rsi": rsi, "trend_strength": trend_strength, "volume_ratio": volume_ratio}
        ),
    }


def exit_event(symbol, pnl_usd, created_at="2026-07-03T11:00:00+00:00"):
    return {
        "event_type": "exit_executed",
        "symbol": symbol,
        "created_at": created_at,
        "payload_json": json.dumps({"estimated_pnl_usd": pnl_usd}),
    }


def halt_event(symbol, created_at="2026-07-03T12:00:00+00:00"):
    return {"event_type": "daily_loss_limit_triggered", "symbol": symbol, "created_at": created_at}


class RebuildDailyStateFromEventsTests(unittest.TestCase):
    def test_empty_events_matches_new_daily_state(self):
        state = rebuild_daily_state_from_events("2026-07-03", 1000.0, [])
        self.assertEqual(state["trades"], 0)
        self.assertEqual(state["symbol_trades"], {})
        self.assertAlmostEqual(state["start_equity_usd"], 1000.0)

    def test_replays_entries_and_exits_per_coin(self):
        events = [
            entry_event("BTC/USD"),
            entry_event("BTC/USD"),
            entry_event("ETH/USD"),
            exit_event("BTC/USD", -20.0),
            exit_event("ETH/USD", 15.0),
        ]
        state = rebuild_daily_state_from_events("2026-07-03", 1000.0, events)
        self.assertEqual(state["trades"], 3)
        self.assertEqual(symbol_trade_count(state, "BTC/USD"), 2)
        self.assertEqual(symbol_trade_count(state, "ETH/USD"), 1)
        self.assertAlmostEqual(symbol_realized_pnl(state, "BTC/USD"), -20.0)
        self.assertAlmostEqual(symbol_realized_pnl(state, "ETH/USD"), 15.0)
        self.assertAlmostEqual(state["realized_pnl_usd"], -5.0)

    def test_replays_explicit_halt_events(self):
        events = [entry_event("BTC/USD"), halt_event("BTC/USD")]
        state = rebuild_daily_state_from_events("2026-07-03", 1000.0, events)
        self.assertTrue(state["symbol_halted"].get("BTC/USD"))

    def test_restores_last_entry_signal_for_stronger_reentry_gate(self):
        events = [entry_event("BTC/USD", rsi=60.0, trend_strength=0.02, volume_ratio=1.5)]
        state = rebuild_daily_state_from_events("2026-07-03", 1000.0, events)
        # A subsequent weaker signal should now be blocked, exactly as if the entry
        # had happened in this same process rather than before a restart.
        self.assertFalse(
            setup_is_stronger(state, "BTC/USD", rsi=50.0, trend_strength=0.01, volume_ratio=1.0)
        )

    def test_safety_net_halts_symbol_even_without_explicit_event(self):
        # Loss crossed the 5% budget but the daily_loss_limit_triggered event is
        # missing (e.g. a transient journal write failure) -- the belt-and-suspenders
        # recompute should still catch it when a limit pct is supplied.
        events = [exit_event("BTC/USD", -60.0)]
        state = rebuild_daily_state_from_events(
            "2026-07-03", 1000.0, events, daily_loss_limit_pct=0.05
        )
        self.assertTrue(state["symbol_halted"].get("BTC/USD"))

    def test_no_safety_net_when_limit_pct_not_supplied(self):
        events = [exit_event("BTC/USD", -60.0)]
        state = rebuild_daily_state_from_events("2026-07-03", 1000.0, events)
        self.assertFalse(state["symbol_halted"].get("BTC/USD"))

    def test_ignores_events_without_a_symbol(self):
        events = [{"event_type": "bot_started", "symbol": None, "created_at": "2026-07-03T09:00:00+00:00"}]
        state = rebuild_daily_state_from_events("2026-07-03", 1000.0, events)
        self.assertEqual(state["trades"], 0)

    def test_malformed_payload_json_does_not_raise(self):
        events = [{"event_type": "exit_executed", "symbol": "BTC/USD", "payload_json": "{not-json"}]
        state = rebuild_daily_state_from_events("2026-07-03", 1000.0, events)
        self.assertAlmostEqual(symbol_realized_pnl(state, "BTC/USD"), 0.0)


def empty_position():
    return {
        "in_position": False,
        "pending_order_id": None,
        "pending_order_side": None,
        "pending_entry_signal": None,
        "pending_order_amount": 0.0,
        "pending_order_price": 0.0,
    }


class RestorePendingOrdersFromEventsTests(unittest.TestCase):
    def test_restores_unresolved_entry_limit(self):
        positions = {"BTC/USD": empty_position(), "ETH/USD": empty_position()}
        events = [
            {
                "event_type": "entry_unfilled_or_failed",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": "ord-btc-1",
                "amount": 0.01,
                "price": 100000.0,
                "payload_json": json.dumps(
                    {"signal": {"rsi": 60.0, "trend_strength": 0.02, "volume_ratio": 1.5}}
                ),
            }
        ]
        restored = restore_pending_orders_from_events(positions, events)
        self.assertEqual(set(restored), {"BTC/USD"})
        self.assertEqual(positions["BTC/USD"]["pending_order_id"], "ord-btc-1")
        self.assertEqual(positions["BTC/USD"]["pending_order_side"], "buy")
        self.assertEqual(positions["BTC/USD"]["pending_order_amount"], 0.01)
        self.assertEqual(positions["BTC/USD"]["pending_entry_signal"]["rsi"], 60.0)
        self.assertIsNone(positions["ETH/USD"]["pending_order_id"])

    def test_clears_pending_after_cancel(self):
        positions = {"BTC/USD": empty_position()}
        events = [
            {
                "event_type": "entry_unfilled_or_failed",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": "ord-1",
                "amount": 0.01,
                "price": 100.0,
            },
            {
                "event_type": "pending_order_cancelled",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": "ord-1",
            },
        ]
        restored = restore_pending_orders_from_events(positions, events)
        self.assertEqual(restored, {})
        self.assertIsNone(positions["BTC/USD"]["pending_order_id"])

    def test_clears_pending_after_late_fill(self):
        positions = {"ETH/USD": empty_position()}
        events = [
            {
                "event_type": "entry_unfilled_or_failed",
                "symbol": "ETH/USD",
                "side": "buy",
                "order_id": "ord-eth",
                "amount": 1.0,
                "price": 3000.0,
            },
            {
                "event_type": "pending_buy_order_filled",
                "symbol": "ETH/USD",
                "side": "buy",
                "order_id": "ord-eth",
            },
            {
                "event_type": "entry_executed",
                "symbol": "ETH/USD",
                "side": "buy",
                "order_id": "ord-eth",
            },
        ]
        restored = restore_pending_orders_from_events(positions, events)
        self.assertEqual(restored, {})
        self.assertIsNone(positions["ETH/USD"]["pending_order_id"])

    def test_does_not_clear_when_unrelated_order_id_fills(self):
        # A fill for a different order must not drop tracking of the still-resting
        # limit -- that would recreate the overlapping-order bug after restart.
        positions = {"BTC/USD": empty_position()}
        events = [
            {
                "event_type": "entry_unfilled_or_failed",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": "resting-limit",
                "amount": 0.01,
                "price": 100.0,
            },
            {
                "event_type": "entry_executed",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": "some-other-order",
            },
        ]
        restored = restore_pending_orders_from_events(positions, events)
        self.assertEqual(restored["BTC/USD"]["order_id"], "resting-limit")
        self.assertEqual(positions["BTC/USD"]["pending_order_id"], "resting-limit")

    def test_restores_unresolved_exit_limit(self):
        positions = {"BTC/USD": empty_position()}
        events = [
            {
                "event_type": "exit_unfilled_or_failed",
                "symbol": "BTC/USD",
                "side": "sell",
                "order_id": "sell-1",
                "amount": 0.5,
                "price": 110000.0,
            }
        ]
        restored = restore_pending_orders_from_events(positions, events)
        self.assertEqual(restored["BTC/USD"]["side"], "sell")
        self.assertEqual(positions["BTC/USD"]["pending_order_id"], "sell-1")
        self.assertEqual(positions["BTC/USD"]["pending_order_side"], "sell")

    def test_ignores_unfilled_events_without_order_id(self):
        positions = {"BTC/USD": empty_position()}
        events = [
            {
                "event_type": "entry_unfilled_or_failed",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": None,
                "amount": 0.01,
                "price": 100.0,
            }
        ]
        restored = restore_pending_orders_from_events(positions, events)
        self.assertEqual(restored, {})
        self.assertIsNone(positions["BTC/USD"]["pending_order_id"])

    def test_keeps_latest_unresolved_pending_per_symbol(self):
        positions = {"BTC/USD": empty_position()}
        events = [
            {
                "event_type": "entry_unfilled_or_failed",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": "old-order",
                "amount": 0.01,
                "price": 90.0,
            },
            {
                "event_type": "pending_order_cancelled",
                "symbol": "BTC/USD",
                "order_id": "old-order",
            },
            {
                "event_type": "entry_unfilled_or_failed",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": "new-order",
                "amount": 0.02,
                "price": 95.0,
            },
        ]
        restored = restore_pending_orders_from_events(positions, events)
        self.assertEqual(restored["BTC/USD"]["order_id"], "new-order")
        self.assertEqual(positions["BTC/USD"]["pending_order_amount"], 0.02)

    def test_market_entry_without_order_id_clears_matching_buy_pending(self):
        positions = {"BTC/USD": empty_position()}
        events = [
            {
                "event_type": "entry_unfilled_or_failed",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": "limit-1",
                "amount": 0.01,
                "price": 100.0,
            },
            {
                "event_type": "entry_executed",
                "symbol": "BTC/USD",
                "side": "buy",
                "order_id": None,
            },
        ]
        restored = restore_pending_orders_from_events(positions, events)
        self.assertEqual(restored, {})
        self.assertIsNone(positions["BTC/USD"]["pending_order_id"])


class ValidateSymbolConfigurationTests(unittest.TestCase):
    def test_no_warnings_for_clean_configuration(self):
        warnings = validate_symbol_configuration(
            ["BTC/USD", "ETH/USD", "LINK/USD"],
            {"BTC/USD", "ETH/USD"},
            {"LINK/USD"},
            set(),
        )
        self.assertEqual(warnings, [])

    def test_warns_on_bucket_symbol_missing_from_trading_symbols(self):
        warnings = validate_symbol_configuration(
            ["BTC/USD"], {"BTC/USD", "XRP/USD"}, set(), set()
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("XRP/USD", warnings[0])
        self.assertIn("TRADING_CORE_SYMBOLS", warnings[0])

    def test_warns_on_symbol_in_multiple_buckets(self):
        warnings = validate_symbol_configuration(
            ["BTC/USD"], {"BTC/USD"}, {"BTC/USD"}, set()
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("BTC/USD", warnings[0])
        self.assertIn("core", warnings[0])

    def test_can_report_multiple_distinct_warnings(self):
        warnings = validate_symbol_configuration(
            ["BTC/USD", "ETH/USD"],
            {"BTC/USD", "ETH/USD"},
            {"ETH/USD", "SOL/USD"},
            set(),
        )
        self.assertEqual(len(warnings), 2)


if __name__ == "__main__":
    unittest.main()
