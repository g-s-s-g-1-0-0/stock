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
            "Alphabet Inc. - Class A Common Stock": "Alphabet Class A",
            "Alphabet Inc. - Class C Capital Stock": "Alphabet Class C",
            "Alphabet Inc. - Depositary Shares representing a 1/20th Interest in a Share of Series A Mandatory Convertible Preferred Stock": "Alphabet Series A Pref",
            "Fox Corporation - Class B Common Stock": "Fox Class B",
            "Alphabet Series A Pref": "Alphabet Series A Pref",
            "Alphabet Class A": "Alphabet Class A",
        }

        for raw_name, expected in cases.items():
            with self.subTest(raw_name=raw_name):
                self.assertEqual(expected, self.pipeline.clean_stock_name(raw_name))

    def test_clean_us_name_keeps_share_class_labels(self) -> None:
        universe = importlib.import_module("calculator.build_stock_universe")
        cases = {
            "Alphabet Inc. - Class A Common Stock": "Alphabet Class A",
            "Alphabet Inc. - Class C Capital Stock": "Alphabet Class C",
            "Alphabet Inc. - Depositary Shares representing a 1/20th Interest in a Share of Series B Mandatory Convertible Preferred Stock": "Alphabet Series B Pref",
            "Meta Platforms, Inc. - Class A Common Stock": "Meta Platforms Class A",
            "Alphabet Series A Pref": "Alphabet Series A Pref",
        }
        for raw_name, expected in cases.items():
            with self.subTest(raw_name=raw_name):
                self.assertEqual(expected, universe.clean_us_name(raw_name))


if __name__ == "__main__":
    unittest.main()
