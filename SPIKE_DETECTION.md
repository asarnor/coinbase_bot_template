# Spike Detection & Profit Capture

## 🎯 Problem Solved

Your bot was missing profit opportunities when prices spiked up then reversed. For example:
- Price goes up 5% → Bot doesn't sell (waiting for 3% target)
- Price drops to 2.5% → Bot still doesn't sell (below 3% target)
- Price drops further → Stop-loss triggers → Lost profit opportunity

## ✅ New Features

### 1. **Spike Detection & Reversal Capture**
Tracks the **highest price** reached and sells when price reverses from the peak.

**How it works:**
- Tracks `peak_price` (highest price since entry)
- If price drops **1.5%** from peak → **SELL** (captures profit before it disappears)
- Only activates after **2% profit** (avoids selling on small fluctuations)

**Example:**
```
Entry: $100
Price spikes to $105 (5% profit) → Peak recorded
Price drops to $103.43 (1.5% drop from $105) → SELL at $103.43
Result: Captured 3.43% profit instead of waiting for stop-loss
```

### 2. **Trailing Profit Target**
Dynamic profit target that moves up as price increases.

**How it works:**
- Starts at 3% above entry (static target)
- Moves up as price increases
- Captures more profit if price continues rising

### 3. **Multiple Exit Strategies**

The bot now has **4 ways to exit**:

1. **Static Profit Target** (3%): Original target, always active
2. **Trailing Profit Target**: Moves up with price
3. **Spike Reversal**: Sells on 1.5% drop from peak (after 2% profit)
4. **Stop-Loss**: Protects against losses

## 📊 Configuration

### Environment Variables

```bash
# Spike detection settings
TRADING_SPIKE_REVERSAL_PCT=0.015    # Sell if price drops 1.5% from peak
TRADING_MIN_SPIKE_PROFIT=0.02       # Only activate after 2% profit

# Existing profit target (still works)
TRADING_PROFIT_TARGET_PCT=0.03      # Static 3% target
```

### Default Values

- **Spike Reversal**: 1.5% drop from peak
- **Min Spike Profit**: 2% (must be up 2% before spike detection activates)
- **Profit Target**: 3% (static)

## 🔍 How It Works in Practice

### Scenario 1: Price Spikes Then Reverses
```
Entry: $100
Price → $102 (2% profit) → Spike detection activates
Price → $105 (5% profit) → Peak recorded at $105
Price → $103.43 (1.5% drop from $105) → 🚨 SPIKE REVERSAL → SELL
Result: Captured 3.43% profit ✅
```

### Scenario 2: Price Spikes Then Continues Up
```
Entry: $100
Price → $102 (2% profit) → Spike detection activates
Price → $105 (5% profit) → Peak recorded
Price → $106 (still rising) → Peak updated to $106
Price → $104.41 (1.5% drop from $106) → SELL
Result: Captured 4.41% profit ✅
```

### Scenario 3: Price Hits Static Target
```
Entry: $100
Price → $103 (3% profit) → 💰 PROFIT TARGET REACHED → SELL
Result: Captured 3% profit ✅
```

### Scenario 4: Small Fluctuation (No False Triggers)
```
Entry: $100
Price → $101.50 (1.5% profit) → Spike detection NOT active (needs 2%)
Price → $100.50 (drops) → No sell (below 2% threshold)
Result: Position held, avoids premature exits ✅
```

## 📈 Benefits

1. **Captures Spikes**: Sells when price spikes then reverses
2. **Locks in Profits**: Doesn't let profits disappear
3. **Reduces Losses**: Exits before stop-loss triggers
4. **Smart Activation**: Only activates after meaningful profit (2%)
5. **Multiple Strategies**: 4 different exit methods increase chances of profit

## ⚙️ Tuning Recommendations

### More Aggressive (Capture More Spikes)
```bash
TRADING_SPIKE_REVERSAL_PCT=0.01     # Sell on 1% drop (more sensitive)
TRADING_MIN_SPIKE_PROFIT=0.015      # Activate after 1.5% profit
```

### More Conservative (Avoid False Signals)
```bash
TRADING_SPIKE_REVERSAL_PCT=0.02     # Sell on 2% drop (less sensitive)
TRADING_MIN_SPIKE_PROFIT=0.03       # Activate after 3% profit
```

### Current Settings (Balanced)
```bash
TRADING_SPIKE_REVERSAL_PCT=0.015    # Sell on 1.5% drop
TRADING_MIN_SPIKE_PROFIT=0.02       # Activate after 2% profit
```

## 🚀 Deployment

1. **Code is updated** ✅
2. **No Railway changes needed** - Uses default values
3. **Optional**: Add environment variables to Railway for customization

### To Customize in Railway:

1. Go to Railway → Variables
2. Add:
   ```
   TRADING_SPIKE_REVERSAL_PCT=0.015
   TRADING_MIN_SPIKE_PROFIT=0.02
   ```
3. Railway will auto-redeploy

## 📊 Expected Behavior

After deployment, you'll see logs like:

```
[ETH] Price: $3000.00 | RSI: 58.00 | Stop: $2950.00 | Position: YES
[ETH] 📉 SPIKE REVERSAL DETECTED: Price dropped 1.50% from peak $3050.00
[ETH] 💰 Capturing profit: 3.43% (Peak was 5.00%)
[ETH] ✅ Spike reversal sell executed: abc123
```

## ✅ Summary

**Before:**
- Fixed 3% target only
- Missed spikes that reversed
- Lost profits on reversals

**After:**
- Static 3% target ✅
- Trailing profit target ✅
- Spike reversal detection ✅
- Stop-loss protection ✅

**Result:** Better profit capture, fewer missed opportunities! 🎯

