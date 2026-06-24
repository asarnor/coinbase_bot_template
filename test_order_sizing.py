import ast
import math
import unittest
from pathlib import Path
from typing import List


def load_functions(*names):
    source = Path("main_multi_symbol.py").read_text()
    module = ast.parse(source)
    selected = [
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    namespace = {"List": List}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "main_multi_symbol.py", "exec"), namespace)
    return [namespace[name] for name in names]


configure_effective_leverage, get_position_size = load_functions(
    "configure_effective_leverage",
    "get_position_size",
)


class FakeJournal:
    def __init__(self):
        self.events = []

    def log_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


class FakeExchange:
    def __init__(self, free_usd=1000.0, reject_leverage=False):
        self.free_usd = free_usd
        self.reject_leverage = reject_leverage
        self.leverage_calls = []

    def set_leverage(self, leverage, symbol):
        self.leverage_calls.append((leverage, symbol))
        if self.reject_leverage:
            raise RuntimeError("leverage is not supported")

    def fetch_balance(self):
        return {"USD": {"free": self.free_usd}}


class EffectiveLeverageTests(unittest.TestCase):
    def test_falls_back_to_spot_sizing_when_leverage_rejected(self):
        exchange = FakeExchange(reject_leverage=True)
        journal = FakeJournal()

        effective_leverage = configure_effective_leverage(
            exchange,
            ["ETH/USD", "BTC/USD"],
            requested_leverage=5,
            journal=journal,
        )
        amount, cost = get_position_size(
            exchange,
            "ETH/USD",
            current_price=100.0,
            symbol_risk_slice=0.20,
            leverage=effective_leverage,
        )

        self.assertEqual(effective_leverage, 1)
        self.assertEqual(exchange.leverage_calls, [(5, "ETH/USD")])
        self.assertEqual(len(journal.events), 1)
        self.assertTrue(math.isclose(amount * 100.0, cost))

    def test_keeps_requested_leverage_when_all_symbols_accept_it(self):
        exchange = FakeExchange()

        effective_leverage = configure_effective_leverage(
            exchange,
            ["ETH/USD", "BTC/USD"],
            requested_leverage=3,
        )

        self.assertEqual(effective_leverage, 3)
        self.assertEqual(exchange.leverage_calls, [(3, "ETH/USD"), (3, "BTC/USD")])


if __name__ == "__main__":
    unittest.main()
