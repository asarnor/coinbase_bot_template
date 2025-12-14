import ccxt
import pandas as pd
import pandas_ta as ta
import time
import sys

# --- CONFIGURATION ---
symbol = 'ETH/USD'       # Coinbase uses USD, not USDT
timeframe = '5m'         # Fast timeframe
leverage = 5             # 5x Leverage (for futures/advanced trade)
risk_pct = 0.20          # Invest 20% of account balance
atr_multiplier = 1.5     # 1.5x Volatility Safety Net

# --- API KEYS (PASTE YOURS HERE) ---
# Coinbase Pro requires: API Key, Secret, and Passphrase
api_key = 'YOUR_API_KEY'
api_secret = 'YOUR_SECRET_KEY'
api_passphrase = 'YOUR_PASSPHRASE'  # Coinbase Pro passphrase

# API SETUP
try:
    exchange = ccxt.coinbasepro({
        'apiKey': api_key,
        'secret': api_secret,
        'password': api_passphrase,  # Coinbase Pro requires passphrase
        'enableRateLimit': True,
        'sandbox': False,  # Set to True for sandbox testing
    })
    # Check connection
    exchange.load_markets()
    print("✅ Connected to Coinbase Pro successfully.")
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

print(f"🛡️ Active. Risking {risk_pct*100}% of balance per trade.")
print(f"📉 Crash Protection: ATR Trailing Stop active.")

in_position = False
trailing_stop_price = 0.0
position_amount = 0.0  # Track position size for exit orders

def fetch_data():
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        print(f"Data Error: {e}")
        return pd.DataFrame()

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

def analyze_market(df):
    df['ema_20'] = ta.ema(df['close'], length=20)
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    return df.iloc[-1]

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
                    
                    # UNCOMMENT TO ENABLE REAL TRADING:
                    # exchange.create_market_buy_order(symbol, amount)
                    
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
                
                # UNCOMMENT TO ENABLE REAL TRADING:
                # exchange.create_market_sell_order(symbol, position_amount)
                
                in_position = False
                trailing_stop_price = 0.0
                position_amount = 0.0

    time.sleep(60) # Check every 60 seconds