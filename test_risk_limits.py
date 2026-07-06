#!/usr/bin/env python3
"""Unit tests for risk_limits (position sizing, order fills, per-coin daily limits).

Run with:  python -m unittest test_risk_limits    (no extra dependencies required)
"""
import unittest
from datetime import datetime, timezone

from risk_limits import (
    compute_position_size,
    current_day_key,
    daily_utc_bounds,
    evaluate_entry_limits,
    extract_fill,
    new_daily_state,
    record_realized_pnl,
    record_trade,
    reset_daily_state,
    restore_daily_state_from_events,
    setup_is_stronger,
    symbol_loss_limit_hit,
    symbol_realized_pnl,
    symbol_trade_count,
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

    def test_daily_utc_bounds_cover_one_utc_day(self):
        start, end = daily_utc_bounds("2026-07-03")
        self.assertEqual(start, "2026-07-03T00:00:00+00:00")
        self.assertEqual(end, "2026-07-04T00:00:00+00:00")

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

    def test_blocks_when_loss_limit_enabled_without_equity_baseline(self):
        state = new_daily_state("2026-07-03", start_equity_usd=0)
        reasons = evaluate_entry_limits(state, "BTC/USD", 0, 3, 0, 6, 0.05)
        self.assertIn("daily_loss_equity_unavailable", reasons)

    def test_missing_equity_baseline_does_not_block_when_loss_limit_disabled(self):
        state = new_daily_state("2026-07-03", start_equity_usd=0)
        reasons = evaluate_entry_limits(state, "BTC/USD", 0, 3, 0, 6, 0)
        self.assertNotIn("daily_loss_equity_unavailable", reasons)

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


class RestoreDailyStateFromEventsTests(unittest.TestCase):
    def test_restores_trade_counts_pnl_halts_and_last_signal(self):
        events = [
            {
                "event_type": "entry_executed",
                "symbol": "BTC/USD",
                "status": "executed",
                "payload_json": '{"rsi": 61.5, "trend_strength": 0.02, "volume_ratio": 1.4}',
            },
            {
                "event_type": "entry_executed",
                "symbol": "ETH/USD",
                "status": "executed",
                "payload": {"rsi": 58.0, "trend_strength": 0.015, "volume_ratio": 1.1},
            },
            {
                "event_type": "exit_executed",
                "symbol": "BTC/USD",
                "status": "executed",
                "payload_json": '{"estimated_pnl_usd": -75.25}',
            },
            {
                "event_type": "daily_loss_limit_triggered",
                "symbol": "BTC/USD",
                "status": "halted",
                "payload_json": "{}",
            },
        ]

        state = restore_daily_state_from_events(
            "2026-07-03", events, start_equity_usd=1000
        )

        self.assertEqual(state["day"], "2026-07-03")
        self.assertAlmostEqual(state["start_equity_usd"], 1000)
        self.assertEqual(state["trades"], 2)
        self.assertEqual(symbol_trade_count(state, "BTC/USD"), 1)
        self.assertEqual(symbol_trade_count(state, "ETH/USD"), 1)
        self.assertAlmostEqual(symbol_realized_pnl(state, "BTC/USD"), -75.25)
        self.assertTrue(state["symbol_halted"]["BTC/USD"])
        self.assertAlmostEqual(
            state["symbol_last_entry_signal"]["BTC/USD"]["volume_ratio"], 1.4
        )

    def test_ignores_unexecuted_and_malformed_events(self):
        events = [
            {
                "event_type": "entry_executed",
                "symbol": "BTC/USD",
                "status": "pending_or_failed",
                "payload_json": '{"rsi": 90}',
            },
            {
                "event_type": "exit_executed",
                "symbol": "BTC/USD",
                "status": "executed",
                "payload_json": "{not-json",
            },
        ]

        state = restore_daily_state_from_events(
            "2026-07-03", events, start_equity_usd=1000
        )

        self.assertEqual(state["trades"], 0)
        self.assertEqual(state["symbol_trades"], {})
        self.assertEqual(state["symbol_realized_pnl_usd"], {})


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


if __name__ == "__main__":
    unittest.main()
