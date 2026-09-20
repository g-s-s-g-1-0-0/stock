"""Shared swing-portfolio sizing and concentration rules."""

from __future__ import annotations

import re
from typing import Any

from .industry_classification import classify_stock

SWING_MAX_POSITIONS = 10
SWING_SLOT_PERCENT = 10.0
LEVERAGED_ETF_SLOT_PERCENT = 5.0
RISK_GROUP_MAX_PERCENT = 20.0
UNKNOWN_RISK_GROUP = "분류 확인 필요"

RISK_GROUP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "반도체·AI 인프라",
        (
            "반도체",
            "hbm",
            "dram",
            "nand",
            "gpu",
            "asic",
            "ai 인프라",
            "ai 데이터센터",
            "데이터센터 연결",
            "인터커넥트",
            "광인터커넥트",
            "광통신",
            "트랜시버",
        ),
    ),
    ("전력·에너지", ("전력", "에너지", "원전", "smr", "태양광", "풍력", "연료전지", "수소")),
    ("방산·우주", ("방산", "무기", "레이더", "드론", "무인체계", "우주", "위성", "발사체")),
    ("자동차·배터리", ("자동차", "전기차", "배터리", "2차전지", "리튬", "모빌리티")),
    ("금융·가상자산", ("금융", "은행", "보험", "증권", "핀테크", "가상화폐", "암호화폐", "비트코인")),
    ("바이오·헬스케어", ("바이오", "제약", "헬스케어", "의료", "진단")),
    ("소프트웨어·클라우드", ("소프트웨어", "클라우드", "사이버보안", "ai 플랫폼")),
    ("산업재·건설", ("산업재", "건설", "플랜트", "철강", "조선", "물류", "자동화")),
    ("소비재", ("소비재", "식품", "유통", "화장품", "뷰티", "패션", "의류")),
    ("원자재", ("원자재", "광산", "희토류", "구리", "알루미늄", "금속")),
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized_stock(stock: dict[str, Any]) -> dict[str, Any]:
    classified = classify_stock(stock)
    return {
        **stock,
        "industry": _text(stock.get("industry")) or classified["industry"],
        "category": _text(stock.get("category")) or classified["category"],
    }


def risk_group_for_stock(stock: dict[str, Any]) -> str:
    explicit = _text(stock.get("riskGroup"))
    if explicit and explicit != UNKNOWN_RISK_GROUP:
        return explicit
    normalized = _normalized_stock(stock)
    industry = _text(normalized.get("industry"))
    if not industry or industry == "-":
        return UNKNOWN_RISK_GROUP
    haystack = " ".join(
        _text(normalized.get(key))
        for key in ("ticker", "name", "industry", "rawIndustry", "products")
    ).lower()
    for group, keywords in RISK_GROUP_RULES:
        if any(keyword.lower() in haystack for keyword in keywords):
            return group
    return industry.split(",", 1)[0].strip() or UNKNOWN_RISK_GROUP


def is_leveraged_or_inverse_etf(stock: dict[str, Any]) -> bool:
    normalized = _normalized_stock(stock)
    haystack = " ".join(
        _text(normalized.get(key))
        for key in ("ticker", "name", "industry", "rawIndustry", "products")
    ).lower()
    etf_like = any(token in haystack for token in ("etf", "etn", "direxion", "proshares", "kodex", "tiger"))
    leveraged = any(token in haystack for token in ("레버리지", "인버스", "곱버스", "ultra", "bull", "bear"))
    leveraged = leveraged or bool(re.search(r"(?:^|\W)[+-]?[23]x(?:\W|$)", haystack))
    return etf_like and leveraged


def recommended_allocation_percent(stock: dict[str, Any]) -> float:
    return LEVERAGED_ETF_SLOT_PERCENT if is_leveraged_or_inverse_etf(stock) else SWING_SLOT_PERCENT


def position_allocation_percent(trade: dict[str, Any], stock: dict[str, Any] | None = None) -> float:
    value = trade.get("recommendedAllocationPercent")
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return recommended_allocation_percent({**(stock or {}), **trade})


def risk_group_exposure(
    open_trades: list[dict[str, Any]],
    stocks_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> dict[str, float]:
    stocks_by_ticker = stocks_by_ticker or {}
    exposure: dict[str, float] = {}
    for trade in open_trades:
        ticker = _text(trade.get("ticker")).upper()
        stock = {**stocks_by_ticker.get(ticker, {}), **trade}
        group = risk_group_for_stock(stock)
        exposure[group] = exposure.get(group, 0.0) + position_allocation_percent(trade, stock)
    return exposure


def swing_entry_decision(
    stock: dict[str, Any],
    open_trades: list[dict[str, Any]],
    stocks_by_ticker: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ticker = _text(stock.get("ticker")).upper()
    allocation = recommended_allocation_percent(stock)
    group = risk_group_for_stock(stock)
    unique_open_tickers = {
        _text(trade.get("ticker")).upper()
        for trade in open_trades
        if _text(trade.get("ticker"))
    }
    exposure = risk_group_exposure(open_trades, stocks_by_ticker)
    current_group_percent = exposure.get(group, 0.0)
    post_group_percent = current_group_percent + allocation

    status = "진입 가능"
    reason = ""
    if not ticker:
        status, reason = "매수 보류", "종목코드 확인 필요"
    elif ticker in unique_open_tickers:
        status, reason = "보유", "동일 종목은 한 포지션만 허용"
    elif len(unique_open_tickers) >= SWING_MAX_POSITIONS:
        status, reason = "매수 보류", f"전체 {SWING_MAX_POSITIONS}슬롯 사용 중"
    elif group == UNKNOWN_RISK_GROUP:
        status, reason = "매수 보류", UNKNOWN_RISK_GROUP
    elif post_group_percent > RISK_GROUP_MAX_PERCENT + 1e-9:
        status, reason = "매수 보류", f"{group} {current_group_percent:.0f}%로 산업 한도 {RISK_GROUP_MAX_PERCENT:.0f}% 초과"

    return {
        "allocationStatus": status,
        "allocationReason": reason,
        "recommendedAllocationPercent": allocation,
        "riskGroup": group,
        "currentRiskGroupPercent": current_group_percent,
        "postRiskGroupPercent": post_group_percent,
        "openPositionCount": len(unique_open_tickers),
        "maxPositionCount": SWING_MAX_POSITIONS,
    }
