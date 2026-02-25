#!/usr/bin/env python3
"""
Multi-Symbol Trading Bot
Trades multiple symbols (ETH, BTC, etc.) simultaneously
with dynamic trend-adaptive profit targets and crash protection
"""
import ccxt
import pandas as pd
import pandas_ta_classic as ta
import time
import sys
import argparse
import os
from dotenv import load_dotenv
from datetime import datetime

# Load base .env file first
load_dotenv()

# --- CONFIGURATION ---
# Read trading symbols from environment (comma-separated)
symbols_str = os.getenv('TRADING_SYMBOLS', 'ETH/USD,BTC/USD')  # Default: ETH and BTC
symbols = [s.strip() for s in symbols_str.split(',')]  # Parse comma-separated list

timeframe = os.getenv('TRADING_TIMEFRAME', '5m')
leverage = int(os.getenv('TRADING_LEVERAGE', '5'))
risk_pct = float(os.getenv('TRADING_RISK_PCT', '0.20'))
atr_multiplier = float(os.getenv('TRADING_ATR_MULTIPLIER', '1.5'))
check_interval = int(os.getenv('TRADING_CHECK_INTERVAL', '60'))
min_order_size = float(os.getenv('TRADING_MIN_ORDER_SIZE', '1.00'))
profit_target_pct = float(os.getenv('TRADING_PROFIT_TARGET_PCT', '0.035'))  # 3.5% profit target (increased to capture more profit in uptrends)
rsi_entry_threshold = float(os.getenv('TRADING_RSI_ENTRY', '55'))  # Stricter RSI entry (default 55)
min_trend_strength = float(os.getenv('TRADING_MIN_TREND_STRENGTH', '0.01'))  # Minimum 1% distance from EMA
spike_reversal_pct = float(os.getenv('TRADING_SPIKE_REVERSAL_PCT', '0.02'))  # Sell if price drops 2.0% from peak (wider to avoid premature exits)
min_spike_profit_pct = float(os.getenv('TRADING_MIN_SPIKE_PROFIT', '0.02'))  # Activate spike detection after 2.0% profit (let moves develop)
cooldown_minutes = int(os.getenv('TRADING_COOLDOWN_MINUTES', '5'))  # Cooldown period after exit (avoid quick round trips)

# --- API KEYS ---
api_key = os.getenv('COINBASE_API_KEY', 'YOUR_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET', 'YOUR_SECRET_KEY')
api_passphrase = os.getenv('COINBASE_API_PASSPHRASE', '')

# Parse command line arguments
parser = argparse.ArgumentParser(description='Multi-Symbol Coinbase Trading Bot')
parser.add_argument('--test', action='store_true', help='Run in test mode')
parser.add_argument('--sandbox', action='store_true', help='Use sandbox environment')
parser.add_argument('--execute', action='store_true', help='Enable actual trade execution')
args = parser.parse_args()

use_sandbox = args.sandbox or args.test
enable_trading = args.execute

# Load environment-specific .env file if it exists
if use_sandbox and os.path.exists('.env.sandbox'):
    load_dotenv('.env.sandbox', override=True)
elif not use_sandbox and os.path.exists('.env.production'):
    load_dotenv('.env.production', override=True)

# Re-read API keys after loading environment-specific files
api_key = os.getenv('COINBASE_API_KEY', 'YOUR_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET', 'YOUR_SECRET_KEY')
api_passphrase = os.getenv('COINBASE_API_PASSPHRASE', '')

# Re-read symbols after loading environment-specific files
symbols_str = os.getenv('TRADING_SYMBOLS', 'ETH/USD,BTC/USD')
symbols = [s.strip() for s in symbols_str.split(',')]

# Re-read limit order settings
use_limit_orders = os.getenv('TRADING_USE_LIMIT_ORDERS', 'false').lower() == 'true'
limit_order_offset_pct = float(os.getenv('TRADING_LIMIT_ORDER_OFFSET', '0.001'))  # 0.1% offset

# Convert literal \n strings to actual newlines
if api_secret and '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

if args.test:
    print("🧪 TEST MODE ENABLED")
    print("=" * 60)

# API SETUP
try:
    if use_sandbox:
        ExchangeClass = ccxt.coinbaseexchange or ccxt.coinbaseadvanced
    else:
        ExchangeClass = ccxt.coinbaseadvanced or ccxt.coinbaseexchange
    
    exchange_config = {
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'sandbox': use_sandbox,
        'options': {
            'createMarketBuyOrderRequiresPrice': False,
        },
    }
    
    if use_sandbox:
        exchange_config['password'] = api_passphrase if api_passphrase else ''
    elif api_passphrase:
        exchange_config['password'] = api_passphrase
    
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
except Exception as e:
    print(f"❌ Connection Error: {e}")
    sys.exit()

# Try setting leverage
try:
    for symbol in symbols:
        exchange.set_leverage(leverage, symbol)
    print(f"⚡ Leverage set to {leverage}x for all symbols.")
except Exception as e:
    print(f"⚠️  Could not set leverage automatically: {e}")

# Position tracking - one per symbol
positions = {}  # {symbol: {'in_position': bool, 'stop': float, 'amount': float, 'entry_price': float}}

# Initialize positions for all symbols
for symbol in symbols:
    positions[symbol] = {
        'in_position': False,
        'trailing_stop_price': 0.0,
        'position_amount': 0.0,
        'entry_price': 0.0,
        'breakeven_set': False,  # Track if stop moved to breakeven
        'peak_price': 0.0,  # Track highest price reached (for spike detection)
        'trailing_profit_target': 0.0,  # Dynamic profit target that moves up
        'last_exit_time': 0  # Track last exit time for cooldown
    }

portfolio_peak_value = 0.0
portfolio_total_unrealized_pnl = 0.0

def fetch_data(symbol):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        print(f"Data Error for {symbol}: {e}")
        return pd.DataFrame()

def analyze_market(df):
    df['ema_20'] = ta.ema(df['close'], length=20)
    df['ema_50'] = ta.ema(df['close'], length=50)
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    df['ema_slope'] = df['ema_20'].diff(5)
    df['ema_50_slope'] = df['ema_50'].diff(5)

    df['volume_ma'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']

    df['recent_high_5'] = df['high'].rolling(5).max()
    df['red_candle'] = (df['close'] < df['open']).astype(int)
    df['consec_red'] = df['red_candle'].rolling(5).sum()

    return df

def classify_trend(rsi, ema_slope, trend_strength, volume_ratio, price, ema_20, ema_50):
    """Classify trend as 'strong', 'normal', or 'weak' for adaptive targets."""
    score = 0

    if rsi > 70:
        score += 2
    elif rsi > 60:
        score += 1

    if ema_slope > 0:
        score += 1
    if ema_50 is not None and ema_50 > 0 and price > ema_50:
        score += 1

    if trend_strength > 0.02:
        score += 1
    elif trend_strength > 0.01:
        score += 0.5

    if volume_ratio > 1.5:
        score += 1
    elif volume_ratio > 1.0:
        score += 0.5

    if score >= 4.5:
        return 'strong'
    elif score >= 2.5:
        return 'normal'
    return 'weak'

def detect_crash(df, current_price):
    """Detect crash conditions from recent price action and volume."""
    row = df.iloc[-1]
    if len(df) < 5:
        return None

    recent_high = df['high'].tail(5).max()
    decline_pct = (recent_high - current_price) / recent_high if recent_high > 0 else 0

    avg_vol = df['volume_ma'].iloc[-1]
    recent_vol = df['volume'].tail(3).mean()
    volume_spike = recent_vol / avg_vol if avg_vol and avg_vol > 0 else 1.0

    consec_red = int(row.get('consec_red', 0))

    if decline_pct > 0.05 and volume_spike > 2.0:
        return 'severe'
    if decline_pct > 0.03 and volume_spike > 1.5:
        return 'moderate'
    if decline_pct > 0.04 and consec_red >= 4:
        return 'moderate'
    if decline_pct > 0.03:
        return 'mild'
    return None

def get_dynamic_params(trend, is_volatile):
    """Return profit target, spike reversal, min spike profit, and ATR mult based on trend."""
    if is_volatile:
        params = {
            'strong': {'profit_target': 0.03, 'spike_reversal': 0.018, 'min_spike_profit': 0.02, 'atr_mult': 2.5},
            'normal': {'profit_target': 0.02, 'spike_reversal': 0.012, 'min_spike_profit': 0.015, 'atr_mult': 2.0},
            'weak':   {'profit_target': 0.015, 'spike_reversal': 0.01, 'min_spike_profit': 0.01, 'atr_mult': 1.8},
        }
    else:
        params = {
            'strong': {'profit_target': 0.055, 'spike_reversal': 0.03, 'min_spike_profit': 0.025, 'atr_mult': 2.0},
            'normal': {'profit_target': 0.035, 'spike_reversal': 0.02, 'min_spike_profit': 0.02, 'atr_mult': 1.5},
            'weak':   {'profit_target': 0.025, 'spike_reversal': 0.015, 'min_spike_profit': 0.015, 'atr_mult': 1.5},
        }
    return params.get(trend, params['normal'])

def get_position_size(current_price, symbol):
    try:
        balance = exchange.fetch_balance()
        free_usd = balance['USD']['free'] if 'USD' in balance else balance.get('USDC', {}).get('free', 0)

        risk_per_symbol = risk_pct / len(symbols)
        margin_to_use = free_usd * risk_per_symbol
        position_value = margin_to_use * leverage
        amount = position_value / current_price
        return amount, margin_to_use
    except Exception as e:
        print(f"Balance Error for {symbol}: {e}")
        return 0, 0

print(f"🛡️ Active. Risking {risk_pct*100}% total ({risk_pct*100/len(symbols):.1f}% per symbol) of balance per trade.")
print(f"📉 Crash Protection: ATR Trailing Stop + Rapid Decline Detection + Circuit Breaker")
print(f"💰 Dynamic Profit Targets: Adapts to trend strength (strong/normal/weak)")
print(f"   Strong trend: 5.5% target (BTC/ETH/LINK), 3.0% (SHIB)")
print(f"   Normal trend: 3.5% target (BTC/ETH/LINK), 2.0% (SHIB)")
print(f"   Weak trend:   2.5% target (BTC/ETH/LINK), 1.5% (SHIB)")
print(f"📈 Dynamic Spike Detection: Wider in uptrends, tighter in weak trends")
print(f"🚨 Crash Detection: Emergency exit on severe/moderate market drops")
print(f"🔒 Circuit Breaker: Halt trading if total drawdown exceeds 8%")
print(f"⏸️  Cooldown Period: {cooldown_minutes} minutes after exit")
print(f"📊 Entry Conditions: RSI > {rsi_entry_threshold}, Trend strength > {min_trend_strength*100:.1f}%, EMA trending up, Volume adequate")
if use_limit_orders:
    print(f"💵 Order Type: LIMIT ORDERS (Maker fees: 0.4% - saves 33% vs market orders)")
else:
    print(f"💵 Order Type: MARKET ORDERS (Taker fees: 0.6%)")
print(f"⏱️  Check Interval: {check_interval} seconds")
if enable_trading:
    print(f"⚠️  TRADING ENABLED - Real orders will be executed!")
else:
    print(f"ℹ️  Trading disabled - orders are simulated (use --execute to enable)")

CIRCUIT_BREAKER_DRAWDOWN = 0.08
circuit_breaker_triggered = False

def execute_sell(symbol, amount, base_currency, reason, use_market=False):
    """Execute a sell order with limit/market fallback. Returns True on success."""
    force_market = use_market or reason in ('CRASH_EXIT', 'CIRCUIT_BREAKER', 'STOP_LOSS')
    if enable_trading:
        try:
            if use_limit_orders and not force_market:
                limit_sell_price = exchange.fetch_ticker(symbol)['last'] * (1 + limit_order_offset_pct)
                order = exchange.create_limit_sell_order(symbol, amount, limit_sell_price)
                print(f"[{base_currency}] ✅ {reason} limit sell placed: {order.get('id', 'N/A')} at ${limit_sell_price:.2f}")
            else:
                order = exchange.create_market_sell_order(symbol, amount)
                print(f"[{base_currency}] ✅ {reason} market sell executed: {order.get('id', 'N/A')}")
            return True
        except Exception as e:
            print(f"[{base_currency}] ❌ {reason} sell failed: {e}")
            if use_limit_orders and not force_market:
                try:
                    order = exchange.create_market_sell_order(symbol, amount)
                    print(f"[{base_currency}] ✅ Fallback market sell executed: {order.get('id', 'N/A')}")
                    return True
                except Exception as e2:
                    print(f"[{base_currency}] ❌ Fallback also failed: {e2}")
        return False
    else:
        print(f"[{base_currency}]    (Simulated {reason} - use --execute to enable real trading)")
        return True

def reset_position(pos):
    """Reset a position to default state after exit."""
    pos['in_position'] = False
    pos['trailing_stop_price'] = 0.0
    pos['position_amount'] = 0.0
    pos['entry_price'] = 0.0
    pos['peak_price'] = 0.0
    pos['trailing_profit_target'] = 0.0
    pos['breakeven_set'] = False
    pos['last_exit_time'] = time.time()

# --- MAIN LOOP ---
while True:
    # --- CIRCUIT BREAKER CHECK ---
    if circuit_breaker_triggered:
        has_positions = any(positions[s]['in_position'] for s in symbols)
        if not has_positions:
            print("🚨 CIRCUIT BREAKER: All positions closed. Waiting 10 minutes before resuming...")
            time.sleep(600)
            circuit_breaker_triggered = False
            portfolio_peak_value = 0.0
            print("🔄 Circuit breaker reset. Resuming trading.")
        else:
            time.sleep(check_interval)
            continue

    # --- PORTFOLIO-WIDE DRAWDOWN TRACKING ---
    total_unrealized = 0.0
    total_position_value = 0.0
    for symbol in symbols:
        pos = positions[symbol]
        if pos['in_position'] and pos['entry_price'] > 0:
            try:
                ticker = exchange.fetch_ticker(symbol)
                cur_price = ticker['last']
                pnl = (cur_price - pos['entry_price']) / pos['entry_price']
                pos_value = pos['position_amount'] * pos['entry_price']
                total_unrealized += pnl * pos_value
                total_position_value += pos_value
            except:
                pass

    if total_position_value > 0:
        portfolio_pnl_pct = total_unrealized / total_position_value
        if portfolio_pnl_pct < -CIRCUIT_BREAKER_DRAWDOWN:
            print(f"🚨🚨 CIRCUIT BREAKER TRIGGERED: Portfolio drawdown {portfolio_pnl_pct*100:.2f}% exceeds -{CIRCUIT_BREAKER_DRAWDOWN*100}% limit")
            for symbol in symbols:
                pos = positions[symbol]
                if pos['in_position']:
                    base_currency = symbol.split('/')[0]
                    print(f"[{base_currency}] 🚨 EMERGENCY EXIT - Circuit breaker")
                    execute_sell(symbol, pos['position_amount'], base_currency, 'CIRCUIT_BREAKER', use_market=True)
                    reset_position(pos)
            circuit_breaker_triggered = True
            continue

    for symbol in symbols:
        try:
            df = fetch_data(symbol)
            if df.empty:
                continue

            df = analyze_market(df)
            row = df.iloc[-1]
            price = row['close']
            ema_20 = row['ema_20']
            ema_50 = row.get('ema_50', None)
            atr = row['atr']
            rsi = row['rsi']
            ema_slope = row.get('ema_slope', 0)
            volume_ratio = row.get('volume_ratio', 1.0)

            pos = positions[symbol]
            base_currency = symbol.split('/')[0]

            trend_strength = abs(price - ema_20) / ema_20 if ema_20 > 0 else 0
            atr_pct = atr / price if price > 0 else 0
            is_volatile = atr_pct > 0.02

            # Classify trend strength for adaptive parameters
            trend = classify_trend(rsi, ema_slope, trend_strength, volume_ratio, price, ema_20, ema_50)
            dparams = get_dynamic_params(trend, is_volatile)

            dynamic_profit_target = dparams['profit_target']
            dynamic_spike_reversal = dparams['spike_reversal']
            dynamic_min_spike_profit = dparams['min_spike_profit']
            dynamic_atr_multiplier = dparams['atr_mult']

            # --- CRASH DETECTION ---
            crash_level = detect_crash(df, price)

            if crash_level and pos['in_position']:
                profit_pct_now = (price - pos['entry_price']) / pos['entry_price']
                if crash_level == 'severe':
                    print(f"[{base_currency}] 🚨🚨 SEVERE CRASH DETECTED - Emergency exit! (P/L: {profit_pct_now*100:.2f}%)")
                    execute_sell(symbol, pos['position_amount'], base_currency, 'CRASH_EXIT', use_market=True)
                    reset_position(pos)
                    continue
                elif crash_level == 'moderate':
                    # Tighten stop aggressively during moderate crash
                    emergency_stop = price - (atr * 0.5)
                    if emergency_stop > pos['trailing_stop_price']:
                        pos['trailing_stop_price'] = emergency_stop
                        print(f"[{base_currency}] ⚠️ MODERATE CRASH - Stop tightened to ${emergency_stop:.2f}")
                    elif profit_pct_now < -0.01:
                        print(f"[{base_currency}] 🚨 MODERATE CRASH + LOSING - Emergency exit! (P/L: {profit_pct_now*100:.2f}%)")
                        execute_sell(symbol, pos['position_amount'], base_currency, 'CRASH_EXIT', use_market=True)
                        reset_position(pos)
                        continue

            trend_label = f"{'V-' if is_volatile else ''}{trend.upper()}"
            print(f"[{base_currency}] Price: ${price:.2f} | RSI: {rsi:.2f} | Trend: {trend_label} | Target: {dynamic_profit_target*100:.1f}% | Stop: ${pos['trailing_stop_price']:.2f} | Pos: {'YES' if pos['in_position'] else 'NO'}")

            # --- BUY LOGIC ---
            if not pos['in_position']:
                current_time = time.time()
                time_since_exit = current_time - pos['last_exit_time'] if pos['last_exit_time'] > 0 else cooldown_minutes * 60 + 1

                if time_since_exit < cooldown_minutes * 60:
                    continue

                # Don't enter during crash conditions
                if crash_level in ('severe', 'moderate'):
                    print(f"[{base_currency}] ⚠️ Crash detected ({crash_level}), skipping entry")
                    continue

                # Don't enter in weak trends -- wait for better conditions
                if trend == 'weak':
                    continue

                price_above_ema = price > ema_20
                rsi_strong = rsi > rsi_entry_threshold
                trend_strong_enough = trend_strength >= min_trend_strength
                ema_trending_up = ema_slope > 0
                volume_adequate = volume_ratio >= 1.0

                if price_above_ema and rsi_strong and trend_strong_enough and ema_trending_up and volume_adequate:
                    amount, cost = get_position_size(price, symbol)

                    if cost < min_order_size:
                        print(f"[{base_currency}] ⚠️  Order too small: ${cost:.2f} < ${min_order_size:.2f} minimum. Skipping.")
                        continue

                    if amount > 0:
                        if use_limit_orders:
                            limit_price = price * (1 - limit_order_offset_pct)
                            print(f"[{base_currency}] 🚀 ENTER LONG (LIMIT) [{trend.upper()}]: Buying {amount:.6f} {base_currency} at ${limit_price:.2f} (Cost: ${cost:.2f})")

                            if enable_trading:
                                try:
                                    order = exchange.create_limit_buy_order(symbol, amount, limit_price)
                                    print(f"[{base_currency}] ✅ Limit order placed: {order.get('id', 'N/A')}")
                                    time.sleep(5)
                                    try:
                                        order_status = exchange.fetch_order(order.get('id'), symbol)
                                        if order_status.get('status') == 'closed':
                                            print(f"[{base_currency}] ✅ Order filled!")
                                        else:
                                            print(f"[{base_currency}] ⏳ Order pending, will check next cycle")
                                    except:
                                        pass
                                except Exception as e:
                                    print(f"[{base_currency}] ❌ Limit order failed: {e}")
                                    try:
                                        order = exchange.create_market_buy_order(symbol, cost)
                                        print(f"[{base_currency}] ✅ Fallback market order: {order.get('id', 'N/A')}")
                                    except Exception as e2:
                                        print(f"[{base_currency}] ❌ Market order also failed: {e2}")
                                        continue
                            else:
                                print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
                        else:
                            print(f"[{base_currency}] 🚀 ENTER LONG [{trend.upper()}]: Buying {amount:.6f} {base_currency} (Cost: ${cost:.2f})")

                            if enable_trading:
                                try:
                                    order = exchange.create_market_buy_order(symbol, cost)
                                    print(f"[{base_currency}] ✅ Order executed: {order.get('id', 'N/A')}")
                                except Exception as e:
                                    print(f"[{base_currency}] ❌ Order failed: {e}")
                                    continue
                            else:
                                print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")

                        pos['trailing_stop_price'] = price - (atr * dynamic_atr_multiplier)
                        pos['position_amount'] = amount
                        pos['entry_price'] = price
                        pos['peak_price'] = price
                        pos['trailing_profit_target'] = price * (1 + dynamic_profit_target)
                        pos['in_position'] = True
                        pos['breakeven_set'] = False

            # --- SAFETY LOGIC ---
            elif pos['in_position']:
                entry_price = pos['entry_price']
                profit_pct = (price - entry_price) / entry_price

                # Track peak price
                if price > pos['peak_price']:
                    pos['peak_price'] = price
                    trailing_rate = 0.7 if trend == 'strong' else 0.6
                    new_target = entry_price * (1 + dynamic_profit_target) + (price - entry_price) * trailing_rate
                    if new_target > pos['trailing_profit_target']:
                        pos['trailing_profit_target'] = new_target

                profit_target_price = entry_price * (1 + dynamic_profit_target)

                # --- RSI DIVERGENCE EXIT (momentum loss) ---
                if rsi < 30 and profit_pct < 0:
                    print(f"[{base_currency}] 📉 RSI CRASH SIGNAL (RSI: {rsi:.1f}) - Emergency exit (P/L: {profit_pct*100:.2f}%)")
                    execute_sell(symbol, pos['position_amount'], base_currency, 'RSI_CRASH', use_market=True)
                    reset_position(pos)
                    continue

                # --- BELOW-EMA EMERGENCY TIGHTENING ---
                if price < ema_20 and profit_pct < 0:
                    emergency_stop = max(pos['trailing_stop_price'], price - (atr * 0.75))
                    if emergency_stop > pos['trailing_stop_price']:
                        pos['trailing_stop_price'] = emergency_stop
                        print(f"[{base_currency}] ⚠️ Price below EMA while losing - stop tightened to ${emergency_stop:.2f}")

                # --- SPIKE DETECTION & REVERSAL CAPTURE ---
                peak_profit_pct = (pos['peak_price'] - entry_price) / entry_price
                drop_from_peak_pct = (pos['peak_price'] - price) / pos['peak_price'] if pos['peak_price'] > 0 else 0

                if peak_profit_pct >= dynamic_min_spike_profit and drop_from_peak_pct >= dynamic_spike_reversal:
                    print(f"[{base_currency}] 📉 SPIKE REVERSAL: Dropped {drop_from_peak_pct*100:.2f}% from peak ${pos['peak_price']:.2f}")
                    print(f"[{base_currency}] 💰 Capturing profit: {profit_pct*100:.2f}% (Peak was {peak_profit_pct*100:.2f}%)")
                    execute_sell(symbol, pos['position_amount'], base_currency, 'SPIKE_REVERSAL')
                    reset_position(pos)
                    continue

                # --- PROFIT TAKING (Dynamic Target) ---
                if price >= profit_target_price:
                    print(f"[{base_currency}] 💰 PROFIT TARGET [{trend.upper()}] REACHED: {profit_pct*100:.2f}% at ${price:.2f}")
                    execute_sell(symbol, pos['position_amount'], base_currency, 'PROFIT_TARGET')
                    reset_position(pos)
                    continue

                # --- TRAILING PROFIT TARGET ---
                if pos['trailing_profit_target'] > 0 and price >= pos['trailing_profit_target']:
                    print(f"[{base_currency}] 💰 TRAILING PROFIT TARGET: {profit_pct*100:.2f}% at ${price:.2f}")
                    execute_sell(symbol, pos['position_amount'], base_currency, 'TRAILING_TARGET')
                    reset_position(pos)
                    continue

                # --- TRAILING STOP MANAGEMENT ---
                potential_stop = price - (atr * dynamic_atr_multiplier)
                if potential_stop > pos['trailing_stop_price']:
                    pos['trailing_stop_price'] = potential_stop

                # Breakeven protection
                if not pos['breakeven_set'] and price > entry_price * 1.01:
                    pos['trailing_stop_price'] = max(pos['trailing_stop_price'], entry_price * 1.005)
                    pos['breakeven_set'] = True
                    print(f"[{base_currency}] 🔒 Stop moved to breakeven at ${pos['trailing_stop_price']:.2f}")

                # Progressive profit locking (adapts to trend strength)
                if is_volatile:
                    if profit_pct > 0.01:
                        lock = entry_price * 1.005
                        if pos['trailing_stop_price'] < lock:
                            pos['trailing_stop_price'] = lock
                            print(f"[{base_currency}] 🔒 Locked 0.5% at ${lock:.2f}")
                    if profit_pct > 0.02:
                        lock = entry_price * 1.01
                        if pos['trailing_stop_price'] < lock:
                            pos['trailing_stop_price'] = lock
                            print(f"[{base_currency}] 🔒 Locked 1.0% at ${lock:.2f}")
                else:
                    if profit_pct > 0.01:
                        lock = entry_price * 1.005
                        if pos['trailing_stop_price'] < lock:
                            pos['trailing_stop_price'] = lock
                            print(f"[{base_currency}] 🔒 Locked 0.5% at ${lock:.2f}")
                    if profit_pct > 0.02:
                        lock = entry_price * 1.01
                        if pos['trailing_stop_price'] < lock:
                            pos['trailing_stop_price'] = lock
                            print(f"[{base_currency}] 🔒 Locked 1.0% at ${lock:.2f}")
                    if profit_pct > 0.03:
                        lock = entry_price * 1.02
                        if pos['trailing_stop_price'] < lock:
                            pos['trailing_stop_price'] = lock
                            print(f"[{base_currency}] 🔒 Locked 2.0% at ${lock:.2f}")
                    if profit_pct > 0.05:
                        lock = entry_price * 1.035
                        if pos['trailing_stop_price'] < lock:
                            pos['trailing_stop_price'] = lock
                            print(f"[{base_currency}] 🔒 Locked 3.5% at ${lock:.2f}")

                # --- STOP LOSS TRIGGER ---
                if price <= pos['trailing_stop_price']:
                    print(f"[{base_currency}] 🚨 STOP LOSS at ${price:.2f} (Entry: ${entry_price:.2f}, P/L: {profit_pct*100:.2f}%)")
                    execute_sell(symbol, pos['position_amount'], base_currency, 'STOP_LOSS', use_market=True)
                    reset_position(pos)

        except Exception as e:
            print(f"[{symbol}] Error: {e}")
            continue

    time.sleep(check_interval)

