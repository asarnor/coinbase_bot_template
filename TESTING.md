# Testing Guide

This guide will help you test the Coinbase bot locally to verify the connection and trade execution.

## Prerequisites

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure API credentials** in `main.py`:
   ```python
   api_key = 'YOUR_API_KEY'
   api_secret = 'YOUR_SECRET_KEY'
   api_passphrase = 'YOUR_PASSPHRASE'
   ```

3. **Get Coinbase API credentials**:
   - Log in to Coinbase Pro/Advanced Trade
   - Go to Settings → API → New API Key
   - Create API key with **View** and **Trade** permissions
   - Save your credentials securely

## Step 1: Test Connection (Dry Run)

Run the bot in test mode to verify the connection without executing any trades:

```bash
python main.py --test
```

This will:
- ✅ Test connection to Coinbase (sandbox mode)
- ✅ Verify API credentials
- ✅ Check market data fetching
- ✅ Test balance retrieval
- ✅ Test market analysis
- ✅ Simulate trade execution (dry run)

**Expected output:**
```
🧪 TEST MODE ENABLED
============================================================
🔌 Connecting to SANDBOX...
✅ Connected to Coinbase Pro successfully.
📊 Loaded XXX markets
✅ Symbol ETH/USD is available

============================================================
RUNNING TESTS
============================================================

💰 Testing Balance Fetch...
✅ Balance fetched successfully
   USD - Free: $X.XX, Used: $X.XX, Total: $X.XX

📈 Testing Data Fetch...
✅ Data fetched successfully (100 candles)
   Latest price: $XXXX.XX

🔍 Testing Market Analysis...
✅ Analysis complete
   Price: $XXXX.XX
   EMA 20: $XXXX.XX
   RSI: XX.XX
   ATR: $XX.XX

🧪 Testing Trade Execution...
   Current ETH/USD price: $XXXX.XX
   Calculated position size: X.XXXXXX ETH/USD
   Margin to use: $XX.XX
   Position value (with 5x leverage): $XXX.XX
   (Trading disabled - use --execute flag to enable)
   Would execute: BUY X.XXXXXX ETH/USD

============================================================
TEST COMPLETE
============================================================
```

## Step 2: Test Trade Execution (Sandbox)

⚠️ **Important**: Always test in sandbox mode first!

To test actual trade execution in the sandbox environment:

```bash
python main.py --test --execute
```

This will:
- Connect to Coinbase sandbox
- Execute a test buy order
- Show order details
- Attempt to cancel the order (if possible)

**What happens:**
1. The bot calculates a position size based on your balance
2. Executes a market buy order
3. Shows order confirmation with order ID
4. Attempts to cancel the order (for cleanup in sandbox)

**Expected output:**
```
🧪 TEST MODE ENABLED
...
🧪 Testing Trade Execution...
   Current ETH/USD price: $XXXX.XX
   Calculated position size: X.XXXXXX ETH/USD
   Margin to use: $XX.XX
   Position value (with 5x leverage): $XXX.XX

⚠️  EXECUTING TEST TRADE (Sandbox: True)...
   Order: BUY X.XXXXXX ETH/USD at market price
✅ Order executed successfully!
   Order ID: XXXXX-XXXXX-XXXXX
   Status: filled
   Amount: X.XXXXXX
   Price: $XXXX.XX
✅ Test order cancelled (sandbox cleanup)
```

## Step 3: Test Production Connection (No Trading)

To test connection to production without executing trades:

```bash
python main.py --test --sandbox=false
```

⚠️ **Warning**: This connects to production. Make sure you don't use `--execute` flag!

## Step 4: Run Live Bot (Simulated Trading)

To run the bot in live mode with simulated trading (no actual orders):

```bash
python main.py --sandbox
```

The bot will:
- Monitor the market every 60 seconds
- Show entry/exit signals
- Simulate trades (won't execute real orders)
- Display price, RSI, and stop-loss levels

## Step 5: Run Live Bot (Real Trading)

⚠️ **EXTREME CAUTION**: This will execute real trades with real money!

Only enable this after:
- ✅ Thoroughly tested in sandbox
- ✅ Verified all logic works correctly
- ✅ Confirmed you understand the strategy
- ✅ Started with small amounts

```bash
python main.py --execute
```

**Or for sandbox with execution:**
```bash
python main.py --sandbox --execute
```

## Troubleshooting

### Connection Errors

**Error: "Connection Error: Invalid API credentials"**
- Verify your API key, secret, and passphrase are correct
- Check that your API key has the required permissions
- Ensure you're using the correct passphrase (not your account password)

**Error: "Symbol ETH/USD not found"**
- Check available symbols: The test will show available ETH pairs
- Coinbase Pro uses `ETH/USD` (not `ETH/USDT`)
- Verify the symbol format matches exactly

### Balance Errors

**Error: "No USD/USDC balance available"**
- Ensure you have USD or USDC in your account
- For sandbox: You may need to deposit test funds
- Check your account balance on Coinbase

### Trading Errors

**Error: "Insufficient funds"**
- Verify you have enough balance for the position
- Check that leverage is set correctly
- Reduce `risk_pct` if needed

**Error: "Order failed"**
- Check API permissions (must have Trade permission)
- Verify market is open (some markets have trading hours)
- Check minimum order size requirements

## Command Line Options

| Flag | Description |
|------|-------------|
| `--test` | Run in test mode (single run, verbose output, auto-enables sandbox) |
| `--sandbox` | Use sandbox environment (recommended for testing) |
| `--execute` | Enable actual trade execution (use with extreme caution!) |

**Common combinations:**
- `--test` - Test everything in sandbox (dry run)
- `--test --execute` - Test trade execution in sandbox
- `--sandbox` - Run live bot in sandbox (simulated trading)
- `--sandbox --execute` - Run live bot in sandbox (real sandbox trades)
- `--execute` - Run live bot in production (REAL MONEY - use with caution!)

## Next Steps

After successful testing:
1. Review the trading strategy in `main.py`
2. Adjust risk parameters (`risk_pct`, `atr_multiplier`, etc.)
3. Test with different symbols or timeframes
4. Monitor performance in sandbox before going live
5. Start with small amounts when going to production

## Safety Reminders

- ⚠️ **Never commit API credentials** to version control
- ⚠️ **Always test in sandbox first**
- ⚠️ **Start with small amounts** in production
- ⚠️ **Monitor closely** during initial runs
- ⚠️ **Understand the strategy** before enabling real trading
- ⚠️ **Use stop-losses** and risk management (already built-in)
