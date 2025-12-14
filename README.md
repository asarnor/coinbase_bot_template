# Coinbase Trading Bot Template

An automated trading bot for Coinbase Pro/Advanced Trade (available in **Python** and **JavaScript/Node.js**) that uses technical indicators (EMA, RSI, ATR) to execute trading strategies with risk management and trailing stop-loss protection.

## Features

- **Technical Analysis**: Uses EMA (20-period), RSI (14-period), and ATR (14-period) indicators
- **Risk Management**: Configurable position sizing based on account balance percentage
- **Trailing Stop Loss**: ATR-based trailing stop for crash protection
- **Leverage Support**: Configurable leverage for futures trading
- **Real-time Monitoring**: Continuous market analysis with 60-second intervals

## Prerequisites

**For Python version:**
- Python 3.7 or higher
- Coinbase Pro/Advanced Trade account with API access
- API credentials (API Key, Secret, and Passphrase)

**For JavaScript version:**
- Node.js 15.0 or higher (ES modules support)
- npm (comes with Node.js)
- Coinbase Pro/Advanced Trade account with API access
- API credentials (API Key, Secret, and Passphrase)

## Installation

1. **Clone the repository** (or download the files):
   ```bash
   git clone <repository-url>
   cd coinbase_bot_template
   ```

### Python Version

2. **Create a virtual environment** (recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install required dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
   
   Or install manually:
   ```bash
   pip install ccxt pandas pandas-ta-classic
   ```
   
   **Note**: We use `pandas-ta-classic` (community fork) as the original `pandas-ta` library is no longer free/open source.

### JavaScript Version

2. **Install Node.js dependencies**:
   ```bash
   npm install
   ```
   
   This will install:
   - `ccxt` - Exchange API library
   - `technicalindicators` - Technical analysis indicators
   - `yargs` - Command-line argument parsing

**Note**: Both Python and JavaScript versions provide identical functionality. Choose the version you're most comfortable with!

## Configuration

### 1. Get Coinbase API Credentials

1. Log in to your Coinbase Pro/Advanced Trade account
2. Navigate to **Settings** → **API** → **New API Key**
3. Create an API key with appropriate permissions:
   - **View** (required)
   - **Trade** (required for executing orders)
   - **Transfer** (optional, only if needed)
4. Save your **API Key**, **Secret**, and **Passphrase** securely

⚠️ **Important**: Never share your API credentials or commit them to version control.

### 2. Configure the Bot

**Recommended: Use Environment Variables (.env file)**

The bot supports environment variables for secure credential storage. You have **three options**:

### Option 1: Single .env file (Simplest)

Use one `.env` file for both sandbox and production:

1. **Copy the example environment file**:
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env`** and add your API credentials:
   ```bash
   COINBASE_API_KEY=your_api_key
   COINBASE_API_SECRET=your_secret
   COINBASE_API_PASSPHRASE=your_passphrase
   ```

### Option 2: Separate files for Sandbox and Production (Recommended)

Use different API keys for sandbox vs production:

1. **Copy the example files**:
   ```bash
   cp .env.sandbox.example .env.sandbox
   cp .env.production.example .env.production
   ```

2. **Edit each file** with the appropriate credentials:
   - `.env.sandbox` - Your sandbox/test API credentials
   - `.env.production` - Your production API credentials

3. **The bot automatically loads the correct file**:
   - When using `--sandbox` or `--test`: loads `.env.sandbox`
   - When running in production: loads `.env.production`
   - Falls back to `.env` if environment-specific file doesn't exist

### Option 3: System Environment Variables

Set environment variables directly in your system (useful for CI/CD):
```bash
export COINBASE_API_KEY=your_key
export COINBASE_API_SECRET=your_secret
export COINBASE_API_PASSPHRASE=your_passphrase
```

**Note**: All `.env*` files are automatically ignored by git (already in `.gitignore`)

**Alternative: Hardcode in Source Files**

If you prefer not to use `.env` files, you can still configure directly in the source files:

**For Python version**, open `main.py` and update:

```python
# Trading Configuration
symbol = 'ETH/USD'       # Trading pair
timeframe = '5m'         # Candle timeframe
leverage = 5             # Leverage multiplier
risk_pct = 0.20          # Risk percentage per trade (20%)
atr_multiplier = 1.5     # ATR multiplier for stop loss

# API Credentials
api_key = 'YOUR_API_KEY'
api_secret = 'YOUR_SECRET_KEY'
api_passphrase = 'YOUR_PASSPHRASE'
```

**For JavaScript version**, open `main.js` and update:

```javascript
// Trading Configuration
const symbol = 'ETH/USD';       // Trading pair
const timeframe = '5m';         // Candle timeframe
const leverage = 5;             // Leverage multiplier
const riskPct = 0.20;           // Risk percentage per trade (20%)
const atrMultiplier = 1.5;      // ATR multiplier for stop loss

// API Credentials
const apiKey = 'YOUR_API_KEY';
const apiSecret = 'YOUR_SECRET_KEY';
const apiPassphrase = 'YOUR_PASSPHRASE';
```

**Note**: Environment variables take priority over hardcoded values. If both are set, the `.env` file values will be used.

### 3. Sandbox vs Production

The bot supports command-line flags for easy testing. Use `--sandbox` flag to test in Coinbase's sandbox environment, or `--test` for comprehensive testing (automatically uses sandbox).

⚠️ **Warning**: Always test in sandbox mode first before using real funds!

## Running the Bot

### Test Mode (Recommended First)

Run comprehensive tests to verify connection and functionality:

**Python:**
```bash
python main.py --test
```

**JavaScript:**
```bash
node main.js --test
# or
npm test
```

This will:
- ✅ Test connection to Coinbase (sandbox mode)
- ✅ Verify API credentials
- ✅ Check market data fetching
- ✅ Test balance retrieval
- ✅ Test market analysis
- ✅ Simulate trade execution (dry run)

**See `TESTING.md` for detailed testing instructions.**

### Sandbox Mode (Simulated Trading)

Run the bot in sandbox with simulated trading (no real orders):

**Python:**
```bash
python main.py --sandbox
```

**JavaScript:**
```bash
node main.js --sandbox
# or
npm run sandbox
```

The bot will:
- Connect to Coinbase Pro sandbox
- Monitor the market every 60 seconds
- Show entry/exit signals
- Simulate trades (won't execute real orders)
- Display price, RSI, and stop-loss levels

### Production Mode

⚠️ **Before enabling production trading:**

1. **Test thoroughly** in sandbox mode (`--test` and `--sandbox`)
2. **Review the trading logic** and ensure you understand the strategy
3. **Start with small amounts** to verify behavior
4. **Monitor closely** during initial runs

To enable real trading, use the `--execute` flag:

**Python:**
```bash
# Sandbox with real sandbox trades (recommended for final testing)
python main.py --sandbox --execute

# Production with real trades (USE WITH EXTREME CAUTION!)
python main.py --execute
```

**JavaScript:**
```bash
# Sandbox with real sandbox trades (recommended for final testing)
node main.js --sandbox --execute

# Production with real trades (USE WITH EXTREME CAUTION!)
node main.js --execute
```

**Command-line options:**
- `--test` or `-t` - Run comprehensive tests (auto-enables sandbox)
- `--sandbox` or `-s` - Use sandbox environment
- `--execute` or `-e` - Enable actual trade execution (use with caution!)

## Trading Strategy

The bot implements the following strategy:

### Entry Conditions (Long Position)
- Price is above the 20-period EMA (trend filter)
- RSI is above 50 (momentum filter)

### Exit Conditions
- Trailing stop-loss triggered (price drops below ATR-based trailing stop)
- Stop-loss adjusts upward as price increases (never moves down)

### Risk Management
- Position size calculated as: `(Account Balance × Risk %) × Leverage`
- Stop-loss distance: `Current Price - (ATR × Multiplier)`

## Monitoring

The bot outputs real-time information:
- Current price
- RSI value
- Trailing stop-loss price
- Entry/exit signals
- Position status

Example output:
```
✅ Connected to Coinbase Pro successfully.
⚡ Leverage set to 5x.
🛡️ Active. Risking 20.0% of balance per trade.
📉 Crash Protection: ATR Trailing Stop active.
Price: $2450.50 | RSI: 55.30 | Stop: $0.00
🚀 ENTER LONG: Buying 0.1020 ETH (Cost: $50.00)
Price: $2460.75 | RSI: 56.20 | Stop: $2435.00
```

## Troubleshooting

### Connection Errors
- Verify your API credentials are correct
- Check that your API key has the required permissions
- Ensure your IP address is whitelisted (if required by Coinbase)
- Try using sandbox mode first

### Trading Errors
- Ensure you have sufficient balance
- Verify the trading pair symbol is correct (e.g., 'ETH/USD' not 'ETH/USDT')
- Check that leverage is supported for your account type
- Review Coinbase's trading limits and restrictions

### Import Errors

**Python:**
- Ensure all dependencies are installed: `pip install -r requirements.txt`
- Verify you're using the correct Python version (3.7+)
- If you see `ModuleNotFoundError: No module named 'pandas_ta'`, ensure you installed `pandas-ta-classic` (the package name in requirements.txt)
- If you see `ModuleNotFoundError: No module named 'dotenv'`, run `pip install python-dotenv`

**JavaScript:**
- Ensure all dependencies are installed: `npm install`
- Verify you're using Node.js 15.0+ (for ES modules support)
- If you see module errors, try deleting `node_modules` and `package-lock.json`, then run `npm install` again
- If environment variables aren't loading, ensure you've created a `.env` file from `.env.example`

## Important Disclaimers

⚠️ **Trading Risk Warning**: 
- Cryptocurrency trading involves substantial risk of loss
- This bot is provided as a template/example
- Past performance does not guarantee future results
- Always test thoroughly before using real funds
- Never invest more than you can afford to lose

⚠️ **Security Best Practices**:
- **Use `.env` files** for API credentials (recommended) - they're automatically excluded from git
- Never commit API credentials to version control
- Never commit `.env` files (already in `.gitignore`)
- Use environment variables or secure credential storage
- Enable 2FA on your Coinbase account
- Regularly rotate API keys
- Use IP whitelisting if available
- Keep your `.env` file secure and never share it

## License

This project is provided as-is for educational purposes. Use at your own risk.

## Testing

For detailed testing instructions, see **[TESTING.md](TESTING.md)** which includes:
- Step-by-step testing guide
- Connection testing
- Trade execution testing (sandbox)
- Troubleshooting common issues

## Python vs JavaScript Version

Both versions provide **identical functionality**:

| Feature | Python | JavaScript |
|---------|--------|------------|
| Technical Indicators | ✅ EMA, RSI, ATR | ✅ EMA, RSI, ATR |
| Risk Management | ✅ | ✅ |
| Trailing Stop Loss | ✅ | ✅ |
| Sandbox Support | ✅ | ✅ |
| Test Mode | ✅ | ✅ |
| Command-line Args | ✅ | ✅ |

**Choose based on your preference:**
- **Python**: Better for data analysis, easier integration with pandas/ML libraries
- **JavaScript**: Better for web integrations, async/await patterns, Node.js ecosystem

Both versions use the same CCXT library under the hood, so API compatibility is identical.

## Support

For issues related to:
- **Coinbase API**: Check [Coinbase Pro API Documentation](https://docs.pro.coinbase.com/)
- **CCXT Library**: Check [CCXT Documentation](https://docs.ccxt.com/)
- **Python pandas-ta-classic**: Check [pandas-ta-classic GitHub](https://github.com/xgboosted/pandas-ta-classic)
- **JavaScript technicalindicators**: Check [technicalindicators GitHub](https://github.com/anandanand84/technicalindicators)
- **Bot Logic**: Review the code and modify as needed for your use case
