#!/usr/bin/env python3
"""
Portfolio Cleanup Script
Analyzes portfolio and sells small/irrelevant positions to USD for trading capital
"""
import ccxt
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

# Get API credentials
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

# Convert literal \n strings to actual newlines
if api_secret and '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

if not api_key or not api_secret:
    print("❌ Error: API credentials not found")
    exit(1)

# Configuration
MIN_POSITION_VALUE_USD = float(os.getenv('MIN_POSITION_VALUE_USD', '5.00'))  # Sell positions worth less than this
EXCLUDE_CURRENCIES = ['USD', 'USDC']  # Don't sell these
PRIORITY_CURRENCIES = ['BTC', 'ETH']  # Keep these even if small

print("=" * 70)
print("PORTFOLIO CLEANUP - SELL SMALL POSITIONS FOR USD")
print("=" * 70)
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Minimum position value to keep: ${MIN_POSITION_VALUE_USD:.2f}")
print()

try:
    # Connect to Coinbase
    print("🔌 Connecting to Coinbase Advanced Trade...")
    exchange = ccxt.coinbaseadvanced({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'sandbox': False,
        'options': {
            'createMarketBuyOrderRequiresPrice': False,
        },
    })
    
    exchange.load_markets()
    print(f"✅ Connected! Loaded {len(exchange.markets)} markets\n")
    
    # Fetch balance
    print("💰 Fetching portfolio balance...")
    balance = exchange.fetch_balance()
    print("✅ Balance fetched successfully!\n")
    
    # Analyze portfolio
    print("=" * 70)
    print("PORTFOLIO ANALYSIS")
    print("=" * 70)
    
    positions_to_sell = []
    positions_to_keep = []
    total_usd_value = 0
    
    # Get current prices for all currencies
    print("📊 Fetching current prices...")
    tickers = {}
    for currency in balance.keys():
        if currency in EXCLUDE_CURRENCIES:
            continue
        if isinstance(balance[currency], dict) and balance[currency].get('total', 0) > 0:
            # Try to get price
            pair = f"{currency}/USD"
            if pair in exchange.markets:
                try:
                    ticker = exchange.fetch_ticker(pair)
                    tickers[currency] = ticker['last']
                except:
                    pass
    
    print(f"✅ Fetched prices for {len(tickers)} currencies\n")
    
    # Analyze each position
    print("=" * 70)
    print("POSITION ANALYSIS")
    print("=" * 70)
    print(f"{'Currency':<12} {'Amount':>20} {'Price':>15} {'Value USD':>15} {'Action':>15}")
    print("-" * 70)
    
    for currency, bal_info in balance.items():
        if not isinstance(bal_info, dict):
            continue
        
        total = bal_info.get('total', 0)
        free = bal_info.get('free', 0)
        
        if total <= 0:
            continue
        
        # Skip USD/USDC
        if currency in EXCLUDE_CURRENCIES:
            if currency == 'USD':
                total_usd_value += total
            continue
        
        # Get USD value
        if currency in tickers:
            price = tickers[currency]
            usd_value = total * price
        else:
            # Try alternative pairs
            usd_value = 0
            price = 0
            for base in ['BTC', 'ETH', 'USDC']:
                pair = f"{currency}/{base}"
                if pair in exchange.markets:
                    try:
                        ticker = exchange.fetch_ticker(pair)
                        if base == 'BTC':
                            btc_price = tickers.get('BTC', exchange.fetch_ticker('BTC/USD')['last'])
                            price = ticker['last'] * btc_price
                        elif base == 'ETH':
                            eth_price = tickers.get('ETH', exchange.fetch_ticker('ETH/USD')['last'])
                            price = ticker['last'] * eth_price
                        else:
                            price = ticker['last']
                        usd_value = total * price
                        break
                    except:
                        pass
        
        # Format display
        if currency in ['USD', 'USDC']:
            value_str = f"${usd_value:.2f}"
        else:
            value_str = f"${usd_value:.2f}" if usd_value > 0 else "N/A"
        
        amount_str = f"{total:.8f}".rstrip('0').rstrip('.')
        
        # Decide action
        if currency in PRIORITY_CURRENCIES:
            action = "KEEP (Priority)"
            positions_to_keep.append({
                'currency': currency,
                'amount': total,
                'free': free,
                'usd_value': usd_value,
                'price': price
            })
        elif usd_value > 0 and usd_value < MIN_POSITION_VALUE_USD:
            action = "SELL (Too Small)"
            positions_to_sell.append({
                'currency': currency,
                'amount': free,  # Only sell free balance
                'total': total,
                'free': free,
                'usd_value': usd_value,
                'price': price
            })
        else:
            action = "KEEP"
            positions_to_keep.append({
                'currency': currency,
                'amount': total,
                'free': free,
                'usd_value': usd_value,
                'price': price
            })
        
        print(f"{currency:<12} {amount_str:>20} ${price:>14.6f} {value_str:>15} {action:>15}")
    
    print("=" * 70)
    print(f"\n💵 Current USD Balance: ${total_usd_value:.2f}")
    print(f"📊 Positions to keep: {len(positions_to_keep)}")
    print(f"🗑️  Positions to sell: {len(positions_to_sell)}")
    
    if positions_to_sell:
        total_sell_value = sum(p['usd_value'] for p in positions_to_sell)
        print(f"💰 Estimated USD after sales: ${total_usd_value + total_sell_value:.2f}")
    
    print()
    
    # Execute sales
    if positions_to_sell:
        print("=" * 70)
        print("EXECUTING SALES")
        print("=" * 70)
        
        total_sold_usd = 0
        successful_sales = 0
        failed_sales = 0
        
        for position in positions_to_sell:
            currency = position['currency']
            amount = position['free']  # Only sell free balance
            usd_value = position['usd_value']
            
            if amount <= 0:
                print(f"⏭️  Skipping {currency}: No free balance to sell")
                continue
            
            # Find trading pair
            pair = f"{currency}/USD"
            if pair not in exchange.markets:
                # Try alternative pairs
                pair = None
                for base in ['USDC', 'BTC', 'ETH']:
                    alt_pair = f"{currency}/{base}"
                    if alt_pair in exchange.markets:
                        pair = alt_pair
                        break
                
                if not pair:
                    print(f"⚠️  {currency}: No USD trading pair found, skipping")
                    failed_sales += 1
                    continue
            
            print(f"\n💸 Selling {currency}:")
            print(f"   Amount: {amount:.8f} {currency}")
            print(f"   Pair: {pair}")
            print(f"   Estimated value: ${usd_value:.2f}")
            
            try:
                # Check minimum order size
                market_info = exchange.markets[pair]
                min_cost = market_info.get('limits', {}).get('cost', {}).get('min', 1.0)
                
                if usd_value < min_cost:
                    print(f"⚠️  Value ${usd_value:.2f} below minimum ${min_cost:.2f}, skipping")
                    failed_sales += 1
                    continue
                
                # Execute sell order
                order = exchange.create_market_sell_order(pair, amount)
                
                print(f"✅ Sold successfully!")
                print(f"   Order ID: {order.get('id', 'N/A')}")
                print(f"   Status: {order.get('status', 'N/A')}")
                
                # Get actual sale value
                order_cost = order.get('cost', 0)
                if order_cost:
                    total_sold_usd += order_cost
                    print(f"   Sale value: ${order_cost:.2f}")
                
                successful_sales += 1
                
            except Exception as e:
                print(f"❌ Sale failed: {e}")
                failed_sales += 1
        
        print("\n" + "=" * 70)
        print("SALES SUMMARY")
        print("=" * 70)
        print(f"✅ Successful sales: {successful_sales}")
        print(f"❌ Failed sales: {failed_sales}")
        print(f"💰 Total USD from sales: ${total_sold_usd:.2f}")
        
        # Show updated balance
        print("\n" + "=" * 70)
        print("UPDATED USD BALANCE")
        print("=" * 70)
        updated_balance = exchange.fetch_balance()
        if 'USD' in updated_balance:
            new_usd = updated_balance['USD']['free']
            print(f"New USD Balance: ${new_usd:.2f}")
            print(f"Increase: ${new_usd - total_usd_value:.2f}")
    else:
        print("✅ No positions to sell - all positions are above minimum value or priority currencies")
    
    print("\n" + "=" * 70)
    print("✅ CLEANUP COMPLETE")
    print("=" * 70)
    print(f"Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

