#!/usr/bin/env python3
"""
Simple script to connect to Coinbase and display portfolio balances
"""
import ccxt
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get API credentials
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

# Convert literal \n strings to actual newlines (required for ECDSA private key)
if api_secret and '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

if not api_key or not api_secret:
    print("❌ Error: API credentials not found in .env file")
    print("   Please make sure COINBASE_API_KEY and COINBASE_API_SECRET are set")
    exit(1)

print("🔌 Connecting to Coinbase Advanced Trade...")
print(f"   API Key: {api_key[:50]}...")
print()

try:
    # Connect to Coinbase Advanced Trade API
    exchange = ccxt.coinbaseadvanced({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'sandbox': False,  # Production mode
    })
    
    # Load markets
    print("📊 Loading markets...")
    exchange.load_markets()
    print(f"✅ Connected! Loaded {len(exchange.markets)} markets\n")
    
    # Fetch balance
    print("💰 Fetching account balance...")
    balance = exchange.fetch_balance()
    print("✅ Balance fetched successfully!\n")
    
    # Display portfolio
    print("=" * 70)
    print("PORTFOLIO BALANCES")
    print("=" * 70)
    
    # Get all currencies with non-zero balances
    currencies_with_balance = []
    for currency, bal_info in balance.items():
        if isinstance(bal_info, dict):
            total = bal_info.get('total', 0)
            free = bal_info.get('free', 0)
            used = bal_info.get('used', 0)
            if total > 0 or free > 0 or used > 0:
                currencies_with_balance.append({
                    'currency': currency,
                    'total': total,
                    'free': free,
                    'used': used
                })
    
    # Sort by total balance (descending)
    currencies_with_balance.sort(key=lambda x: x['total'], reverse=True)
    
    if currencies_with_balance:
        print(f"{'Currency':<12} {'Total':>20} {'Free':>20} {'Used':>20}")
        print("-" * 70)
        
        total_usd_value = 0
        
        for item in currencies_with_balance:
            currency = item['currency']
            total = item['total']
            free = item['free']
            used = item['used']
            
            # Format numbers appropriately
            if currency in ['USD', 'USDC']:
                total_str = f"${total:,.2f}"
                free_str = f"${free:,.2f}"
                used_str = f"${used:,.2f}"
                if currency == 'USD':
                    total_usd_value += total
            else:
                total_str = f"{total:.8f}".rstrip('0').rstrip('.')
                free_str = f"{free:.8f}".rstrip('0').rstrip('.')
                used_str = f"{used:.8f}".rstrip('0').rstrip('.')
            
            print(f"{currency:<12} {total_str:>20} {free_str:>20} {used_str:>20}")
        
        print("=" * 70)
        if total_usd_value > 0:
            print(f"\n💵 Total USD Balance: ${total_usd_value:,.2f}")
    else:
        print("   No balances found")
    
    # Show account info if available
    print("\n" + "=" * 70)
    print("ACCOUNT INFORMATION")
    print("=" * 70)
    print(f"Markets Available: {len(exchange.markets)}")
    
    # Check for common trading pairs
    common_pairs = ['ETH/USD', 'BTC/USD', 'ETH/BTC']
    available_pairs = []
    for pair in common_pairs:
        if pair in exchange.markets:
            available_pairs.append(pair)
    
    if available_pairs:
        print(f"Available Trading Pairs: {', '.join(available_pairs)}")
    
    print("\n✅ Portfolio retrieved successfully!")
    
except Exception as e:
    print(f"\n❌ Error connecting to Coinbase: {e}")
    import traceback
    print("\nFull error details:")
    traceback.print_exc()
    exit(1)
