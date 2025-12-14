import ccxt
import pandas as pd
import pandas_ta_classic as ta
import time
import sys
import argparse
import os
from dotenv import load_dotenv

# Load base .env file first (for shared config)
load_dotenv()

# --- CONFIGURATION ---
# Read from environment variables, fallback to defaults
symbol = os.getenv('TRADING_SYMBOL', 'ETH/USD')       # Coinbase uses USD, not USDT
timeframe = os.getenv('TRADING_TIMEFRAME', '5m')       # Fast timeframe
leverage = int(os.getenv('TRADING_LEVERAGE', '5'))     # 5x Leverage (for futures/advanced trade)
risk_pct = float(os.getenv('TRADING_RISK_PCT', '0.20'))  # Invest 20% of account balance
atr_multiplier = float(os.getenv('TRADING_ATR_MULTIPLIER', '1.5'))  # 1.5x Volatility Safety Net

# --- API KEYS ---
# Read from environment variables (recommended) or use hardcoded values as fallback
# Priority: Environment variables > .env file > hardcoded defaults
api_key = os.getenv('COINBASE_API_KEY', 'YOUR_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET', 'YOUR_SECRET_KEY')
api_passphrase = os.getenv('COINBASE_API_PASSPHRASE', 'YOUR_PASSPHRASE')  # Coinbase Pro passphrase

# Parse command line arguments
parser = argparse.ArgumentParser(description='Coinbase Trading Bot')
parser.add_argument('--test', action='store_true', help='Run in test mode (single iteration, verbose output)')
parser.add_argument('--sandbox', action='store_true', help='Use sandbox environment')
parser.add_argument('--execute', action='store_true', help='Enable actual trade execution (use with caution!)')
args = parser.parse_args()

# Determine if we should use sandbox
use_sandbox = args.sandbox or args.test  # Auto-enable sandbox in test mode
enable_trading = args.execute

# Load environment-specific .env file if it exists (overrides base .env)
# This allows separate API keys for sandbox vs production
# Priority: .env.sandbox/.env.production > .env > hardcoded defaults
if use_sandbox and os.path.exists('.env.sandbox'):
    load_dotenv('.env.sandbox', override=True)
elif not use_sandbox and os.path.exists('.env.production'):
    load_dotenv('.env.production', override=True)

if args.test:
    print("🧪 TEST MODE ENABLED")
    print("=" * 60)

# API SETUP
try:
    exchange = ccxt.coinbasepro({
        'apiKey': api_key,
        'secret': api_secret,
        'password': api_passphrase,  # Coinbase Pro requires passphrase
        'enableRateLimit': True,
        'sandbox': use_sandbox,
    })
    # Check connection
    print(f"🔌 Connecting to {'SANDBOX' if use_sandbox else 'PRODUCTION'}...")
    exchange.load_markets()
    print("✅ Connected to Coinbase Pro successfully.")
    
    if args.test:
        print(f"📊 Loaded {len(exchange.markets)} markets")
        if symbol in exchange.markets:
            market_info = exchange.markets[symbol]
            print(f"✅ Symbol {symbol} is available")
            print(f"   Market info: {market_info.get('info', {}).get('display_name', 'N/A')}")
        else:
            print(f"⚠️  Symbol {symbol} not found in available markets")
            print("   Available ETH pairs:", [m for m in exchange.markets.keys() if 'ETH' in m][:10])
except Exception as e:
    print(f"❌ Connection Error: {e}")
    print("Note: Coinbase Pro requires API Key, Secret, and Passphrase.")
    sys.exit()

# Try setting leverage (Coinbase Advanced Trade supports futures)
try:
    # Coinbase Advanced Trade futures leverage setting
    exchange.set_leverage(leverage, symbol)
    print(f"⚡ Leverage set to {leverage}x.")
except Exception as e:
    print(f"⚠️  Could not set leverage automatically: {e}")
    print("⚠️  Ensure leverage is set manually in Coinbase Advanced Trade, or use spot trading.")

# Define core functions (needed for testing)
def fetch_data():
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        print(f"Data Error: {e}")
        return pd.DataFrame()

def analyze_market(df):
    df['ema_20'] = ta.ema(df['close'], length=20)
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    return df.iloc[-1]

# Test balance fetching
def test_balance():
    """Test fetching account balance"""
    try:
        print("\n💰 Testing Balance Fetch...")
        balance = exchange.fetch_balance()
        print("✅ Balance fetched successfully")
        
        # Show USD/USDC balance
        if 'USD' in balance:
            usd_balance = balance['USD']
            print(f"   USD - Free: ${usd_balance.get('free', 0):.2f}, Used: ${usd_balance.get('used', 0):.2f}, Total: ${usd_balance.get('total', 0):.2f}")
        
        if 'USDC' in balance:
            usdc_balance = balance['USDC']
            print(f"   USDC - Free: ${usdc_balance.get('free', 0):.2f}, Used: ${usdc_balance.get('used', 0):.2f}, Total: ${usdc_balance.get('total', 0):.2f}")
        
        return balance
    except Exception as e:
        print(f"❌ Balance Error: {e}")
        return None

# Test trade execution (dry run or actual)
def test_trade_execution():
    """Test trade execution capability"""
    try:
        print("\n🧪 Testing Trade Execution...")
        
        # Fetch current price
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker['last']
        print(f"   Current {symbol} price: ${current_price:.2f}")
        
        # Calculate position size
        balance = exchange.fetch_balance()
        free_usd = balance['USD']['free'] if 'USD' in balance else balance.get('USDC', {}).get('free', 0)
        
        if free_usd == 0:
            print("⚠️  No USD/USDC balance available for testing")
            return False
        
        margin_to_use = free_usd * risk_pct
        position_value = margin_to_use * leverage
        amount_eth = position_value / current_price
        
        print(f"   Calculated position size: {amount_eth:.6f} {symbol.split('/')[0]}")
        print(f"   Margin to use: ${margin_to_use:.2f}")
        print(f"   Position value (with {leverage}x leverage): ${position_value:.2f}")
        
        if enable_trading:
            print(f"\n⚠️  EXECUTING TEST TRADE (Sandbox: {use_sandbox})...")
            print(f"   Order: BUY {amount_eth:.6f} {symbol} at market price")
            
            # Execute test buy order
            try:
                order = exchange.create_market_buy_order(symbol, amount_eth)
                print(f"✅ Order executed successfully!")
                print(f"   Order ID: {order.get('id', 'N/A')}")
                print(f"   Status: {order.get('status', 'N/A')}")
                print(f"   Amount: {order.get('amount', 'N/A')}")
                print(f"   Price: ${order.get('price', 'N/A')}")
                
                # Try to cancel if in sandbox (for testing)
                if use_sandbox:
                    time.sleep(2)  # Wait a moment
                    try:
                        cancel_result = exchange.cancel_order(order['id'], symbol)
                        print(f"✅ Test order cancelled (sandbox cleanup)")
                    except:
                        print("   (Order may have filled immediately)")
                
                return True
            except Exception as e:
                print(f"❌ Trade execution failed: {e}")
                return False
        else:
            print(f"   (Trading disabled - use --execute flag to enable)")
            print(f"   Would execute: BUY {amount_eth:.6f} {symbol}")
            return True  # Test passed (dry run)
            
    except Exception as e:
        print(f"❌ Trade test error: {e}")
        return False

if args.test:
    # Run comprehensive tests
    print("\n" + "=" * 60)
    print("RUNNING TESTS")
    print("=" * 60)
    
    # Test 1: Balance
    balance = test_balance()
    
    # Test 2: Data fetching
    print("\n📈 Testing Data Fetch...")
    try:
        df = fetch_data()
        if not df.empty:
            print(f"✅ Data fetched successfully ({len(df)} candles)")
            print(f"   Latest price: ${df.iloc[-1]['close']:.2f}")
        else:
            print("❌ No data returned")
    except Exception as e:
        print(f"❌ Data fetch error: {e}")
    
    # Test 3: Market analysis
    print("\n🔍 Testing Market Analysis...")
    try:
        df = fetch_data()
        if not df.empty:
            row = analyze_market(df)
            print(f"✅ Analysis complete")
            print(f"   Price: ${row['close']:.2f}")
            print(f"   EMA 20: ${row['ema_20']:.2f}")
            print(f"   RSI: {row['rsi']:.2f}")
            print(f"   ATR: ${row['atr']:.2f}")
        else:
            print("❌ Cannot analyze - no data")
    except Exception as e:
        print(f"❌ Analysis error: {e}")
    
    # Test 4: Trade execution
    if balance:
        test_trade_execution()
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
    sys.exit(0)

print(f"🛡️ Active. Risking {risk_pct*100}% of balance per trade.")
print(f"📉 Crash Protection: ATR Trailing Stop active.")
if enable_trading:
    print(f"⚠️  TRADING ENABLED - Real orders will be executed!")
else:
    print(f"ℹ️  Trading disabled - orders are simulated (use --execute to enable)")

in_position = False
trailing_stop_price = 0.0
position_amount = 0.0  # Track position size for exit orders

def get_position_size(current_price):
    try:
        balance = exchange.fetch_balance()
        # Coinbase uses USD instead of USDT
        free_usd = balance['USD']['free'] if 'USD' in balance else balance.get('USDC', {}).get('free', 0)
        margin_to_use = free_usd * risk_pct
        position_value = margin_to_use * leverage
        amount_eth = position_value / current_price
        return amount_eth, margin_to_use
    except Exception as e:
        print(f"Balance Error: {e}")
        return 0, 0

# --- MAIN LOOP ---
while True:
    df = fetch_data()
    if not df.empty:
        row = analyze_market(df)
        price = row['close']
        ema_20 = row['ema_20']
        atr = row['atr']
        rsi = row['rsi']

        print(f"Price: ${price:.2f} | RSI: {rsi:.2f} | Stop: ${trailing_stop_price:.2f}")

        # --- BUY LOGIC ---
        if not in_position:
            # Trend Filter: Price > EMA 20 AND RSI > 50
            if price > ema_20 and rsi > 50:
                amount, cost = get_position_size(price)
                
                if amount > 0:
                    print(f"🚀 ENTER LONG: Buying {amount:.4f} ETH (Cost: ${cost:.2f})")
                    
                    if enable_trading:
                        try:
                            order = exchange.create_market_buy_order(symbol, amount)
                            print(f"✅ Order executed: {order.get('id', 'N/A')}")
                        except Exception as e:
                            print(f"❌ Order failed: {e}")
                            continue  # Skip position update if order failed
                    else:
                        print(f"   (Simulated - use --execute to enable real trading)")
                    
                    trailing_stop_price = price - (atr * atr_multiplier)
                    position_amount = amount  # Store position size for exit
                    in_position = True

        # --- SAFETY LOGIC ---
        elif in_position:
            # Raise Safety Net
            potential_stop = price - (atr * atr_multiplier)
            if potential_stop > trailing_stop_price:
                trailing_stop_price = potential_stop
            
            # Crash Protection Trigger
            if price <= trailing_stop_price:
                print(f"🚨 STOP LOSS TRIGGERED at ${price:.2f}")
                
                if enable_trading:
                    try:
                        order = exchange.create_market_sell_order(symbol, position_amount)
                        print(f"✅ Sell order executed: {order.get('id', 'N/A')}")
                    except Exception as e:
                        print(f"❌ Sell order failed: {e}")
                else:
                    print(f"   (Simulated - use --execute to enable real trading)")
                
                in_position = False
                trailing_stop_price = 0.0
                position_amount = 0.0

    time.sleep(60) # Check every 60 seconds