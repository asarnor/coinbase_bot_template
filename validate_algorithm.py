#!/usr/bin/env python3
"""
Algorithm Validation Script

Validates the trading algorithm to ensure:
1. Maximum profit capture when coins go up
2. Significant loss prevention when market crashes
3. Sell recommendations for non-core portfolio coins (MKR, AAVE, CRO, ALGO, XLM, LTC)
   based on their historical performance vs ETH/BTC

Usage:
  python3 validate_algorithm.py              # Run validation and get recommendations
  python3 validate_algorithm.py --execute-sells  # Also execute sells for SELL-recommended coins
"""
import ccxt
import pandas as pd
import pandas_ta_classic as ta
import os
import sys
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# Core trading symbols (keep these)
CORE_SYMBOLS = ['ETH/USD', 'BTC/USD', 'LINK/USD', 'SHIB/USD']

# Other portfolio coins to analyze for sell recommendations
OTHER_PORTFOLIO_COINS = ['MKR/USD', 'AAVE/USD', 'CRO/USD', 'ALGO/USD', 'XLM/USD', 'LTC/USD']

# Algorithm parameters (must match main_multi_symbol.py)
PROFIT_TARGET_PCT = 0.035  # 3.5% for ETH/BTC/LINK
PROFIT_TARGET_SHIB = 0.02  # 2.0% for SHIB
SPIKE_REVERSAL_PCT = 0.02  # 2.0% for ETH/BTC/LINK
SPIKE_REVERSAL_SHIB = 0.012  # 1.2% for SHIB
MIN_SPIKE_PROFIT_PCT = 0.02  # 2.0% activation
MIN_SPIKE_PROFIT_SHIB = 0.015  # 1.5% for SHIB
ATR_MULTIPLIER = 1.5
ATR_MULTIPLIER_SHIB = 2.0
RSI_ENTRY_THRESHOLD = 55
MIN_TREND_STRENGTH = 0.01
TIMEFRAME = '5m'


def get_exchange():
    """Initialize CCXT exchange (read-only, no API keys needed for public OHLCV)."""
    api_key = os.getenv('COINBASE_API_KEY', '')
    api_secret = os.getenv('COINBASE_API_SECRET', '')
    if api_secret and '\\n' in api_secret:
        api_secret = api_secret.replace('\\n', '\n')
    
    config = {
        'enableRateLimit': True,
        'sandbox': False,
        'options': {'createMarketBuyOrderRequiresPrice': False},
    }
    if api_key and api_secret:
        config['apiKey'] = api_key
        config['secret'] = api_secret
    
    exchange = ccxt.coinbaseadvanced(config)
    exchange.load_markets()
    return exchange


def fetch_historical_ohlcv(exchange, symbol, days=14, timeframe=TIMEFRAME):
    """Fetch historical OHLCV data. Coinbase limits ~300 candles per request."""
    all_bars = []
    since = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    
    # 5m = 288 candles/day, so 14 days = ~4032 candles. Fetch in batches of 300.
    batch_size = 300
    max_iterations = (days * 288 // batch_size) + 1
    
    for _ in range(min(max_iterations, 20)):  # Cap at 20 batches
        try:
            bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=batch_size)
            if not bars:
                break
            all_bars.extend(bars)
            since = bars[-1][0] + 1
            if len(bars) < batch_size:
                break
        except Exception as e:
            print(f"  ⚠️  Fetch error for {symbol}: {e}")
            break
    
    if not all_bars:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df


def analyze_market(df):
    """Compute indicators (matches main_multi_symbol.py)."""
    if len(df) < 25:
        return None
    df = df.copy()
    df['ema_20'] = ta.ema(df['close'], length=20)
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df['ema_slope'] = df['ema_20'].diff(5)
    df['volume_ma'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']
    return df


def backtest_symbol(df, symbol):
    """
    Backtest the algorithm on historical data.
    Returns: trades list, total_pnl_pct, max_drawdown_pct, win_rate
    """
    df = analyze_market(df)
    if df is None or len(df) < 25:
        return [], 0, 0, 0
    
    base = symbol.split('/')[0]
    is_shib = base == 'SHIB'
    profit_target = PROFIT_TARGET_SHIB if is_shib else PROFIT_TARGET_PCT
    spike_reversal = SPIKE_REVERSAL_SHIB if is_shib else SPIKE_REVERSAL_PCT
    min_spike_profit = MIN_SPIKE_PROFIT_SHIB if is_shib else MIN_SPIKE_PROFIT_PCT
    atr_mult = ATR_MULTIPLIER_SHIB if is_shib else ATR_MULTIPLIER
    
    trades = []
    in_position = False
    entry_price = 0
    entry_idx = 0
    peak_price = 0
    trailing_stop = 0
    trailing_profit_target = 0
    breakeven_set = False
    
    for i in range(24, len(df)):
        row = df.iloc[i]
        price = row['close']
        ema_20 = row['ema_20']
        atr = row['atr']
        rsi = row['rsi']
        ema_slope = row.get('ema_slope', 0)
        volume_ratio = row.get('volume_ratio', 1.0)
        
        if pd.isna(ema_20) or pd.isna(atr) or pd.isna(rsi):
            continue
        
        atr_pct = atr / price if price > 0 else 0
        is_volatile = atr_pct > 0.02
        trend_strength = abs(price - ema_20) / ema_20 if ema_20 > 0 else 0
        
        # --- ENTRY ---
        if not in_position:
            price_above_ema = price > ema_20
            rsi_strong = rsi > RSI_ENTRY_THRESHOLD
            trend_strong = trend_strength >= MIN_TREND_STRENGTH
            ema_up = ema_slope > 0
            vol_ok = volume_ratio >= 1.0
            
            if price_above_ema and rsi_strong and trend_strong and ema_up and vol_ok:
                in_position = True
                entry_price = price
                entry_idx = i
                peak_price = price
                trailing_stop = price - (atr * (2.0 if is_volatile else atr_mult))
                trailing_profit_target = price * (1 + profit_target)
                breakeven_set = False
            continue
        
        # --- IN POSITION: EXIT CHECKS ---
        profit_pct = (price - entry_price) / entry_price
        peak_profit_pct = (peak_price - entry_price) / entry_price
        drop_from_peak = (peak_price - price) / peak_price if peak_price > 0 else 0
        
        # Update peak and trailing target
        if price > peak_price:
            peak_price = price
            new_target = entry_price * (1 + profit_target) + (price - entry_price) * 0.6
            if new_target > trailing_profit_target:
                trailing_profit_target = new_target
        
        # 1. Spike reversal
        if peak_profit_pct >= min_spike_profit and drop_from_peak >= spike_reversal:
            trades.append({'entry': entry_price, 'exit': price, 'pnl_pct': profit_pct, 'reason': 'spike_reversal'})
            in_position = False
            continue
        
        # 2. Static profit target
        if price >= entry_price * (1 + profit_target):
            trades.append({'entry': entry_price, 'exit': price, 'pnl_pct': profit_pct, 'reason': 'profit_target'})
            in_position = False
            continue
        
        # 3. Trailing profit target
        if trailing_profit_target > 0 and price >= trailing_profit_target:
            trades.append({'entry': entry_price, 'exit': price, 'pnl_pct': profit_pct, 'reason': 'trailing_target'})
            in_position = False
            continue
        
        # 4. Trailing stop (crash protection)
        potential_stop = price - (atr * atr_mult)
        if potential_stop > trailing_stop:
            trailing_stop = potential_stop
        
        if not breakeven_set and price > entry_price * 1.01:
            trailing_stop = max(trailing_stop, entry_price * 1.005)
            breakeven_set = True
        
        if profit_pct > 0.01:
            trailing_stop = max(trailing_stop, entry_price * 1.005)
        if profit_pct > 0.02:
            trailing_stop = max(trailing_stop, entry_price * 1.01)
        if not is_volatile and profit_pct > 0.03:
            trailing_stop = max(trailing_stop, entry_price * 1.02)
        
        if price <= trailing_stop:
            trades.append({'entry': entry_price, 'exit': price, 'pnl_pct': profit_pct, 'reason': 'stop_loss'})
            in_position = False
    
    # Compute metrics
    if not trades:
        return [], 0, 0, 0
    
    total_pnl = sum(t['pnl_pct'] for t in trades)
    wins = [t for t in trades if t['pnl_pct'] > 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    
    # Max drawdown: peak-to-trough decline
    cum_pnl = 0
    peak = 0
    max_dd = 0
    for t in trades:
        cum_pnl += t['pnl_pct']
        peak = max(peak, cum_pnl)
        dd = peak - cum_pnl
        if dd > max_dd:
            max_dd = dd
    
    return trades, total_pnl * 100, max_dd * 100, win_rate


def analyze_other_coins(exchange):
    """
    Analyze non-core portfolio coins (MKR, AAVE, CRO, ALGO, XLM, LTC).
    Compare their historical performance to ETH/BTC to recommend sell/hold.
    """
    print("\n" + "=" * 70)
    print("PORTFOLIO COIN ANALYSIS (Non-Core: MKR, AAVE, CRO, ALGO, XLM, LTC)")
    print("=" * 70)
    print("Comparing historical performance vs ETH/BTC to recommend sell/hold.\n")
    
    # Fetch ETH and BTC as benchmarks
    eth_df = fetch_historical_ohlcv(exchange, 'ETH/USD', days=30)
    btc_df = fetch_historical_ohlcv(exchange, 'BTC/USD', days=30)
    
    if eth_df.empty or btc_df.empty:
        print("⚠️  Could not fetch ETH/BTC benchmark data.")
        return []
    
    eth_start = eth_df['close'].iloc[0]
    eth_end = eth_df['close'].iloc[-1]
    btc_start = btc_df['close'].iloc[0]
    btc_end = btc_df['close'].iloc[-1]
    
    eth_return = (eth_end - eth_start) / eth_start * 100
    btc_return = (btc_end - btc_start) / btc_start * 100
    benchmark_return = (eth_return + btc_return) / 2
    
    print(f"📊 Benchmark (30-day): ETH {eth_return:+.2f}%, BTC {btc_return:+.2f}%")
    print(f"   Average: {benchmark_return:+.2f}%\n")
    
    recommendations = []
    
    for symbol in OTHER_PORTFOLIO_COINS:
        if symbol not in exchange.markets:
            continue
        try:
            df = fetch_historical_ohlcv(exchange, symbol, days=30)
            if df.empty or len(df) < 50:
                recommendations.append({
                    'symbol': symbol,
                    'return_30d': None,
                    'vs_benchmark': None,
                    'recommendation': 'UNKNOWN',
                    'reason': 'Insufficient data'
                })
                continue
            
            start_price = df['close'].iloc[0]
            end_price = df['close'].iloc[-1]
            ret_30d = (end_price - start_price) / start_price * 100
            
            # Volatility (ATR as % of price)
            df_analyzed = analyze_market(df)
            if df_analyzed is not None and len(df_analyzed) > 0:
                last_atr = df_analyzed['atr'].iloc[-1]
                atr_pct = last_atr / end_price * 100 if end_price > 0 else 0
            else:
                atr_pct = 0
            
            # Max drawdown in period
            rolling_max = df['close'].cummax()
            drawdown = (df['close'] - rolling_max) / rolling_max * 100
            max_dd = drawdown.min()
            
            vs_benchmark = ret_30d - benchmark_return if benchmark_return is not None else 0
            
            # Recommendation logic
            if ret_30d < -15 and vs_benchmark < -5:
                rec = 'SELL'
                reason = f"Severe underperformance: {ret_30d:.1f}% vs benchmark {benchmark_return:.1f}%"
            elif ret_30d < -10:
                rec = 'SELL'
                reason = f"Significant loss ({ret_30d:.1f}%), consider reallocating to core coins"
            elif vs_benchmark < -10:
                rec = 'SELL'
                reason = f"Underperforming benchmark by {abs(vs_benchmark):.1f}% - capital better in ETH/BTC"
            elif ret_30d < 0 and vs_benchmark < -5:
                rec = 'CONSIDER SELL'
                reason = f"Underperforming in down market ({vs_benchmark:.1f}% vs benchmark)"
            elif max_dd < -20:
                rec = 'CONSIDER SELL'
                reason = f"High drawdown ({max_dd:.1f}%) - volatile, consider reducing exposure"
            else:
                rec = 'HOLD'
                reason = f"Performance in line or better than benchmark"
            
            recommendations.append({
                'symbol': symbol,
                'return_30d': ret_30d,
                'vs_benchmark': vs_benchmark,
                'max_drawdown': max_dd,
                'atr_pct': atr_pct,
                'recommendation': rec,
                'reason': reason
            })
            
        except Exception as e:
            recommendations.append({
                'symbol': symbol,
                'return_30d': None,
                'vs_benchmark': None,
                'recommendation': 'UNKNOWN',
                'reason': str(e)
            })
    
    return recommendations


def execute_sells(exchange, sell_symbols):
    """Execute market sells for recommended coins. Requires --execute-sells flag."""
    from dotenv import load_dotenv
    load_dotenv()
    api_passphrase = os.getenv('COINBASE_API_PASSPHRASE', '')
    
    for symbol in sell_symbols:
        base = symbol.split('/')[0]
        try:
            balance = exchange.fetch_balance()
            amount = balance.get(base, {}).get('free', 0) or balance.get(base, {}).get('total', 0)
            if amount <= 0:
                print(f"   ⏭️  {symbol}: No balance to sell")
                continue
            # Check min order size
            market = exchange.markets.get(symbol)
            if market:
                min_cost = market.get('limits', {}).get('cost', {}).get('min', 1.0)
                ticker = exchange.fetch_ticker(symbol)
                value = amount * ticker['last']
                if value < min_cost:
                    print(f"   ⏭️  {symbol}: Value ${value:.2f} below min ${min_cost:.2f}")
                    continue
            order = exchange.create_market_sell_order(symbol, amount)
            print(f"   ✅ Sold {amount:.8f} {base} - Order: {order.get('id', 'N/A')}")
        except Exception as e:
            print(f"   ❌ {symbol} sell failed: {e}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Validate algorithm and get portfolio sell recommendations')
    parser.add_argument('--execute-sells', action='store_true', help='Execute sells for SELL-recommended coins (use with caution)')
    args = parser.parse_args()
    
    print("=" * 70)
    print("ALGORITHM VALIDATION - Profit Maximization & Loss Prevention")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    exchange = get_exchange()
    
    # --- 1. Backtest core symbols ---
    print("=" * 70)
    print("1. ALGORITHM BACKTEST (Core Symbols: ETH, BTC, LINK, SHIB)")
    print("=" * 70)
    
    all_results = []
    for symbol in CORE_SYMBOLS:
        if symbol not in exchange.markets:
            print(f"⚠️  {symbol} not available, skipping")
            continue
        print(f"\n📊 Fetching {symbol} (14 days)...")
        df = fetch_historical_ohlcv(exchange, symbol, days=14)
        if df.empty:
            print(f"   No data for {symbol}")
            continue
        print(f"   Loaded {len(df)} candles")
        
        trades, total_pnl, max_dd, win_rate = backtest_symbol(df, symbol)
        base = symbol.split('/')[0]
        
        if trades:
            print(f"\n   [{base}] Backtest Results:")
            print(f"   - Trades: {len(trades)}")
            print(f"   - Total P&L: {total_pnl:+.2f}%")
            print(f"   - Max Drawdown: {max_dd:.2f}%")
            print(f"   - Win Rate: {win_rate:.1f}%")
            
            # Validate profit capture and loss prevention
            losses = [t for t in trades if t['pnl_pct'] < 0]
            avg_loss = sum(t['pnl_pct'] for t in losses) * 100 / len(losses) if losses else 0
            avg_win = sum(t['pnl_pct'] for t in trades if t['pnl_pct'] > 0) * 100
            wins_list = [t for t in trades if t['pnl_pct'] > 0]
            avg_win = avg_win / len(wins_list) if wins_list else 0
            
            print(f"   - Avg Win: {avg_win:+.2f}%")
            print(f"   - Avg Loss: {avg_loss:.2f}%")
            
            # Validation verdict
            profit_ok = total_pnl > 0 or (len(trades) < 3)  # Allow few trades
            loss_ok = max_dd < 8 or not losses  # Max drawdown < 8% is reasonable
            if profit_ok and loss_ok:
                print(f"   ✅ VALIDATION PASSED: Algorithm captures profit, limits drawdown")
            else:
                print(f"   ⚠️  REVIEW: Consider tightening stops or adjusting targets")
            
            all_results.append({
                'symbol': symbol,
                'trades': len(trades),
                'total_pnl': total_pnl,
                'max_dd': max_dd,
                'win_rate': win_rate
            })
        else:
            print(f"   No trades in backtest period (market conditions)")
    
    # --- 2. Portfolio coin sell recommendations ---
    recs = analyze_other_coins(exchange)
    
    if recs:
        print(f"\n{'Symbol':<10} {'30d Return':>12} {'vs Benchmark':>14} {'Max DD':>10} {'Recommendation':<18} {'Reason'}")
        print("-" * 90)
        for r in recs:
            ret_str = f"{r['return_30d']:+.1f}%" if r['return_30d'] is not None else "N/A"
            vs_str = f"{r['vs_benchmark']:+.1f}%" if r.get('vs_benchmark') is not None else "N/A"
            dd_str = f"{r.get('max_drawdown', 0):.1f}%" if r.get('max_drawdown') is not None else "N/A"
            print(f"{r['symbol']:<10} {ret_str:>12} {vs_str:>14} {dd_str:>10} {r['recommendation']:<18} {r['reason'][:40]}")
        
        sell_list = [r['symbol'] for r in recs if r['recommendation'] == 'SELL']
        consider_list = [r['symbol'] for r in recs if r['recommendation'] == 'CONSIDER SELL']
        
        print("\n" + "=" * 70)
        print("SELL RECOMMENDATIONS SUMMARY")
        print("=" * 70)
        if sell_list:
            print(f"\n🔴 SELL (not worth keeping): {', '.join(sell_list)}")
            print("   These coins have underperformed significantly. Consider selling to reallocate to ETH/BTC/LINK/SHIB.")
            if args.execute_sells:
                print(f"\n⚠️  Executing sells for: {', '.join(sell_list)}")
                execute_sells(exchange, sell_list)
        if consider_list:
            print(f"\n🟡 CONSIDER SELLING: {', '.join(consider_list)}")
            print("   Review these positions - may be better to consolidate into core holdings.")
        if not sell_list and not consider_list:
            print("\n✅ No sell recommendations - all non-core coins performing adequately.")
    
    print("\n" + "=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)
    return 0


if __name__ == '__main__':
    sys.exit(main())
