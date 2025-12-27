# Portfolio Cleanup Script

Automatically analyzes your portfolio and sells small/irrelevant positions to USD, freeing up capital for trading ETH, Bitcoin, and other valuable assets.

## What It Does

1. **Analyzes Portfolio**: Fetches all your positions and their USD values
2. **Identifies Small Positions**: Finds positions worth less than a minimum threshold (default: $5)
3. **Sells to USD**: Automatically sells small positions to free up trading capital
4. **Preserves Priority Assets**: Keeps BTC and ETH even if small

## Usage

### Basic Usage
```bash
python cleanup_portfolio.py
```

### With Custom Minimum Value
```bash
export MIN_POSITION_VALUE_USD=10.00
python cleanup_portfolio.py
```

Or add to `.env`:
```
MIN_POSITION_VALUE_USD=10.00
```

## Configuration

### Environment Variables

- `MIN_POSITION_VALUE_USD` (default: $5.00)
  - Positions worth less than this will be sold
  - Adjust based on your preference

### What Gets Sold

✅ **Will Sell:**
- Positions worth less than `MIN_POSITION_VALUE_USD`
- Only sells "free" balance (not locked in orders)
- Skips if no USD trading pair available

❌ **Will NOT Sell:**
- BTC (Bitcoin) - Priority currency
- ETH (Ethereum) - Priority currency  
- USD/USDC - Base currencies
- Positions above minimum value

## Example Output

```
======================================================================
PORTFOLIO ANALYSIS
======================================================================
Currency        Amount              Price        Value USD         Action
----------------------------------------------------------------------
SHIB    21242915.06476066    $0.000012      $254.92         KEEP
SUSHI         0.00715916    $0.302600        $0.00    SELL (Too Small)
AMP           923.75091793    $0.001234        $1.14    SELL (Too Small)
...
======================================================================

💵 Current USD Balance: $87.12
📊 Positions to keep: 15
🗑️  Positions to sell: 8
💰 Estimated USD after sales: $95.50
```

## Integration Options

### Option 1: Run Manually
Run the script whenever you want to clean up your portfolio:
```bash
python cleanup_portfolio.py
```

### Option 2: Schedule Automatically
Add to cron or scheduled task to run periodically:
```bash
# Run daily at 2 AM
0 2 * * * cd /path/to/bot && python cleanup_portfolio.py
```

### Option 3: Integrate into Main Bot
You could add this as a periodic function in `main.py` to run automatically.

## Safety Features

- ✅ Only sells "free" balance (not locked in orders)
- ✅ Checks minimum order sizes before selling
- ✅ Preserves BTC and ETH
- ✅ Skips positions without trading pairs
- ✅ Shows detailed analysis before selling
- ✅ Reports success/failure for each sale

## Tips

1. **Start Conservative**: Use a low `MIN_POSITION_VALUE_USD` ($1-5) initially
2. **Review Before Selling**: The script shows what will be sold before executing
3. **Check Trading Pairs**: Some small coins may not have USD pairs (will be skipped)
4. **Monitor Results**: Check the summary to see how much USD was freed up

## Troubleshooting

**No positions to sell?**
- All your positions are above the minimum value (good!)
- Or you only have BTC/ETH which are preserved

**Sales failing?**
- Check if trading pairs exist for those currencies
- Some positions may be below Coinbase's minimum order size
- Check API permissions (needs Trade permission)

**Want to keep specific coins?**
- Add them to `PRIORITY_CURRENCIES` list in the script
- Or increase `MIN_POSITION_VALUE_USD` threshold


