# Multi-Symbol Trading Bot

Trade multiple cryptocurrencies (ETH, BTC, etc.) simultaneously with a single bot instance.

## Overview

The `main_multi_symbol.py` script allows you to trade multiple symbols at the same time, each with independent position tracking and stop-loss management.

## Features

- ✅ **Multiple Symbols**: Trade ETH, BTC, and other pairs simultaneously
- ✅ **Independent Positions**: Each symbol has its own position tracking
- ✅ **Risk Distribution**: Risk is divided equally across all symbols
- ✅ **Separate Stop-Losses**: Each position has its own trailing stop-loss
- ✅ **Efficient**: Single bot instance manages all symbols

## Configuration

### Environment Variables

Add to your `.env` file or Railway Variables:

```bash
# Trading symbols (comma-separated)
TRADING_SYMBOLS=ETH/USD,BTC/USD

# Other settings (same as main bot)
TRADING_TIMEFRAME=5m
TRADING_LEVERAGE=5
TRADING_RISK_PCT=0.20  # Total risk, divided across symbols
TRADING_ATR_MULTIPLIER=1.5
TRADING_CHECK_INTERVAL=60
TRADING_MIN_ORDER_SIZE=1.00
```

### Risk Distribution

If you set `TRADING_RISK_PCT=0.20` (20%) and trade 2 symbols:
- **Total risk**: 20% of balance
- **Per symbol**: 10% of balance (20% ÷ 2)

Example with $100 balance:
- ETH trade: $10 (10% of $100)
- BTC trade: $10 (10% of $100)
- **Total at risk**: $20 (20%)

## Usage

### Local Testing

```bash
# Test mode (no real trades)
python main_multi_symbol.py --test

# Sandbox mode
python main_multi_symbol.py --sandbox

# Production with real trades
python main_multi_symbol.py --execute
```

### Railway Deployment

1. **Update Railway Variables:**
   ```
   TRADING_SYMBOLS=ETH/USD,BTC/USD
   ```

2. **Update Dockerfile** (or create new one):
   ```dockerfile
   CMD ["python", "main_multi_symbol.py", "--execute"]
   ```

3. **Deploy** - Railway will auto-deploy

## Example Output

```
🔌 Connecting to PRODUCTION...
✅ Connected to Coinbase Advanced Trade successfully.
📊 Trading symbols: ETH/USD, BTC/USD
🛡️ Active. Risking 20.0% total (10.0% per symbol) of balance per trade.

[ETH] Price: $2970.00 | RSI: 58.95 | Stop: $0.00 | Position: NO
[BTC] Price: $88960.00 | RSI: 55.20 | Stop: $0.00 | Position: NO

[ETH] 🚀 ENTER LONG: Buying 0.021696 ETH (Cost: $10.00)
[ETH] ✅ Order executed: abc123...

[ETH] Price: $2971.00 | RSI: 59.81 | Stop: $2961.53 | Position: YES
[BTC] Price: $89000.00 | RSI: 56.20 | Stop: $0.00 | Position: NO

[BTC] 🚀 ENTER LONG: Buying 0.000112 BTC (Cost: $10.00)
[BTC] ✅ Order executed: def456...

[ETH] Price: $2970.00 | RSI: 63.50 | Stop: $2964.78 | Position: YES
[BTC] Price: $89100.00 | RSI: 57.20 | Stop: $88800.00 | Position: YES
```

## Comparison: Single vs Multi-Symbol

### Single Symbol (`main.py`)
- ✅ Simpler
- ✅ Easier to understand
- ❌ Only trades one asset at a time
- ❌ Need multiple instances for multiple symbols

### Multi-Symbol (`main_multi_symbol.py`)
- ✅ Trade multiple assets simultaneously
- ✅ More efficient (single instance)
- ✅ Better diversification
- ❌ Slightly more complex
- ❌ Risk is divided (smaller per-symbol positions)

## Options

### Option 1: Use Multi-Symbol Bot (Recommended)

**Pros:**
- Single bot instance
- Better resource usage
- Easier to manage
- Automatic risk distribution

**Cons:**
- Risk divided across symbols (smaller positions)

**Best for:** Most users who want to trade multiple assets

### Option 2: Run Multiple Instances

**Pros:**
- Full risk per symbol (not divided)
- Independent control
- Can use different strategies per symbol

**Cons:**
- More resource usage
- More complex to manage
- Need separate deployments/configs

**How to do it:**

1. **Railway**: Create multiple services, each with different `TRADING_SYMBOL`
2. **Local**: Run multiple terminal windows:
   ```bash
   # Terminal 1
   export TRADING_SYMBOL=ETH/USD
   python main.py --execute

   # Terminal 2
   export TRADING_SYMBOL=BTC/USD
   python main.py --execute
   ```

## Recommended Setup

For most users, **use the multi-symbol bot**:

1. Set `TRADING_SYMBOLS=ETH/USD,BTC/USD`
2. Set `TRADING_RISK_PCT=0.20` (20% total, 10% per symbol)
3. Deploy `main_multi_symbol.py` instead of `main.py`

This gives you:
- Diversification across assets
- Efficient resource usage
- Single bot to manage
- Automatic risk distribution

## Troubleshooting

**Symbols not trading?**
- Check symbols are comma-separated: `ETH/USD,BTC/USD`
- Verify symbols exist on Coinbase
- Check minimum order sizes

**Positions too small?**
- Increase `TRADING_RISK_PCT` (total risk)
- Or reduce number of symbols
- Or add more USD balance

**Want different risk per symbol?**
- Currently risk is divided equally
- For different risks, use multiple instances

## Migration from Single Symbol

If you're currently using `main.py`:

1. **Update environment variable:**
   ```
   # Change from:
   TRADING_SYMBOL=ETH/USD
   
   # To:
   TRADING_SYMBOLS=ETH/USD,BTC/USD
   ```

2. **Update Dockerfile** (if deployed):
   ```dockerfile
   CMD ["python", "main_multi_symbol.py", "--execute"]
   ```

3. **Redeploy** - That's it!

Your existing positions will continue to be managed, and new trades will use the multi-symbol logic.

