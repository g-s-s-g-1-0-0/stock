# 시장 주요 이벤트 공식 일정 검증

최종 갱신: 2026-09-21

## 동작

- 금리·고용·CPI·PPI·PCE만 공식 출처에서 날짜와 시간이 명확하면 캐시를 자동 수정한다.
- 확실하지 않으면 기존 캐시를 유지하고 관리자 확인 메일을 보낸다. 비공식 캘린더는 쓰지 않는다.

근거: `calculator/pipeline.py`의 `apply_market_event_verification`, `scripts/web_refresh_notifications.py`

## BLS 조회

- `bls.gov` 일정 HTML은 Akamai가 자동 클라이언트에 HTTP 403을 준다. ICS·연간 일정 페이지도 같다.
- 폴백은 Internet Archive Wayback이다. 기본 스냅샷 URL은 툴바와 `playback` iframe만 있는 껍데기라 발표일이 없다.
- 2026-09-21 수정 후 Wayback는 `.../web/{timestamp}if_/...` 원문을 읽고, 껍데기가 오면 iframe을 따라가며, 429·타임아웃은 재시도한다.

근거: `calculator/pipeline.py`의 `fetch_bls_schedule_html`, `wayback_playback_url`, `fetch_wayback_html`, `tests/test_market_events.py`

## 한계

- BLS 라이브 403 자체는 우회하지 않는다.
- Wayback이 429이거나 스냅샷이 없으면 확인 메일은 다시 온다. 그때는 관리자 화면에서 공식 일정을 직접 고친다.

연결: [[web-data-refresh]], [[index]]
