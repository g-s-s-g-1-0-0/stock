from calculator.portfolio_risk import (
    RISK_GROUP_MAX_PERCENT,
    recommended_allocation_percent,
    risk_group_for_stock,
    swing_entry_decision,
)


def test_semiconductor_and_ai_infrastructure_share_one_risk_group():
    stocks = [
        {"ticker": "000660", "name": "SK하이닉스"},
        {"ticker": "SOXL", "name": "Direxion Daily Semiconductor Bull 3X ETF"},
        {"ticker": "ALAB", "name": "Astera Labs"},
        {"ticker": "CRDO", "name": "Credo Technology Group"},
    ]

    assert {risk_group_for_stock(stock) for stock in stocks} == {"반도체·AI 인프라"}


def test_leveraged_etf_uses_half_sized_allocation():
    assert recommended_allocation_percent(
        {"ticker": "SOXL", "name": "Direxion Daily Semiconductor Bull 3X ETF"}
    ) == 5.0
    assert recommended_allocation_percent({"ticker": "ALAB", "name": "Astera Labs"}) == 10.0


def test_industry_cap_blocks_third_standard_position_but_keeps_signal_metadata():
    open_trades = [
        {"ticker": "000660", "name": "SK하이닉스", "recommendedAllocationPercent": 10},
        {"ticker": "CRDO", "name": "Credo Technology Group", "recommendedAllocationPercent": 10},
    ]

    decision = swing_entry_decision({"ticker": "ALAB", "name": "Astera Labs"}, open_trades)

    assert decision["allocationStatus"] == "매수 보류"
    assert decision["currentRiskGroupPercent"] == RISK_GROUP_MAX_PERCENT
    assert decision["postRiskGroupPercent"] == 30
    assert "산업 한도" in decision["allocationReason"]


def test_half_sized_leveraged_etf_can_fill_remaining_industry_capacity():
    open_trades = [
        {"ticker": "000660", "name": "SK하이닉스", "recommendedAllocationPercent": 10},
        {"ticker": "CRDO", "name": "Credo Technology Group", "recommendedAllocationPercent": 5},
    ]

    decision = swing_entry_decision(
        {"ticker": "SOXL", "name": "Direxion Daily Semiconductor Bull 3X ETF"},
        open_trades,
    )

    assert decision["allocationStatus"] == "진입 가능"
    assert decision["recommendedAllocationPercent"] == 5
    assert decision["postRiskGroupPercent"] == 20


def test_same_ticker_is_one_position_and_ten_other_tickers_fill_account():
    held = swing_entry_decision(
        {"ticker": "ALAB", "name": "Astera Labs"},
        [{"ticker": "ALAB", "name": "Astera Labs"}],
    )
    full = swing_entry_decision(
        {"ticker": "NEW", "name": "New Software", "industry": "소프트웨어"},
        [{"ticker": f"T{i}", "riskGroup": f"그룹{i}"} for i in range(10)],
    )

    assert held["allocationStatus"] == "보유"
    assert full["allocationStatus"] == "매수 보류"
    assert "10슬롯" in full["allocationReason"]


def test_unknown_industry_requires_manual_classification():
    decision = swing_entry_decision({"ticker": "UNKNOWN", "name": "Unknown"}, [])

    assert decision["allocationStatus"] == "매수 보류"
    assert decision["riskGroup"] == "분류 확인 필요"
