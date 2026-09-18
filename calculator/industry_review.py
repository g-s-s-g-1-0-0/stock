"""Weekly review of whether a watchlist stock's displayed industry is still the main theme."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .industry_classification import (
    CATEGORY_VALUES,
    is_curated_ticker,
    summarize_industry,
)
from .sheet_sources import USER_AGENT
from .ticker_aliases import canonical_ticker

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_INDUSTRY_REVIEW_DEFAULT_MODEL = "openai/gpt-oss-20b"
GROQ_INDUSTRY_REVIEW_SUPPORTED_MODELS = {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}
REVIEW_MAX_AGE = timedelta(days=10)
REVIEW_BATCH_SIZE = 12
ReviewRequester = Callable[[list[dict[str, Any]], str], list[dict[str, str]]]


def industry_review_model() -> str:
    configured = os.environ.get("GROQ_MARKET_TREND_MODEL", "").strip()
    if configured in GROQ_INDUSTRY_REVIEW_SUPPORTED_MODELS:
        return configured
    return GROQ_INDUSTRY_REVIEW_DEFAULT_MODEL


def parse_reviewed_at(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def reviewed_industry_is_fresh(row: dict[str, Any], now: datetime | None = None) -> bool:
    industry = summarize_industry(row.get("industry"))
    if industry in ("", "-"):
        return False
    reviewed_at = parse_reviewed_at(row.get("industryReviewedAt"))
    if reviewed_at is None:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current - reviewed_at <= REVIEW_MAX_AGE


def preserve_reviewed_industries(
    payload: dict[str, Any],
    previous_payload: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    previous_rows = previous_payload.get("rows") if isinstance(previous_payload, dict) else []
    previous_by_ticker: dict[str, dict[str, Any]] = {}
    if isinstance(previous_rows, list):
        for row in previous_rows:
            if not isinstance(row, dict):
                continue
            ticker = canonical_ticker(row.get("ticker"))
            if ticker:
                previous_by_ticker[ticker] = row

    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not previous_by_ticker or not isinstance(rows, list):
        return payload

    preserved: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            preserved.append(row)
            continue
        ticker = canonical_ticker(row.get("ticker"))
        previous = previous_by_ticker.get(ticker)
        if (
            previous
            and ticker
            and not is_curated_ticker(ticker)
            and reviewed_industry_is_fresh(previous, now)
        ):
            next_row = {
                **row,
                "industry": summarize_industry(previous.get("industry")),
                "industryReviewedAt": previous.get("industryReviewedAt"),
            }
            previous_category = str(previous.get("category") or "").strip()
            if previous_category in CATEGORY_VALUES:
                next_row["category"] = previous_category
            preserved.append(next_row)
            continue
        preserved.append(row)

    return {**payload, "rows": preserved}


def parse_industry_reviews(payload: Any, expected_tickers: set[str]) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        raise ValueError("산업군 검토 결과가 JSON 객체가 아닙니다.")
    raw_reviews = payload.get("reviews")
    if not isinstance(raw_reviews, list):
        raise ValueError("산업군 검토 결과에 reviews 배열이 없습니다.")

    reviews: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_reviews:
        if not isinstance(item, dict):
            continue
        ticker = canonical_ticker(item.get("ticker"))
        if not ticker or ticker not in expected_tickers or ticker in seen:
            continue
        industry = summarize_industry(item.get("industry"))
        if industry in ("", "-"):
            continue
        category = str(item.get("category") or "").strip()
        review = {"ticker": ticker, "industry": industry}
        if category in CATEGORY_VALUES:
            review["category"] = category
        reviews.append(review)
        seen.add(ticker)
    return reviews


def apply_industry_reviews(
    payload: dict[str, Any],
    reviews: list[dict[str, str]],
    reviewed_at: str,
) -> tuple[dict[str, Any], int]:
    reviews_by_ticker = {item["ticker"]: item for item in reviews}
    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not reviews_by_ticker or not isinstance(rows, list):
        return payload, 0

    changed = 0
    next_rows: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            next_rows.append(row)
            continue
        ticker = canonical_ticker(row.get("ticker"))
        review = reviews_by_ticker.get(ticker)
        if not review:
            next_rows.append(row)
            continue
        next_row = {
            **row,
            "industry": review["industry"],
            "industryReviewedAt": reviewed_at,
        }
        if review.get("category") in CATEGORY_VALUES:
            next_row["category"] = review["category"]
        if next_row != row:
            changed += 1
        next_rows.append(next_row)

    if not changed:
        return payload, 0
    return {
        **payload,
        "meta": {
            **(payload.get("meta", {}) if isinstance(payload.get("meta"), dict) else {}),
            "industryReviewedAt": reviewed_at,
            "industryReviewedTickers": changed,
        },
        "rows": next_rows,
    }, changed


def _chunked(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index:index + size] for index in range(0, len(rows), size)]


def _review_prompt(rows: list[dict[str, Any]], trend_text: str) -> str:
    lines = []
    for row in rows:
        lines.append(
            " - ".join([
                str(row.get("ticker") or ""),
                str(row.get("name") or ""),
                f"현재산업: {row.get('industry') or '-'}",
                f"원천산업: {row.get('rawIndustry') or '-'}",
                f"제품: {row.get('products') or '-'}",
            ])
        )
    stock_block = "\n".join(lines)
    return f"""관심종목 산업군이 지금 시장에서 이 종목의 메인 테마가 맞는지 주 1회 검토합니다.

[규칙]
- Finviz/KIND의 넓은 섹터(Industrial, Machinery 등)만 보고 끝내지 마세요.
- 본업은 유지하되, 지금 시장에서 이 종목이 주목받는 이유가 분명하면 그걸 맨 앞에 두세요.
- 예: 비상발전기 회사인데 데이터센터 백업전력이 테마면 "데이터센터 전력, 백업발전기, 산업재"
- 한국어 콤마 구분, 최대 5개. 기존 라벨이 이미 맞으면 그대로 반환하세요.
- 없는 사업을 만들지 마세요.

[이번 주 시장 테마]
{trend_text or "없음"}

[종목]
{stock_block}

JSON만 출력합니다. reviews에는 위에 있는 종목만 넣고, 각 항목은 ticker, industry, category(가치주/혼합주/성장주/스윙주)를 포함합니다."""


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    detail = exc.read().decode("utf-8", errors="replace").strip()
    return f"HTTP {exc.code}: {detail[:500]}" if detail else f"HTTP {exc.code}"


def review_industries_with_groq(rows: list[dict[str, Any]], trend_text: str, api_key: str) -> list[dict[str, str]]:
    expected = {canonical_ticker(row.get("ticker")) for row in rows if canonical_ticker(row.get("ticker"))}
    request_body: dict[str, Any] = {
        "model": industry_review_model(),
        "messages": [{"role": "user", "content": _review_prompt(rows, trend_text)}],
        "temperature": 0.2,
        "max_completion_tokens": 2048,
        "reasoning_effort": "low",
        "include_reasoning": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "industry_review",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["reviews"],
                    "properties": {
                        "reviews": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["ticker", "industry", "category"],
                                "properties": {
                                    "ticker": {"type": "string"},
                                    "industry": {"type": "string"},
                                    "category": {"type": "string"},
                                },
                            },
                        }
                    },
                },
            },
        },
    }
    last_error: Exception | None = None
    for attempt in range(2):
        request = urllib.request.Request(
            GROQ_CHAT_COMPLETIONS_URL,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = _http_error_detail(exc)
            if attempt == 0 and exc.code == 400 and "json_validate_failed" in detail:
                request_body["response_format"] = {"type": "json_object"}
                continue
            raise

        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        try:
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Groq 응답에 검토 텍스트가 없습니다.")
            return parse_industry_reviews(json.loads(content), expected)
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc

    raise RuntimeError(f"Groq 산업군 검토 응답을 처리하지 못했습니다: {last_error}")


def review_universe_industries(
    payload: dict[str, Any],
    tickers: list[str],
    *,
    trend_text: str = "",
    api_key: str = "",
    now: datetime | None = None,
    request_reviews: ReviewRequester | None = None,
) -> tuple[dict[str, Any], int]:
    if not api_key:
        return payload, 0

    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return payload, 0

    rows_by_ticker = {
        canonical_ticker(row.get("ticker")): row
        for row in rows
        if isinstance(row, dict) and canonical_ticker(row.get("ticker"))
    }
    targets: list[dict[str, Any]] = []
    for ticker in tickers:
        normalized = canonical_ticker(ticker)
        row = rows_by_ticker.get(normalized)
        if not row or is_curated_ticker(normalized):
            continue
        targets.append(row)
    if not targets:
        return payload, 0

    requester = request_reviews or (
        lambda batch, trends: review_industries_with_groq(batch, trends, api_key)
    )
    reviews: list[dict[str, str]] = []
    for batch in _chunked(targets, REVIEW_BATCH_SIZE):
        reviews.extend(requester(batch, trend_text))

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    reviewed_at = current.astimezone(timezone.utc).isoformat(timespec="seconds")
    return apply_industry_reviews(payload, reviews, reviewed_at)
