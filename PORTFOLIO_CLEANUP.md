# Portfolio Cleanup Script

Automatically analyzes your portfolio and identifies positions to sell based on:

1. **Dust cleanup** (very small holdings)
2. **Historical strategy validation** (coins that fail uptrend capture/crash protection checks)

It preserves your core assets by default: **ETH, BTC, LINK, SHIB**.

## What It Does

1. **Analyzes Portfolio**: Fetches balances and estimates USD value per asset
2. **Identifies Dust Positions**: Marks positions worth less than a minimum threshold (default: $5)
3. **Validates Strategy History**: Backtests non-core coins using recent history (default: 120 days @ 1h candles)
4. **Scores Risk/Reward**:
   - Uptrend capture (profit when coins rally)
   - Crash protection (loss control during sharp drops)
   - Max drawdown and strategy return
5. **Preserves Core Assets**: Keeps ETH, BTC, LINK, SHIB even if they would otherwise be sold

## Usage

### Basic Usage (Dry Run)
```bash
# Shows what would be sold (no real orders)
python cleanup_portfolio.py
```

### Execute Real Sells
```bash
python cleanup_portfolio.py --execute
```

### Dust-only Mode (Skip History Validation)
```bash
python cleanup_portfolio.py --skip-history-check
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

- `MIN_POSITION_VALUE_USD` (default: `5.00`)
  - Sell non-priority positions below this USD value

- `PRIORITY_CURRENCIES` (default: `ETH,BTC,LINK,SHIB`)
  - Comma-separated assets that are always kept

- `HISTORY_VALIDATION_TIMEFRAME` (default: `1h`)
  - Candle timeframe for backtesting non-core holdings

- `HISTORY_VALIDATION_LOOKBACK_DAYS` (default: `120`)
  - Number of days used in historical validation

- `HISTORY_VALIDATION_MIN_BARS` (default: `200`)
  - Minimum candles required to score a coin

- `HISTORY_VALIDATION_MIN_SCORE` (default: `60`)
  - Minimum historical score (0-100) to keep a non-core coin

### What Gets Sold

✅ **Will Sell:**
- Positions worth less than `MIN_POSITION_VALUE_USD`
- Non-core positions with weak historical score
- Only sells "free" balance (not locked in orders)
- Skips assets with no supported sell pair

❌ **Will NOT Sell:**
- ETH, BTC, LINK, SHIB (priority assets by default)
- USD/USDC
- Non-core positions with strong historical score

## Example Output

```
========================================================================================================================
POSITION ANALYSIS
========================================================================================================================
Currency           Amount      Value USD    Score     Action Reason
------------------------------------------------------------------------------------------------------------------------
ETH            0.12540000       $320.50        -       KEEP Core priority asset
LINK           9.10000000       $180.33        -       KEEP Core priority asset
MKR            0.02200000        $42.15     71.3       KEEP History strong: score=71.3, uptrend=0.82, return=9.4%
ALGO         350.00000000        $69.20     42.8       SELL History weak: score=42.8, uptrend=0.27, crash=0.08, return=-12.3%
AMP          420.00000000         $2.64        -       SELL Small position (< $5.00)
...
------------------------------------------------------------------------------------------------------------------------
💵 Current USD Balance: $87.12
📊 Positions to keep: 12
🗑️  Positions to sell: 4
💰 Estimated USD after sales: $159.88
🔍 Mode: DRY RUN (no orders)
```

## Integration Options

### Option 1: Run Manually
Dry-run first, then execute:
```bash
python cleanup_portfolio.py
python cleanup_portfolio.py --execute
```

### Option 2: Schedule Automatically
Add to cron or scheduled task to run periodically:
```bash
# Run daily at 2 AM (dry-run)
0 2 * * * cd /path/to/bot && python cleanup_portfolio.py
```

### Option 3: Integrate into Main Bot
You can call this script periodically from your main automation flow.

## Safety Features

- ✅ Dry-run by default (no accidental sells)
- ✅ Only sells "free" balance (not locked in open orders)
- ✅ Checks minimum order sizes before selling
- ✅ Preserves ETH/BTC/LINK/SHIB by default
- ✅ Prints score + reason for each action
- ✅ Reports success/failure for each sale

## Tips

1. **Dry-run first**: Review the action table before using `--execute`.
2. **Tune strictness**: Increase `HISTORY_VALIDATION_MIN_SCORE` to sell more aggressively.
3. **Adjust lookback**: Use 180-365 days for longer-term filters.
4. **Check supported pairs**: Some assets may only trade in cross pairs.
5. **Monitor results**: Track freed USD and strategy performance over time.

## Troubleshooting

**No positions to sell?**
- All non-core positions passed historical checks
- Or all positions are above the dust threshold and healthy
- Or you only hold priority assets

**Sales failing?**
- Check if market pairs exist for those currencies
- Some positions may be below Coinbase minimum order size
- Verify API permissions include Trade

**Want to keep specific coins?**
- Add them to `PRIORITY_CURRENCIES` in `.env` or with `--priority-currencies`
- Lower `HISTORY_VALIDATION_MIN_SCORE` to keep more assets


