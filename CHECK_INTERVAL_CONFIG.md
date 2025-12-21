# Check Interval Configuration

The bot's check frequency is now configurable via the `TRADING_CHECK_INTERVAL` environment variable.

## Default Behavior

- **Default**: 60 seconds (1 minute)
- The bot checks the market, analyzes indicators, and executes trades every 60 seconds

## Configuration

### Via Environment Variable (Recommended)

Add to your `.env` file or cloud platform environment variables:

```bash
TRADING_CHECK_INTERVAL=60  # Check every 60 seconds
```

### Common Values

- **30 seconds**: `TRADING_CHECK_INTERVAL=30` - More frequent checks
- **60 seconds**: `TRADING_CHECK_INTERVAL=60` - Default (recommended)
- **120 seconds**: `TRADING_CHECK_INTERVAL=120` - Every 2 minutes
- **300 seconds**: `TRADING_CHECK_INTERVAL=300` - Every 5 minutes

### Examples

**Faster checking (30 seconds):**
```bash
export TRADING_CHECK_INTERVAL=30
python main.py --execute
```

**Slower checking (5 minutes):**
```bash
export TRADING_CHECK_INTERVAL=300
python main.py --execute
```

## Considerations

### API Rate Limits
- Coinbase Advanced Trade has rate limits
- 60 seconds is safe and recommended
- Shorter intervals (30 seconds) may approach rate limits
- Very short intervals (< 15 seconds) may cause rate limit errors

### Data Freshness
- Your timeframe is `5m` (5-minute candles)
- Checking every 60 seconds is appropriate for 5-minute data
- Checking more frequently than your timeframe doesn't provide new data

### Resource Usage
- More frequent checks = more API calls
- More API calls = higher resource usage
- Consider your cloud platform's limits and costs

## Verification

When the bot starts, you'll see:
```
⏱️  Check Interval: 60 seconds
```

This confirms the check interval is set correctly.

## Best Practices

1. **Start with default (60 seconds)** - Test and verify everything works
2. **Monitor API usage** - Check if you're hitting rate limits
3. **Adjust based on strategy** - Faster for scalping, slower for swing trading
4. **Consider timeframe** - Don't check more frequently than your candle timeframe

## Troubleshooting

**Bot seems slow?**
- Check your `TRADING_CHECK_INTERVAL` value
- Verify it's not set too high (e.g., 3600 = 1 hour)

**Rate limit errors?**
- Increase `TRADING_CHECK_INTERVAL` to 120 or higher
- Check Coinbase API documentation for current rate limits

**Want faster execution?**
- Decrease to 30 seconds (be careful of rate limits)
- Consider if your strategy actually needs faster checks

