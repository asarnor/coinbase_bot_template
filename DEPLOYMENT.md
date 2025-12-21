# Cloud Deployment Guide

This guide will help you deploy your Coinbase trading bot to various cloud platforms.

## ⚠️ Important Security Notes

- **Never commit API keys** to version control
- Use environment variables for all sensitive data
- Enable 2FA on your Coinbase account
- Use IP whitelisting if available
- Regularly rotate API keys

## Prerequisites

1. **GitHub Account** (recommended for easy deployment)
2. **Cloud Platform Account** (choose one from below)
3. **Coinbase API Credentials** ready to configure

---

## Option 1: Railway (Recommended - Easiest)

Railway is the simplest option with a generous free tier and automatic deployments.

### Steps:

1. **Sign up at [railway.app](https://railway.app)**

2. **Create a New Project**
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Connect your GitHub account
   - Select this repository

3. **Configure Environment Variables**
   - Go to your project → Variables tab
   - Add the following:
     ```
     COINBASE_API_KEY=your_api_key_here
     COINBASE_API_SECRET=your_secret_here
     COINBASE_API_PASSPHRASE=your_passphrase_here (if needed)
     TRADING_SYMBOL=ETH/USD
     TRADING_TIMEFRAME=5m
     TRADING_LEVERAGE=5
     TRADING_RISK_PCT=0.20
     TRADING_ATR_MULTIPLIER=1.5
     TRADING_CHECK_INTERVAL=60
     ```

4. **Deploy**
   - Railway will automatically detect the Dockerfile
   - Click "Deploy" or push to GitHub (auto-deploys)
   - The bot will start running

5. **Monitor**
   - View logs in the Railway dashboard
   - Set up email notifications for crashes

### Railway Pricing:
- **Free Tier**: $5 credit/month (usually enough for a bot)
- **Hobby Plan**: $20/month for more resources

---

## Option 2: Render (Free Tier Available)

Render offers a free tier perfect for testing.

### Steps:

1. **Sign up at [render.com](https://render.com)**

2. **Create a New Web Service**
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Select this repository

3. **Configure Settings**
   - **Name**: `coinbase-trading-bot`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py --execute`

4. **Add Environment Variables**
   - Scroll to "Environment Variables"
   - Add all variables (same as Railway above)

5. **Deploy**
   - Click "Create Web Service"
   - Render will build and deploy automatically

### Render Pricing:
- **Free Tier**: 750 hours/month (enough for continuous running)
- **Starter Plan**: $7/month for always-on service

**Note**: Free tier spins down after 15 minutes of inactivity. For continuous operation, use a paid plan or set up a health check ping.

---

## Option 3: AWS EC2 (Most Control)

AWS EC2 gives you full control but requires more setup.

### Steps:

1. **Launch EC2 Instance**
   - Go to AWS Console → EC2
   - Launch Instance
   - Choose Ubuntu 22.04 LTS (free tier eligible)
   - Instance type: `t2.micro` (free tier) or `t3.small` (recommended)
   - Configure security group (allow SSH on port 22)
   - Create/select key pair

2. **SSH into Instance**
   ```bash
   ssh -i your-key.pem ubuntu@your-instance-ip
   ```

3. **Install Dependencies**
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip git
   ```

4. **Clone Repository**
   ```bash
   git clone https://github.com/your-username/coinbase_bot_template.git
   cd coinbase_bot_template
   ```

5. **Install Python Dependencies**
   ```bash
   pip3 install -r requirements.txt
   ```

6. **Set Environment Variables**
   ```bash
   export COINBASE_API_KEY="your_key"
   export COINBASE_API_SECRET="your_secret"
   export COINBASE_API_PASSPHRASE="your_passphrase"  # if needed
   export TRADING_SYMBOL="ETH/USD"
   export TRADING_TIMEFRAME="5m"
   export TRADING_LEVERAGE="5"
   export TRADING_RISK_PCT="0.20"
   export TRADING_ATR_MULTIPLIER="1.5"
   export TRADING_CHECK_INTERVAL="60"
   ```

7. **Run with Screen/Tmux (keeps running after disconnect)**
   ```bash
   # Install screen
   sudo apt install screen
   
   # Start screen session
   screen -S trading_bot
   
   # Run bot
   python3 main.py --execute
   
   # Detach: Press Ctrl+A then D
   # Reattach: screen -r trading_bot
   ```

8. **Or Use systemd (Better for Production)**
   ```bash
   # Create service file
   sudo nano /etc/systemd/system/coinbase-bot.service
   ```
   
   Add this content:
   ```ini
   [Unit]
   Description=Coinbase Trading Bot
   After=network.target
   
   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/home/ubuntu/coinbase_bot_template
   Environment="COINBASE_API_KEY=your_key"
   Environment="COINBASE_API_SECRET=your_secret"
   Environment="TRADING_SYMBOL=ETH/USD"
   Environment="TRADING_TIMEFRAME=5m"
   Environment="TRADING_LEVERAGE=5"
   Environment="TRADING_RISK_PCT=0.20"
   Environment="TRADING_ATR_MULTIPLIER=1.5"
   Environment="TRADING_CHECK_INTERVAL=60"
   ExecStart=/usr/bin/python3 /home/ubuntu/coinbase_bot_template/main.py --execute
   Restart=always
   RestartSec=10
   
   [Install]
   WantedBy=multi-user.target
   ```
   
   Then:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable coinbase-bot
   sudo systemctl start coinbase-bot
   sudo systemctl status coinbase-bot  # Check status
   ```

### AWS Pricing:
- **Free Tier**: 750 hours/month of t2.micro (first year)
- **t3.small**: ~$15/month

---

## Option 4: Google Cloud Run (Serverless)

Google Cloud Run is serverless and scales automatically.

### Steps:

1. **Install Google Cloud SDK**
   ```bash
   # Follow: https://cloud.google.com/sdk/docs/install
   ```

2. **Build and Deploy**
   ```bash
   # Set project
   gcloud config set project YOUR_PROJECT_ID
   
   # Build container
   gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/coinbase-bot
   
   # Deploy
   gcloud run deploy coinbase-bot \
     --image gcr.io/YOUR_PROJECT_ID/coinbase-bot \
     --platform managed \
     --region us-central1 \
     --set-env-vars COINBASE_API_KEY=your_key,COINBASE_API_SECRET=your_secret \
     --allow-unauthenticated
   ```

3. **Set Environment Variables**
   - Go to Cloud Run → Edit & Deploy New Revision
   - Add environment variables in the UI

### Google Cloud Pricing:
- **Free Tier**: 2 million requests/month
- **Pay per use**: Very affordable for bots

---

## Option 5: Docker + Any Cloud Provider

You can use Docker on any platform:

### Build Locally:
```bash
docker build -t coinbase-bot .
```

### Run Locally:
```bash
docker run -d \
  --name coinbase-bot \
  -e COINBASE_API_KEY=your_key \
  -e COINBASE_API_SECRET=your_secret \
  -e TRADING_SYMBOL=ETH/USD \
  coinbase-bot
```

### Deploy to:
- **DigitalOcean**: Use Docker on Droplets
- **Linode**: Use Docker on Linodes
- **Vultr**: Use Docker on VPS
- **Any VPS**: Install Docker and run

---

## Monitoring & Logs

### View Logs:

**Railway:**
- Dashboard → Deployments → View Logs

**Render:**
- Dashboard → Your Service → Logs

**AWS EC2:**
```bash
# If using systemd
sudo journalctl -u coinbase-bot -f

# If using screen
screen -r trading_bot
```

**Docker:**
```bash
docker logs -f coinbase-bot
```

### Health Checks:

Add a simple health check endpoint or use monitoring services:
- **UptimeRobot** (free): Monitor if bot is running
- **Pingdom**: Monitor uptime
- **Sentry**: Error tracking

---

## Troubleshooting

### Bot Stops Running:
- Check logs for errors
- Verify API keys are correct
- Check if Coinbase API is accessible
- Ensure environment variables are set

### Connection Issues:
- Verify API credentials
- Check IP whitelisting (if enabled)
- Test API connection locally first

### High Costs:
- Use free tiers when possible
- Monitor resource usage
- Set up billing alerts

---

## Recommended Setup for Production

1. **Use Railway or Render** (easiest)
2. **Set up monitoring** (UptimeRobot)
3. **Enable logging** to external service (optional)
4. **Set up alerts** for critical errors
5. **Test in sandbox first** before production

---

## Quick Start (Railway - Recommended)

1. Push code to GitHub
2. Sign up at railway.app
3. Connect GitHub repo
4. Add environment variables
5. Deploy!

**That's it!** Railway handles everything else automatically.

---

## Need Help?

- Check platform-specific documentation
- Review bot logs for errors
- Test locally first with `--sandbox` flag
- Verify API credentials are correct

