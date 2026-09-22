"""Human-readable opinion change reasons for watch/sell transitions."""

from __future__ import annotations

from typing import Any

from .rules import (
    STRATEGY_LABELS,
    STRATEGY_RULES,
    IndicatorRow,
    enrich_profit_exit_reason,
    normalize_strategy_code,
    strategy_display_name,
    strategy_stop_criterion_label,
    strategy_target_criterion_label,
)


def _fmt_price(value: Any, market: str) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if market == "KR":
        return f"₩{round(number):,.0f}"
    return f"${number:,.2f}"


def strategy_label(code: str | None) -> str:
    normalized = normalize_strategy_code(code)
    if not normalized:
        return "매수 조건"
    return strategy_display_name(normalized)


def exit_criteria_summary(code: str | None, trade: dict[str, Any] | None = None) -> str:
    normalized = normalize_strategy_code(code)
    if not normalized:
        return ""

    market = str((trade or {}).get("market") or "US")
    parts: list[str] = []

    if normalized in {"5", "6"}:
        target_pct = int(round(float(STRATEGY_RULES.get(f"TARGET_PCT_{normalized}", 0.12)) * 100))
        parts.append(f"익절 +{target_pct}%")
        support_stop = (trade or {}).get("supportStopPrice")
        if support_stop is not None:
            parts.append(f"손절 { _fmt_price(support_stop, market)}")
        elif normalized == "5":
            parts.append("손절 -8%")
        max_days = int(STRATEGY_RULES.get(f"MAX_HOLD_DAYS_{normalized}", 60))
        parts.append(f"최대 {max_days}거래일")
        return " · ".join(parts)

    if normalized == "3":
        target_pct = int(round(float(STRATEGY_RULES.get("TARGET_PCT_3", 0.12)) * 100))
        parts.append(f"익절 +{target_pct}%")
        support_stop = (trade or {}).get("supportStopPrice")
        if support_stop is not None:
            parts.append(f"지지선 이탈 { _fmt_price(support_stop, market)}")
        parts.append("횡보장 고점·시장 청산")
        return " · ".join(parts)

    if normalized in {"1", "2", "4"}:
        target = strategy_target_criterion_label(normalized)
        stop = strategy_stop_criterion_label(normalized)
        if "기준" in target:
            target = target.split(" 기준 ", 1)[-1]
        if "기준" in stop:
            stop = stop.split(" 기준 ", 1)[-1]
        return f"익절 {target} · 손절 {stop}"

    return ""


def _holding_release_detail(
    code: str,
    *,
    buy: dict[str, Any] | None,
    qqq_market_state: dict[str, Any] | None,
    ind: IndicatorRow | None,
    holding_signal_close: float | None,
) -> str:
    normalized = normalize_strategy_code(code) or code
    buy = buy or {}
    qqq = qqq_market_state or {}

    if normalized in {"5", "6"}:
        buy_block = qqq.get("buyBlockMax")
        premium = qqq.get("premiumPercent")
        if premium is not None and buy_block is not None and float(premium) > float(buy_block):
            return f"QQQ 과열({float(premium):+.1f}% > 차단선 +{float(buy_block):.0f}%)"
        if holding_signal_close and ind and ind.current_price > holding_signal_close * 1.03:
            return "신호가 대비 +3% 추격 한도 초과"
        if qqq.get("trendEntryBlocked"):
            return "추세형 매수 허용 구간 종료"
        return "신규 진입 신호 종료"

    if normalized == "1" and ind:
        if ind.ma200 is not None and ind.current_price >= ind.ma200:
            return "200일선 위 회복"
        rsi = ind.rsi
        cci = ind.cci
        if rsi is not None and cci is not None:
            if rsi >= float(STRATEGY_RULES["RSI_MAX"]) and cci >= float(STRATEGY_RULES["CCI_MIN"]):
                return "과매도 해소"
        return "공포 저점 조건 이탈"

    if normalized == "2" and ind:
        buy_block = qqq.get("buyBlockMax")
        premium = qqq.get("premiumPercent")
        if premium is not None and buy_block is not None and float(premium) > float(buy_block):
            return f"QQQ 과열({float(premium):+.1f}% > 차단선 +{float(buy_block):.0f}%)"
        if not qqq.get("isRecoveryMarket"):
            return "회복장 종료"
        if ind.ma20 is not None and ind.current_price < ind.ma20 * float(STRATEGY_RULES.get("MA_RECLAIM_RATIO", 0.995)):
            return "20일선 회복 실패"
        return "이평선 눌림 조건 이탈"

    if normalized == "3" and ind:
        if ind.ma200 is not None and ind.current_price <= ind.ma200:
            return "MA200 아래 이탈"
        buy_block = qqq.get("buyBlockMax")
        premium = qqq.get("premiumPercent")
        if premium is not None and float(premium) > float(STRATEGY_RULES["S3_ENTRY_QQQ_MAX"]):
            return f"QQQ +{float(STRATEGY_RULES['S3_ENTRY_QQQ_MAX']):.0f}% 초과"
        return "워시아웃·정상장 조건 이탈"

    if normalized == "4" and ind:
        if ind.ma200 is not None and ind.current_price >= ind.ma200:
            return "200일선 위 회복"
        return "장기선 아래 반등 조건 이탈"

    conditions = buy.get("conditions", {}).get(normalized, [])
    if conditions:
        passed = sum(1 for value in conditions if value)
        return f"전략 {normalized} 조건 {passed}/{len(conditions)} 충족"
    return "매수 유지 조건 이탈"


def build_held_watch_opinion_reason(
    strategy_code: str | None,
    *,
    buy: dict[str, Any] | None = None,
    qqq_market_state: dict[str, Any] | None = None,
    ind: IndicatorRow | None = None,
    holding_signal_close: float | None = None,
    trade: dict[str, Any] | None = None,
    additional_buy_blocked: bool = False,
) -> str:
    label = strategy_label(strategy_code)
    criteria = exit_criteria_summary(strategy_code, trade)
    criteria_suffix = f" ({criteria})" if criteria else ""

    if additional_buy_blocked:
        return f"보유 유지 — {label} · 추가매수 대기{criteria_suffix}"

    detail = _holding_release_detail(
        strategy_code or "",
        buy=buy,
        qqq_market_state=qqq_market_state,
        ind=ind,
        holding_signal_close=holding_signal_close,
    )
    return f"매수 조건 해제 — {label}: {detail} · 보유 유지{criteria_suffix}"


def build_plain_watch_opinion_reason(
    *,
    buy: dict[str, Any] | None = None,
    qqq_market_state: dict[str, Any] | None = None,
) -> str:
    qqq = qqq_market_state or {}
    buy_block = qqq.get("buyBlockMax")
    premium = qqq.get("premiumPercent")
    if premium is not None and buy_block is not None and float(premium) > float(buy_block):
        return (
            f"관망 — QQQ 과열({float(premium):+.1f}% > 차단선 +{float(buy_block):.0f}%)으로 "
            "신규 매수 조건 미충족"
        )
    if buy and not buy.get("entryTriggered"):
        return "관망 — 현재 신규 매수 조건 미충족"
    return "관망 — 현재 매수/매도 조건 미충족"


def format_sell_opinion_reason(
    reason: str,
    strategy_code: str | None,
    return_pct: float | None = None,
    *,
    trade: dict[str, Any] | None = None,
    return_pct_is_percent: bool = True,
) -> str:
    text = str(reason or "").strip() or "시스템 매도"
    label = strategy_label(strategy_code)
    enriched = enrich_profit_exit_reason(
        text,
        strategy_code or "",
        return_pct,
        return_pct_is_percent=return_pct_is_percent,
    )
    criteria = exit_criteria_summary(strategy_code, trade)

    if enriched.startswith(label):
        return enriched

    if enriched in {"시스템 매도", "매도"}:
        base = "매도 조건 충족"
        if criteria:
            return f"{label} · {base} ({criteria})"
        return f"{label} · {base}"

    if label and label not in enriched:
        return f"{label} · {enriched}"
    return enriched


def strategy_code_from_trade(trade: dict[str, Any] | None) -> str | None:
    if not isinstance(trade, dict):
        return None
    return normalize_strategy_code(trade.get("strategy"))


def is_sparse_watch_reason(reason: Any) -> bool:
    text = str(reason or "").strip()
    sparse = {
        "",
        "-",
        "보유 유지",
        "보유 중 — 추가매수 조건 미충족",
        "보유 유지 — 추가매수 조건 미충족으로 추가 매수 신호만 보류",
    }
    return text in sparse
