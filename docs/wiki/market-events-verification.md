# 시장 주요 이벤트 공식 일정 검증

최종 갱신: 2026-10-06

## 동작

- 금리·고용·CPI·PPI·PCE만 공식 출처에서 날짜와 시간이 명확하면 캐시를 자동 수정한다.
- 확실하지 않으면 기존 캐시를 유지하고 관리자 화면에 확인 필요 내용을 기록한다. 조회 실패·수동 확인 요청 메일은 보내지 않는다. 비공식 캘린더는 쓰지 않는다.
- 공식 일정이 실제 자동 수정된 경우에만 수정 내역 메일을 보낸다. 같은 실행에 조회 실패가 있어도 수정 메일에 수동 확인 요청을 포함하지 않는다.

근거: `calculator/pipeline.py`의 `apply_market_event_verification`, `scripts/web_refresh_notifications.py`

## BLS 조회

- `bls.gov` 일정 HTML은 Akamai가 자동 클라이언트에 HTTP 403을 준다. ICS·연간 일정 페이지도 같다.
- 폴백은 Internet Archive Wayback이다. 기본 스냅샷 URL은 툴바와 `playback` iframe만 있는 껍데기라 발표일이 없다.
- Wayback의 가장 가까운 스냅샷이 대상 연도 일정을 담지 않을 수 있다. 최근 스냅샷을 여러 개 조회해 원문을 읽고, 요청 연도의 발표일 행이 있는 사본을 자동 선택한다.
- `.../web/{timestamp}if_/...` 원문을 읽고, 껍데기가 오면 iframe을 따라가며, 429·타임아웃은 재시도한다.

근거: `calculator/pipeline.py`의 `fetch_bls_schedule_html`, `wayback_playback_url`, `fetch_wayback_html`, `tests/test_market_events.py`

## 한계

- BLS 라이브 403 자체는 우회하지 않는다.
- BLS 라이브 페이지가 막혀 있고 Wayback에도 대상 연도 발표일이 포함된 사본이 없으면 관리자 화면에 기록하고 기존 일정을 유지한다. 임의의 날짜를 채우지 않는다.

연결: [[web-data-refresh]], [[index]]
