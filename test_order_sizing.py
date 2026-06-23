import ast
import types
import unittest
from pathlib import Path
from typing import List, Tuple


ROOT = Path(__file__).resolve().parent


def load_functions(path, function_names):
    tree = ast.parse(Path(path).read_text())
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    module = types.ModuleType("extracted_bot_helpers")
    module.__dict__.update({"List": List, "Tuple": Tuple})
    compiled = compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec")
    exec(compiled, module.__dict__)
    return module


class FakeExchange:
    def __init__(self, free_usd=1000.0, free_usdc=0.0, leverage_error=None):
        self.balance = {
            "USD": {"free": free_usd},
            "USDC": {"free": free_usdc},
        }
        self.leverage_error = leverage_error
        self.leverage_calls = []

    def fetch_balance(self):
        return self.balance

    def set_leverage(self, leverage, symbol):
        self.leverage_calls.append((leverage, symbol))
        if self.leverage_error is not None:
            raise self.leverage_error


class FakeJournal:
    def __init__(self):
        self.events = []

    def log_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


class OrderSizingTests(unittest.TestCase):
    def test_multi_symbol_falls_back_to_spot_sizing_when_leverage_is_rejected(self):
        helpers = load_functions(
            ROOT / "main_multi_symbol.py",
            {"configure_effective_leverage", "get_position_size"},
        )
        exchange = FakeExchange(leverage_error=RuntimeError("leverage not supported"))
        journal = FakeJournal()

        effective_leverage = helpers.configure_effective_leverage(
            exchange, ["ETH/USD", "BTC/USD"], 5, journal
        )
        amount, cost = helpers.get_position_size(
            exchange, "ETH/USD", current_price=2000.0, symbol_risk_slice=0.2, leverage=effective_leverage
        )

        self.assertEqual(effective_leverage, 1)
        self.assertEqual(exchange.leverage_calls, [(5, "ETH/USD")])
        self.assertEqual(cost, 200.0)
        self.assertEqual(amount, 0.1)
        self.assertEqual(journal.events[0][1]["payload"]["requested_leverage"], 5)

    def test_multi_symbol_keeps_requested_leverage_only_after_all_symbols_configure(self):
        helpers = load_functions(
            ROOT / "main_multi_symbol.py",
            {"configure_effective_leverage"},
        )
        exchange = FakeExchange()

        effective_leverage = helpers.configure_effective_leverage(
            exchange, ["ETH/USD", "BTC/USD"], 5, FakeJournal()
        )

        self.assertEqual(effective_leverage, 5)
        self.assertEqual(exchange.leverage_calls, [(5, "ETH/USD"), (5, "BTC/USD")])

    def test_single_symbol_sizing_uses_effective_leverage(self):
        helpers = load_functions(ROOT / "main.py", {"get_position_size"})
        helpers.exchange = FakeExchange()
        helpers.risk_pct = 0.2
        helpers.effective_leverage = 1

        amount, cost = helpers.get_position_size(current_price=2000.0)

        self.assertEqual(cost, 200.0)
        self.assertEqual(amount, 0.1)


if __name__ == "__main__":
    unittest.main()
