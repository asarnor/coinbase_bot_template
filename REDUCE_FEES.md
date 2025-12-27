# How to Reduce Trading Fees

## Current Fee Structure

**Coinbase Advanced Trade Fees:**
- **Maker Orders** (Limit orders): ~0.4% fee
- **Taker Orders** (Market orders): ~0.6% fee
- **Current Bot**: Uses market orders = 0.6% fee per trade

**Fee Impact Example:**
- Trade $100 → Pay $0.60 fee (market order)
- Trade $100 → Pay $0.40 fee (limit order)
- **Savings: $0.20 per $100 trade (33% reduction)**

## Strategies to Reduce Fees

### 1. ✅ Use Limit Orders (BEST OPTION)

**Current:** Market orders (taker) = 0.6% fee
**Better:** Limit orders (maker) = 0.4% fee
**Savings:** 33% reduction in fees

**How it works:**
- Place limit order slightly below current price (buy) or above (sell)
- Order sits in order book (maker order)
- Fills when price reaches your limit
- Lower fee (0.4% vs 0.6%)

**Trade-off:**
- Slightly slower execution (may not fill immediately)
- But saves 33% on fees

### 2. Reduce Trading Frequency

**Current:** Bot checks every 60 seconds
**Better:** Increase check interval

**Options:**
- Increase `TRADING_CHECK_INTERVAL` to 120 or 300 seconds
- Fewer checks = fewer trades = fewer fees
- Still catches good opportunities

### 3. Increase Position Sizes

**Current:** 20% risk per trade
**Better:** Larger positions, fewer trades

**Options:**
- Increase `TRADING_RISK_PCT` to 0.30 or 0.40
- Fewer trades needed to deploy capital
- Same percentage fee, but fewer total trades

### 4. Use Stricter Entry Conditions

**Current:** Already improved with filters
**Better:** Even stricter = fewer trades

**Options:**
- Increase `TRADING_RSI_ENTRY` to 60 or 65
- Increase `TRADING_MIN_TREND_STRENGTH` to 0.02 (2%)
- Only trade in strongest trends

### 5. Coinbase Fee Tiers

**Volume-Based Discounts:**
- Higher 30-day volume = lower fees
- Check your Coinbase fee tier
- May qualify for lower fees automatically

## Recommended Implementation

### Option A: Switch to Limit Orders (Recommended)

**Pros:**
- 33% fee reduction immediately
- No change to trading frequency
- Better for larger orders

**Cons:**
- Slightly slower execution
- Orders may not fill if price moves away

### Option B: Reduce Trading Frequency

**Pros:**
- Fewer trades = fewer fees
- Less API usage
- Still profitable

**Cons:**
- May miss some opportunities
- Slower to enter/exit

### Option C: Combine Both

**Best of both worlds:**
- Limit orders (33% fee reduction)
- Longer check interval (fewer trades)
- Stricter entry conditions (quality over quantity)

## Fee Calculation Example

**Current Setup (Market Orders):**
- 10 trades/month × $100 each = $1,000 traded
- Fees: $1,000 × 0.6% = $6.00/month

**With Limit Orders:**
- 10 trades/month × $100 each = $1,000 traded
- Fees: $1,000 × 0.4% = $4.00/month
- **Savings: $2.00/month (33% reduction)**

**With Reduced Frequency:**
- 5 trades/month × $100 each = $500 traded
- Fees: $500 × 0.6% = $3.00/month
- **Savings: $3.00/month (50% reduction)**

**Combined (Limit + Reduced Frequency):**
- 5 trades/month × $100 each = $500 traded
- Fees: $500 × 0.4% = $2.00/month
- **Savings: $4.00/month (67% reduction)**

## Quick Wins

1. **Switch to limit orders** - 33% fee reduction
2. **Increase check interval** - Fewer trades
3. **Stricter entry conditions** - Quality over quantity

## Next Steps

See implementation guide for switching to limit orders.

