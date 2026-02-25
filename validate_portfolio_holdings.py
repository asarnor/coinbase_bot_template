#!/usr/bin/env python3
"""
Validate the trading algorithm against historical candles and review portfolio holdings.

- Focuses on maximizing profits *subject to* limiting large drawdowns.
- For non-core coins (excluding ETH/BTC/LINK/SHIB), produces KEEP vs SELL-CANDIDATE suggestions
  based on historical return + crash-risk metrics.

This script is DRY-RUN by default. Use --execute to place sells.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Dict, List, Optional, Tuple

import pandas as pd

from algo_validation.backtest import StrategyParams, run_backtest
from algo_validation.coinbase_utils import (
    best_usd_pair,
    create_coinbase_exchange,
    fetch_ohlcv_history,
    get_portfolio_holdings,
)
from algo_validation.metrics import summarize_performance


CORE_DO_NOT_SELL = {"ETH", "BTC", "LINK", "SHIB", "USD", "USDC"}


def _env_float(key: str, default: float) -> float:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _format_pct(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    return f"{x*100:>7.2f}%"

def _format_ratio(x: Optional[float]) -> str:
    if x is None:
        return "N/A"
    return f"{x:>7.2f}x"


def _timeframe_to_minutes(tf: str) -> Optional[int]:
    tf = tf.strip().lower()
    mapping = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "2h": 120,
        "4h": 240,
        "6h": 360,
        "12h": 720,
        "1d": 1440,
    }
    return mapping.get(tf)


def _hold_equity_curve(close: pd.Series) -> pd.DataFrame:
    eq = close.astype(float) / float(close.iloc[0])
    return pd.DataFrame({"equity": eq, "in_position": 1.0}, index=close.index)


def score_keep_sell(
    *,
    usd_value: float,
    hold_total_return: float,
    hold_max_dd: float,
    trade_total_return: float,
    trade_max_dd: float,
    downside_capture: Optional[float],
) -> Tuple[str, int, List[str]]:
    """
    Heuristic scoring (not financial advice). Produces a label + score + reasons.
    """
    score = 0
    reasons: List[str] = []

    # Focus on *holding* quality for "worth keeping", but reward if strategy materially improves crash-risk.
    if hold_total_return > 0:
        score += 2
        reasons.append("Positive hold return")
    elif hold_total_return < -0.20:
        score -= 2
        reasons.append("Negative hold return")

    if hold_max_dd > -0.40:
        score += 2
        reasons.append("Hold drawdown < 40%")
    elif hold_max_dd < -0.60:
        score -= 2
        reasons.append("Hold drawdown > 60%")

    # Does the trading algorithm reduce crash loss vs holding?
    if trade_total_return > hold_total_return + 0.05:
        score += 1
        reasons.append("Trading improves return vs hold")

    if trade_max_dd > hold_max_dd:
        score += 1
        reasons.append("Trading reduces drawdown vs hold")
    elif trade_max_dd < hold_max_dd - 0.10:
        score -= 1
        reasons.append("Trading drawdown worse than hold")

    if downside_capture is not None:
        # < 1.0 means the strategy loses less than the underlying on down bars (good).
        if downside_capture < 0.75:
            score += 1
            reasons.append("Good downside capture")
        elif downside_capture > 1.10:
            score -= 1
            reasons.append("Poor downside capture")

    # De-emphasize tiny dust positions (avoid over-optimizing time on them).
    if 0 < usd_value < 10:
        score -= 1
        reasons.append("Small position")

    if score <= -2:
        return "SELL_CANDIDATE", score, reasons
    if score >= 2:
        if hold_total_return < 0 and trade_total_return < 0:
            reasons.append("Both hold and trading returns negative")
            return "WATCH", score, reasons
        return "KEEP", score, reasons
    return "WATCH", score, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate algorithm & review portfolio holdings")
    parser.add_argument("--timeframe", default=os.getenv("TRADING_TIMEFRAME", "1h"))
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--symbols", default="", help="Comma-separated symbols like SOL/USD,ADA/USD (overrides portfolio scan)")
    parser.add_argument("--min-usd", type=float, default=5.0, help="Ignore holdings below this USD value in report")
    parser.add_argument("--crash-threshold", type=float, default=-0.03, help="Underlying bar return treated as 'crash' (e.g. -0.03)")
    parser.add_argument("--execution-model", choices=["close", "intrabar"], default="close")
    parser.add_argument("--fee-rate", type=float, default=_env_float("TRADING_FEE_RATE", 0.006))
    parser.add_argument("--leverage", type=float, default=_env_float("TRADING_LEVERAGE", 1.0))
    parser.add_argument("--execute", action="store_true", help="Execute sells for SELL_CANDIDATE coins")
    parser.add_argument("--max-sells", type=int, default=3, help="Safety cap on number of sells when using --execute")
    parser.add_argument("--report-json", default="", help="Write full results to JSON file")
    args = parser.parse_args()

    tf_minutes = _timeframe_to_minutes(args.timeframe)
    cooldown_minutes = max(0, _env_int("TRADING_COOLDOWN_MINUTES", 5))
    cooldown_bars = 1
    if tf_minutes:
        cooldown_bars = max(1, int((cooldown_minutes + tf_minutes - 1) / tf_minutes))

    # Strategy params are wired to the current multi-symbol bot env vars.
    p = StrategyParams(
        atr_multiplier=_env_float("TRADING_ATR_MULTIPLIER", 1.5),
        profit_target_pct=_env_float("TRADING_PROFIT_TARGET_PCT", 0.035),
        rsi_entry_threshold=_env_float("TRADING_RSI_ENTRY", 55.0),
        min_trend_strength=_env_float("TRADING_MIN_TREND_STRENGTH", 0.01),
        spike_reversal_pct=_env_float("TRADING_SPIKE_REVERSAL_PCT", 0.02),
        min_spike_profit_pct=_env_float("TRADING_MIN_SPIKE_PROFIT", 0.02),
        cooldown_bars=cooldown_bars,
        fee_rate=float(args.fee_rate),
        leverage=float(args.leverage),
        execution_model=str(args.execution_model),
    )

    # Public exchange for candles; authenticated exchange only if we need portfolio + execution.
    ex_public = create_coinbase_exchange(sandbox=False, require_auth=False)
    ex_public.load_markets()

    symbols: List[str] = []
    holdings: Dict[str, Dict] = {}

    if args.symbols.strip():
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        for s in symbols:
            base = s.split("/")[0]
            holdings[base] = {"currency": base, "total": 0.0, "free": 0.0}
    else:
        ex_auth = create_coinbase_exchange(sandbox=False, require_auth=True)
        ex_auth.load_markets()
        raw_holdings = get_portfolio_holdings(ex_auth)
        for h in raw_holdings:
            ccy = h["currency"]
            if ccy in CORE_DO_NOT_SELL:
                continue
            pair = best_usd_pair(ex_auth, ccy)
            if not pair:
                continue
            symbols.append(pair)
            holdings[ccy] = h

    results: List[Dict] = []

    for symbol in symbols:
        base = symbol.split("/")[0]
        try:
            ticker = ex_public.fetch_ticker(symbol)
            last = float(ticker.get("last") or 0.0)
        except Exception:
            last = 0.0

        h = holdings.get(base, {"currency": base, "total": 0.0, "free": 0.0})
        usd_value = float(h.get("total", 0.0)) * last if last > 0 else 0.0
        if usd_value and usd_value < args.min_usd:
            continue

        try:
            df = fetch_ohlcv_history(ex_public, symbol, args.timeframe, args.days)
            if df.empty:
                continue

            bt = run_backtest(df, p)
            strat_perf = summarize_performance(
                bt.equity_curve,
                bt.trades,
                timeframe=args.timeframe,
                underlying_close=bt.equity_curve["close"],
                crash_threshold=float(args.crash_threshold),
            )

            hold_curve = _hold_equity_curve(bt.equity_curve["close"])
            hold_perf = summarize_performance(hold_curve, [], timeframe=args.timeframe)

            label, score, reasons = score_keep_sell(
                usd_value=usd_value,
                hold_total_return=hold_perf.total_return,
                hold_max_dd=hold_perf.max_drawdown,
                trade_total_return=strat_perf.total_return,
                trade_max_dd=strat_perf.max_drawdown,
                downside_capture=strat_perf.downside_capture,
            )

            results.append(
                {
                    "symbol": symbol,
                    "base": base,
                    "usd_value": usd_value,
                    "hold": {
                        "cagr": hold_perf.cagr,
                        "max_drawdown": hold_perf.max_drawdown,
                        "total_return": hold_perf.total_return,
                    },
                    "trade": {
                        "cagr": strat_perf.cagr,
                        "max_drawdown": strat_perf.max_drawdown,
                        "total_return": strat_perf.total_return,
                        "sharpe": strat_perf.sharpe,
                        "sortino": strat_perf.sortino,
                        "trades": strat_perf.num_trades,
                        "win_rate": strat_perf.win_rate,
                        "downside_capture": strat_perf.downside_capture,
                    },
                    "decision": {"label": label, "score": score, "reasons": reasons},
                }
            )
        except Exception as e:
            results.append(
                {
                    "symbol": symbol,
                    "base": base,
                    "usd_value": usd_value,
                    "error": str(e),
                }
            )

    # Sort: highest USD value first, then lowest score (sell candidates bubble up)
    results.sort(key=lambda r: (-float(r.get("usd_value", 0.0)), int(r.get("decision", {}).get("score", 0))))

    print("\n" + "=" * 100)
    print("PORTFOLIO HISTORY REVIEW (NON-CORE COINS)")
    print("=" * 100)
    print(
        f"{'Coin':<8} {'USD':>10}  {'HoldRet':>10} {'HoldDD':>10}  {'TradeRet':>10} {'TradeDD':>10}  {'DwnCap':>10}  {'Score':>6}  {'Decision':>14}"
    )
    print("-" * 100)

    for r in results:
        if "error" in r:
            continue
        coin = r["base"]
        usd = float(r["usd_value"])
        hold_ret = float(r["hold"]["total_return"])
        hold_dd = float(r["hold"]["max_drawdown"])
        trade_ret = float(r["trade"]["total_return"])
        trade_dd = float(r["trade"]["max_drawdown"])
        dcap = r["trade"].get("downside_capture", None)
        score = int(r["decision"]["score"])
        label = r["decision"]["label"]
        print(
            f"{coin:<8} ${usd:>9.2f}  {_format_pct(hold_ret):>10} {_format_pct(hold_dd):>10}  {_format_pct(trade_ret):>10} {_format_pct(trade_dd):>10}  {_format_ratio(dcap):>10}  {score:>6}  {label:>14}"
        )

    sell_list = [r for r in results if r.get("decision", {}).get("label") == "SELL_CANDIDATE"]
    if sell_list:
        print("\nSELL CANDIDATES (review manually before executing):")
        for r in sell_list[:20]:
            reasons = ", ".join(r["decision"]["reasons"][:3])
            print(f"- {r['symbol']}: score={r['decision']['score']} ({reasons})")
    else:
        print("\nNo sell candidates identified by the current heuristic.")

    if args.report_json:
        with open(args.report_json, "w", encoding="utf-8") as f:
            json.dump({"timeframe": args.timeframe, "days": args.days, "results": results}, f, indent=2)
        print(f"\nWrote JSON report to: {args.report_json}")

    # Optional execution: sell free balance only, capped.
    if args.execute and sell_list:
        ex_auth = create_coinbase_exchange(sandbox=False, require_auth=True)
        ex_auth.load_markets()
        sells_done = 0
        print("\n" + "=" * 100)
        print("EXECUTION MODE: SELLING SELL_CANDIDATE COINS")
        print("=" * 100)
        for r in sell_list:
            if sells_done >= int(args.max_sells):
                print(f"Safety cap reached (--max-sells={args.max_sells}). Stopping.")
                break
            coin = r["base"]
            if coin in CORE_DO_NOT_SELL:
                continue
            holding = holdings.get(coin)
            if not holding:
                continue
            amount = float(holding.get("free", 0.0) or 0.0)
            if amount <= 0:
                continue
            pair = best_usd_pair(ex_auth, coin)
            if not pair:
                continue

            try:
                print(f"Selling {coin}: {amount} via {pair} ...")
                order = ex_auth.create_market_sell_order(pair, amount)
                sells_done += 1
                print(f"✅ Sold {coin}. Order id: {order.get('id', 'N/A')}")
            except Exception as e:
                print(f"❌ Failed to sell {coin}: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

