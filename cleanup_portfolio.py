#!/usr/bin/env python3
"""
Portfolio cleanup with historical validation.

This script can:
1) Sell tiny dust positions.
2) Backtest non-core holdings against the live strategy profile.
3) Mark historically weak coins for sale to free capital.

Core assets are preserved by default: ETH, BTC, LINK, SHIB.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import os
import sys

import ccxt
from dotenv import load_dotenv

from strategy_validation import StrategyValidationResult, evaluate_symbol_history


EXCLUDE_CURRENCIES = {"USD", "USDC"}
DEFAULT_PRIORITY_CURRENCIES = ["ETH", "BTC", "LINK", "SHIB"]
PAIR_PRIORITY = ("USD", "USDC", "BTC", "ETH")


@dataclass
class PositionDecision:
    currency: str
    total: float
    free: float
    price_usd: float
    usd_value: float
    sell_pair: Optional[str]
    action: str
    reason: str
    validation: Optional[StrategyValidationResult] = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Portfolio cleanup and history-based sell decisions")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute real sell orders. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--min-position-value",
        type=float,
        default=float(os.getenv("MIN_POSITION_VALUE_USD", "5.00")),
        help="Sell non-priority positions below this USD value.",
    )
    parser.add_argument(
        "--skip-history-check",
        action="store_true",
        help="Skip historical strategy validation and only sell dust positions.",
    )
    parser.add_argument(
        "--history-timeframe",
        default=os.getenv("HISTORY_VALIDATION_TIMEFRAME", "1h"),
        help="OHLCV timeframe used for history validation (default: 1h).",
    )
    parser.add_argument(
        "--history-lookback-days",
        type=int,
        default=int(os.getenv("HISTORY_VALIDATION_LOOKBACK_DAYS", "120")),
        help="How many days of history to backtest.",
    )
    parser.add_argument(
        "--history-min-bars",
        type=int,
        default=int(os.getenv("HISTORY_VALIDATION_MIN_BARS", "200")),
        help="Minimum bars required for history validation.",
    )
    parser.add_argument(
        "--min-history-score",
        type=float,
        default=float(os.getenv("HISTORY_VALIDATION_MIN_SCORE", "60")),
        help="Minimum score to keep a non-core asset (0-100).",
    )
    parser.add_argument(
        "--priority-currencies",
        default=os.getenv("PRIORITY_CURRENCIES", ",".join(DEFAULT_PRIORITY_CURRENCIES)),
        help="Comma-separated list of currencies to always keep.",
    )
    return parser.parse_args()


def normalize_secret(secret: Optional[str]) -> Optional[str]:
    if secret and "\\n" in secret:
        return secret.replace("\\n", "\n")
    return secret


def connect_exchange() -> ccxt.Exchange:
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = normalize_secret(os.getenv("COINBASE_API_SECRET"))

    if not api_key or not api_secret:
        raise RuntimeError("API credentials not found. Set COINBASE_API_KEY and COINBASE_API_SECRET.")

    exchange = ccxt.coinbaseadvanced(
        {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "sandbox": False,
            "options": {
                "createMarketBuyOrderRequiresPrice": False,
            },
        }
    )
    exchange.load_markets()
    return exchange


def parse_priority_currencies(raw: str) -> List[str]:
    parsed = [item.strip().upper() for item in raw.split(",") if item.strip()]
    return parsed or DEFAULT_PRIORITY_CURRENCIES


def fetch_last_price(exchange: ccxt.Exchange, pair: str, ticker_cache: Dict[str, float]) -> Optional[float]:
    if pair in ticker_cache:
        return ticker_cache[pair]
    if pair not in exchange.markets:
        return None
    try:
        ticker = exchange.fetch_ticker(pair)
        last = ticker.get("last")
        if last is None:
            return None
        ticker_cache[pair] = float(last)
        return float(last)
    except Exception:
        return None


def find_best_sell_pair(exchange: ccxt.Exchange, currency: str) -> Optional[str]:
    for quote in PAIR_PRIORITY:
        pair = f"{currency}/{quote}"
        if pair in exchange.markets:
            return pair
    return None


def estimate_usd_price(exchange: ccxt.Exchange, currency: str, ticker_cache: Dict[str, float]) -> Tuple[float, Optional[str]]:
    if currency == "USD":
        return 1.0, "USD/USD"
    if currency == "USDC":
        return 1.0, "USDC/USD"

    direct_pairs = [f"{currency}/USD", f"{currency}/USDC"]
    for pair in direct_pairs:
        last = fetch_last_price(exchange, pair, ticker_cache)
        if last is not None:
            return float(last), pair

    for quote in ("BTC", "ETH"):
        cross_pair = f"{currency}/{quote}"
        cross_last = fetch_last_price(exchange, cross_pair, ticker_cache)
        quote_usd = fetch_last_price(exchange, f"{quote}/USD", ticker_cache)
        if cross_last is not None and quote_usd is not None:
            return float(cross_last * quote_usd), cross_pair

    return 0.0, None


def choose_validation_pair(exchange: ccxt.Exchange, currency: str, fallback_pair: Optional[str]) -> Optional[str]:
    for quote in ("USD", "USDC"):
        pair = f"{currency}/{quote}"
        if pair in exchange.markets:
            return pair
    return fallback_pair if fallback_pair in exchange.markets else None


def analyze_positions(
    exchange: ccxt.Exchange,
    balance: dict,
    priority_currencies: List[str],
    min_position_value: float,
    skip_history_check: bool,
    history_timeframe: str,
    history_lookback_days: int,
    history_min_bars: int,
    min_history_score: float,
) -> Tuple[List[PositionDecision], float]:
    ticker_cache: Dict[str, float] = {}
    decisions: List[PositionDecision] = []
    usd_balance = 0.0

    for currency, bal_info in balance.items():
        if not isinstance(bal_info, dict):
            continue

        total = float(bal_info.get("total", 0.0) or 0.0)
        free = float(bal_info.get("free", 0.0) or 0.0)
        if total <= 0:
            continue

        if currency == "USD":
            usd_balance += total

        if currency in EXCLUDE_CURRENCIES:
            continue

        price_usd, discovered_pair = estimate_usd_price(exchange, currency, ticker_cache)
        usd_value = total * price_usd if price_usd > 0 else 0.0
        sell_pair = find_best_sell_pair(exchange, currency)

        if currency in priority_currencies:
            decisions.append(
                PositionDecision(
                    currency=currency,
                    total=total,
                    free=free,
                    price_usd=price_usd,
                    usd_value=usd_value,
                    sell_pair=sell_pair,
                    action="KEEP",
                    reason="Core priority asset",
                )
            )
            continue

        if usd_value > 0 and usd_value < min_position_value:
            decisions.append(
                PositionDecision(
                    currency=currency,
                    total=total,
                    free=free,
                    price_usd=price_usd,
                    usd_value=usd_value,
                    sell_pair=sell_pair,
                    action="SELL",
                    reason=f"Small position (< ${min_position_value:.2f})",
                )
            )
            continue

        if skip_history_check:
            decisions.append(
                PositionDecision(
                    currency=currency,
                    total=total,
                    free=free,
                    price_usd=price_usd,
                    usd_value=usd_value,
                    sell_pair=sell_pair,
                    action="KEEP",
                    reason="History check skipped",
                )
            )
            continue

        validation_pair = choose_validation_pair(exchange, currency, discovered_pair)
        if not validation_pair:
            decisions.append(
                PositionDecision(
                    currency=currency,
                    total=total,
                    free=free,
                    price_usd=price_usd,
                    usd_value=usd_value,
                    sell_pair=sell_pair,
                    action="KEEP",
                    reason="No supported pair for history validation",
                )
            )
            continue

        try:
            validation = evaluate_symbol_history(
                exchange=exchange,
                symbol=validation_pair,
                timeframe=history_timeframe,
                lookback_days=history_lookback_days,
                min_bars=history_min_bars,
            )
        except Exception as exc:
            decisions.append(
                PositionDecision(
                    currency=currency,
                    total=total,
                    free=free,
                    price_usd=price_usd,
                    usd_value=usd_value,
                    sell_pair=sell_pair,
                    action="KEEP",
                    reason=f"Validation failed ({exc})",
                )
            )
            continue

        insufficient_history = validation.bars < history_min_bars
        if insufficient_history:
            decisions.append(
                PositionDecision(
                    currency=currency,
                    total=total,
                    free=free,
                    price_usd=price_usd,
                    usd_value=usd_value,
                    sell_pair=sell_pair,
                    action="KEEP",
                    reason=f"Insufficient history ({validation.bars} bars)",
                    validation=validation,
                )
            )
            continue

        score_too_low = validation.score < min_history_score
        strategy_negative = validation.strategy_return < -0.08
        should_sell = validation.recommendation == "SELL" or score_too_low or strategy_negative

        if should_sell:
            reason = (
                f"History weak: score={validation.score:.1f}, "
                f"uptrend={validation.uptrend_capture:.2f}, "
                f"crash={validation.crash_protection if validation.crash_protection is not None else 0.50:.2f}, "
                f"return={validation.strategy_return*100:.1f}%"
            )
            action = "SELL"
        else:
            reason = (
                f"History strong: score={validation.score:.1f}, "
                f"uptrend={validation.uptrend_capture:.2f}, "
                f"return={validation.strategy_return*100:.1f}%"
            )
            action = "KEEP"

        decisions.append(
            PositionDecision(
                currency=currency,
                total=total,
                free=free,
                price_usd=price_usd,
                usd_value=usd_value,
                sell_pair=sell_pair,
                action=action,
                reason=reason,
                validation=validation,
            )
        )

    decisions.sort(key=lambda item: item.usd_value, reverse=True)
    return decisions, usd_balance


def print_analysis_summary(decisions: List[PositionDecision], usd_balance: float, dry_run: bool) -> None:
    print("=" * 120)
    print("POSITION ANALYSIS")
    print("=" * 120)
    print(f"{'Currency':<10} {'Amount':>16} {'Value USD':>14} {'Score':>8} {'Action':>10} {'Reason'}")
    print("-" * 120)

    for decision in decisions:
        amount_str = f"{decision.total:.8f}".rstrip("0").rstrip(".")
        score_str = f"{decision.validation.score:.1f}" if decision.validation else "-"
        value_str = f"${decision.usd_value:,.2f}" if decision.usd_value > 0 else "N/A"
        print(
            f"{decision.currency:<10} "
            f"{amount_str:>16} "
            f"{value_str:>14} "
            f"{score_str:>8} "
            f"{decision.action:>10} "
            f"{decision.reason}"
        )

    to_sell = [d for d in decisions if d.action == "SELL"]
    to_keep = [d for d in decisions if d.action == "KEEP"]
    total_sell_value = sum(d.usd_value for d in to_sell)

    print("-" * 120)
    print(f"💵 Current USD Balance: ${usd_balance:,.2f}")
    print(f"📊 Positions to keep: {len(to_keep)}")
    print(f"🗑️  Positions to sell: {len(to_sell)}")
    if to_sell:
        print(f"💰 Estimated USD after sales: ${usd_balance + total_sell_value:,.2f}")
    print(f"🔍 Mode: {'EXECUTE (real orders)' if not dry_run else 'DRY RUN (no orders)'}")
    print("=" * 120)


def execute_sales(exchange: ccxt.Exchange, positions_to_sell: List[PositionDecision]) -> Tuple[int, int]:
    successful = 0
    failed = 0

    for position in positions_to_sell:
        currency = position.currency
        amount = position.free
        pair = position.sell_pair

        if amount <= 0:
            print(f"⏭️  {currency}: No free balance to sell")
            continue

        if not pair:
            print(f"⚠️  {currency}: No supported market pair to sell")
            failed += 1
            continue

        market_info = exchange.markets.get(pair, {})
        min_cost = market_info.get("limits", {}).get("cost", {}).get("min", 1.0)
        if position.usd_value > 0 and position.usd_value < float(min_cost):
            print(f"⚠️  {currency}: Value ${position.usd_value:.2f} below min cost ${float(min_cost):.2f}")
            failed += 1
            continue

        print(f"\n💸 Selling {currency}:")
        print(f"   Amount: {amount:.8f} {currency}")
        print(f"   Pair: {pair}")
        print(f"   Reason: {position.reason}")

        try:
            order = exchange.create_market_sell_order(pair, amount)
            print(f"✅ Sold successfully. Order ID: {order.get('id', 'N/A')}")
            successful += 1
        except Exception as exc:
            print(f"❌ Sale failed for {currency}: {exc}")
            failed += 1

    return successful, failed


def main() -> None:
    load_dotenv()
    args = parse_args()
    priority_currencies = parse_priority_currencies(args.priority_currencies)

    print("=" * 120)
    print("PORTFOLIO CLEANUP + HISTORICAL VALIDATION")
    print("=" * 120)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Priority currencies (always kept): {', '.join(priority_currencies)}")
    print(f"Minimum position value: ${args.min_position_value:.2f}")
    print(
        "History validation: "
        f"{'DISABLED' if args.skip_history_check else f'ENABLED ({args.history_lookback_days}d @ {args.history_timeframe})'}"
    )
    print(f"History min score to keep: {args.min_history_score:.1f}")
    print(f"Execution mode: {'LIVE EXECUTION' if args.execute else 'DRY RUN'}")
    print()

    exchange = connect_exchange()
    print(f"✅ Connected to Coinbase. Loaded {len(exchange.markets)} markets.")

    print("💰 Fetching portfolio balance...")
    balance = exchange.fetch_balance()
    print("✅ Balance fetched.\n")

    decisions, usd_balance = analyze_positions(
        exchange=exchange,
        balance=balance,
        priority_currencies=priority_currencies,
        min_position_value=args.min_position_value,
        skip_history_check=args.skip_history_check,
        history_timeframe=args.history_timeframe,
        history_lookback_days=args.history_lookback_days,
        history_min_bars=args.history_min_bars,
        min_history_score=args.min_history_score,
    )

    print_analysis_summary(decisions, usd_balance, dry_run=not args.execute)

    positions_to_sell = [decision for decision in decisions if decision.action == "SELL"]
    if not positions_to_sell:
        print("✅ Nothing to sell. Portfolio already aligned with your rules.")
        return

    if not args.execute:
        print("🧪 Dry run complete. Re-run with --execute to place sell orders.")
        return

    print("\n" + "=" * 120)
    print("EXECUTING SALES")
    print("=" * 120)
    successful, failed = execute_sales(exchange, positions_to_sell)

    print("\n" + "=" * 120)
    print("SALES SUMMARY")
    print("=" * 120)
    print(f"✅ Successful sales: {successful}")
    print(f"❌ Failed sales: {failed}")

    updated_balance = exchange.fetch_balance()
    new_usd = updated_balance.get("USD", {}).get("free", 0.0)
    print(f"💵 Updated USD balance: ${new_usd:,.2f}")
    print("=" * 120)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n❌ Error: {exc}")
        sys.exit(1)

