from calculator.industry_classification import classify_stock, looks_like_etf
from calculator.pipeline import fair_price_unavailable_reason, is_etf_stock, stock_industry


def test_qqq_trust_is_etf_not_financial() -> None:
    row = {
        "ticker": "QQQ",
        "name": "Invesco QQQ Trust",
        "market": "US",
        "rawIndustry": "Financial | Exchange Traded Fund",
        "industry": "금융, 은행·자산운용·증권",
        "industryReviewedAt": "2026-09-20T17:47:46+00:00",
    }

    result = classify_stock(row)
    assert looks_like_etf(row)
    assert result["industry"] == "ETF, 테마·지수형 상장상품"
    assert "금융" not in result["industry"]
    assert stock_industry(row) == "ETF, 테마·지수형 상장상품"
    assert is_etf_stock(row, {"industry": row["industry"]})
    assert fair_price_unavailable_reason(row, {"epsTtm": "-"}) == "etf"


def test_qqq_etf_flag_without_etf_in_name() -> None:
    row = {"ticker": "QQQ", "name": "Invesco QQQ Trust", "market": "US", "etfFlag": True}
    assert looks_like_etf(row)
    assert "ETF" in classify_stock(row)["industry"]


def test_named_etf_keeps_existing_etf_label() -> None:
    result = classify_stock(
        {
            "ticker": "SPY",
            "name": "State Street SPDR S&P 500 ETF Trust",
            "market": "US",
        }
    )
    assert "ETF" in result["industry"]


def test_curated_soxl_keeps_semiconductor_leverage_etf() -> None:
    result = classify_stock(
        {
            "ticker": "SOXL",
            "name": "Direxion Daily Semiconductor Bull 3X ETF",
            "market": "US",
        }
    )
    assert result["industry"] == "반도체 레버리지 ETF"


def test_iwm_index_fund_without_etf_suffix() -> None:
    row = {
        "ticker": "IWM",
        "name": "iShares Russell 2000 Index Fund",
        "market": "US",
    }
    assert looks_like_etf(row)
    assert "ETF" in classify_stock(row)["industry"]


def test_apple_is_not_an_etf() -> None:
    row = {"ticker": "AAPL", "name": "Apple", "market": "US", "rawIndustry": "Technology | Consumer Electronics"}
    assert not looks_like_etf(row)
    assert "ETF" not in classify_stock(row)["industry"]


def test_eaton_ticker_etn_is_not_an_etf() -> None:
    row = {"ticker": "ETN", "name": "Eaton", "market": "US"}
    assert not looks_like_etf(row)
    assert "ETF" not in classify_stock(row)["industry"]


def test_bigbear_ai_is_not_an_etf() -> None:
    row = {"ticker": "BBAI", "name": "BigBear.ai", "market": "US"}
    assert not looks_like_etf(row)
    assert "ETF" not in classify_stock(row)["industry"]


def test_northern_trust_bank_is_not_an_etf() -> None:
    row = {"ticker": "NTRS", "name": "Northern Trust", "market": "US"}
    assert not looks_like_etf(row)


def test_netflix_is_not_an_etf_even_with_stale_industry() -> None:
    row = {
        "ticker": "NFLX",
        "name": "Netflix",
        "market": "US",
        "industry": "레버리지·테마 ETF",
    }
    assert not looks_like_etf(row)
    assert "ETF" not in classify_stock(row)["industry"]
