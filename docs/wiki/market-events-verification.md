# 시장 주요 이벤트 공식 일정 검증

최종 갱신: 2026-10-12

## 동작

- 금리·고용·CPI·PPI·PCE만 공식 출처에서 날짜와 시간이 명확하면 캐시를 자동 수정한다.
- 확실하지 않으면 기존 캐시를 유지하고 관리자 확인 메일을 보낸다. 비공식 캘린더는 쓰지 않는다.

근거: `calculator/pipeline.py`의 `apply_market_event_verification`, `scripts/web_refresh_notifications.py`

## BLS 조회

- `bls.gov` 일정 HTML은 일반 Python 클라이언트에 HTTP 403을 줄 수 있다. ICS·연간 일정 페이지도 같은 문제가 있다.
- 일반 HTTP 조회가 실패하거나 요청 연도의 유효한 날짜·시간 행이 없으면 `curl_cffi`의 Chrome 호환 HTTP/TLS 요청으로 같은 공식 페이지를 다시 읽는다. 자동 실행은 고정 버전 `0.13.0`을 설치한다.
- 타임아웃·429·502·503·504는 각 통신 방식에서 한 번 재시도한다. 두 방식 모두 실패하면 기존 일정을 유지하고 수동 확인 메일을 보낸다.
- Wayback 사본은 과거 자료이므로 최신 일정 변경 여부를 검증하거나 자동 수정하는 근거로 사용하지 않는다.
- CPI·PPI 개별 일정 페이지는 현재 발표월을 지우고 다음 달 이후만 남길 수 있다. 따라서 HTTP 성공과 일부 행 파싱만으로 전체 일정 검증 성공을 판단하지 않는다.
- 캐시에서 아직 지나지 않은 CPI·PPI 발표월이 개별 페이지에 없으면 `/schedule/{year}/{month:02d}_sched_list.htm`의 공식 월간 목록을 읽는다. 누락이 남으면 `/schedule/{year}/home.htm`의 공식 연간 목록도 읽는다. 각 페이지는 일반 HTTP와 Chrome 호환 HTTP를 순서대로 시도하고 일시 오류는 재시도한다.
- 목록의 `Date / Time / Release`를 읽으며, `Consumer Price Index for `와 `Producer Price Index for `만 정확히 선택한다. 통계 대상월이 아닌 발표일의 월로 매칭하고, 동부시간을 서머타임을 반영한 한국시간으로 바꾼다.
- 복구된 항목만 기존 검증 경로로 전달한다. 공식 날짜·시간이 끝내 없으면 기존 일정을 보존한다. 다른 이벤트와 트렌드 생성 로직은 변경하지 않는다.

근거: `calculator/pipeline.py`의 `fetch_bls_schedule_html`, `fetch_bls_browser_text`, `.github/workflows/web-data-refresh.yml`, `tests/test_market_events.py`

## 한계

- BLS 서버 장애·추가 접속 제한·페이지 형식 변경까지 영구적으로 방지할 수는 없다.
- 현재 공식 페이지를 두 통신 방식으로도 확인할 수 없으면 수동 확인 메일을 보낸다. 임의의 날짜를 채우거나 검증 성공으로 표시하지 않는다.

연결: [[web-data-refresh]], [[index]]
