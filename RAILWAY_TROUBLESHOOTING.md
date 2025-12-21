# Railway Deployment Troubleshooting

## 401 Unauthorized Error

If you're seeing:
```
Connection Error: coinbaseadvanced GET https://api.coinbase.com/api/v3/brokerage/transaction_summary 401 Unauthorized
```

This is an **authentication issue**. Here's how to fix it:

---

## Common Causes & Solutions

### 1. API Secret Format Issue (Most Common)

Coinbase Advanced Trade uses **ECDSA private keys** which are multi-line. Railway environment variables might not preserve newlines correctly.

**Solution:**

1. **In Railway Dashboard:**
   - Go to your project → Variables
   - Find `COINBASE_API_SECRET`
   - The secret should be formatted as a single line with `\n` literals

2. **Format your secret correctly:**
   ```
   COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\nYOUR_KEY_CONTENT_HERE\n-----END EC PRIVATE KEY-----
   ```
   
   OR paste it exactly as shown in Coinbase (with actual newlines):
   ```
   -----BEGIN EC PRIVATE KEY-----
   YOUR_KEY_CONTENT_HERE
   -----END EC PRIVATE KEY-----
   ```

3. **The code automatically converts `\n` to actual newlines**, so either format works.

### 2. Verify API Credentials Are Set

**Check in Railway:**
1. Go to your project → Variables tab
2. Verify these are set (not empty):
   - `COINBASE_API_KEY` ✅
   - `COINBASE_API_SECRET` ✅
   - `COINBASE_API_PASSPHRASE` (optional, usually not needed)

**Test locally first:**
```bash
# Test with your credentials locally
export COINBASE_API_KEY="your_key"
export COINBASE_API_SECRET="your_secret"
python main.py --test
```

If it works locally but not on Railway, it's an environment variable issue.

### 3. API Key Permissions

Your Coinbase API key needs these permissions:
- ✅ **View** (required)
- ✅ **Trade** (required for executing orders)

**Check permissions:**
1. Go to [Coinbase Developer Platform](https://portal.cdp.coinbase.com/)
2. Navigate to API Keys
3. Check your key's permissions
4. If missing permissions, create a new key with correct permissions

### 4. API Key Type Mismatch

Make sure you're using **Coinbase Advanced Trade** API keys, not legacy Coinbase Pro keys.

**Check:**
- API keys from `portal.cdp.coinbase.com` = ✅ Advanced Trade (correct)
- API keys from old Coinbase Pro = ❌ Legacy (won't work)

### 5. Environment Variable Formatting

**In Railway, make sure:**
- No extra quotes around values
- No trailing spaces
- Secret is complete (not truncated)

**Wrong:**
```
COINBASE_API_SECRET="your_secret"  ❌ (quotes)
COINBASE_API_SECRET=your_secret   ❌ (trailing space)
```

**Correct:**
```
COINBASE_API_SECRET=your_secret  ✅
```

### 6. Secret Contains Special Characters

If your secret has special characters, Railway might escape them incorrectly.

**Solution:**
- Copy the secret exactly from Coinbase
- Paste directly into Railway (don't modify)
- If it has newlines, use the `\n` format mentioned above

---

## Step-by-Step Fix

### Step 1: Verify Locally
```bash
# Test locally with your credentials
python main.py --test
```

If this works, the issue is Railway configuration.

### Step 2: Check Railway Variables

1. **Go to Railway Dashboard**
2. **Project → Variables**
3. **Verify:**
   - `COINBASE_API_KEY` is set and matches your Coinbase key
   - `COINBASE_API_SECRET` is set and complete
   - No extra characters or formatting

### Step 3: Re-enter Secret

Sometimes re-entering the secret fixes formatting issues:

1. Copy your secret from Coinbase (fresh copy)
2. In Railway, delete the `COINBASE_API_SECRET` variable
3. Create it again and paste the secret
4. Redeploy

### Step 4: Check Logs

In Railway, check the deployment logs for:
- Any warnings about API keys
- The actual error message
- Whether it's connecting to the right endpoint

### Step 5: Test Connection

Add a test script to verify credentials:

```python
# test_connection.py
import ccxt
import os

api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

if api_secret and '\\n' in api_secret:
    api_secret = api_secret.replace('\\n', '\n')

exchange = ccxt.coinbaseadvanced({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'sandbox': False,
})

try:
    exchange.load_markets()
    print("✅ Connection successful!")
    balance = exchange.fetch_balance()
    print(f"✅ Balance fetched: {len(balance)} currencies")
except Exception as e:
    print(f"❌ Error: {e}")
```

---

## Debugging Tips

### Enable Verbose Logging

Add this to your Railway environment variables:
```
DEBUG=1
```

### Check Secret Format

The secret should start with:
```
-----BEGIN EC PRIVATE KEY-----
```

And end with:
```
-----END EC PRIVATE KEY-----
```

### Verify API Key Format

The API key should look like:
```
organizations/xxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx/api_keys/xxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

---

## Still Not Working?

1. **Create a new API key** in Coinbase (sometimes keys get corrupted)
2. **Delete and recreate** the Railway environment variables
3. **Check Railway logs** for the exact error message
4. **Test with sandbox** first: Set `sandbox: true` in code temporarily
5. **Contact support**: Share the exact error from Railway logs

---

## Quick Checklist

- [ ] API key is from Coinbase Advanced Trade (not legacy Pro)
- [ ] API key has View and Trade permissions
- [ ] `COINBASE_API_KEY` is set in Railway
- [ ] `COINBASE_API_SECRET` is set in Railway (complete, no truncation)
- [ ] Secret format is correct (with `\n` or actual newlines)
- [ ] No extra quotes or spaces in Railway variables
- [ ] Tested locally and it works
- [ ] Redeployed after changing variables

---

## Example Railway Variables

Here's how your Railway variables should look:

```
COINBASE_API_KEY=organizations/xxxxx/api_keys/xxxxx
COINBASE_API_SECRET=-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEI...\n-----END EC PRIVATE KEY-----
TRADING_SYMBOL=ETH/USD
TRADING_TIMEFRAME=5m
TRADING_LEVERAGE=5
TRADING_RISK_PCT=0.20
TRADING_ATR_MULTIPLIER=1.5
TRADING_CHECK_INTERVAL=60
```

**Note:** The secret above is truncated (`...`) - yours should be complete!

