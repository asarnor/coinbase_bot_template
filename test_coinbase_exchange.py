#!/usr/bin/env python3
"""Tests for safe Coinbase production/sandbox class resolution."""

import unittest
from types import SimpleNamespace

from coinbase_exchange import resolve_coinbase_exchange_class


class ResolveCoinbaseExchangeClassTests(unittest.TestCase):
    def test_sandbox_uses_coinbaseexchange(self):
        sandbox_class = object()
        production_class = object()
        module = SimpleNamespace(
            coinbaseexchange=sandbox_class,
            coinbase=production_class,
        )

        exchange_class, exchange_id = resolve_coinbase_exchange_class(True, module)

        self.assertIs(exchange_class, sandbox_class)
        self.assertEqual(exchange_id, "coinbaseexchange")

    def test_sandbox_fails_closed_without_coinbaseexchange(self):
        module = SimpleNamespace(coinbase=object(), coinbaseadvanced=object())

        with self.assertRaisesRegex(RuntimeError, "refusing to fall back"):
            resolve_coinbase_exchange_class(True, module)

    def test_production_prefers_current_coinbase_class(self):
        production_class = object()
        module = SimpleNamespace(
            coinbase=production_class,
            coinbaseadvanced=object(),
            coinbaseexchange=object(),
        )

        exchange_class, exchange_id = resolve_coinbase_exchange_class(False, module)

        self.assertIs(exchange_class, production_class)
        self.assertEqual(exchange_id, "coinbase")


if __name__ == "__main__":
    unittest.main()
