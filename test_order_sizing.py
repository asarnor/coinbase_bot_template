import ast
import pathlib
import typing
import unittest


def load_bot_functions(*function_names):
    source_path = pathlib.Path(__file__).with_name("main_multi_symbol.py")
    tree = ast.parse(source_path.read_text())
    selected = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {
        "Dict": typing.Dict,
        "List": typing.List,
        "Tuple": typing.Tuple,
    }
    exec(compile(module, str(source_path), "exec"), namespace)
    return {name: namespace[name] for name in function_names}


functions = load_bot_functions("configure_effective_leverage", "get_position_size")
configure_effective_leverage = functions["configure_effective_leverage"]
get_position_size = functions["get_position_size"]


class FakeJournal:
    def __init__(self):
        self.events = []

    def log_event(self, *args, **kwargs):
        self.events.append((args, kwargs))


class BalanceExchange:
    def __init__(self, free_usd):
        self.free_usd = free_usd

    def fetch_balance(self):
        return {"USD": {"free": self.free_usd}}


class LeverageExchange:
    def __init__(self, failing_symbols=None):
        self.failing_symbols = set(failing_symbols or [])
        self.calls = []

    def set_leverage(self, leverage, symbol):
        self.calls.append((leverage, symbol))
        if symbol in self.failing_symbols:
            raise RuntimeError("leverage unsupported")


class OrderSizingTests(unittest.TestCase):
    def test_spot_sizing_matches_entry_cost_when_leverage_is_effectively_disabled(self):
        amount, cost = get_position_size(
            BalanceExchange(free_usd=1_000),
            "ETH/USD",
            current_price=100,
            symbol_risk_slice=0.05,
            leverage=1,
        )

        self.assertEqual(cost, 50)
        self.assertEqual(amount, 0.5)
        self.assertEqual(amount * 100, cost)

    def test_configure_effective_leverage_falls_back_per_symbol_on_setup_failure(self):
        exchange = LeverageExchange(failing_symbols={"ETH/USD"})
        journal = FakeJournal()

        effective = configure_effective_leverage(exchange, ["ETH/USD", "BTC/USD"], 5, journal)

        self.assertEqual(effective, {"ETH/USD": 1, "BTC/USD": 5})
        self.assertEqual(exchange.calls, [(5, "ETH/USD"), (5, "BTC/USD")])
        self.assertEqual(len(journal.events), 1)
        self.assertEqual(journal.events[0][1]["symbol"], "ETH/USD")


if __name__ == "__main__":
    unittest.main()
