# Adding LINK and SHIB to Trading List

## ✅ What Changed

**Current Trading List:**
- ETH/USD
- BTC/USD

**New Trading List:**
- ETH/USD
- BTC/USD
- LINK/USD
- SHIB/USD

## 🚀 How to Update

### In Railway:

1. Go to your Railway project
2. Click on **Variables** tab
3. Find `TRADING_SYMBOLS`
4. Update it to:
   ```
   TRADING_SYMBOLS=ETH/USD,BTC/USD,LINK/USD,SHIB/USD
   ```
5. Railway will **auto-redeploy** automatically

### Expected Behavior After Deployment:

You'll see logs like:
```
📊 Trading symbols: ETH/USD, BTC/USD, LINK/USD, SHIB/USD
🛡️ Active. Risking 20.0% total (5.0% per symbol) of balance per trade.
```

## 📊 Risk Distribution

**Before (2 symbols):**
- Total risk: 20%
- Per symbol: 10.0%

**After (4 symbols):**
- Total risk: 20%
- Per symbol: 5.0% each

## 💰 Your Positions

- **ETH:** $3,007.98
- **BTC:** $528.67
- **SHIB:** $156.35
- **LINK:** $93.83

All positions are substantial enough for trading!

## 📈 What to Expect

After deployment, the bot will:
1. Monitor all 4 symbols simultaneously
2. Check market conditions for each
3. Enter trades independently when conditions are met
4. Manage positions separately for each symbol

## ⚠️ Important Notes

- **Smaller positions:** Each symbol gets 5% risk instead of 10%
- **More opportunities:** 4x the trading opportunities
- **More monitoring:** Keep an eye on all 4 symbols
- **Auto-deploy:** Railway will redeploy automatically when you save

## ✅ Verification

After deployment, check logs for:
```
[ETH] Price: $XXXX.XX | RSI: XX.XX | Stop: $X.XX | Position: NO
[BTC] Price: $XXXX.XX | RSI: XX.XX | Stop: $X.XX | Position: NO
[LINK] Price: $XX.XX | RSI: XX.XX | Stop: $X.XX | Position: NO
[SHIB] Price: $0.XXXXX | RSI: XX.XX | Stop: $0.XXXXX | Position: NO
```

All 4 symbols should appear in the logs!

