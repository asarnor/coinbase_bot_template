import unittest

import numpy as np
import pandas as pd

from algo_validation.backtest import StrategyParams, run_backtest
from algo_validation.metrics import summarize_performance


def _df_from_closes(closes, freq="1h"):
    closes = np.asarray(closes, dtype=float)
    ts = pd.date_range("2024-01-01", periods=len(closes), freq=freq, tz="UTC")
    ms = (ts.view("int64") // 1_000_000).astype("int64")
    # Give candles a small range so ATR is defined.
    high = closes * 1.01
    low = closes * 0.99
    return pd.DataFrame(
        {
            "timestamp": ms,
            "open": closes,
            "high": high,
            "low": low,
            "close": closes,
            "volume": np.full_like(closes, 1000.0),
        }
    )


class BacktestSmokeTests(unittest.TestCase):
    def test_backtest_runs_and_generates_trades(self):
        closes = np.linspace(100, 140, 300)  # steady uptrend
        df = _df_from_closes(closes)
        p = StrategyParams(
            rsi_entry_threshold=10.0,  # make entry easy
            min_trend_strength=0.0,
            min_volume_ratio=0.0,
            fee_rate=0.0,
            leverage=1.0,
            cooldown_bars=1,
            execution_model="close",
        )
        bt = run_backtest(df, p)
        self.assertGreater(len(bt.equity_curve), 50)
        self.assertGreaterEqual(len(bt.trades), 1)

    def test_trading_drawdown_not_worse_than_hold_in_simple_crash(self):
        up = np.linspace(100, 130, 200)
        crash = np.linspace(130, 80, 30)
        recover = np.linspace(80, 90, 70)
        closes = np.concatenate([up, crash, recover])
        df = _df_from_closes(closes)
        p = StrategyParams(
            rsi_entry_threshold=10.0,
            min_trend_strength=0.0,
            min_volume_ratio=0.0,
            atr_multiplier=1.5,
            fee_rate=0.0,
            leverage=1.0,
            cooldown_bars=1,
            execution_model="close",
        )
        bt = run_backtest(df, p)
        strat = summarize_performance(bt.equity_curve, bt.trades, timeframe="1h", underlying_close=bt.equity_curve["close"])
        hold_curve = pd.DataFrame(
            {"equity": bt.equity_curve["close"] / bt.equity_curve["close"].iloc[0], "in_position": 1.0},
            index=bt.equity_curve.index,
        )
        hold = summarize_performance(hold_curve, [], timeframe="1h")
        # On this synthetic series, the strategy should not be catastrophically worse than holding.
        self.assertGreaterEqual(strat.max_drawdown, hold.max_drawdown - 0.05)


if __name__ == "__main__":
    unittest.main()

