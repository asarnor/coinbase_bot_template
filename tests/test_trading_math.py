import unittest

from trading_math import calculate_spot_position_size


class SpotPositionSizingTest(unittest.TestCase):
    def test_spot_amount_matches_quote_cost(self):
        amount, cost = calculate_spot_position_size(
            free_quote_balance=1000.0,
            current_price=2000.0,
            risk_slice=0.20,
        )

        self.assertEqual(cost, 200.0)
        self.assertEqual(amount, 0.10)

    def test_invalid_inputs_return_zero_size(self):
        for free_quote_balance, current_price, risk_slice in [
            (0.0, 2000.0, 0.20),
            (1000.0, 0.0, 0.20),
            (1000.0, 2000.0, 0.0),
        ]:
            with self.subTest(
                free_quote_balance=free_quote_balance,
                current_price=current_price,
                risk_slice=risk_slice,
            ):
                self.assertEqual(
                    calculate_spot_position_size(
                        free_quote_balance=free_quote_balance,
                        current_price=current_price,
                        risk_slice=risk_slice,
                    ),
                    (0.0, 0.0),
                )


if __name__ == "__main__":
    unittest.main()
