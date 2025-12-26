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
positions = {}  # {symbol: {'in_position': bool, 'stop': float, 'amount': float}}

# Initialize positions for all symbols
for symbol in symbols:
    positions[symbol] = {
        'in_position': False,
        'trailing_stop_price': 0.0,
        'position_amount': 0.0
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
print(f"📉 Crash Protection: ATR Trailing Stop active.")
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
            
            pos = positions[symbol]
            base_currency = symbol.split('/')[0]
            
            print(f"[{base_currency}] Price: ${price:.2f} | RSI: {rsi:.2f} | Stop: ${pos['trailing_stop_price']:.2f} | Position: {'YES' if pos['in_position'] else 'NO'}")

            # --- BUY LOGIC ---
            if not pos['in_position']:
                if price > ema_20 and rsi > 50:
                    amount, cost = get_position_size(price, symbol)
                    
                    if cost < min_order_size:
                        print(f"[{base_currency}] ⚠️  Order too small: ${cost:.2f} < ${min_order_size:.2f} minimum. Skipping.")
                        continue
                    
                    if amount > 0:
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
                        
                        pos['trailing_stop_price'] = price - (atr * atr_multiplier)
                        pos['position_amount'] = amount
                        pos['in_position'] = True

            # --- SAFETY LOGIC ---
            elif pos['in_position']:
                # Raise Safety Net
                potential_stop = price - (atr * atr_multiplier)
                if potential_stop > pos['trailing_stop_price']:
                    pos['trailing_stop_price'] = potential_stop
                
                # Crash Protection Trigger
                if price <= pos['trailing_stop_price']:
                    print(f"[{base_currency}] 🚨 STOP LOSS TRIGGERED at ${price:.2f}")
                    
                    if enable_trading:
                        try:
                            order = exchange.create_market_sell_order(symbol, pos['position_amount'])
                            print(f"[{base_currency}] ✅ Sell order executed: {order.get('id', 'N/A')}")
                        except Exception as e:
                            print(f"[{base_currency}] ❌ Sell order failed: {e}")
                    else:
                        print(f"[{base_currency}]    (Simulated - use --execute to enable real trading)")
                    
                    pos['in_position'] = False
                    pos['trailing_stop_price'] = 0.0
                    pos['position_amount'] = 0.0
        
        except Exception as e:
            print(f"[{symbol}] Error: {e}")
            continue
    
    time.sleep(check_interval)

