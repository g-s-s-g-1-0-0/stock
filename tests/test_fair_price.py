import importlib
import unittest


class FairPriceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = importlib.import_module("calculator.pipeline")
        self.stock = {"ticker": "TEST", "name": "Test", "market": "US", "category": "성장주"}

    def test_growth_is_capped_and_quality_adjusted(self) -> None:
        price_range = self.pipeline.fair_price_range(self.stock, {
            "epsTtm": "$10.00",
            "epsNextYear": "$30.00",
            "salesYoyTtm": "120.00%",
            "roe": "30.00%",
            "operatingMargin": "30.00%",
            "debtToEquity": "20.00%",
        })

        self.assertEqual("$334.05 ~ $451.95", price_range)

    def test_weak_profitability_and_high_debt_reduce_multiple(self) -> None:
        price_range = self.pipeline.fair_price_range(self.stock, {
            "epsTtm": "$10.00",
            "epsNextYear": "$10.00",
            "salesYoyTtm": "0.00%",
            "roe": "5.00%",
            "operatingMargin": "3.00%",
            "debtToEquity": "180.00%",
        })

        self.assertEqual("$68.00 ~ $92.00", price_range)

    def test_requires_a_growth_input_and_keeps_loss_making_unavailable(self) -> None:
        self.assertEqual("-", self.pipeline.fair_price_range(self.stock, {"epsTtm": "$10.00"}))
        self.assertEqual(
            self.pipeline.FAIR_PRICE_UNAVAILABLE_LABEL,
            self.pipeline.fair_price_range(self.stock, {"epsTtm": "-$1.00", "salesYoyTtm": "10.00%"}),
        )


if __name__ == "__main__":
    unittest.main()
