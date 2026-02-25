from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Tuple

import ccxt
import pandas as pd
from dotenv import load_dotenv


def _normalize_secret(secret: Optional[str]) -> Optional[str]:
    if not secret:
        return secret
    if "\\n" in secret:
        return secret.replace("\\n", "\n")
    return secret


def create_coinbase_exchange(*, sandbox: bool = False, require_auth: bool = False):
    """
    Returns a CCXT exchange instance.

    - If credentials exist in env, they'll be used.
    - If `require_auth=True`, raises if credentials are missing.
    """
    load_dotenv()

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = _normalize_secret(os.getenv("COINBASE_API_SECRET"))
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")

    if require_auth and (not api_key or not api_secret):
        raise RuntimeError(
            "Missing Coinbase credentials. Set COINBASE_API_KEY and COINBASE_API_SECRET in your environment (.env)."
        )

    cfg = {"enableRateLimit": True, "sandbox": sandbox}
    if api_key and api_secret:
        cfg.update({"apiKey": api_key, "secret": api_secret})
        # Sandbox (coinbaseexchange) expects `password` even if empty.
        if sandbox:
            cfg["password"] = api_passphrase or ""
        elif api_passphrase:
            cfg["password"] = api_passphrase

    # Best-effort exchange selection: prefer Advanced Trade for prod, Exchange for sandbox.
    candidates = []
    if sandbox:
        candidates = [getattr(ccxt, "coinbaseexchange", None), getattr(ccxt, "coinbaseadvanced", None)]
    else:
        candidates = [getattr(ccxt, "coinbaseadvanced", None), getattr(ccxt, "coinbase", None), getattr(ccxt, "coinbaseexchange", None)]
    ExchangeClass = next((c for c in candidates if c), None)
    if not ExchangeClass:
        raise RuntimeError("No Coinbase exchange class available in ccxt installation.")

    ex = ExchangeClass(cfg)
    return ex


def fetch_ohlcv_history(
    exchange,
    symbol: str,
    timeframe: str,
    days: int,
    *,
    limit: int = 300,
    pause_s: float = 0.2,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles for roughly the last `days` days.
    """
    now_ms = exchange.milliseconds()
    since_ms = now_ms - int(days * 24 * 60 * 60 * 1000)

    all_rows: List[List[float]] = []
    last_ts = None

    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=limit)
        if not batch:
            break

        # Guard against infinite loops if exchange keeps returning same last candle
        batch_last_ts = batch[-1][0]
        if last_ts is not None and batch_last_ts <= last_ts:
            break

        all_rows.extend(batch)
        last_ts = batch_last_ts
        since_ms = batch_last_ts + 1

        # Stop once we've reached "now"
        if batch_last_ts >= now_ms - 60_000:
            break

        time.sleep(pause_s)

    df = pd.DataFrame(all_rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
    return df


def get_portfolio_holdings(exchange) -> List[Dict]:
    """
    Returns holdings with totals/free amounts.
    Requires an authenticated exchange instance.
    """
    balance = exchange.fetch_balance()
    out: List[Dict] = []
    for currency, bal_info in balance.items():
        if not isinstance(bal_info, dict):
            continue
        total = float(bal_info.get("total", 0) or 0)
        free = float(bal_info.get("free", 0) or 0)
        if total <= 0 and free <= 0:
            continue
        out.append({"currency": currency, "total": total, "free": free})
    return out


def best_usd_pair(exchange, currency: str) -> Optional[str]:
    """
    Prefer a direct USD quote pair (or USDC) for analysis/selling.
    """
    for quote in ("USD", "USDC"):
        pair = f"{currency}/{quote}"
        if pair in getattr(exchange, "markets", {}):
            m = exchange.markets[pair]
            if m.get("active", True):
                return pair
    return None

