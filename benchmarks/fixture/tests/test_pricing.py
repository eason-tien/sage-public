from decimal import Decimal
import unittest

from src.pricing import calculate_invoice


class PricingTests(unittest.TestCase):
    def test_basic_invoice(self):
        result = calculate_invoice(
            [{"unit_price": "10.00", "quantity": 2}],
            discount_bps=1000,
            tax_bps=500,
        )
        self.assertEqual(
            result,
            {
                "subtotal": "20.00",
                "discount": "2.00",
                "tax": "0.90",
                "total": "18.90",
            },
        )

    def test_decimal_input_and_half_up_rounding(self):
        result = calculate_invoice([{"unit_price": Decimal("0.005"), "quantity": 1}])
        self.assertEqual(result["subtotal"], "0.01")
        self.assertEqual(result["total"], "0.01")

    def test_rejects_float_price(self):
        with self.assertRaises((TypeError, ValueError)):
            calculate_invoice([{"unit_price": 1.25, "quantity": 1}])


if __name__ == "__main__":
    unittest.main()
