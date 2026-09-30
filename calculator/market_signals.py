"""Compact market breadth and funding-cost signals used by the technical summary."""

from __future__ import annotations

import csv
import io
import urllib.request
from typing import Any


def _fred_series(series_id: str) -> list[float]:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        text = response.read().decode("utf-8", errors="replace")
    values: list[float] = []
    for row in csv.DictReader(io.StringIO(text)):
        raw = next((value for key, value in row.items() if key != "observation_date"), "")
        try:
            values.append(float(raw))
        except (TypeError, ValueError):
            continue
    return values


def _status(value: float, caution: float, warning: float) -> str:
    return "경고" if value >= warning else "주의" if value >= caution else "정상"


def _breadth(us_rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible: list[bool] = []
    for row in us_rows:
        try:
            price = float(str(row.get("현재가", "")).replace("$", "").replace(",", ""))
            ma20 = float(str(row.get("20일 이동평균선", "")).replace("$", "").replace(",", ""))
        except (TypeError, ValueError):
            continue
        if price > 0 and ma20 > 0:
            eligible.append(price > ma20)
    if not eligible:
        return {"status": "판단 불가", "value": None, "count": 0}
    percent = sum(eligible) / len(eligible) * 100
    return {
        "status": "경고" if percent < 40 else "주의" if percent < 60 else "정상",
        "value": percent,
        "count": len(eligible),
    }


def build_market_signals(us_rows: list[dict[str, Any]]) -> dict[str, Any]:
    breadth = _breadth(us_rows)
    signals: dict[str, Any] = {
        "breadth": breadth,
        "treasury": {"status": "판단 불가", "change": None, "current": None},
        "credit": {"status": "판단 불가", "change": None, "current": None},
    }
    for key, series_id, caution, warning in (
        ("treasury", "DGS10", 0.25, 0.50),
        ("credit", "BAMLH0A0HYM2", 0.50, 1.00),
    ):
        try:
            values = _fred_series(series_id)
            if len(values) < 21:
                continue
            change = values[-1] - values[-21]
            signals[key] = {
                "status": _status(change, caution, warning),
                "change": change,
                "current": values[-1],
            }
        except Exception:  # noqa: BLE001 - market signals remain best-effort
            continue
    statuses = [signals[key]["status"] for key in ("breadth", "treasury", "credit")]
    signals["status"] = (
        "경고" if "경고" in statuses or statuses.count("주의") >= 2
        else "주의" if "주의" in statuses
        else "정상" if "정상" in statuses
        else "판단 불가"
    )
    return signals


def market_signal_rows(signals: dict[str, Any]) -> list[list[str]]:
    breadth = signals["breadth"]
    treasury = signals["treasury"]
    credit = signals["credit"]
    breadth_text = (
        f"{breadth['value']:.0f}% ({breadth['count']}개 중) · {breadth['status']}"
        if breadth["value"] is not None else "데이터 부족 · 판단 불가"
    )
    treasury_text = (
        f"{treasury['current']:.2f}% · 20거래일 {treasury['change']:+.2f}%p · {treasury['status']}"
        if treasury["change"] is not None else "데이터 수집 실패 · 판단 불가"
    )
    credit_text = (
        f"{credit['current']:.2f}%p · 20거래일 {credit['change']:+.2f}%p · {credit['status']}"
        if credit["change"] is not None else "데이터 수집 실패 · 판단 불가"
    )
    return [
        ["고점 신호 종합", signals["status"]],
        ["미국 분석종목 20일선 상회 비율", breadth_text],
        ["미국 10년물 금리 20일 변화", treasury_text],
        ["미국 하이일드 차입비용 20일 변화", credit_text],
    ]
