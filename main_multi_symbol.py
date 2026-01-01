#!/usr/bin/env python3
"""
Multi-Symbol Trading Bot
Trades multiple symbols (ETH, BTC, etc.) simultaneously
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
profit_target_pct = float(os.getenv('TRADING_PROFIT_TARGET_PCT', '0.03'))  # 3% profit target
rsi_entry_threshold = float(os.getenv('TRADING_RSI_ENTRY', '55'))  # Stricter RSI entry (default 55)
min_trend_strength = float(os.getenv('TRADING_MIN_TREND_STRENGTH', '0.01'))  # Minimum 1% distance from EMA
spike_reversal_pct = float(os.getenv('TRADING_SPIKE_REVERSAL_PCT', '0.015'))  # Sell if price drops 1.5% from peak
min_spike_profit_pct = float(os.getenv('TRADING_MIN_SPIKE_PROFIT', '0.02'))  # Only activate spike detection after 2% profit

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
        'trailing_profit_target': 0.0  # Dynamic profit target that moves up
    }

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
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    # Calculate EMA trend (slope)
    df['ema_slope'] = df['ema_20'].diff(5)  # 5-period change in EMA
    
    # Calculate volume metrics
    df['volume_ma'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']
    
    return df.iloc[-1]

def get_position_size(current_price, symbol):
    try:
        balance = exchange.fetch_balance()
        free_usd = balance['USD']['free'] if 'USD' in balance else balance.get('USDC', {}).get('free', 0)
        
        # Divide risk across all symbols
        risk_per_symbol = risk_pct / len(symbols)
        margin_to_use = free_usd * risk_per_symbol
        position_value = margin_to_use * leverage
        amount = position_value / current_price
        return amount, margin_to_use
    except Exception as e:
        print(f"Balance Error for {symbol}: {e}")
        return 0, 0

print(f"🛡️ Active. Risking {risk_pct*100}% total ({risk_pct*100/len(symbols):.1f}% per symbol) of balance per trade.")
print(f"📉 Crash Protection: ATR Trailing Stop active (ATR × {atr_multiplier})")
print(f"💰 Profit Target: {profit_target_pct*100:.1f}% (Static) + Trailing Target (Dynamic)")
print(f"📈 Spike Detection: Sell on {spike_reversal_pct*100:.1f}% reversal from peak (after {min_spike_profit_pct*100:.1f}% profit)")
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

# --- MAIN LOOP ---
while True:
    for symbol in symbols:
        try:
            df = fetch_data(symbol)
            if df.empty:
                continue
            
            row = analyze_market(df)
            price = row['close']
            ema_20 = row['ema_20']
            atr = row['atr']
            rsi = row['rsi']
            ema_slope = row.get('ema_slope', 0)
            volume_ratio = row.get('volume_ratio', 1.0)
            
            pos = positions[symbol]
            base_currency = symbol.split('/')[0]
            
            # Calculate trend strength (distance from EMA as percentage)
            trend_strength = abs(price - ema_20) / ema_20 if ema_20 > 0 else 0
            
            # Calculate volatility (ATR as percentage of price) for asset-specific adjustments
            atr_pct = atr / price if price > 0 else 0
            
            # Adjust parameters for volatile assets (like SHIB)
            # High volatility = faster exits, tighter spike detection, wider stops
            is_volatile = atr_pct > 0.02  # 2%+ ATR indicates high volatility
            
            # Dynamic parameters based on volatility
            if is_volatile:
                # For volatile assets: faster profit capture, tighter spike detection
                dynamic_spike_reversal = 0.008  # 0.8% drop from peak (faster exit)
                dynamic_profit_target = 0.015   # 1.5% profit target (faster profit-taking)
                dynamic_atr_multiplier = 2.0    # Wider stop (ATR × 2.0)
                dynamic_min_spike_profit = 0.01  # Activate spike detection at 1% profit
                if pos['in_position']:  # Only log when in position to avoid spam
                    print(f"[{base_currency}] ⚡ Volatile asset detected (ATR: {atr_pct*100:.2f}%) - Using fast profit capture mode")
            else:
                # Standard settings for less volatile assets
                dynamic_spike_reversal = spike_reversal_pct
                dynamic_profit_target = profit_target_pct
                dynamic_atr_multiplier = atr_multiplier
                dynamic_min_spike_profit = min_spike_profit_pct
            
            print(f"[{base_currency}] Price: ${price:.2f} | RSI: {rsi:.2f} | Stop: ${pos['trailing_stop_price']:.2f} | Position: {'YES' if pos['in_position'] else 'NO'}")

            # --- BUY LOGIC ---
            if not pos['in_position']:
                # Market condition filters
                # 1. Price must be above EMA (trend filter)
                # 2. RSI must be above threshold (momentum filter)
                # 3. Trend strength must be sufficient (avoid sideways markets)
                # 4. EMA must be trending up (slope positive)
                # 5. Volume should be above average (confirmation)
                
                price_above_ema = price > ema_20
                rsi_strong = rsi > rsi_entry_threshold
                trend_strong_enough = trend_strength >= min_trend_strength
                ema_trending_up = ema_slope > 0
                volume_adequate = volume_ratio >= 1.0  # At least average volume
                
                if price_above_ema and rsi_strong and trend_strong_enough and ema_trending_up and volume_adequate:
                    amount, cost = get_position_size(price, symbol)
                    
                    if cost < min_order_size:
                        print(f"[{base_currency}] ⚠️  Order too small: ${cost:.2f} < ${min_order_size:.2f} minimum. Skipping.")
                        continue
                    
                    if amount > 0:
                        if use_limit_orders:
                            # Use limit order (maker) - lower fees (0.4% vs 0.6%)
                            limit_price = price * (1 - limit_order_offset_pct)  # Slightly below market for buy
                            print(f"[{base_currency}] 🚀 ENTER LONG (LIMIT): Buying {amount:.6f} {base_currency} at ${limit_price:.2f} (Cost: ${cost:.2f})")
                            print(f"[{base_currency}] 💰 Using limit order to save fees (maker fee: 0.4% vs taker: 0.6%)")
                            
                            if enable_trading:
                                try:
                                    # Create limit buy order
                                    order = exchange.create_limit_buy_order(symbol, amount, limit_price)
                                    print(f"[{base_currency}] ✅ Limit order placed: {order.get('id', 'N/A')}")
                                    print(f"[{base_currency}] ⏳ Waiting for order to fill at ${limit_price:.2f}")
                                    
                                    # Wait a bit and check if order filled
                                    time.sleep(5)
                                    try:
                                        order_status = exchange.fetch_order(order.get('id'), symbol)
                                        if order_status.get('status') == 'closed':
                                            print(f"[{base_currency}] ✅ Order filled!")
                                        else:
                                            print(f"[{base_currency}] ⏳ Order pending, will check next cycle")
                                    except:
                                        pass  # Order check failed, continue
                                except Exception as e:
                                    print(f"[{base_currency}] ❌ Limit order failed: {e}")
                                    # Fallback to market order if limit fails
                                    try:
                                        print(f"[{base_currency}] 🔄 Falling back to market order...")
                                        order = exchange.create_market_buy_order(symbol, cost)
                                        print(f"[{base_currency}] ✅ Market order executed: {order.get('id', 'N/A')}")
                                    except Exception as e2:
                                        print(f"[{base_currency}] ❌ Market order also failed: {e2}")
                                        continue
                            else:
                                print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
                        else:
                            # Use market order (taker) - faster but higher fees
                            print(f"[{base_currency}] 🚀 ENTER LONG: Buying {amount:.6f} {base_currency} (Cost: ${cost:.2f})")
                            
                            if enable_trading:
                                try:
                                    order = exchange.create_market_buy_order(symbol, cost)
                                    print(f"[{base_currency}] ✅ Order executed: {order.get('id', 'N/A')}")
                                except Exception as e:
                                    print(f"[{base_currency}] ❌ Order failed: {e}")
                                    continue
                            else:
                                print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
                        
                        # Use volatility-adjusted ATR multiplier for initial stop
                        initial_atr_mult = 2.0 if atr_pct > 0.02 else atr_multiplier
                        pos['trailing_stop_price'] = price - (atr * initial_atr_mult)
                        pos['position_amount'] = amount
                        pos['entry_price'] = price
                        pos['peak_price'] = price  # Initialize peak price
                        pos['trailing_profit_target'] = price * (1 + profit_target_pct)  # Initial profit target
                        pos['in_position'] = True
                        pos['breakeven_set'] = False

            # --- SAFETY LOGIC ---
            elif pos['in_position']:
                entry_price = pos['entry_price']
                profit_pct = (price - entry_price) / entry_price
                
                # Track peak price (highest price reached)
                if price > pos['peak_price']:
                    pos['peak_price'] = price
                    # Update trailing profit target: moves up as price increases
                    # Target is always at least profit_target_pct above entry, but moves up with price
                    new_target = entry_price * (1 + profit_target_pct) + (price - entry_price) * 0.5
                    if new_target > pos['trailing_profit_target']:
                        pos['trailing_profit_target'] = new_target
                
                # Calculate profit target price (volatility-adjusted)
                profit_target_price = entry_price * (1 + dynamic_profit_target)
                
                # --- SPIKE DETECTION & REVERSAL CAPTURE ---
                # If price has spiked up significantly, sell on reversal
                peak_profit_pct = (pos['peak_price'] - entry_price) / entry_price
                drop_from_peak_pct = (pos['peak_price'] - price) / pos['peak_price'] if pos['peak_price'] > 0 else 0
                
                # Use volatility-adjusted parameters
                # Only activate spike detection if we've made meaningful profit
                if peak_profit_pct >= dynamic_min_spike_profit and drop_from_peak_pct >= dynamic_spike_reversal:
                    print(f"[{base_currency}] 📉 SPIKE REVERSAL DETECTED: Price dropped {drop_from_peak_pct*100:.2f}% from peak ${pos['peak_price']:.2f}")
                    print(f"[{base_currency}] 💰 Capturing profit: {profit_pct*100:.2f}% (Peak was {peak_profit_pct*100:.2f}%)")
                    
                    if enable_trading:
                        try:
                            if use_limit_orders:
                                limit_sell_price = price * (1 + limit_order_offset_pct)
                                print(f"[{base_currency}] 💰 Using limit order to save fees")
                                order = exchange.create_limit_sell_order(symbol, pos['position_amount'], limit_sell_price)
                                print(f"[{base_currency}] ✅ Limit sell order placed: {order.get('id', 'N/A')} at ${limit_sell_price:.2f}")
                            else:
                                order = exchange.create_market_sell_order(symbol, pos['position_amount'])
                                print(f"[{base_currency}] ✅ Spike reversal sell executed: {order.get('id', 'N/A')}")
                        except Exception as e:
                            print(f"[{base_currency}] ❌ Spike reversal sell failed: {e}")
                            if use_limit_orders:
                                try:
                                    print(f"[{base_currency}] 🔄 Falling back to market order...")
                                    order = exchange.create_market_sell_order(symbol, pos['position_amount'])
                                    print(f"[{base_currency}] ✅ Market sell executed: {order.get('id', 'N/A')}")
                                except Exception as e2:
                                    print(f"[{base_currency}] ❌ Market sell also failed: {e2}")
                    else:
                        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
                    
                    pos['in_position'] = False
                    pos['trailing_stop_price'] = 0.0
                    pos['position_amount'] = 0.0
                    pos['entry_price'] = 0.0
                    pos['peak_price'] = 0.0
                    pos['trailing_profit_target'] = 0.0
                    pos['breakeven_set'] = False
                    continue
                
                # --- PROFIT TAKING (Static Target) ---
                if price >= profit_target_price:
                    print(f"[{base_currency}] 💰 PROFIT TARGET REACHED: {profit_pct*100:.2f}% profit at ${price:.2f}")
                    
                    if enable_trading:
                        try:
                            if use_limit_orders:
                                # Use limit sell order (maker) - lower fees
                                limit_sell_price = price * (1 + limit_order_offset_pct)  # Slightly above market for sell
                                print(f"[{base_currency}] 💰 Using limit order to save fees")
                                order = exchange.create_limit_sell_order(symbol, pos['position_amount'], limit_sell_price)
                                print(f"[{base_currency}] ✅ Limit sell order placed: {order.get('id', 'N/A')} at ${limit_sell_price:.2f}")
                            else:
                                order = exchange.create_market_sell_order(symbol, pos['position_amount'])
                                print(f"[{base_currency}] ✅ Profit-taking sell executed: {order.get('id', 'N/A')}")
                        except Exception as e:
                            print(f"[{base_currency}] ❌ Profit-taking sell failed: {e}")
                            # If limit order fails, try market order
                            if use_limit_orders:
                                try:
                                    print(f"[{base_currency}] 🔄 Falling back to market order...")
                                    order = exchange.create_market_sell_order(symbol, pos['position_amount'])
                                    print(f"[{base_currency}] ✅ Market sell executed: {order.get('id', 'N/A')}")
                                except Exception as e2:
                                    print(f"[{base_currency}] ❌ Market sell also failed: {e2}")
                    else:
                        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
                    
                    pos['in_position'] = False
                    pos['trailing_stop_price'] = 0.0
                    pos['position_amount'] = 0.0
                    pos['entry_price'] = 0.0
                    pos['peak_price'] = 0.0
                    pos['trailing_profit_target'] = 0.0
                    pos['breakeven_set'] = False
                    continue
                
                # --- TRAILING PROFIT TARGET (Dynamic) ---
                # Also check trailing profit target (moves up with price)
                if pos['trailing_profit_target'] > 0 and price >= pos['trailing_profit_target']:
                    print(f"[{base_currency}] 💰 TRAILING PROFIT TARGET REACHED: {profit_pct*100:.2f}% profit at ${price:.2f}")
                    
                    if enable_trading:
                        try:
                            if use_limit_orders:
                                limit_sell_price = price * (1 + limit_order_offset_pct)
                                print(f"[{base_currency}] 💰 Using limit order to save fees")
                                order = exchange.create_limit_sell_order(symbol, pos['position_amount'], limit_sell_price)
                                print(f"[{base_currency}] ✅ Limit sell order placed: {order.get('id', 'N/A')} at ${limit_sell_price:.2f}")
                            else:
                                order = exchange.create_market_sell_order(symbol, pos['position_amount'])
                                print(f"[{base_currency}] ✅ Trailing profit sell executed: {order.get('id', 'N/A')}")
                        except Exception as e:
                            print(f"[{base_currency}] ❌ Trailing profit sell failed: {e}")
                            if use_limit_orders:
                                try:
                                    print(f"[{base_currency}] 🔄 Falling back to market order...")
                                    order = exchange.create_market_sell_order(symbol, pos['position_amount'])
                                    print(f"[{base_currency}] ✅ Market sell executed: {order.get('id', 'N/A')}")
                                except Exception as e2:
                                    print(f"[{base_currency}] ❌ Market sell also failed: {e2}")
                    else:
                        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
                    
                    pos['in_position'] = False
                    pos['trailing_stop_price'] = 0.0
                    pos['position_amount'] = 0.0
                    pos['entry_price'] = 0.0
                    pos['peak_price'] = 0.0
                    pos['trailing_profit_target'] = 0.0
                    pos['breakeven_set'] = False
                    continue
                
                # --- BETTER STOP-LOSS MANAGEMENT ---
                # Raise Safety Net (trailing stop) - use volatility-adjusted multiplier
                potential_stop = price - (atr * dynamic_atr_multiplier)
                if potential_stop > pos['trailing_stop_price']:
                    pos['trailing_stop_price'] = potential_stop
                
                # Faster profit locking for volatile assets
                # Move stop to breakeven once in profit (protect capital)
                if not pos['breakeven_set'] and price > entry_price * 1.01:  # 1% profit
                    pos['trailing_stop_price'] = max(pos['trailing_stop_price'], entry_price * 1.005)  # 0.5% above entry
                    pos['breakeven_set'] = True
                    print(f"[{base_currency}] 🔒 Stop moved to breakeven at ${pos['trailing_stop_price']:.2f}")
                
                # Faster profit locking for volatile assets
                if is_volatile:
                    # For volatile assets: lock profits faster
                    if profit_pct > 0.01:  # 1% profit
                        min_profit_stop = entry_price * 1.005  # Lock 0.5% profit
                        if pos['trailing_stop_price'] < min_profit_stop:
                            pos['trailing_stop_price'] = min_profit_stop
                            print(f"[{base_currency}] 🔒 Profit locked: 0.5% at ${pos['trailing_stop_price']:.2f}")
                    
                    if profit_pct > 0.02:  # 2% profit
                        min_profit_stop = entry_price * 1.01  # Lock 1% profit
                        if pos['trailing_stop_price'] < min_profit_stop:
                            pos['trailing_stop_price'] = min_profit_stop
                            print(f"[{base_currency}] 🔒 Profit locked: 1.0% at ${pos['trailing_stop_price']:.2f}")
                else:
                    # Standard profit locking for less volatile assets
                    if profit_pct > 0.02:  # More than 2% profit
                        # Move stop to lock in at least 1.5% profit
                        min_profit_stop = entry_price * 1.015
                        if pos['trailing_stop_price'] < min_profit_stop:
                            pos['trailing_stop_price'] = min_profit_stop
                    
                    if profit_pct > 0.05:  # More than 5% profit
                        # Lock in at least 3% profit
                        min_profit_stop = entry_price * 1.03
                        if pos['trailing_stop_price'] < min_profit_stop:
                            pos['trailing_stop_price'] = min_profit_stop
                
                # Crash Protection Trigger
                if price <= pos['trailing_stop_price']:
                    print(f"[{base_currency}] 🚨 STOP LOSS TRIGGERED at ${price:.2f} (Entry: ${entry_price:.2f}, P/L: {(profit_pct*100):.2f}%)")
                    
                    if enable_trading:
                        try:
                            # For stop-loss, use market order for immediate execution (safety first)
                            # Limit orders might not fill fast enough during crashes
                            order = exchange.create_market_sell_order(symbol, pos['position_amount'])
                            print(f"[{base_currency}] ✅ Stop-loss sell executed: {order.get('id', 'N/A')}")
                        except Exception as e:
                            print(f"[{base_currency}] ❌ Sell order failed: {e}")
                    else:
                        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
                    
                    pos['in_position'] = False
                    pos['trailing_stop_price'] = 0.0
                    pos['position_amount'] = 0.0
                    pos['entry_price'] = 0.0
                    pos['peak_price'] = 0.0
                    pos['trailing_profit_target'] = 0.0
                    pos['breakeven_set'] = False
        
        except Exception as e:
            print(f"[{symbol}] Error: {e}")
            continue
    
    time.sleep(check_interval)

