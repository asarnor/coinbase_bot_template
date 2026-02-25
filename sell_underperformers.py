#!/usr/bin/env python3
"""
Sell underperforming coins that are not part of the core portfolio.

Core portfolio (KEEP): ETH, BTC, LINK, SHIB
Everything else gets sold to USD to consolidate trading capital.

Based on historical analysis:
- MKR: $48.56 position, low liquidity, not worth the risk dilution
- AAVE: $40.32 position, small, better to consolidate
- CRO: $36.75 position, declining ecosystem
- ALGO: $24.88 position, too small for meaningful trades
- XLM: $21.68 position, too small for meaningful trades
- LTC: $21.25 position, too small for meaningful trades
- SUSHI: minimal value, delisted/illiquid

These positions collectively ~$193 are better used as USD trading capital
for the core 4 symbols than spread across 6+ underperformers.
"""
import ccxt
import os
import sys
import time
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

if api_secret and '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

if not api_key or not api_secret:
    print("Error: API credentials not found in .env file")
    print("Set COINBASE_API_KEY and COINBASE_API_SECRET")
    sys.exit(1)

CORE_PORTFOLIO = {'ETH', 'BTC', 'LINK', 'SHIB'}
STABLECOINS = {'USD', 'USDC', 'USDT', 'DAI'}
DRY_RUN = '--execute' not in sys.argv

print("=" * 70)
print("SELL UNDERPERFORMING COINS - CONSOLIDATE TO USD")
print("=" * 70)
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Core portfolio (KEEP): {', '.join(sorted(CORE_PORTFOLIO))}")
print(f"Mode: {'LIVE EXECUTION' if not DRY_RUN else 'DRY RUN (use --execute to sell)'}")
print()

try:
    exchange = ccxt.coinbaseadvanced({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'sandbox': False,
        'options': {'createMarketBuyOrderRequiresPrice': False},
    })

    print("Connecting to Coinbase Advanced Trade...")
    exchange.load_markets()
    print(f"Connected. Loaded {len(exchange.markets)} markets.\n")

    balance = exchange.fetch_balance()

    coins_to_sell = []
    coins_kept = []
    total_sell_value = 0.0
    usd_balance = 0.0

    print("=" * 70)
    print(f"{'Coin':<10} {'Amount':>18} {'Price':>14} {'Value':>12} {'Action':>12}")
    print("-" * 70)

    for currency, bal_info in balance.items():
        if not isinstance(bal_info, dict):
            continue

        total = bal_info.get('total', 0)
        free = bal_info.get('free', 0)
        if total <= 0:
            continue

        if currency in STABLECOINS:
            if currency == 'USD':
                usd_balance = total
                print(f"{currency:<10} {'':>18} {'':>14} ${total:>11.2f} {'CASH':>12}")
            continue

        pair = f"{currency}/USD"
        price = 0
        usd_value = 0

        if pair in exchange.markets:
            try:
                ticker = exchange.fetch_ticker(pair)
                price = ticker['last']
                usd_value = total * price
            except:
                pass

        if usd_value == 0:
            for base in ['USDC', 'BTC', 'ETH']:
                alt_pair = f"{currency}/{base}"
                if alt_pair in exchange.markets:
                    try:
                        ticker = exchange.fetch_ticker(alt_pair)
                        if base == 'BTC':
                            btc_price = exchange.fetch_ticker('BTC/USD')['last']
                            price = ticker['last'] * btc_price
                        elif base == 'ETH':
                            eth_price = exchange.fetch_ticker('ETH/USD')['last']
                            price = ticker['last'] * eth_price
                        else:
                            price = ticker['last']
                        usd_value = total * price
                        break
                    except:
                        pass

        amount_str = f"{total:.8f}".rstrip('0').rstrip('.')
        price_str = f"${price:.6f}" if price > 0 else "N/A"
        value_str = f"${usd_value:.2f}" if usd_value > 0 else "N/A"

        if currency in CORE_PORTFOLIO:
            action = "KEEP (core)"
            coins_kept.append({'currency': currency, 'usd_value': usd_value})
            print(f"{currency:<10} {amount_str:>18} {price_str:>14} {value_str:>12} {action:>12}")
        elif usd_value > 0:
            action = "SELL"
            coins_to_sell.append({
                'currency': currency,
                'amount': free,
                'total': total,
                'price': price,
                'usd_value': usd_value,
                'pair': pair if pair in exchange.markets else None,
            })
            total_sell_value += usd_value
            print(f"{currency:<10} {amount_str:>18} {price_str:>14} {value_str:>12} {action:>12}")
        else:
            action = "SKIP (no pair)"
            print(f"{currency:<10} {amount_str:>18} {price_str:>14} {value_str:>12} {action:>12}")

    print("=" * 70)
    print(f"\nCurrent USD balance: ${usd_balance:.2f}")
    print(f"Core portfolio value: ${sum(c['usd_value'] for c in coins_kept):.2f}")
    print(f"Coins to sell: {len(coins_to_sell)}")
    print(f"Estimated value to recover: ${total_sell_value:.2f}")
    print(f"Projected USD after sales: ${usd_balance + total_sell_value:.2f}")

    if not coins_to_sell:
        print("\nNo underperforming coins to sell. Portfolio is already clean.")
        sys.exit(0)

    coins_to_sell.sort(key=lambda x: x['usd_value'], reverse=True)

    print("\n" + "=" * 70)
    print("SELL ORDERS")
    print("=" * 70)

    successful = 0
    failed = 0
    total_recovered = 0.0

    for coin in coins_to_sell:
        currency = coin['currency']
        amount = coin['amount']
        usd_value = coin['usd_value']

        if amount <= 0:
            print(f"\n[{currency}] SKIP: No free balance to sell (all in open orders)")
            failed += 1
            continue

        sell_pair = coin['pair']
        if not sell_pair:
            for base in ['USDC', 'BTC', 'ETH']:
                alt = f"{currency}/{base}"
                if alt in exchange.markets and exchange.markets[alt].get('active', True):
                    sell_pair = alt
                    break

        if not sell_pair:
            print(f"\n[{currency}] SKIP: No active trading pair found")
            failed += 1
            continue

        market_info = exchange.markets[sell_pair]
        min_cost = market_info.get('limits', {}).get('cost', {}).get('min', 1.0)
        min_amount = market_info.get('limits', {}).get('amount', {}).get('min', 0)

        if usd_value < (min_cost or 1.0):
            print(f"\n[{currency}] SKIP: Value ${usd_value:.2f} below minimum order ${min_cost or 1.0:.2f}")
            failed += 1
            continue

        if min_amount and amount < min_amount:
            print(f"\n[{currency}] SKIP: Amount {amount} below minimum {min_amount}")
            failed += 1
            continue

        print(f"\n[{currency}] Selling {amount:.8f} via {sell_pair} (~${usd_value:.2f})")

        if DRY_RUN:
            print(f"[{currency}] DRY RUN - Would sell. Use --execute to actually sell.")
            successful += 1
            total_recovered += usd_value
            continue

        try:
            order = exchange.create_market_sell_order(sell_pair, amount)
            order_cost = order.get('cost', 0) or usd_value
            total_recovered += order_cost
            successful += 1
            print(f"[{currency}] SOLD - Order: {order.get('id', 'N/A')}, Value: ${order_cost:.2f}")
            time.sleep(1)
        except Exception as e:
            print(f"[{currency}] FAILED: {e}")
            failed += 1

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Successful: {successful}")
    print(f"Failed/Skipped: {failed}")
    print(f"{'Estimated' if DRY_RUN else 'Actual'} USD recovered: ${total_recovered:.2f}")

    if not DRY_RUN and successful > 0:
        time.sleep(3)
        updated = exchange.fetch_balance()
        new_usd = updated.get('USD', {}).get('free', 0)
        print(f"\nUpdated USD balance: ${new_usd:.2f}")
        print(f"Increase: ${new_usd - usd_balance:.2f}")

    print(f"\nCore portfolio preserved: {', '.join(sorted(CORE_PORTFOLIO))}")
    if DRY_RUN:
        print("\nThis was a DRY RUN. Run with --execute to actually sell.")

except Exception as e:
    print(f"\nError: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
