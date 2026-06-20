#!/usr/bin/env python3
"""
Multi-Symbol Trading Bot
Trades multiple symbols with profile-based risk management.
"""
import argparse
import os
import sys
import time
from typing import Any, Dict, List, Tuple

import ccxt
import pandas as pd
import pandas_ta_classic as ta
from dotenv import load_dotenv

from portfolio_utils import fetch_portfolio_snapshot
from trading_journal import TradingJournal


def parse_symbol_list(raw_value: str) -> List[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def format_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def format_price(value: float) -> str:
    if value >= 1000:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:.2f}"
    return f"${value:.8f}"


def reset_position_state(position: Dict, record_exit: bool = False) -> None:
    if record_exit:
        position["last_exit_time"] = time.time()
    position["in_position"] = False
    position["trailing_stop_price"] = 0.0
    position["position_amount"] = 0.0
    position["entry_price"] = 0.0
    position["peak_price"] = 0.0
    position["trailing_profit_target"] = 0.0
    position["breakeven_set"] = False


def order_float(order: Dict[str, Any], field: str) -> float:
    if not isinstance(order, dict):
        return 0.0

    value = order.get(field)
    if value is None or value == "":
        return 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def order_id(order: Dict[str, Any]) -> str:
    if not isinstance(order, dict):
        return ""
    return str(order.get("id") or "")


def entry_result(
    executed: bool,
    *,
    filled_amount: float = 0.0,
    average_price: float = 0.0,
    cost_usd: float = 0.0,
    placed_order_id: str = "",
    pending: bool = False,
) -> Dict[str, Any]:
    return {
        "executed": executed,
        "filled_amount": filled_amount,
        "average_price": average_price,
        "cost_usd": cost_usd,
        "order_id": placed_order_id,
        "pending": pending,
    }


def entry_result_from_order(
    order: Dict[str, Any],
    fallback_amount: float,
    fallback_price: float,
    fallback_cost: float,
) -> Dict[str, Any]:
    filled_amount = order_float(order, "filled") or fallback_amount
    cost_usd = order_float(order, "cost") or fallback_cost
    average_price = order_float(order, "average") or order_float(order, "price")

    if average_price <= 0 and filled_amount > 0 and cost_usd > 0:
        average_price = cost_usd / filled_amount
    if average_price <= 0:
        average_price = fallback_price

    return entry_result(
        True,
        filled_amount=filled_amount,
        average_price=average_price,
        cost_usd=cost_usd,
        placed_order_id=order_id(order),
    )


def cancel_order_safely(exchange, symbol: str, base_currency: str, placed_order_id: str, context: str) -> None:
    if not placed_order_id:
        return

    try:
        exchange.cancel_order(placed_order_id, symbol)
        print(f"[{base_currency}] ✅ Canceled unfilled {context} limit order: {placed_order_id}")
    except Exception as exc:
        print(f"[{base_currency}] ⚠️  Could not cancel {context} limit order {placed_order_id}: {exc}")


def fetch_data(exchange, symbol: str, timeframe: str, limit: int = 100) -> pd.DataFrame:
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return pd.DataFrame(
            bars,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
    except Exception as exc:
        print(f"Data Error for {symbol}: {exc}")
        return pd.DataFrame()


def analyze_market(df: pd.DataFrame) -> pd.Series:
    working = df.copy()
    working["ema_20"] = ta.ema(working["close"], length=20)
    working["rsi"] = ta.rsi(working["close"], length=14)
    working["atr"] = ta.atr(working["high"], working["low"], working["close"], length=14)
    working["ema_slope"] = working["ema_20"].diff(5)
    working["volume_ma"] = working["volume"].rolling(20).mean()
    working["volume_ratio"] = working["volume"] / working["volume_ma"]
    return working.iloc[-1]


def analyze_regime(df: pd.DataFrame) -> pd.Series:
    working = df.copy()
    working["ema_50"] = ta.ema(working["close"], length=50)
    working["rsi"] = ta.rsi(working["close"], length=14)
    working["ema_slope"] = working["ema_50"].diff(5)
    return working.iloc[-1]


def env_float(name: str, default: str, fallback_name: str = None) -> float:
    raw_value = os.getenv(name)
    if raw_value is None and fallback_name:
        raw_value = os.getenv(fallback_name)
    if raw_value is None:
        raw_value = default
    return float(str(raw_value).strip())


def build_profile_settings() -> Dict[str, Dict]:
    return {
        "core": {
            "label": "core",
            "risk_weight": float(os.getenv("TRADING_CORE_RISK_WEIGHT", "1.00")),
            "profit_target_pct": env_float("TRADING_CORE_PROFIT_TARGET_PCT", "0.030", "TRADING_PROFIT_TARGET_PCT"),
            "spike_reversal_pct": env_float("TRADING_CORE_SPIKE_REVERSAL_PCT", "0.018", "TRADING_SPIKE_REVERSAL_PCT"),
            "min_spike_profit_pct": env_float("TRADING_CORE_MIN_SPIKE_PROFIT", "0.015", "TRADING_MIN_SPIKE_PROFIT"),
            "atr_multiplier": env_float("TRADING_CORE_ATR_MULTIPLIER", "1.60", "TRADING_ATR_MULTIPLIER"),
            "rsi_entry_threshold": env_float("TRADING_CORE_RSI_ENTRY", "54", "TRADING_RSI_ENTRY"),
            "min_trend_strength": env_float("TRADING_CORE_MIN_TREND_STRENGTH", "0.008", "TRADING_MIN_TREND_STRENGTH"),
            "min_volume_ratio": float(os.getenv("TRADING_CORE_MIN_VOLUME_RATIO", "0.95")),
            "breakeven_trigger_pct": float(os.getenv("TRADING_CORE_BREAKEVEN_TRIGGER", "0.012")),
            "breakeven_lock_pct": float(os.getenv("TRADING_CORE_BREAKEVEN_LOCK", "0.003")),
            "trail_capture_ratio": float(os.getenv("TRADING_CORE_TRAIL_CAPTURE_RATIO", "0.55")),
            "high_volatility_atr_pct": float(os.getenv("TRADING_CORE_HIGH_VOL_ATR_PCT", "0.030")),
            "high_volatility_profit_target_scale": float(os.getenv("TRADING_CORE_HIGH_VOL_TARGET_SCALE", "0.90")),
            "high_volatility_spike_scale": float(os.getenv("TRADING_CORE_HIGH_VOL_SPIKE_SCALE", "0.90")),
            "high_volatility_atr_scale": float(os.getenv("TRADING_CORE_HIGH_VOL_ATR_SCALE", "1.10")),
            "profit_locks": [
                (0.015, 0.005),
                (0.030, 0.012),
                (0.050, 0.025),
            ],
            "allowed_regimes": {"risk_on", "mixed"},
        },
        "tactical": {
            "label": "tactical",
            "risk_weight": float(os.getenv("TRADING_TACTICAL_RISK_WEIGHT", "0.90")),
            "profit_target_pct": env_float("TRADING_TACTICAL_PROFIT_TARGET_PCT", "0.025", "TRADING_PROFIT_TARGET_PCT"),
            "spike_reversal_pct": env_float("TRADING_TACTICAL_SPIKE_REVERSAL_PCT", "0.014", "TRADING_SPIKE_REVERSAL_PCT"),
            "min_spike_profit_pct": env_float("TRADING_TACTICAL_MIN_SPIKE_PROFIT", "0.012", "TRADING_MIN_SPIKE_PROFIT"),
            "atr_multiplier": env_float("TRADING_TACTICAL_ATR_MULTIPLIER", "1.80", "TRADING_ATR_MULTIPLIER"),
            "rsi_entry_threshold": env_float("TRADING_TACTICAL_RSI_ENTRY", "56", "TRADING_RSI_ENTRY"),
            "min_trend_strength": env_float("TRADING_TACTICAL_MIN_TREND_STRENGTH", "0.010", "TRADING_MIN_TREND_STRENGTH"),
            "min_volume_ratio": float(os.getenv("TRADING_TACTICAL_MIN_VOLUME_RATIO", "1.00")),
            "breakeven_trigger_pct": float(os.getenv("TRADING_TACTICAL_BREAKEVEN_TRIGGER", "0.010")),
            "breakeven_lock_pct": float(os.getenv("TRADING_TACTICAL_BREAKEVEN_LOCK", "0.004")),
            "trail_capture_ratio": float(os.getenv("TRADING_TACTICAL_TRAIL_CAPTURE_RATIO", "0.65")),
            "high_volatility_atr_pct": float(os.getenv("TRADING_TACTICAL_HIGH_VOL_ATR_PCT", "0.025")),
            "high_volatility_profit_target_scale": float(os.getenv("TRADING_TACTICAL_HIGH_VOL_TARGET_SCALE", "0.90")),
            "high_volatility_spike_scale": float(os.getenv("TRADING_TACTICAL_HIGH_VOL_SPIKE_SCALE", "0.85")),
            "high_volatility_atr_scale": float(os.getenv("TRADING_TACTICAL_HIGH_VOL_ATR_SCALE", "1.10")),
            "profit_locks": [
                (0.010, 0.005),
                (0.020, 0.010),
                (0.035, 0.020),
            ],
            "allowed_regimes": {"risk_on", "mixed"},
        },
        "speculative": {
            "label": "speculative",
            "risk_weight": float(os.getenv("TRADING_SPECULATIVE_RISK_WEIGHT", "1.20")),
            "profit_target_pct": env_float("TRADING_SPECULATIVE_PROFIT_TARGET_PCT", "0.020", "TRADING_PROFIT_TARGET_PCT"),
            "spike_reversal_pct": env_float("TRADING_SPECULATIVE_SPIKE_REVERSAL_PCT", "0.010", "TRADING_SPIKE_REVERSAL_PCT"),
            "min_spike_profit_pct": env_float("TRADING_SPECULATIVE_MIN_SPIKE_PROFIT", "0.010", "TRADING_MIN_SPIKE_PROFIT"),
            "atr_multiplier": env_float("TRADING_SPECULATIVE_ATR_MULTIPLIER", "2.00", "TRADING_ATR_MULTIPLIER"),
            "rsi_entry_threshold": env_float("TRADING_SPECULATIVE_RSI_ENTRY", "60", "TRADING_RSI_ENTRY"),
            "min_trend_strength": env_float("TRADING_SPECULATIVE_MIN_TREND_STRENGTH", "0.015", "TRADING_MIN_TREND_STRENGTH"),
            "min_volume_ratio": float(os.getenv("TRADING_SPECULATIVE_MIN_VOLUME_RATIO", "1.10")),
            "breakeven_trigger_pct": float(os.getenv("TRADING_SPECULATIVE_BREAKEVEN_TRIGGER", "0.008")),
            "breakeven_lock_pct": float(os.getenv("TRADING_SPECULATIVE_BREAKEVEN_LOCK", "0.004")),
            "trail_capture_ratio": float(os.getenv("TRADING_SPECULATIVE_TRAIL_CAPTURE_RATIO", "0.75")),
            "high_volatility_atr_pct": float(os.getenv("TRADING_SPECULATIVE_HIGH_VOL_ATR_PCT", "0.020")),
            "high_volatility_profit_target_scale": float(os.getenv("TRADING_SPECULATIVE_HIGH_VOL_TARGET_SCALE", "0.85")),
            "high_volatility_spike_scale": float(os.getenv("TRADING_SPECULATIVE_HIGH_VOL_SPIKE_SCALE", "0.80")),
            "high_volatility_atr_scale": float(os.getenv("TRADING_SPECULATIVE_HIGH_VOL_ATR_SCALE", "1.15")),
            "profit_locks": [
                (0.008, 0.004),
                (0.015, 0.008),
                (0.025, 0.015),
            ],
            "allowed_regimes": {"risk_on"},
        },
    }


def resolve_symbol_profile(
    symbol: str,
    core_symbols: set,
    tactical_symbols: set,
    speculative_symbols: set,
) -> str:
    if symbol in core_symbols:
        return "core"
    if symbol in tactical_symbols:
        return "tactical"
    if symbol in speculative_symbols:
        return "speculative"
    if symbol in {"ETH/USD", "BTC/USD"}:
        return "core"
    return "tactical"


def place_entry_order(
    exchange,
    symbol: str,
    base_currency: str,
    amount: float,
    cost: float,
    current_price: float,
    use_limit_orders: bool,
    limit_order_offset_pct: float,
    enable_trading: bool,
) -> Dict[str, Any]:
    if use_limit_orders:
        limit_price = exchange.fetch_ticker(symbol)["last"] * (1 - limit_order_offset_pct)
        print(
            f"[{base_currency}] 🚀 ENTER LONG (LIMIT): Buying {amount:.6f} {base_currency} "
            f"at ${limit_price:.2f} (Cost: ${cost:.2f})"
        )
        if not enable_trading:
            print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
            return entry_result(True, filled_amount=amount, average_price=limit_price, cost_usd=cost)

        order = None
        try:
            order = exchange.create_limit_buy_order(symbol, amount, limit_price)
            placed_order_id = order_id(order)
            print(f"[{base_currency}] ✅ Limit order placed: {placed_order_id or 'N/A'}")
            time.sleep(5)
            order_status = exchange.fetch_order(placed_order_id, symbol)
            if order_status.get("status") == "closed":
                print(f"[{base_currency}] ✅ Limit order filled")
                return entry_result_from_order(order_status, amount, limit_price, cost)
            print(f"[{base_currency}] ⏳ Limit order still open; canceling before the next cycle")
            cancel_order_safely(exchange, symbol, base_currency, placed_order_id, "entry")
            return entry_result(False, placed_order_id=placed_order_id, pending=True)
        except Exception as exc:
            print(f"[{base_currency}] ❌ Limit entry failed: {exc}")
            placed_order_id = order_id(order)
            if placed_order_id:
                cancel_order_safely(exchange, symbol, base_currency, placed_order_id, "entry")
                return entry_result(False, placed_order_id=placed_order_id, pending=True)
            try:
                order = exchange.create_market_buy_order(symbol, cost)
                print(f"[{base_currency}] ✅ Fallback market order executed: {order.get('id', 'N/A')}")
                return entry_result_from_order(order, amount, current_price, cost)
            except Exception as fallback_exc:
                print(f"[{base_currency}] ❌ Market entry also failed: {fallback_exc}")
                return entry_result(False)

    print(f"[{base_currency}] 🚀 ENTER LONG: Buying {amount:.6f} {base_currency} (Cost: ${cost:.2f})")
    if not enable_trading:
        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
        return entry_result(True, filled_amount=amount, average_price=current_price, cost_usd=cost)

    try:
        order = exchange.create_market_buy_order(symbol, cost)
        print(f"[{base_currency}] ✅ Order executed: {order.get('id', 'N/A')}")
        return entry_result_from_order(order, amount, current_price, cost)
    except Exception as exc:
        print(f"[{base_currency}] ❌ Order failed: {exc}")
        return entry_result(False)


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
) -> bool:
    if not enable_trading:
        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
        return True

    if use_limit_orders and not force_market:
        order = None
        try:
            last_price = exchange.fetch_ticker(symbol)["last"]
            limit_price = last_price * (1 + limit_order_offset_pct)
            order = exchange.create_limit_sell_order(symbol, amount, limit_price)
            placed_order_id = order_id(order)
            print(
                f"[{base_currency}] ✅ {reason} limit order placed: "
                f"{placed_order_id or 'N/A'} at ${limit_price:.2f}"
            )
            time.sleep(5)
            order_status = exchange.fetch_order(placed_order_id, symbol)
            if order_status.get("status") == "closed":
                print(f"[{base_currency}] ✅ Limit exit filled")
                return True
            print(f"[{base_currency}] ⏳ Exit limit order still open; canceling and keeping position state intact")
            cancel_order_safely(exchange, symbol, base_currency, placed_order_id, "exit")
            return False
        except Exception as exc:
            print(f"[{base_currency}] ❌ Limit exit failed: {exc}")
            placed_order_id = order_id(order)
            if placed_order_id:
                cancel_order_safely(exchange, symbol, base_currency, placed_order_id, "exit")
                return False

    try:
        order = exchange.create_market_sell_order(symbol, amount)
        print(f"[{base_currency}] ✅ {reason} market sell executed: {order.get('id', 'N/A')}")
        return True
    except Exception as exc:
        print(f"[{base_currency}] ❌ {reason} sell failed: {exc}")
        return False


def get_regime_state(exchange, benchmark_symbols: List[str], regime_timeframe: str) -> Tuple[str, Dict[str, Dict]]:
    snapshots = {}
    bullish = 0
    bearish = 0

    for benchmark_symbol in benchmark_symbols:
        df = fetch_data(exchange, benchmark_symbol, regime_timeframe, limit=120)
        if df.empty or len(df) < 55:
            continue

        row = analyze_regime(df)
        price = row["close"]
        ema_50 = row["ema_50"]
        rsi = row["rsi"]
        ema_slope = row["ema_slope"]

        is_bullish = price > ema_50 and rsi >= 52 and ema_slope > 0
        is_bearish = price < ema_50 and rsi <= 48 and ema_slope < 0

        snapshots[benchmark_symbol] = {
            "price": price,
            "ema_50": ema_50,
            "rsi": rsi,
            "is_bullish": is_bullish,
            "is_bearish": is_bearish,
        }

        if is_bullish:
            bullish += 1
        elif is_bearish:
            bearish += 1

    if not snapshots:
        return "mixed", snapshots
    if bullish == len(snapshots):
        return "risk_on", snapshots
    if bearish == len(snapshots):
        return "risk_off", snapshots
    return "mixed", snapshots


def get_position_size(exchange, symbol: str, current_price: float, symbol_risk_slice: float, leverage: int) -> Tuple[float, float]:
    try:
        balance = exchange.fetch_balance()
        free_usd = balance.get("USD", {}).get("free", 0)
        if free_usd <= 0:
            free_usd = balance.get("USDC", {}).get("free", 0)

        margin_to_use = free_usd * symbol_risk_slice
        quote_to_spend = margin_to_use * max(leverage, 1)
        amount = quote_to_spend / current_price if current_price > 0 else 0
        return amount, quote_to_spend
    except Exception as exc:
        print(f"Balance Error for {symbol}: {exc}")
        return 0, 0


def configure_effective_leverage(exchange, symbols: List[str], requested_leverage: int, journal: TradingJournal) -> int:
    if requested_leverage <= 1:
        return 1

    try:
        for symbol in symbols:
            exchange.set_leverage(requested_leverage, symbol)
        print(f"⚡ Leverage set to {requested_leverage}x for all symbols.")
        return requested_leverage
    except Exception as exc:
        journal.log_event(
            "warning",
            reason="set_leverage_not_supported",
            status="warning",
            payload={"message": str(exc), "effective_leverage": 1},
        )
        print(f"⚠️  Could not set leverage automatically: {exc}")
        print("⚠️  Using 1x sizing so recorded position size matches actual spot fills.")
        return 1


load_dotenv()

parser = argparse.ArgumentParser(description="Multi-Symbol Coinbase Trading Bot")
parser.add_argument("--test", action="store_true", help="Run in test mode")
parser.add_argument("--sandbox", action="store_true", help="Use sandbox environment")
parser.add_argument("--execute", action="store_true", help="Enable actual trade execution")
args = parser.parse_args()

use_sandbox = args.sandbox or args.test
enable_trading = args.execute

if use_sandbox and os.path.exists(".env.sandbox"):
    load_dotenv(".env.sandbox", override=True)
elif not use_sandbox and os.path.exists(".env.production"):
    load_dotenv(".env.production", override=True)

symbols = parse_symbol_list(
    os.getenv("TRADING_SYMBOLS", "ETH/USD,BTC/USD,LINK/USD,SHIB/USD,ALGO/USD,FET/USD")
)
timeframe = os.getenv("TRADING_TIMEFRAME", "5m")
leverage = int(os.getenv("TRADING_LEVERAGE", "5"))
risk_pct = float(os.getenv("TRADING_RISK_PCT", "0.20"))
check_interval = int(os.getenv("TRADING_CHECK_INTERVAL", "60"))
cooldown_minutes = int(os.getenv("TRADING_COOLDOWN_MINUTES", "5"))
min_order_size = float(os.getenv("TRADING_MIN_ORDER_SIZE", "1.00"))
benchmark_symbols = parse_symbol_list(os.getenv("TRADING_REGIME_SYMBOLS", "BTC/USD,ETH/USD"))
regime_timeframe = os.getenv("TRADING_REGIME_TIMEFRAME", "1h")

use_limit_orders = os.getenv("TRADING_USE_LIMIT_ORDERS", "false").lower() == "true"
limit_order_offset_pct = float(os.getenv("TRADING_LIMIT_ORDER_OFFSET", "0.001"))
log_signal_checks = os.getenv("TRADING_LOG_SIGNAL_CHECKS", "true").lower() == "true"
snapshot_interval_minutes = int(os.getenv("TRADING_PORTFOLIO_SNAPSHOT_MINUTES", "30"))

core_symbols = set(parse_symbol_list(os.getenv("TRADING_CORE_SYMBOLS", "ETH/USD,BTC/USD")))
tactical_symbols = set(parse_symbol_list(os.getenv("TRADING_TACTICAL_SYMBOLS", "LINK/USD,SHIB/USD")))
speculative_symbols = set(parse_symbol_list(os.getenv("TRADING_SPECULATIVE_SYMBOLS", "ALGO/USD,FET/USD")))
profile_settings = build_profile_settings()

symbol_profiles = {
    symbol: resolve_symbol_profile(symbol, core_symbols, tactical_symbols, speculative_symbols)
    for symbol in symbols
}
symbol_weights = {
    symbol: profile_settings[symbol_profiles[symbol]]["risk_weight"]
    for symbol in symbols
}
total_risk_weight = sum(symbol_weights.values()) or float(len(symbols) or 1)

api_key = os.getenv("COINBASE_API_KEY", "YOUR_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET", "YOUR_SECRET_KEY")
api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")
journal = TradingJournal.from_env()

if api_secret and "\\n" in api_secret:
    api_secret = api_secret.replace("\\n", "\n")

if args.test:
    print("🧪 TEST MODE ENABLED")
    print("=" * 60)

try:
    if use_sandbox:
        ExchangeClass = ccxt.coinbaseexchange or ccxt.coinbaseadvanced
    else:
        ExchangeClass = ccxt.coinbaseadvanced or ccxt.coinbaseexchange

    exchange_config = {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "sandbox": use_sandbox,
        "options": {
            "createMarketBuyOrderRequiresPrice": False,
        },
    }

    if use_sandbox:
        exchange_config["password"] = api_passphrase if api_passphrase else ""
    elif api_passphrase:
        exchange_config["password"] = api_passphrase

    exchange = ExchangeClass(exchange_config)
    print(f"🔌 Connecting to {'SANDBOX' if use_sandbox else 'PRODUCTION'}...")
    exchange.load_markets()
    print("✅ Connected to Coinbase Advanced Trade successfully.")
    print(f"📊 Trading symbols: {', '.join(symbols)}")

    if args.test:
        print(f"📊 Loaded {len(exchange.markets)} markets")
        for symbol in symbols:
            if symbol in exchange.markets:
                print(f"✅ Symbol {symbol} is available")
            else:
                print(f"⚠️  Symbol {symbol} not found")
except Exception as exc:
    journal.log_event(
        "runtime_error",
        reason="exchange_connection",
        status="failed",
        payload={"message": str(exc)},
    )
    print(f"❌ Connection Error: {exc}")
    sys.exit()

effective_leverage = configure_effective_leverage(exchange, symbols, leverage, journal)

positions = {}
for symbol in symbols:
    positions[symbol] = {
        "in_position": False,
        "trailing_stop_price": 0.0,
        "position_amount": 0.0,
        "entry_price": 0.0,
        "breakeven_set": False,
        "peak_price": 0.0,
        "trailing_profit_target": 0.0,
        "last_exit_time": 0,
    }

print(f"🛡️ Active. Risking {risk_pct * 100:.1f}% total across {len(symbols)} symbols.")
print(f"🧭 Market regime guardrails use {', '.join(benchmark_symbols)} on {regime_timeframe} candles.")
print(
    "🗃️ Journal backend: "
    f"{journal.describe_backend()}"
    + ("" if journal.is_persistent() else " (non-persistent unless you add DATABASE_URL)")
)
if use_limit_orders:
    print("💵 Order Type: LIMIT ORDERS with market fallback")
else:
    print("💵 Order Type: MARKET ORDERS")
for symbol in symbols:
    profile_name = symbol_profiles[symbol]
    profile = profile_settings[profile_name]
    risk_slice = risk_pct * symbol_weights[symbol] / total_risk_weight
    print(
        f"   {symbol:<10} profile={profile_name:<11} "
        f"risk={format_pct(risk_slice)} target={format_pct(profile['profit_target_pct'])} "
        f"spike={format_pct(profile['spike_reversal_pct'])}"
    )
print(f"⏸️  Cooldown Period: {cooldown_minutes} minutes after exit")
print(f"⏱️  Check Interval: {check_interval} seconds")
if enable_trading:
    print("⚠️  TRADING ENABLED - Real orders will be executed!")
else:
    print("ℹ️  Trading disabled - orders are simulated (use --execute to enable)")

journal.log_event(
    "bot_started",
    status="running",
    payload={
        "symbols": symbols,
        "timeframe": timeframe,
        "regime_symbols": benchmark_symbols,
        "risk_pct": risk_pct,
        "leverage": leverage,
        "effective_leverage": effective_leverage,
        "enable_trading": enable_trading,
        "journal_backend": journal.describe_backend(),
    },
)

try:
    initial_snapshot = fetch_portfolio_snapshot(exchange)
    journal.log_portfolio_snapshot(
        total_estimated_usd=initial_snapshot["total_estimated_usd"],
        free_usd=initial_snapshot["free_usd"],
        invested_usd=initial_snapshot["invested_usd"],
        positions=initial_snapshot["positions"],
    )
except Exception as exc:
    journal.log_event(
        "warning",
        reason="initial_snapshot_failed",
        status="warning",
        payload={"message": str(exc)},
    )

last_regime_label = None
last_snapshot_time = time.time()

while True:
    regime_label, regime_snapshots = get_regime_state(exchange, benchmark_symbols, regime_timeframe)
    if regime_label != last_regime_label:
        print(f"🌡️ Market Regime: {regime_label.upper()}")
        for benchmark_symbol, snapshot in regime_snapshots.items():
            print(
                f"   {benchmark_symbol}: price={format_price(snapshot['price'])} "
                f"EMA50={format_price(snapshot['ema_50'])} RSI={snapshot['rsi']:.2f}"
            )
        journal.log_event(
            "regime_changed",
            regime=regime_label,
            status="updated",
            payload={"snapshots": regime_snapshots},
        )
        last_regime_label = regime_label

    for symbol in symbols:
        try:
            df = fetch_data(exchange, symbol, timeframe)
            if df.empty or len(df) < 30:
                continue

            row = analyze_market(df)
            price = row["close"]
            ema_20 = row["ema_20"]
            atr = row["atr"]
            rsi = row["rsi"]
            ema_slope = row.get("ema_slope", 0)
            volume_ratio = row.get("volume_ratio", 1.0)

            base_currency = symbol.split("/")[0]
            pos = positions[symbol]
            profile_name = symbol_profiles[symbol]
            profile = profile_settings[profile_name]

            trend_strength = abs(price - ema_20) / ema_20 if ema_20 > 0 else 0
            atr_pct = atr / price if price > 0 else 0

            dynamic_profit_target = profile["profit_target_pct"]
            dynamic_spike_reversal = profile["spike_reversal_pct"]
            dynamic_min_spike_profit = profile["min_spike_profit_pct"]
            dynamic_atr_multiplier = profile["atr_multiplier"]

            if atr_pct >= profile["high_volatility_atr_pct"]:
                dynamic_profit_target *= profile["high_volatility_profit_target_scale"]
                dynamic_spike_reversal *= profile["high_volatility_spike_scale"]
                dynamic_atr_multiplier *= profile["high_volatility_atr_scale"]

            print(
                f"[{base_currency}] Price: {format_price(price)} | RSI: {rsi:.2f} | "
                f"Stop: {format_price(pos['trailing_stop_price'])} | "
                f"Position: {'YES' if pos['in_position'] else 'NO'} | "
                f"Profile: {profile_name}"
            )

            if not pos["in_position"]:
                current_time = time.time()
                time_since_exit = (
                current_time - pos["last_exit_time"]
                    if pos["last_exit_time"] > 0
                    else cooldown_minutes * 60 + 1
                )

                price_above_ema = price > ema_20
                rsi_strong = rsi > profile["rsi_entry_threshold"]
                trend_strong_enough = trend_strength >= profile["min_trend_strength"]
                ema_trending_up = ema_slope > 0
                volume_adequate = volume_ratio >= profile["min_volume_ratio"]
                cooldown_active = time_since_exit < cooldown_minutes * 60
                regime_allowed = regime_label in profile["allowed_regimes"]
                blocked_reasons = []

                if cooldown_active:
                    blocked_reasons.append("cooldown_active")
                if not regime_allowed:
                    blocked_reasons.append("regime_blocked")
                if not price_above_ema:
                    blocked_reasons.append("price_below_ema")
                if not rsi_strong:
                    blocked_reasons.append("rsi_below_threshold")
                if not trend_strong_enough:
                    blocked_reasons.append("trend_too_weak")
                if not ema_trending_up:
                    blocked_reasons.append("ema_not_rising")
                if not volume_adequate:
                    blocked_reasons.append("volume_below_average")

                if log_signal_checks:
                    journal.log_event(
                        "signal_evaluation",
                        symbol=symbol,
                        profile=profile_name,
                        regime=regime_label,
                        status="entry_ready" if not blocked_reasons else "blocked",
                        price=price,
                        payload={
                            "entry_ready": not blocked_reasons,
                            "blocked_reasons": blocked_reasons,
                            "rsi": rsi,
                            "ema_20": ema_20,
                            "atr": atr,
                            "atr_pct": atr_pct,
                            "trend_strength": trend_strength,
                            "ema_slope": ema_slope,
                            "volume_ratio": volume_ratio,
                            "cooldown_seconds_remaining": max(cooldown_minutes * 60 - time_since_exit, 0),
                        },
                    )

                if blocked_reasons:
                    continue

                if price_above_ema and rsi_strong and trend_strong_enough and ema_trending_up and volume_adequate:
                    risk_slice = risk_pct * symbol_weights[symbol] / total_risk_weight
                    amount, cost = get_position_size(exchange, symbol, price, risk_slice, effective_leverage)

                    if cost < min_order_size:
                        journal.log_event(
                            "entry_skipped",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            reason="order_below_minimum",
                            status="skipped",
                            price=price,
                            amount=amount,
                            cost_usd=cost,
                        )
                        print(
                            f"[{base_currency}] ⚠️  Order too small: "
                            f"${cost:.2f} < ${min_order_size:.2f} minimum. Skipping."
                        )
                        continue

                    if amount <= 0:
                        journal.log_event(
                            "entry_skipped",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            reason="no_position_size",
                            status="skipped",
                            price=price,
                        )
                        continue

                    entry_executed = place_entry_order(
                        exchange,
                        symbol,
                        base_currency,
                        amount,
                        cost,
                        price,
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                    )

                    if entry_executed["executed"]:
                        filled_amount = entry_executed["filled_amount"]
                        entry_price = entry_executed["average_price"] or price
                        entry_cost = entry_executed["cost_usd"] or (filled_amount * entry_price)
                        pos["trailing_stop_price"] = entry_price - (atr * dynamic_atr_multiplier)
                        pos["position_amount"] = filled_amount
                        pos["entry_price"] = entry_price
                        pos["peak_price"] = entry_price
                        pos["trailing_profit_target"] = entry_price * (1 + dynamic_profit_target)
                        pos["in_position"] = True
                        pos["breakeven_set"] = False
                        journal.log_event(
                            "entry_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="buy",
                            order_id=entry_executed["order_id"] or None,
                            status="executed",
                            price=entry_price,
                            amount=filled_amount,
                            cost_usd=entry_cost,
                            payload={
                                "rsi": rsi,
                                "atr_pct": atr_pct,
                                "trend_strength": trend_strength,
                                "volume_ratio": volume_ratio,
                                "profit_target_pct": dynamic_profit_target,
                                "spike_reversal_pct": dynamic_spike_reversal,
                                "requested_amount": amount,
                                "requested_cost_usd": cost,
                            },
                        )
                    else:
                        journal.log_event(
                            "entry_unfilled_or_failed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="buy",
                            order_id=entry_executed["order_id"] or None,
                            status="pending_or_failed",
                            price=price,
                            amount=amount,
                            cost_usd=cost,
                        )

            else:
                entry_price = pos["entry_price"]
                profit_pct = (price - entry_price) / entry_price if entry_price > 0 else 0

                if price > pos["peak_price"]:
                    pos["peak_price"] = price
                    new_target = entry_price * (1 + dynamic_profit_target) + (
                        (price - entry_price) * profile["trail_capture_ratio"]
                    )
                    if new_target > pos["trailing_profit_target"]:
                        pos["trailing_profit_target"] = new_target

                peak_profit_pct = (
                    (pos["peak_price"] - entry_price) / entry_price if entry_price > 0 else 0
                )
                drop_from_peak_pct = (
                    (pos["peak_price"] - price) / pos["peak_price"] if pos["peak_price"] > 0 else 0
                )

                if (
                    peak_profit_pct >= dynamic_min_spike_profit
                    and drop_from_peak_pct >= dynamic_spike_reversal
                ):
                    print(
                        f"[{base_currency}] 📉 SPIKE REVERSAL DETECTED: "
                        f"Price dropped {drop_from_peak_pct * 100:.2f}% from peak "
                        f"{format_price(pos['peak_price'])}"
                    )
                    print(
                        f"[{base_currency}] 💰 Capturing profit: {profit_pct * 100:.2f}% "
                        f"(Peak was {peak_profit_pct * 100:.2f}%)"
                    )

                    exit_executed = place_exit_order(
                        exchange,
                        symbol,
                        base_currency,
                        pos["position_amount"],
                        "Spike reversal",
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                    )
                    if exit_executed:
                        journal.log_event(
                            "exit_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="spike_reversal",
                            status="executed",
                            price=price,
                            amount=pos["position_amount"],
                            cost_usd=price * pos["position_amount"],
                            profit_pct=profit_pct,
                            payload={
                                "estimated_pnl_usd": (price - entry_price) * pos["position_amount"],
                                "peak_profit_pct": peak_profit_pct,
                                "drop_from_peak_pct": drop_from_peak_pct,
                            },
                        )
                        reset_position_state(pos, record_exit=True)
                        continue
                    journal.log_event(
                        "exit_unfilled_or_failed",
                        symbol=symbol,
                        profile=profile_name,
                        regime=regime_label,
                        side="sell",
                        reason="spike_reversal",
                        status="pending_or_failed",
                        price=price,
                        amount=pos["position_amount"],
                        profit_pct=profit_pct,
                    )
                    continue

                profit_target_price = entry_price * (1 + dynamic_profit_target)
                if price >= profit_target_price:
                    print(
                        f"[{base_currency}] 💰 PROFIT TARGET REACHED: "
                        f"{profit_pct * 100:.2f}% profit at {format_price(price)}"
                    )
                    exit_executed = place_exit_order(
                        exchange,
                        symbol,
                        base_currency,
                        pos["position_amount"],
                        "Profit-taking",
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                    )
                    if exit_executed:
                        journal.log_event(
                            "exit_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="profit_target",
                            status="executed",
                            price=price,
                            amount=pos["position_amount"],
                            cost_usd=price * pos["position_amount"],
                            profit_pct=profit_pct,
                            payload={
                                "estimated_pnl_usd": (price - entry_price) * pos["position_amount"],
                                "target_price": profit_target_price,
                            },
                        )
                        reset_position_state(pos, record_exit=True)
                        continue
                    journal.log_event(
                        "exit_unfilled_or_failed",
                        symbol=symbol,
                        profile=profile_name,
                        regime=regime_label,
                        side="sell",
                        reason="profit_target",
                        status="pending_or_failed",
                        price=price,
                        amount=pos["position_amount"],
                        profit_pct=profit_pct,
                    )
                    continue

                if pos["trailing_profit_target"] > 0 and price >= pos["trailing_profit_target"]:
                    print(
                        f"[{base_currency}] 💰 TRAILING PROFIT TARGET REACHED: "
                        f"{profit_pct * 100:.2f}% profit at {format_price(price)}"
                    )
                    exit_executed = place_exit_order(
                        exchange,
                        symbol,
                        base_currency,
                        pos["position_amount"],
                        "Trailing profit",
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                    )
                    if exit_executed:
                        journal.log_event(
                            "exit_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="trailing_profit",
                            status="executed",
                            price=price,
                            amount=pos["position_amount"],
                            cost_usd=price * pos["position_amount"],
                            profit_pct=profit_pct,
                            payload={
                                "estimated_pnl_usd": (price - entry_price) * pos["position_amount"],
                                "trailing_profit_target": pos["trailing_profit_target"],
                            },
                        )
                        reset_position_state(pos, record_exit=True)
                        continue
                    journal.log_event(
                        "exit_unfilled_or_failed",
                        symbol=symbol,
                        profile=profile_name,
                        regime=regime_label,
                        side="sell",
                        reason="trailing_profit",
                        status="pending_or_failed",
                        price=price,
                        amount=pos["position_amount"],
                        profit_pct=profit_pct,
                    )
                    continue

                potential_stop = price - (atr * dynamic_atr_multiplier)
                if potential_stop > pos["trailing_stop_price"]:
                    pos["trailing_stop_price"] = potential_stop

                if (
                    not pos["breakeven_set"]
                    and profit_pct >= profile["breakeven_trigger_pct"]
                ):
                    protected_price = entry_price * (1 + profile["breakeven_lock_pct"])
                    pos["trailing_stop_price"] = max(pos["trailing_stop_price"], protected_price)
                    pos["breakeven_set"] = True
                    print(
                        f"[{base_currency}] 🔒 Stop moved above breakeven at "
                        f"{format_price(pos['trailing_stop_price'])}"
                    )

                for trigger_pct, locked_pct in profile["profit_locks"]:
                    if profit_pct >= trigger_pct:
                        locked_price = entry_price * (1 + locked_pct)
                        if pos["trailing_stop_price"] < locked_price:
                            pos["trailing_stop_price"] = locked_price
                            print(
                                f"[{base_currency}] 🔒 Profit locked: {locked_pct * 100:.1f}% "
                                f"at {format_price(pos['trailing_stop_price'])}"
                            )

                if price <= pos["trailing_stop_price"]:
                    print(
                        f"[{base_currency}] 🚨 STOP LOSS TRIGGERED at {format_price(price)} "
                        f"(Entry: {format_price(entry_price)}, P/L: {profit_pct * 100:.2f}%)"
                    )
                    exit_executed = place_exit_order(
                        exchange,
                        symbol,
                        base_currency,
                        pos["position_amount"],
                        "Stop-loss",
                        use_limit_orders,
                        limit_order_offset_pct,
                        enable_trading,
                        force_market=True,
                    )
                    if exit_executed:
                        journal.log_event(
                            "exit_executed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="stop_loss",
                            status="executed",
                            price=price,
                            amount=pos["position_amount"],
                            cost_usd=price * pos["position_amount"],
                            profit_pct=profit_pct,
                            payload={
                                "estimated_pnl_usd": (price - entry_price) * pos["position_amount"],
                                "stop_price": pos["trailing_stop_price"],
                            },
                        )
                        reset_position_state(pos, record_exit=True)
                    else:
                        journal.log_event(
                            "exit_unfilled_or_failed",
                            symbol=symbol,
                            profile=profile_name,
                            regime=regime_label,
                            side="sell",
                            reason="stop_loss",
                            status="failed",
                            price=price,
                            amount=pos["position_amount"],
                            profit_pct=profit_pct,
                        )

        except Exception as exc:
            journal.log_event(
                "runtime_error",
                symbol=symbol,
                profile=symbol_profiles.get(symbol),
                regime=last_regime_label,
                reason="symbol_loop_exception",
                status="error",
                payload={"message": str(exc)},
            )
            print(f"[{symbol}] Error: {exc}")
            continue

    if snapshot_interval_minutes > 0 and (time.time() - last_snapshot_time) >= snapshot_interval_minutes * 60:
        try:
            snapshot = fetch_portfolio_snapshot(exchange)
            journal.log_portfolio_snapshot(
                total_estimated_usd=snapshot["total_estimated_usd"],
                free_usd=snapshot["free_usd"],
                invested_usd=snapshot["invested_usd"],
                positions=snapshot["positions"],
            )
            last_snapshot_time = time.time()
        except Exception as exc:
            journal.log_event(
                "warning",
                reason="portfolio_snapshot_failed",
                status="warning",
                payload={"message": str(exc)},
            )

    time.sleep(check_interval)
