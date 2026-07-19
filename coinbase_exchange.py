"""Safe Coinbase exchange-class selection."""

import ccxt


def resolve_coinbase_exchange_class(use_sandbox: bool, ccxt_module=ccxt):
    """Return a Coinbase ccxt class without crossing environment boundaries."""
    if use_sandbox:
        exchange_class = getattr(ccxt_module, "coinbaseexchange", None)
        if exchange_class is None:
            raise RuntimeError(
                "Coinbase sandbox requires ccxt.coinbaseexchange; refusing to "
                "fall back to the production Coinbase API. Update ccxt."
            )
        return exchange_class, "coinbaseexchange"

    for exchange_id in ("coinbase", "coinbaseadvanced", "coinbaseexchange"):
        exchange_class = getattr(ccxt_module, exchange_id, None)
        if exchange_class is not None:
            return exchange_class, exchange_id

    raise RuntimeError("No Coinbase exchange class found in ccxt. Update ccxt.")
