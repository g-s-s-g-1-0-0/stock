from calculator.leveraged_reference import resolve_leveraged_reference


def test_semiconductor_and_nasdaq_products_use_the_one_times_etf() -> None:
    soxl = resolve_leveraged_reference({
        "ticker": "SOXL",
        "name": "Direxion Daily Semiconductor Bull 3X ETF",
        "industry": "NYSE 반도체 지수 3배 레버리지 ETF(일일 3배)",
    })
    soxs = resolve_leveraged_reference({
        "ticker": "SOXS",
        "industry": "반도체 지수 3배 인버스 레버리지 ETF(일일 3배)",
    })
    qld = resolve_leveraged_reference({
        "ticker": "QLD",
        "industry": "나스닥100 지수 2배 레버리지 ETF(일일 2배)",
    })
    tqqq = resolve_leveraged_reference({"ticker": "TQQQ", "name": "ProShares UltraPro QQQ"})

    assert soxl == {"product": "SOXL", "ticker": "SOXX", "multiple": 3, "kind": "etf", "label": "반도체"}
    assert soxs["ticker"] == "SOXX" and soxs["multiple"] == -3
    assert qld["ticker"] == "QQQ" and qld["multiple"] == 2
    assert tqqq["ticker"] == "QQQ" and tqqq["multiple"] == 3


def test_dow_semiconductor_two_times_still_uses_soxx() -> None:
    usd = resolve_leveraged_reference({
        "ticker": "USD",
        "industry": "다우존스 미국 반도체 지수 2배 레버리지 ETF(일일 2배)",
    })

    assert usd["ticker"] == "SOXX"
    assert usd["multiple"] == 2


def test_single_name_leverage_uses_the_stock_in_parentheses_or_the_name() -> None:
    hoog = resolve_leveraged_reference({
        "ticker": "HOOG",
        "name": "Leverage Shares 2X Long HOOD Daily ETF",
        "industry": "Robinhood(HOOD) 단일종목 2배 레버리지 ETF(일일 2배)",
    })
    aapl = resolve_leveraged_reference({
        "ticker": "AAPB",
        "industry": "Leverage 2X Long AAPL 2배 레버리지 ETF",
    })

    assert hoog["ticker"] == "HOOD" and hoog["kind"] == "stock" and hoog["multiple"] == 2
    assert aapl["ticker"] == "AAPL" and aapl["multiple"] == 2 and aapl["kind"] == "stock"


def test_plain_stock_and_one_times_etf_have_no_reference_chart() -> None:
    assert resolve_leveraged_reference({
        "ticker": "NVDA",
        "name": "NVIDIA",
        "industry": "반도체, AI GPU",
    }) is None
    assert resolve_leveraged_reference({
        "ticker": "QQQ",
        "industry": "나스닥100 지수 ETF(1배), 대형 기술·성장주 묶음",
    }) is None
    assert resolve_leveraged_reference({
        "ticker": "FIXD",
        "name": "Example Short-Term Bond ETF",
        "industry": "채권·국채 ETF",
    }) is None
