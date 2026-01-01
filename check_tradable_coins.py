#!/usr/bin/env python3
"""
Check which coins in your portfolio are tradable on Coinbase
"""
import ccxt
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

if api_secret and '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

if not api_key or not api_secret:
    print("❌ Error: API credentials not found")
    exit(1)

print("=" * 70)
print("CHECKING TRADABLE COINS FROM YOUR PORTFOLIO")
print("=" * 70)
print()

try:
    exchange = ccxt.coinbaseadvanced({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'sandbox': False,
    })
    
    exchange.load_markets()
    print(f"✅ Connected! Loaded {len(exchange.markets)} markets\n")
    
    # Fetch balance
    balance = exchange.fetch_balance()
    
    # Check which coins have USD pairs
    tradable_coins = []
    non_tradable_coins = []
    
    print("Checking coins in your portfolio...\n")
    
    for currency, bal_info in balance.items():
        if not isinstance(bal_info, dict):
            continue
        
        total = bal_info.get('total', 0)
        if total <= 0:
            continue
        
        if currency in ['USD', 'USDC']:
            continue
        
        # Check if USD pair exists
        pair = f"{currency}/USD"
        if pair in exchange.markets:
            market_info = exchange.markets[pair]
            if market_info.get('active', True):
                # Get current price
                try:
                    ticker = exchange.fetch_ticker(pair)
                    price = ticker['last']
                    usd_value = total * price
                    
                    tradable_coins.append({
                        'currency': currency,
                        'amount': total,
                        'price': price,
                        'usd_value': usd_value,
                        'pair': pair
                    })
                except:
                    pass
        else:
            non_tradable_coins.append(currency)
    
    # Sort by USD value
    tradable_coins.sort(key=lambda x: x['usd_value'], reverse=True)
    
    print("=" * 70)
    print("TRADABLE COINS (Have USD pairs on Coinbase)")
    print("=" * 70)
    print(f"{'Coin':<10} {'Amount':>20} {'Price':>15} {'USD Value':>15} {'Pair':>15}")
    print("-" * 70)
    
    for coin in tradable_coins:
        print(f"{coin['currency']:<10} {coin['amount']:>20.8f} ${coin['price']:>14.6f} ${coin['usd_value']:>14.2f} {coin['pair']:>15}")
    
    print("=" * 70)
    print(f"\n✅ Found {len(tradable_coins)} tradable coins")
    
    if non_tradable_coins:
        print(f"\n⚠️  {len(non_tradable_coins)} coins don't have USD pairs: {', '.join(non_tradable_coins[:10])}")
    
    # Recommendations
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)
    
    # Good candidates (larger positions, liquid)
    good_candidates = [c for c in tradable_coins if c['usd_value'] > 20]
    
    if good_candidates:
        print("\n💡 Good candidates to add (larger positions, liquid):")
        for coin in good_candidates[:10]:
            print(f"   - {coin['currency']}/USD (Value: ${coin['usd_value']:.2f})")
    
    # Current trading symbols
    current_symbols = os.getenv('TRADING_SYMBOLS', 'ETH/USD,BTC/USD').split(',')
    current_symbols = [s.strip() for s in current_symbols]
    
    print(f"\n📊 Currently trading: {', '.join(current_symbols)}")
    
    # Risk distribution note
    num_symbols = len(current_symbols)
    risk_pct = float(os.getenv('TRADING_RISK_PCT', '0.20'))
    risk_per_symbol = risk_pct / num_symbols
    
    print(f"\n💰 Current risk distribution:")
    print(f"   Total risk: {risk_pct*100}%")
    print(f"   Per symbol: {risk_per_symbol*100:.1f}%")
    
    if len(tradable_coins) > num_symbols:
        print(f"\n💡 If you add more symbols:")
        for add_count in [1, 2, 3]:
            new_total = num_symbols + add_count
            new_risk_per = risk_pct / new_total
            print(f"   {new_total} symbols: {new_risk_per*100:.1f}% risk per symbol")
    
    print("\n" + "=" * 70)
    print("CONSIDERATIONS")
    print("=" * 70)
    print("✅ Pros of adding more coins:")
    print("   - More diversification")
    print("   - More trading opportunities")
    print("   - Better use of capital")
    print()
    print("⚠️  Cons of adding more coins:")
    print("   - Risk divided across more symbols (smaller positions)")
    print("   - More to monitor")
    print("   - Some coins may be less liquid")
    print("   - More API calls")
    print()
    print("💡 Recommendation:")
    if len(good_candidates) > 0:
        print(f"   Consider adding 1-2 high-value coins: {', '.join([c['currency'] for c in good_candidates[:2]])}")
        print("   Start small, monitor performance, then add more if successful")
    else:
        print("   Stick with ETH and BTC for now (most liquid, reliable)")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

