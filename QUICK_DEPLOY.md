# Quick Deployment Guide

## 🚀 Fastest Way: Railway (5 minutes)

### Step 1: Push to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/coinbase_bot_template.git
git push -u origin main
```

### Step 2: Deploy on Railway
1. Go to [railway.app](https://railway.app)
2. Sign up/login with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repository
5. Railway will auto-detect Dockerfile and start building

### Step 3: Add Environment Variables
In Railway dashboard:
- Go to your project → Variables
- Add these (click "New Variable" for each):
  ```
  COINBASE_API_KEY=your_key
  COINBASE_API_SECRET=your_secret
  TRADING_SYMBOL=ETH/USD
  TRADING_TIMEFRAME=5m
  TRADING_LEVERAGE=5
  TRADING_RISK_PCT=0.20
  TRADING_ATR_MULTIPLIER=1.5
  ```

### Step 4: Deploy!
- Railway will automatically redeploy when you add variables
- Check "Deployments" tab to see logs
- Bot is now running! 🎉

---

## 🆓 Free Option: Render (10 minutes)

### Step 1: Push to GitHub (same as above)

### Step 2: Deploy on Render
1. Go to [render.com](https://render.com)
2. Sign up/login with GitHub
3. Click "New +" → "Web Service"
4. Connect your repository
5. Configure:
   - **Name**: `coinbase-bot`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py --execute`
6. Add environment variables (same as Railway)
7. Click "Create Web Service"

**Note**: Free tier spins down after inactivity. Upgrade to "Starter" ($7/mo) for always-on.

---

## 🐳 Test Locally with Docker

```bash
# Build image
docker build -t coinbase-bot .

# Run with environment variables
docker run -d \
  --name coinbase-bot \
  -e COINBASE_API_KEY=your_key \
  -e COINBASE_API_SECRET=your_secret \
  -e TRADING_SYMBOL=ETH/USD \
  coinbase-bot

# View logs
docker logs -f coinbase-bot

# Stop
docker stop coinbase-bot
```

Or use docker-compose:
```bash
# Copy .env.example to .env and fill in values
cp .env.example .env

# Run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

---

## ✅ Verify It's Working

1. **Check Logs**: View logs in your platform's dashboard
2. **Test Connection**: Look for "✅ Connected to Coinbase Advanced Trade successfully"
3. **Monitor Activity**: Bot should show price updates every 60 seconds

---

## 🔧 Troubleshooting

**Bot won't start?**
- Check environment variables are set correctly
- Verify API keys are valid
- Check logs for error messages

**Bot stops running?**
- Check platform logs
- Verify API credentials haven't expired
- Ensure platform isn't sleeping (free tiers)

**Need help?**
- See full guide: `DEPLOYMENT.md`
- Check platform-specific documentation
- Test locally first with `--sandbox` flag

---

## 💡 Pro Tips

1. **Start with Sandbox**: Test with `--sandbox` flag first
2. **Monitor Closely**: Watch logs for first few hours
3. **Set Alerts**: Use UptimeRobot to monitor bot status
4. **Backup Config**: Keep environment variables documented securely
5. **Start Small**: Use low `TRADING_RISK_PCT` initially

---

**Ready to deploy?** Choose Railway for easiest setup, or Render for free tier!

