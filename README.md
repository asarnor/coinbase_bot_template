# Coinbase Trading Bot

Automated Coinbase Advanced Trade bot with multi-symbol execution, profile-based risk, structured journaling, and daily portfolio reporting.

The primary maintained path in this repo is the Python multi-symbol bot in `main_multi_symbol.py`. Legacy single-symbol Python and Node scripts are still included for reference, but the newer journaling, reporting, and Railway deployment flow are built around the Python stack.

## Highlights

- Trades multiple symbols from one worker using Coinbase Advanced Trade through CCXT
- Splits symbols into `core`, `tactical`, and `speculative` profiles with different thresholds and risk weights
- Applies market-regime guardrails using BTC and ETH on a higher timeframe before allowing entries
- Uses EMA, RSI, ATR, trend strength, and volume filters to qualify entries
- Supports profit targets, trailing profit capture, spike-reversal exits, break-even protection, and ATR-based stop-losses
- Logs structured events for signal checks, blocked reasons, entries, exits, warnings, runtime errors, and portfolio snapshots
- Stores journal data in SQLite by default or Postgres when `DATABASE_URL` is provided
- Generates daily markdown reports with transactions, account value, blocked-entry analysis, and current market context
- Can email reports through Resend
- Deploys cleanly to Railway through a single app entrypoint that switches behavior by `APP_ROLE`

## Tech Stack

- Python 3.9+
- [CCXT](https://github.com/ccxt/ccxt) for Coinbase exchange access
- `pandas` and `pandas-ta-classic` for indicator calculations
- `python-dotenv` for environment-based configuration
- SQLite for local journaling
- Postgres via `psycopg` for persistent production journaling
- Resend for report email delivery
- Railway for container deployment and scheduled jobs

## Project Layout

- `main_multi_symbol.py`: primary bot runtime
- `trading_journal.py`: structured journal for events and portfolio snapshots
- `portfolio_utils.py`: portfolio valuation and market snapshot helpers
- `daily_report.py`: markdown report generator and email sender
- `app_entrypoint.py`: runtime router for Railway services via `APP_ROLE`
- `show_portfolio.py`: quick balance viewer
- `cleanup_portfolio.py`: optional script to liquidate very small positions
- `sell_sushi.py`: one-off utility for liquidating SUSHI holdings
- `.env.example`, `.env.production.example`, `.env.sandbox.example`: configuration templates
- `Dockerfile`, `Procfile`, `railway.json`: deployment configuration

## Strategy Overview

The bot scans a symbol list every cycle and only enters when all required filters line up:

- Price is above the short EMA
- RSI is above the profile threshold
- Trend strength is high enough
- EMA slope is positive
- Volume is strong enough
- The current market regime allows that profile to trade
- Cooldown rules are satisfied

Each symbol belongs to one of three profiles:

- `core`: lower-noise majors with steadier thresholds
- `tactical`: medium-risk names with slightly tighter profit capture
- `speculative`: higher-risk names that only trade in `risk_on` conditions

The regime engine evaluates benchmark symbols, by default `BTC/USD` and `ETH/USD`, on a higher timeframe and labels the tape as:

- `risk_on`
- `mixed`
- `risk_off`

Blocked entry reasons are journaled, which makes it possible to review whether the bot is being selective for good reasons or simply too conservative.

## Prerequisites

- Python 3.9 or higher
- A Coinbase Advanced Trade account
- Coinbase API credentials with at least `View` permissions
- `Trade` permissions if you want the bot to place real orders

Notes:

- Coinbase Advanced Trade typically uses `COINBASE_API_KEY` and `COINBASE_API_SECRET`
- `COINBASE_API_PASSPHRASE` is optional and mainly relevant for legacy or sandbox compatibility paths

## Quick Start

1. Clone the repository:

```bash
git clone <your-repo-url>
cd coinbase_bot_template
```

2. Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create your environment file:

```bash
cp .env.example .env
```

5. Add your Coinbase credentials to `.env`:

```bash
COINBASE_API_KEY=your_api_key
COINBASE_API_SECRET=your_secret
```

6. Start in sandbox or simulated mode first:

```bash
python main_multi_symbol.py --sandbox
```

That connects to sandbox credentials if `.env.sandbox` exists, keeps trading disabled, and continuously logs what the bot would do.

## Configuration

You can run from a single `.env` file or use environment-specific files:

- `.env`
- `.env.production`
- `.env.sandbox`

Runtime loading behavior:

- `--sandbox` or `--test` prefers `.env.sandbox`
- production runs prefer `.env.production`
- both fall back to `.env`

### Core Variables

| Variable | Purpose | Example / Default |
| --- | --- | --- |
| `APP_ROLE` | Selects runtime role for `app_entrypoint.py` | `bot` |
| `BOT_EXECUTE` | Enables live orders when `APP_ROLE=bot`; leave `false` for simulation | `false` |
| `COINBASE_API_KEY` | Coinbase API key | required |
| `COINBASE_API_SECRET` | Coinbase API secret | required |
| `COINBASE_API_PASSPHRASE` | Optional passphrase | optional |
| `TRADING_SYMBOLS` | All tracked symbols | `ETH/USD,BTC/USD,LINK/USD,SHIB/USD,ALGO/USD,FET/USD` |
| `TRADING_CORE_SYMBOLS` | Symbols assigned to the `core` profile | `ETH/USD,BTC/USD` |
| `TRADING_TACTICAL_SYMBOLS` | Symbols assigned to the `tactical` profile | `LINK/USD,SHIB/USD` |
| `TRADING_SPECULATIVE_SYMBOLS` | Symbols assigned to the `speculative` profile | `ALGO/USD,FET/USD` |
| `TRADING_REGIME_SYMBOLS` | Higher-timeframe benchmark symbols | `BTC/USD,ETH/USD` |
| `TRADING_REGIME_TIMEFRAME` | Timeframe used for regime detection | `1h` |
| `TRADING_TIMEFRAME` | Trading timeframe for signal generation | `5m` |
| `TRADING_LEVERAGE` | Requested leverage setting | `5` |
| `TRADING_RISK_PCT` | Total portfolio risk allocated across all tracked symbols | `0.20` |
| `TRADING_CHECK_INTERVAL` | Seconds between cycles | `60` |
| `TRADING_COOLDOWN_MINUTES` | Cooldown after exits | `5` |
| `TRADING_MIN_ORDER_SIZE` | Skip entries below this USD value | `1.00` |
| `TRADING_USE_LIMIT_ORDERS` | Use limit entries/exits with market fallback | `false` |
| `TRADING_LOG_SIGNAL_CHECKS` | Record blocked-entry reasons | `true` |
| `TRADING_PORTFOLIO_SNAPSHOT_MINUTES` | Minutes between account snapshots | `30` |
| `TRADING_JOURNAL_ENABLED` | Enable structured event logging | `true` |
| `TRADING_JOURNAL_DB_PATH` | Local SQLite path when Postgres is not configured | `data/trading_journal.db` |
| `DATABASE_URL` | Optional Postgres connection string for persistent journaling | unset by default |
| `REPORT_TIMEZONE` | Reporting timezone | `America/Los_Angeles` |
| `REPORT_RECIPIENT_EMAILS` | Comma-separated report recipients | `you@example.com` |
| `REPORT_SUBJECT_PREFIX` | Email subject prefix | `Coinbase Bot Daily Report` |
| `REPORT_REPLY_TO` | Reply-to address for reports | optional |
| `RESEND_API_KEY` | Resend API key | required for email |
| `RESEND_FROM_EMAIL` | Sender address on a Resend-verified domain | required for email |
| `REPORT_STDOUT` | Also print the report body to logs | `true` or `false` |

The profile-specific entry, stop, and profit settings are also exposed in `.env.example`. Use those only after you are comfortable with the default behavior.

## Running Locally

### Simulated Trading

Production credentials, no real orders:

```bash
python main_multi_symbol.py
```

Sandbox credentials, no real orders:

```bash
python main_multi_symbol.py --sandbox
```

### Real Trading

Sandbox with real sandbox orders:

```bash
python main_multi_symbol.py --sandbox --execute
```

Production with real orders:

```bash
python main_multi_symbol.py --execute
```

### About `--test`

`--test` currently behaves like sandbox mode with a `TEST MODE` banner. It does not exit after one cycle, so treat it as a verbose sandbox run rather than a one-shot smoke test.

```bash
python main_multi_symbol.py --test
```

## Journal and Daily Reports

### Journal Backends

By default, the bot writes to local SQLite:

```bash
TRADING_JOURNAL_DB_PATH=data/trading_journal.db
```

For persistent storage, provide `DATABASE_URL` and the bot will automatically switch to Postgres.

### What Gets Logged

- bot startup
- market regime changes
- signal evaluations
- blocked entry reasons
- skipped entries
- executed entries and exits
- warnings and runtime errors
- portfolio snapshots

### Generate Reports

Generate a report for today:

```bash
python daily_report.py --stdout
```

Generate yesterday's report:

```bash
python daily_report.py --yesterday --stdout
```

Generate a report for a specific date:

```bash
python daily_report.py --date 2026-04-04 --stdout
```

By default, reports are written to:

```text
reports/daily_report_YYYY-MM-DD.md
```

### Email Reports

Email yesterday's report:

```bash
python daily_report.py --yesterday --email
```

Required email variables:

```bash
REPORT_RECIPIENT_EMAILS=you@example.com
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=reports@yourdomain.com
REPORT_REPLY_TO=you@yourmailbox.com
```

Important:

- `RESEND_FROM_EMAIL` must use a domain verified in Resend
- personal inbox domains like `gmail.com` or `hotmail.com` will be rejected as the sender
- if you want replies to land in a personal inbox, use `REPORT_REPLY_TO`

## Helpful Utility Scripts

View balances:

```bash
python show_portfolio.py
```

Sell small positions below `MIN_POSITION_VALUE_USD`:

```bash
python cleanup_portfolio.py
```

Sell all SUSHI at market:

```bash
python sell_sushi.py
```

## Railway Deployment

This repo is set up to deploy through:

- `Dockerfile`
- `Procfile`
- `railway.json`
- `app_entrypoint.py`

The entrypoint chooses behavior by `APP_ROLE`:

- `bot`: runs `main_multi_symbol.py` in simulation unless `BOT_EXECUTE=true`
- `daily_report`: generates yesterday's report
- `daily_report_email`: generates and emails yesterday's report

### Recommended Production Architecture

Use three Railway services:

1. `worker`
   Runs the live trading bot with `APP_ROLE=bot`

2. `Postgres`
   Stores persistent journal data

3. `dailyreport`
   A scheduled job that runs `APP_ROLE=daily_report_email`

### Worker Setup

Minimum worker variables:

```bash
APP_ROLE=bot
COINBASE_API_KEY=...
COINBASE_API_SECRET=...
TRADING_SYMBOLS=ETH/USD,BTC/USD,LINK/USD,SHIB/USD,ALGO/USD,FET/USD
TRADING_RISK_PCT=0.20
TRADING_JOURNAL_ENABLED=true
DATABASE_URL=${{Postgres.DATABASE_URL}}
REPORT_TIMEZONE=America/Los_Angeles
```

Deploy the worker and confirm logs show:

- Coinbase connection success
- symbol profile assignments
- current regime
- `Journal backend: Postgres via DATABASE_URL`

### Daily Report Job Setup

The report service should be configured as a scheduled job, not an always-on worker. It runs once, generates and sends the report, then exits.

Minimum report-job variables:

```bash
APP_ROLE=daily_report_email
DATABASE_URL=${{Postgres.DATABASE_URL}}
COINBASE_API_KEY=${{worker.COINBASE_API_KEY}}
COINBASE_API_SECRET=${{worker.COINBASE_API_SECRET}}
COINBASE_API_PASSPHRASE=${{worker.COINBASE_API_PASSPHRASE}}
TRADING_SYMBOLS=${{worker.TRADING_SYMBOLS}}
TRADING_JOURNAL_ENABLED=true
REPORT_TIMEZONE=America/Los_Angeles
REPORT_RECIPIENT_EMAILS=you@example.com
REPORT_SUBJECT_PREFIX=Coinbase Bot Daily Report
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=reports@yourdomain.com
REPORT_REPLY_TO=you@yourmailbox.com
REPORT_STDOUT=true
```

### Scheduling

Railway scheduled jobs use UTC.

Examples for `8:10 AM` Los Angeles time:

- daylight saving time: `10 15 * * *`
- standard time: `10 16 * * *`

If you want the job to run at the same Los Angeles wall-clock time year-round, you will need to adjust the UTC schedule when DST changes.

## Local Docker Run

Build:

```bash
docker build -t coinbase-bot .
```

Run the trading worker:

```bash
docker run --env-file .env coinbase-bot
```

Run the report generator:

```bash
docker run --env-file .env -e APP_ROLE=daily_report coinbase-bot
```

## Legacy Files

These files still exist, but they are not the primary maintained deployment path for the latest features:

- `main.py`: older single-symbol Python bot
- `main.js`: older Node.js implementation
- `render.yaml`: legacy deployment example that does not reflect the new `APP_ROLE` flow

If you are starting fresh, use the Python multi-symbol stack documented in this README.

## Safety Notes

- Start with sandbox mode first
- Do not enable `--execute` until you are comfortable with the symbol list, thresholds, and sizing
- Review logs after deploys to confirm the bot is actually on the expected journal backend
- Keep your API keys and `.env` files out of version control
- No strategy guarantees profits; treat this repo as automation infrastructure, not financial advice
