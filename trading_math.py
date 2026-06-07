#!/usr/bin/env python3
"""
Shared trading calculations.
"""
from typing import Tuple


def calculate_spot_position_size(
    free_quote_balance: float,
    current_price: float,
    risk_slice: float,
) -> Tuple[float, float]:
    """
    Return the base amount and quote cost for a Coinbase spot buy.

    Coinbase spot market buys are submitted with quote currency cost. The tracked
    base amount must therefore be derived from the same unleveraged quote cost.
    """
    if free_quote_balance <= 0 or current_price <= 0 or risk_slice <= 0:
        return 0.0, 0.0

    quote_cost = free_quote_balance * risk_slice
    base_amount = quote_cost / current_price
    return base_amount, quote_cost
