# Fix Railway 401 Error - Step by Step

## ✅ Your Credentials Work Locally!
- API Key: ✅ Valid (95 characters)
- API Secret: ✅ Valid (232 characters, contains `\n`)
- Connection: ✅ Successful locally

## The Problem
Railway is not receiving or processing your API secret correctly. This is almost always a **variable sharing** or **format** issue.

---

## 🔧 Fix Steps (Do These in Order)

### Step 1: Get Your Exact Secret

Your secret should look like this (232 characters):
```
-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIEDImw3ZWO...\n-----END EC PRIVATE KEY-----
```

**Copy it fresh from Coinbase:**
1. Go to https://portal.cdp.coinbase.com/
2. Navigate to API Keys
3. Find your key
4. Click "Show" or "Reveal" on the secret
5. Copy the ENTIRE secret (all lines)

### Step 2: Delete and Recreate in Railway

**In Railway Dashboard:**

1. Go to your project → **Variables** tab
2. Find `COINBASE_API_SECRET`
3. Click the **three dots (⋯)** menu → **Delete**
4. Confirm deletion

5. Click **"Add Variable"** or **"New Variable"**
6. **Variable Name**: `COINBASE_API_SECRET`
7. **Value**: Paste your complete secret

**Important Format Options:**

**Option A: With `\n` (Recommended)**
```
-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIEDImw3ZWO...\n-----END EC PRIVATE KEY-----
```

**Option B: With Actual Newlines**
Paste it exactly as shown in Coinbase (with real line breaks):
```
-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIEDImw3ZWO...
-----END EC PRIVATE KEY-----
```

8. Click **Save** or **Add**

### Step 3: SHARE the Variable (CRITICAL!)

This is the most common issue!

1. After creating `COINBASE_API_SECRET`, you'll see a **purple "SHARE" button**
2. **Click "SHARE"** - This makes it available to your service
3. Do the same for `COINBASE_API_KEY` - **Click "SHARE"**
4. Verify both show as **"Shared"** (not just set)

**Why this matters:**
- Railway has "Shared Variables" (environment-level) and "Service Variables" (service-specific)
- Your bot service needs the variables to be **shared** with it
- Orange exclamation marks mean "not shared with service"

### Step 4: Verify All Variables Are Shared

Check that ALL these variables are **shared**:
- ✅ `COINBASE_API_KEY` - **SHARED**
- ✅ `COINBASE_API_SECRET` - **SHARED**
- ✅ `TRADING_SYMBOL` - **SHARED**
- ✅ `TRADING_TIMEFRAME` - **SHARED**
- ✅ `TRADING_LEVERAGE` - **SHARED**
- ✅ `TRADING_RISK_PCT` - **SHARED**
- ✅ `TRADING_ATR_MULTIPLIER` - **SHARED**
- ✅ `TRADING_CHECK_INTERVAL` - **SHARED** (add if missing: value `60`)

### Step 5: Redeploy

1. Go to **Deployments** tab
2. Click **"Redeploy"** or **"Deploy"**
3. Watch the build logs
4. Check for connection success

### Step 6: Check Logs

After deployment, check logs for:

**✅ Success:**
```
✅ Connected to Coinbase Advanced Trade successfully
⏱️  Check Interval: 60 seconds
```

**❌ Still failing:**
```
❌ Connection Error: 401 Unauthorized
```

---

## 🎯 Most Common Issues

### Issue 1: Variable Not Shared
**Symptom:** Orange exclamation mark next to variable
**Fix:** Click "SHARE" button

### Issue 2: Secret Truncated
**Symptom:** Secret is shorter than 232 characters
**Fix:** Copy complete secret from Coinbase (all lines)

### Issue 3: Extra Characters
**Symptom:** Secret has quotes or spaces
**Fix:** Paste raw secret, no quotes, no spaces

### Issue 4: Wrong Format
**Symptom:** Secret doesn't start with `-----BEGIN`
**Fix:** Copy fresh from Coinbase

---

## 🔍 Verify Secret Format

Your secret should:
- ✅ Start with: `-----BEGIN EC PRIVATE KEY-----`
- ✅ End with: `-----END EC PRIVATE KEY-----`
- ✅ Be 232 characters long (approximately)
- ✅ Contain `\n` or actual newlines

---

## 🧪 Test After Fix

After redeploying, check Railway logs. You should see:

```
🔌 Connecting to PRODUCTION...
📊 Loading markets...
✅ Connected! Loaded 1125 markets
⏱️  Check Interval: 60 seconds
```

If you still see 401:
1. Double-check variable is **SHARED** (not just set)
2. Verify secret is complete (232 chars)
3. Try creating a NEW API key in Coinbase
4. Copy that new secret fresh into Railway

---

## 📋 Quick Checklist

- [ ] Deleted old `COINBASE_API_SECRET` in Railway
- [ ] Created new `COINBASE_API_SECRET` with complete secret
- [ ] Clicked **"SHARE"** on `COINBASE_API_SECRET`
- [ ] Clicked **"SHARE"** on `COINBASE_API_KEY`
- [ ] Verified all variables show as "Shared"
- [ ] Added `TRADING_CHECK_INTERVAL=60` if missing
- [ ] Redeployed
- [ ] Checked logs for success message

---

## 💡 Pro Tip

If still not working, try this:
1. Create a **NEW API key** in Coinbase (fresh start)
2. Copy the new secret immediately
3. Delete ALL variables in Railway
4. Recreate them all fresh
5. Share all variables
6. Redeploy

This eliminates any hidden formatting issues.

