# Deploy to Railway - Quick Steps

## Your code is ready! ✅
- ✅ Code pushed to GitHub: https://github.com/asarnor/coinbase_bot_template.git
- ✅ Dockerfile exists
- ✅ railway.json configured
- ✅ All deployment files ready

## Deploy via Railway Web Interface (Easiest)

### Step 1: Go to Railway
1. Open https://railway.app
2. Log in to your account

### Step 2: Create New Project
1. Click **"New Project"** button
2. Select **"Deploy from GitHub repo"**
3. If prompted, authorize Railway to access your GitHub
4. Search for: `coinbase_bot_template`
5. Select your repository: `asarnor/coinbase_bot_template`

### Step 3: Railway Auto-Detects
- Railway will automatically detect the Dockerfile
- It will start building your project
- Wait for the build to complete (2-3 minutes)

### Step 4: Verify Variables Are Shared
1. Go to your project → **Variables** tab
2. Make sure all variables show as **"Shared"** (not just set)
3. If you see orange exclamation marks, click **"SHARE"** on each variable
4. Especially important: Share `COINBASE_API_KEY` and `COINBASE_API_SECRET`

### Step 5: Add Missing Variable
Add this if not already there:
- **Variable**: `TRADING_CHECK_INTERVAL`
- **Value**: `60`

### Step 6: Deploy!
- Railway will automatically redeploy when you share variables
- Or click **"Redeploy"** button manually
- Check **"Deployments"** tab for logs

### Step 7: Verify It's Running
1. Go to **"Deployments"** tab
2. Click on the latest deployment
3. View **"Logs"**
4. Look for: `✅ Connected to Coinbase Advanced Trade successfully`
5. Look for: `⏱️  Check Interval: 60 seconds`

---

## Deploy via Railway CLI (Alternative)

If you prefer CLI:

```bash
# Login to Railway (opens browser)
railway login

# Link to your project
cd /Users/abdulsarnor/Documents/GitHub/coinbase_bot_template
railway link

# Deploy
railway up
```

---

## Troubleshooting

**If you get 401 error:**
- Check that `COINBASE_API_SECRET` is shared with your service
- Verify secret format (should start with `-----BEGIN EC PRIVATE KEY-----`)
- Re-enter the secret fresh from Coinbase

**If build fails:**
- Check Railway logs for specific error
- Verify Dockerfile is correct
- Make sure all dependencies are in requirements.txt

**If bot doesn't start:**
- Check Variables are shared (not just set)
- Verify all required variables are present
- Check logs for connection errors

---

## Your Repository
https://github.com/asarnor/coinbase_bot_template.git

## Next Steps After Deployment
1. Monitor logs for first few minutes
2. Verify bot is checking market every 60 seconds
3. Test with small trades first
4. Set up monitoring/alerts

