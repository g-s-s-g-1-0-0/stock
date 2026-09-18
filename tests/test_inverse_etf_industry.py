from calculator.industry_classification import classify_stock
from calculator import pipeline


def test_soxs_industry_identifies_inverse_leverage() -> None:
    result = classify_stock(
        {
            "ticker": "SOXS",
            "name": "Direxion Daily Semiconductor Bear 3X ETF",
            "market": "US",
        }
    )

    assert result["industry"] == "반도체 인버스 레버리지 ETF"


def test_generic_short_etf_industry_identifies_inverse() -> None:
    result = classify_stock(
        {
            "ticker": "SQQQ",
            "name": "ProShares UltraPro Short QQQ",
            "market": "US",
        }
    )

    assert "인버스" in result["industry"]
    assert "ETF" in result["industry"]


def test_short_term_bond_etf_is_not_mislabeled_as_inverse() -> None:
    result = classify_stock(
        {
            "ticker": "FIXD",
            "name": "Example Short-Term Bond ETF",
            "market": "US",
        }
    )

    assert "인버스" not in result["industry"]


def test_vix_short_term_futures_etf_is_not_mislabeled_as_inverse() -> None:
    result = classify_stock(
        {
            "ticker": "UVXY",
            "name": "ProShares Ultra VIX Short Term Futures ETF",
            "market": "US",
        }
    )

    assert "인버스" not in result["industry"]


def test_ultrashort_etf_industry_identifies_inverse() -> None:
    result = classify_stock(
        {
            "ticker": "SDS",
            "name": "ProShares UltraShort S&P500",
            "market": "US",
        }
    )

    assert "인버스" in result["industry"]
    assert "ETF" in result["industry"]


def test_inverse_leveraged_etn_keeps_product_type() -> None:
    result = classify_stock(
        {
            "ticker": "BERZ",
            "name": "MicroSectors FANG & Innovation -3x Inverse Leveraged ETN",
            "market": "US",
        }
    )

    assert result["industry"] == "인버스 레버리지 ETN"


def test_negative_multiple_short_etn_identifies_inverse() -> None:
    result = classify_stock(
        {
            "ticker": "SMHD",
            "name": "MicroSectors -3x Short Semiconductor ETNs",
            "market": "US",
        }
    )

    assert result["industry"] == "인버스 레버리지 ETN"


def test_ultrapro_short_without_etf_suffix_identifies_inverse() -> None:
    result = classify_stock(
        {
            "ticker": "SDOW",
            "name": "UltraPro Short Dow30",
            "market": "US",
        }
    )

    assert result["industry"] == "인버스 레버리지 ETF"


def test_negative_multiple_short_bond_etn_is_directional_inverse() -> None:
    result = classify_stock(
        {
            "ticker": "HYGD",
            "name": "MicroSectors -3x Short High Yield Corporate Bond ETNs",
            "market": "US",
        }
    )

    assert result["industry"] == "인버스 레버리지 ETN"


def test_proshares_short_bond_product_is_directional_inverse() -> None:
    result = classify_stock(
        {
            "ticker": "SJB",
            "name": "ProShares Short High Yield",
            "market": "US",
        }
    )

    assert result["industry"] == "인버스 ETF"


def test_stock_search_refresh_reclassifies_stale_inverse_industry(monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline,
        "read_search_universe",
        lambda: [
            {
                "ticker": "SOXS",
                "name": "Direxion Daily Semiconductor Bear 3X ETF",
                "market": "US",
                "category": "성장주",
                "industry": "반도체 레버리지 ETF",
            }
        ],
    )

    payload = pipeline.build_stock_search_cache()

    assert payload["rows"][0]["industry"] == "반도체 인버스 레버리지 ETF"
