#!/usr/bin/env python3
"""
Helpers for Coinbase portfolio valuation and symbol market snapshots.
"""
import os
from typing import Dict, List, Optional

from dotenv import load_dotenv

from coinbase_exchange import resolve_coinbase_exchange_class


def load_exchange_from_env(use_sandbox: bool = False):
    load_dotenv()
    if use_sandbox and os.path.exists(".env.sandbox"):
        load_dotenv(".env.sandbox", override=True)
    elif not use_sandbox and os.path.exists(".env.production"):
        load_dotenv(".env.production", override=True)

    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE", "")

    if api_secret and "\\n" in api_secret:
        api_secret = api_secret.replace("\\n", "\n")

    exchange_class, _ = resolve_coinbase_exchange_class(use_sandbox)

    config = {
        "apiKey": api_key,
        "secret": api_secret,
        "enableRateLimit": True,
        "sandbox": use_sandbox,
        "options": {
            "createMarketBuyOrderRequiresPrice": False,
        },
    }
    if use_sandbox:
        config["password"] = api_passphrase if api_passphrase else ""
    elif api_passphrase:
        config["password"] = api_passphrase

    exchange = exchange_class(config)
    exchange.load_markets()
    return exchange


def _resolve_usd_price(exchange, currency: str, base_prices: Dict[str, float], price_cache: Dict[str, float]) -> float:
    if currency in ["USD", "USDC"]:
        return 1.0
    if currency in price_cache:
        return price_cache[currency]

    for quote in ["USD", "USDC", "BTC", "ETH"]:
        pair = f"{currency}/{quote}"
        if pair not in exchange.markets:
            continue
        try:
            ticker = exchange.fetch_ticker(pair)
            raw_price = ticker["last"]
            usd_price = raw_price * base_prices.get(quote, 0)
            if usd_price > 0:
                price_cache[currency] = usd_price
                return usd_price
        except Exception:
            continue
    price_cache[currency] = 0.0
    return 0.0


def fetch_portfolio_snapshot(exchange, max_positions: int = 20) -> Dict:
    balance = exchange.fetch_balance()
    base_prices = {"USD": 1.0, "USDC": 1.0}
    price_cache = {}

    for pair in ["BTC/USD", "ETH/USD"]:
        if pair in exchange.markets:
            ticker = exchange.fetch_ticker(pair)
            base_prices[pair.split("/")[0]] = ticker["last"]

    positions = []
    total_estimated_usd = 0.0
    free_usd = balance.get("USD", {}).get("free", 0.0)
    if free_usd <= 0:
        free_usd = balance.get("USDC", {}).get("free", 0.0)

    for currency, balance_info in balance.items():
        if not isinstance(balance_info, dict):
            continue
        total_amount = balance_info.get("total", 0.0)
        if total_amount <= 0:
            continue

        usd_price = _resolve_usd_price(exchange, currency, base_prices, price_cache)
        usd_value = total_amount * usd_price
        total_estimated_usd += usd_value
        positions.append(
            {
                "currency": currency,
                "amount": total_amount,
                "usd_price": usd_price,
                "usd_value": usd_value,
            }
        )

    positions.sort(key=lambda item: item["usd_value"], reverse=True)
    invested_usd = max(total_estimated_usd - free_usd, 0.0)

    return {
        "free_usd": free_usd,
        "invested_usd": invested_usd,
        "total_estimated_usd": total_estimated_usd,
        "positions": positions[:max_positions],
    }


def fetch_symbol_market_snapshot(exchange, symbol: str) -> Dict:
    df = exchange.fetch_ohlcv(symbol, timeframe="1d", limit=8)
    closes = [row[4] for row in df if row and row[4] is not None]
    price = closes[-1] if closes else exchange.fetch_ticker(symbol)["last"]

    change_24h = 0.0
    change_7d = 0.0
    if len(closes) >= 2 and closes[-2]:
        change_24h = (closes[-1] / closes[-2] - 1) * 100
    if len(closes) >= 8 and closes[-8]:
        change_7d = (closes[-1] / closes[-8] - 1) * 100

    return {
        "symbol": symbol,
        "price": price,
        "change_24h_pct": change_24h,
        "change_7d_pct": change_7d,
    }


def summarize_holdings(positions: List[Dict], limit: int = 8) -> List[Dict]:
    return positions[:limit]
