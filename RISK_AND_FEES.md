# Risk Management with Limit Orders

## Understanding Risk vs Fees

**Limit orders reduce fees, but don't change trade risk.**

However, the fee savings can be strategically used to:
1. **Trade more frequently** (more opportunities)
2. **Increase position sizes** (larger trades)
3. **Trade more symbols** (more diversification)

## Current Risk Controls

Your risk is controlled by:
- `TRADING_RISK_PCT` - Percentage of balance per trade (default: 20%)
- `TRADING_LEVERAGE` - Leverage multiplier (default: 5x)
- `TRADING_MIN_ORDER_SIZE` - Minimum trade size

**Example:**
- Balance: $100
- Risk: 20% = $20 per trade
- With 5x leverage: $100 position value
- **Risk per trade: $20** (not affected by order type)

## How Fee Savings Can Enable More Aggressive Trading

### Scenario: Fee Savings Allow More Capital

**With Market Orders (0.6% fee):**
- Trade $100 → Pay $0.60 fee
- Net capital after fees: $99.40
- Can make ~99 trades before fees eat all capital

**With Limit Orders (0.4% fee):**
- Trade $100 → Pay $0.40 fee  
- Net capital after fees: $99.60
- Can make ~149 trades before fees eat all capital
- **50% more trades possible!**

### Strategic Options

#### Option 1: Increase Position Size
**Current:** 20% risk per trade
**With limit orders:** Could increase to 22-25% risk

**Math:**
- Fee savings: 0.2% per trade
- Over 10 trades: Save 2% in fees
- Can afford slightly larger positions

**Railway Variable:**
```
TRADING_RISK_PCT=0.22  # Increase from 0.20 to 0.22
```

#### Option 2: Trade More Frequently
**Current:** Check every 60 seconds
**With limit orders:** Could check more often

**Math:**
- Lower fees = can afford more trades
- More opportunities = more potential profits

**Railway Variable:**
```
TRADING_CHECK_INTERVAL=30  # Check every 30 seconds instead of 60
```

#### Option 3: Add More Symbols
**Current:** ETH only (or ETH + BTC)
**With limit orders:** Could add more symbols

**Math:**
- Fee savings offset cost of trading more symbols
- Better diversification

**Railway Variable:**
```
TRADING_SYMBOLS=ETH/USD,BTC/USD,SOL/USD  # Add more symbols
```

## Risk Considerations

### ⚠️ Important Notes

1. **Fee savings ≠ Risk reduction**
   - Lower fees don't make trades safer
   - Still subject to market risk

2. **More trades = More exposure**
   - Trading more frequently increases total exposure
   - More symbols = more positions = more risk

3. **Leverage amplifies everything**
   - 5x leverage = 5x risk
   - Fee savings don't reduce leverage risk

## Recommended Approach

### Conservative (Recommended)
- Use limit orders (save fees)
- Keep current risk settings (20% risk, 5x leverage)
- Benefit: Same risk, lower costs = better net returns

### Moderate
- Use limit orders (save fees)
- Increase risk slightly: `TRADING_RISK_PCT=0.22` (22%)
- Benefit: Slightly larger positions, still manageable

### Aggressive
- Use limit orders (save fees)
- Increase risk: `TRADING_RISK_PCT=0.25` (25%)
- Add more symbols
- Benefit: More opportunities, but higher total risk

## Fee Savings Calculation

**Monthly Trading Example:**

**Market Orders:**
- 20 trades × $100 = $2,000 traded
- Fees: $2,000 × 0.6% = $12.00

**Limit Orders:**
- 20 trades × $100 = $2,000 traded  
- Fees: $2,000 × 0.4% = $8.00
- **Savings: $4.00/month**

**With Increased Risk (22%):**
- Same 20 trades, but $110 per trade (22% vs 20%)
- Fees: $2,200 × 0.4% = $8.80
- **Still cheaper than market orders at 20% risk!**

## Best Practice

**Recommended Strategy:**
1. ✅ Enable limit orders (save 33% on fees)
2. ✅ Keep current risk settings initially
3. ✅ Monitor performance for 1-2 weeks
4. ✅ If profitable, consider slight risk increase (22-25%)
5. ✅ Use fee savings to improve net returns

**Don't:**
- ❌ Increase risk just because fees are lower
- ❌ Trade more frequently without strategy
- ❌ Add leverage beyond your comfort zone

## Summary

**Limit orders enable:**
- ✅ Lower costs (33% fee reduction)
- ✅ More capital efficiency
- ✅ Option to trade more aggressively IF desired

**But remember:**
- ⚠️ Risk is still controlled by position size and leverage
- ⚠️ Fee savings don't reduce market risk
- ⚠️ More aggressive = higher potential losses

**Recommendation:** Start with limit orders at current risk, then gradually increase if performance is good.

