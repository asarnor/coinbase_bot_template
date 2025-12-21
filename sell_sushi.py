#!/usr/bin/env python3
"""
Script to sell all SUSHI cryptocurrency at market price
"""
import ccxt
import os
from dotenv import load_dotenv
import time
from datetime import datetime

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

print("=" * 70)
print("SUSHI SELL ORDER - MARKET PRICE")
print("=" * 70)
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"API Key: {api_key[:50]}...")
print()

try:
    # Connect to Coinbase Advanced Trade API
    print("🔌 Connecting to Coinbase Advanced Trade...")
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
    
    # Check for SUSHI balance
    sushi_balance = None
    if 'SUSHI' in balance:
        sushi_info = balance['SUSHI']
        if isinstance(sushi_info, dict):
            sushi_total = sushi_info.get('total', 0)
            sushi_free = sushi_info.get('free', 0)
            sushi_used = sushi_info.get('used', 0)
            
            if sushi_total > 0:
                sushi_balance = {
                    'total': sushi_total,
                    'free': sushi_free,
                    'used': sushi_used
                }
    
    # Display SUSHI balance
    print("=" * 70)
    print("SUSHI BALANCE CHECK")
    print("=" * 70)
    
    if not sushi_balance:
        print("❌ No SUSHI found in your account")
        print("   Total SUSHI: 0.00000000")
        exit(0)
    
    print(f"Total SUSHI: {sushi_balance['total']:.8f}")
    print(f"Free SUSHI: {sushi_balance['free']:.8f}")
    print(f"Used SUSHI: {sushi_balance['used']:.8f}")
    print()
    
    # Check available trading pairs for SUSHI
    print("=" * 70)
    print("CHECKING AVAILABLE TRADING PAIRS")
    print("=" * 70)
    
    possible_pairs = ['SUSHI/USD', 'SUSHI/USDC', 'SUSHI/BTC', 'SUSHI/ETH']
    available_pair = None
    
    for pair in possible_pairs:
        if pair in exchange.markets:
            market_info = exchange.markets[pair]
            if market_info.get('active', True):  # Check if market is active
                available_pair = pair
                print(f"✅ Found trading pair: {pair}")
                print(f"   Market ID: {market_info.get('id', 'N/A')}")
                print(f"   Active: {market_info.get('active', 'N/A')}")
                break
    
    if not available_pair:
        print("❌ No available trading pair found for SUSHI")
        print("   Checked pairs:", ', '.join(possible_pairs))
        print("   Please check Coinbase for available SUSHI trading pairs")
        exit(1)
    
    print()
    
    # Get current price
    print("=" * 70)
    print("FETCHING CURRENT MARKET PRICE")
    print("=" * 70)
    
    try:
        ticker = exchange.fetch_ticker(available_pair)
        current_price = ticker['last']
        print(f"Current {available_pair} price: ${current_price:.6f}")
        print(f"Bid: ${ticker.get('bid', 'N/A')}")
        print(f"Ask: ${ticker.get('ask', 'N/A')}")
        print()
    except Exception as e:
        print(f"⚠️  Warning: Could not fetch current price: {e}")
        print("   Proceeding with market order...")
        print()
    
    # Calculate sell amount (use free balance)
    sell_amount = sushi_balance['free']
    
    if sell_amount <= 0:
        print("❌ No free SUSHI available to sell")
        print(f"   Free balance: {sell_amount:.8f}")
        if sushi_balance['used'] > 0:
            print(f"   Note: You have {sushi_balance['used']:.8f} SUSHI in open orders")
        exit(1)
    
    # Estimate USD value
    estimated_usd_value = sell_amount * current_price if 'current_price' in locals() else None
    
    # Confirm and execute sell order
    print("=" * 70)
    print("SELL ORDER DETAILS")
    print("=" * 70)
    print(f"Trading Pair: {available_pair}")
    print(f"Amount to Sell: {sell_amount:.8f} SUSHI")
    if estimated_usd_value:
        print(f"Estimated Value: ${estimated_usd_value:.2f} USD")
    print(f"Order Type: MARKET SELL")
    print()
    
    # Execute the sell order
    print("=" * 70)
    print("EXECUTING MARKET SELL ORDER")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    try:
        order = exchange.create_market_sell_order(available_pair, sell_amount)
        
        print("✅ SELL ORDER EXECUTED SUCCESSFULLY!")
        print()
        print("=" * 70)
        print("ORDER DETAILS")
        print("=" * 70)
        print(f"Order ID: {order.get('id', 'N/A')}")
        print(f"Status: {order.get('status', 'N/A')}")
        print(f"Symbol: {order.get('symbol', 'N/A')}")
        print(f"Type: {order.get('type', 'N/A')}")
        print(f"Side: {order.get('side', 'N/A')}")
        print(f"Amount: {order.get('amount', 'N/A')}")
        print(f"Filled: {order.get('filled', 'N/A')}")
        print(f"Remaining: {order.get('remaining', 'N/A')}")
        print(f"Price: ${order.get('price', 'N/A')}")
        print(f"Cost: ${order.get('cost', 'N/A')}")
        print(f"Fee: {order.get('fee', 'N/A')}")
        print()
        
        # Wait a moment and check updated balance
        print("=" * 70)
        print("VERIFYING UPDATED BALANCE")
        print("=" * 70)
        time.sleep(3)  # Wait 3 seconds for order to settle
        
        updated_balance = exchange.fetch_balance()
        if 'SUSHI' in updated_balance:
            updated_sushi = updated_balance['SUSHI']
            if isinstance(updated_sushi, dict):
                print(f"Updated SUSHI Balance:")
                print(f"  Total: {updated_sushi.get('total', 0):.8f}")
                print(f"  Free: {updated_sushi.get('free', 0):.8f}")
                print(f"  Used: {updated_sushi.get('used', 0):.8f}")
        
        # Show USD/USDC balance change
        if 'USD' in updated_balance:
            usd_balance = updated_balance['USD']
            print(f"\nUpdated USD Balance:")
            print(f"  Total: ${usd_balance.get('total', 0):.2f}")
            print(f"  Free: ${usd_balance.get('free', 0):.2f}")
        
        if 'USDC' in updated_balance:
            usdc_balance = updated_balance['USDC']
            print(f"\nUpdated USDC Balance:")
            print(f"  Total: ${usdc_balance.get('total', 0):.2f}")
            print(f"  Free: ${usdc_balance.get('free', 0):.2f}")
        
        print()
        print("=" * 70)
        print("✅ SELL ORDER COMPLETED SUCCESSFULLY")
        print("=" * 70)
        print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        print("💡 Tip: Check your Coinbase account to verify the trade appears in your transaction history")
        
    except Exception as e:
        print(f"❌ SELL ORDER FAILED: {e}")
        print()
        import traceback
        print("Full error details:")
        traceback.print_exc()
        exit(1)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    print("\nFull error details:")
    traceback.print_exc()
    exit(1)


