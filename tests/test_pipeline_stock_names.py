import importlib
import unittest


class PipelineStockNameTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = importlib.import_module("calculator.pipeline")

    def test_clean_stock_name_removes_unneeded_suffixes(self) -> None:
        cases = {
            "Sigma Lithium Corporation - common shares": "Sigma Lithium",
            "IREN Limited -": "IREN",
            "Arista Networks, Inc.": "Arista Networks",
            "Broadcom Inc.": "Broadcom",
            "Sandisk Corporation When-Issued": "Sandisk",
            "Nebius Group N.V. -": "Nebius Group",
            "Credo Technology Group Holding Ltd -": "Credo Technology Group Holding",
        }

        for raw_name, expected in cases.items():
            with self.subTest(raw_name=raw_name):
                self.assertEqual(expected, self.pipeline.clean_stock_name(raw_name))


if __name__ == "__main__":
    unittest.main()
