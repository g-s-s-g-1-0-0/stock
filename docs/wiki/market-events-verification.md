# 시장 주요 이벤트 공식 일정 검증

최종 갱신: 2026-10-06

## 동작

- 금리·고용·CPI·PPI·PCE만 공식 출처에서 날짜와 시간이 명확하면 캐시를 자동 수정한다.
- 확실하지 않으면 기존 캐시를 유지하고 관리자 확인 메일을 보낸다. 비공식 캘린더는 쓰지 않는다.

근거: `calculator/pipeline.py`의 `apply_market_event_verification`, `scripts/web_refresh_notifications.py`

## BLS 조회

- `bls.gov` 일정 HTML은 일반 Python 클라이언트에 HTTP 403을 줄 수 있다. ICS·연간 일정 페이지도 같은 문제가 있다.
- 일반 HTTP 조회가 실패하거나 요청 연도의 유효한 날짜·시간 행이 없으면 `curl_cffi`의 Chrome 호환 HTTP/TLS 요청으로 같은 공식 페이지를 다시 읽는다. 자동 실행은 고정 버전 `0.13.0`을 설치한다.
- 타임아웃·429·502·503·504는 각 통신 방식에서 한 번 재시도한다. 두 방식 모두 실패하면 기존 일정을 유지하고 수동 확인 메일을 보낸다.
- Wayback 사본은 과거 자료이므로 최신 일정 변경 여부를 검증하거나 자동 수정하는 근거로 사용하지 않는다.

근거: `calculator/pipeline.py`의 `fetch_bls_schedule_html`, `fetch_bls_browser_text`, `.github/workflows/web-data-refresh.yml`, `tests/test_market_events.py`

## 한계

- BLS 서버 장애·추가 접속 제한·페이지 형식 변경까지 영구적으로 방지할 수는 없다.
- 현재 공식 페이지를 두 통신 방식으로도 확인할 수 없으면 수동 확인 메일을 보낸다. 임의의 날짜를 채우거나 검증 성공으로 표시하지 않는다.

연결: [[web-data-refresh]], [[index]]
