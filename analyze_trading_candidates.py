#!/usr/bin/env python3
"""
Detailed analysis of which coins to add to trading list
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

print("=" * 80)
print("TRADING CANDIDATE ANALYSIS")
print("=" * 80)
print()

try:
    exchange = ccxt.coinbaseadvanced({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'sandbox': False,
    })
    
    exchange.load_markets()
    
    # Fetch balance
    balance = exchange.fetch_balance()
    
    # Current trading symbols
    current_symbols = os.getenv('TRADING_SYMBOLS', 'ETH/USD,BTC/USD').split(',')
    current_symbols = [s.strip() for s in current_symbols]
    current_coins = [s.split('/')[0] for s in current_symbols]
    
    print(f"📊 Currently trading: {', '.join(current_symbols)}")
    print()
    
    # Analyze candidates
    candidates = []
    
    for currency, bal_info in balance.items():
        if not isinstance(bal_info, dict):
            continue
        
        total = bal_info.get('total', 0)
        if total <= 0:
            continue
        
        if currency in ['USD', 'USDC'] or currency in current_coins:
            continue
        
        pair = f"{currency}/USD"
        if pair in exchange.markets:
            market_info = exchange.markets[pair]
            if market_info.get('active', True):
                try:
                    ticker = exchange.fetch_ticker(pair)
                    price = ticker['last']
                    usd_value = total * price
                    
                    # Get market data for analysis
                    volume_24h = ticker.get('quoteVolume', 0)  # USD volume
                    bid = ticker.get('bid', price)
                    ask = ticker.get('ask', price)
                    spread_pct = ((ask - bid) / price * 100) if bid > 0 else 0
                    
                    # Score the coin
                    score = 0
                    reasons = []
                    
                    # Value score (higher is better)
                    if usd_value > 50:
                        score += 3
                        reasons.append("High portfolio value")
                    elif usd_value > 20:
                        score += 2
                        reasons.append("Good portfolio value")
                    elif usd_value > 10:
                        score += 1
                        reasons.append("Moderate portfolio value")
                    
                    # Liquidity score (volume)
                    if volume_24h > 10_000_000:  # $10M+ daily volume
                        score += 3
                        reasons.append("Very liquid")
                    elif volume_24h > 1_000_000:  # $1M+ daily volume
                        score += 2
                        reasons.append("Liquid")
                    elif volume_24h > 100_000:  # $100K+ daily volume
                        score += 1
                        reasons.append("Moderate liquidity")
                    
                    # Spread score (lower is better)
                    if spread_pct < 0.1:
                        score += 2
                        reasons.append("Tight spreads")
                    elif spread_pct < 0.5:
                        score += 1
                        reasons.append("Reasonable spreads")
                    
                    # Diversification (different from ETH/BTC)
                    if currency not in ['ETH', 'BTC']:
                        score += 1
                        reasons.append("Diversification")
                    
                    candidates.append({
                        'currency': currency,
                        'pair': pair,
                        'amount': total,
                        'price': price,
                        'usd_value': usd_value,
                        'volume_24h': volume_24h,
                        'spread_pct': spread_pct,
                        'score': score,
                        'reasons': reasons
                    })
                except Exception as e:
                    pass
    
    # Sort by score, then by USD value
    candidates.sort(key=lambda x: (x['score'], x['usd_value']), reverse=True)
    
    print("=" * 80)
    print("TOP TRADING CANDIDATES")
    print("=" * 80)
    print(f"{'Coin':<8} {'Value':>12} {'Volume 24h':>15} {'Spread':>10} {'Score':>8} {'Reasons'}")
    print("-" * 80)
    
    top_candidates = []
    for coin in candidates[:15]:
        volume_str = f"${coin['volume_24h']/1_000_000:.1f}M" if coin['volume_24h'] > 1_000_000 else f"${coin['volume_24h']/1_000:.1f}K"
        spread_str = f"{coin['spread_pct']:.2f}%"
        reasons_str = ", ".join(coin['reasons'][:2])
        
        print(f"{coin['currency']:<8} ${coin['usd_value']:>11.2f} {volume_str:>15} {spread_str:>10} {coin['score']:>8} {reasons_str}")
        
        if coin['score'] >= 5:  # High score candidates
            top_candidates.append(coin)
    
    print("=" * 80)
    
    # Recommendations
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS")
    print("=" * 80)
    
    if top_candidates:
        print("\n🏆 TOP RECOMMENDATIONS (Score ≥ 5):")
        for i, coin in enumerate(top_candidates[:5], 1):
            print(f"\n{i}. {coin['currency']}/USD")
            print(f"   Portfolio Value: ${coin['usd_value']:.2f}")
            print(f"   24h Volume: ${coin['volume_24h']:,.0f}")
            print(f"   Spread: {coin['spread_pct']:.2f}%")
            print(f"   Reasons: {', '.join(coin['reasons'])}")
            print(f"   Score: {coin['score']}/10")
    
    # Suggested trading list
    print("\n" + "=" * 80)
    print("SUGGESTED TRADING LIST")
    print("=" * 80)
    
    suggested = current_coins.copy()
    for coin in top_candidates[:3]:  # Add top 3
        if coin['currency'] not in suggested:
            suggested.append(coin['currency'])
    
    suggested_pairs = [f"{c}/USD" for c in suggested]
    print(f"\n💡 Suggested: {', '.join(suggested_pairs)}")
    print(f"\n   To implement, set in Railway:")
    print(f"   TRADING_SYMBOLS={','.join(suggested_pairs)}")
    
    # Risk distribution
    risk_pct = float(os.getenv('TRADING_RISK_PCT', '0.20'))
    print(f"\n💰 Risk Distribution:")
    print(f"   Total risk: {risk_pct*100}%")
    print(f"   Symbols: {len(suggested_pairs)}")
    print(f"   Risk per symbol: {(risk_pct/len(suggested_pairs)*100):.1f}%")
    
    print("\n" + "=" * 80)
    print("CONSIDERATIONS")
    print("=" * 80)
    print("\n✅ Best candidates have:")
    print("   - High portfolio value (>$20)")
    print("   - High liquidity (>$1M daily volume)")
    print("   - Tight spreads (<0.5%)")
    print("   - Good diversification")
    
    print("\n⚠️  Remember:")
    print("   - More symbols = smaller positions per symbol")
    print("   - Monitor performance closely")
    print("   - Start with 1-2 additions, then expand")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

