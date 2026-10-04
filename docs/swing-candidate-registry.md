# 추가 모의 후보 등록부 — 2026-10-04

기존 14개는 유지한다. 첫 추가 40개와 마지막 보충 15개를 합해 총 69개 비교 버전을 비공개 모의 원장에 기록한다. 공통 청산에는 시장 청산도 포함한다. 1·2·4·6번 대조군은 기존 `strategy-refinements-v1`에 있다. 미국 10월 5일 종가부터 기록하고 한국 12월 8일 이후 첫 점검한다.

| ID | 기준 신호 | 추가 조건 | 청산·시점 |
|---|---|---|---|
| `lab_p_rsi2_pullback` | 상승 추세에서 RSI2 과매도 눌림 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_pocket_pivot` | 최근 하락일 최대 거래량을 넘는 상승 돌파 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_strong_flag` | 급등 후 짧은 조정 돌파 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_volume_climax_recovery` | 대량 투매 다음 날 저점 지키기 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_anchored_vwap_reclaim` | 큰 거래량 발생일 기준 평균가격 재돌파 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_higher_low_breakout` | 확인된 고저점 상승 후 돌파 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_breakout_acceptance` | 돌파 후 5일간 가격 유지 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_obv_leads_price` | 거래량 지표 선행 후 가격 돌파 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_inside3_breakout` | 3일 내부봉 돌파 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_dry_pullback` | 거래량 감소 눌림 후 회복 | 없음 | 공통 -8%/+12%/20일 |
| `lab_p_vcp_breakout` | 변동폭 축소 후 돌파 | 없음 | 공통 -8%/+12%/20일 |
| `lab_s3_base` | 3번 | 없음 | 공통 -8%/+12%/20일 |
| `lab_s5_base` | 5번 | 없음 | 공통 -8%/+12%/20일 |
| `lab_s7_base` | 7번 | 없음 | 공통 -8%/+12%/20일 |
| `lab_s1_ma50_above200` | 1번 | MA50>MA200 | 공통 -8%/+12%/20일 |
| `lab_s1_volume_confirm` | 1번 | 거래량 ≥직전 20일 평균 1.2배 | 공통 -8%/+12%/20일 |
| `lab_s2_rs20_positive` | 2번 | 20일 수익률>QQQ | 공통 -8%/+12%/20일 |
| `lab_s2_efficient_trend` | 2번 | 20일 상승 및 경로 효율 ≥0.3 | 공통 -8%/+12%/20일 |
| `lab_s3_atr_limited` | 3번 | ATR14/가격 ≤5% | 공통 -8%/+12%/20일 |
| `lab_s3_rs20_positive` | 3번 | 20일 수익률>QQQ | 공통 -8%/+12%/20일 |
| `lab_s3_down_day_resilience` | 3번 | QQQ 하락일에 상대적으로 잘 버팀 | 공통 -8%/+12%/20일 |
| `lab_s4_ma50_above200` | 4번 | MA50>MA200 | 공통 -8%/+12%/20일 |
| `lab_s4_qqq_ma20_rising` | 4번 | QQQ MA20 상승 | 공통 -8%/+12%/20일 |
| `lab_s6_ma200_rising` | 6번 | MA200>20일 전 MA200 | 공통 -8%/+12%/20일 |
| `lab_s6_qqq_ma20_rising` | 6번 | QQQ MA20 상승 | 공통 -8%/+12%/20일 |
| `lab_s6_rs_vs_watchlist` | 6번 | 20일 수익률>관심종목 중간값 | 공통 -8%/+12%/20일 |
| `lab_s7_rs20_positive` | 7번 | 20일 수익률>QQQ | 공통 -8%/+12%/20일 |
| `lab_s7_rs_vs_watchlist` | 7번 | 20일 수익률>관심종목 중간값 | 공통 -8%/+12%/20일 |
| `lab_s7_both_relative_strength` | 7번 | QQQ와 관심종목 중간값 모두보다 강함 | 공통 -8%/+12%/20일 |
| `lab_s7_efficient_trend` | 7번 | 20일 상승 및 경로 효율 ≥0.3 | 공통 -8%/+12%/20일 |
| `lab_s7_down_day_resilience` | 7번 | QQQ 하락일에 상대적으로 잘 버팀 | 공통 -8%/+12%/20일 |
| `lab_s7_ma_cross_first_pullback` | 7번 | MA20/MA50 상향 교차 뒤 첫 눌림 | 공통 -8%/+12%/20일 |
| `lab_s3_exit_half_at6` | 3번 | 없음 | +6% 종가 후 다음 시가 절반 익절 |
| `lab_s7_exit_half_at6` | 7번 | 없음 | +6% 종가 후 다음 시가 절반 익절 |
| `lab_rsi2_pullback_exit_half_at6` | 상승 추세에서 RSI2 과매도 눌림 | 없음 | +6% 종가 후 다음 시가 절반 익절 |
| `lab_s4_exit_atr_2r` | 4번 | 없음 | ATR 기반 손절 4~12%, 목표 2배 |
| `lab_rsi2_pullback_exit_atr_2r` | 상승 추세에서 RSI2 과매도 눌림 | 없음 | ATR 기반 손절 4~12%, 목표 2배 |
| `lab_s4_exit_signal_low_failure` | 4번 | 없음 | 신호일 저점 종가 2회 이탈 시 청산 |
| `lab_s3_entry_delay1` | 3번 | 없음 | 공통 -8%/+12%/20일; D+2 시가 진입 |
| `lab_s4_exit_time10` | 4번 | 없음 | 공통 -8%/+12%, 최대 10일 |

## 진단 기록 전체

모의 매매로 선택하지 않은 패턴도 매일 통과·탈락을 저장한다. 패턴 발생 후 5·10·20일의 가격 경로는 시장 차단 여부를 구분해 진단용으로 남긴다. 모든 숫자는 신호일 종가까지의 데이터로 계산한다.

| 패턴 ID | 고정 정의 |
|---|---|
| `range_breakout` | 20-high breakout, volume>=1.5, close top quarter, aboveMA200 |
| `squeeze_breakout` | prior BBwidth<.75 prior60 mean,20-high breakout,volume>=1.2,aboveMA200 |
| `failed_breakdown` | low below prior20 low, close recovers it and open, close location>=.65 |
| `panic_reversal` | prior3 return<=-8%, close>prior high/open,volume>=1.2 |
| `gap_hold` | open gap>=3%,close>open,low>=prior close,volume>=1.5,aboveMA200 |
| `market_divergence` | QQQ5<=-2%,stock5>=0,5-high breakout,volume>=1.2 |
| `narrow_range_breakout` | prior range minimum7, close>prior high/MA200,volume>=1.3 |
| `ma200_reclaim` | cross aboveMA200,close>open,volume>=1.3 |
| `oversold_reversal` | prior RSI14<=30,close>prior high/open |
| `inside3_breakout` | prior3 bars inside D-4 range, close>D-4 high,volume>=1.3,aboveMA200 |
| `dry_pullback` | prior3 volume<.7 prior20 mean, priorclose<=MA20, close>MA20/MA200,MA50>MA200 |
| `rs_leader_pullback` | RS20vsQQQ>0,MA50>MA200,MA20 bullish touch/reclaim |
| `ma50_reclaim` | MA50 recross, aboveMA200 and MA200 rising20,volume>=1.2 |
| `high252_breakout` | 252-high breakout,volume>=1.3,aboveMA200 |
| `high55_breakout` | 55-high breakout,volume>=1.3,aboveMA200 |
| `vcp_breakout` | prior10 range<.6 previous10 range,20-high breakout,volume>=1.3,aboveMA200 |
| `gap_down_reclaim` | open gap<=-3%,close>priorclose/open/MA200,close location>=.7 |
| `double_bottom_reclaim` | prior10 low within3% preceding10 low,5-high breakout,volume>=1.2,aboveMA200 |
| `rs_first_breakout` | stock/QQQ ratio20 high before price20 high,close>prior high/MA200,volume>=1.2 |
| `rsi2_pullback` | close>MA200; MA200 rising over20 sessions; RSI2<10 |
| `pocket_pivot` | close>prior high and MA50>MA200; volume>maximum prior10 down-day volume |
| `strong_flag` | 20-session gain ending D-4>=15%; D-4 to D-1 return -8..0%; close>prior high and open |
| `volume_climax_recovery` | prior day volume>=2 prior20 and TR>=2 previous ATR, close in bottom quarter; today holds prior low and closes above prior midpoint/open/MA200 |
| `anchored_vwap_reclaim` | anchor at highest-volume prior20 bar, volume>=2 its prior20 mean; price crosses fixed-anchor typical-price VWAP; close>MA200, volume>=1.2 prior20 |
| `regression_reclaim` | prior60 causal trend residual z crosses from<=-2 yesterday to>-1 today; close>open and MA200 |
| `higher_low_breakout` | last two confirmed 2+2 pivots have rising highs and lows; first close above last confirmed high; above MA200; volume>=1.2 |
| `breakout_acceptance` | D-5 first closes above prior20 high; five later closes hold fixed level; current close within8% above level and aboveMA200 |
| `obv_leads_price` | OBV made a20-session high in last5 while price below20 high; close now crosses prior5 high aboveMA200; OBV rises over5 |
| `ma_cross_first_pullback` | MA20 crosses aboveMA50 in prior10; first subsequent MA20 touch with bullish reclaim; aboveMA200 |
| `breadth_followthrough` | same-day watchlist breadth aboveMA20>=50%, same members five sessions ago<=30%, at least10 paired names; QQQ3>1%; stock aboveMA20/MA200, volume>=1.2 |

기존 12개 단일 필터: RS20, RS60, MA50>MA200, MA200 상승, 거래량 ≥1.2배, 거래량 ≤2배, 종가 위치 ≥70%, MA20 이격 ≤8%, ATR/가격 ≤5%, QQQ>MA20, QQQ MA20 상승, MACD 개선.

| 추가 단일 필터 | 고정 정의 |
|---|---|
| `efficient_trend` | positive20-return and 20-session efficiency ratio>=.3 |
| `up_volume_dominates` | prior/current5 up-day volume>=1.5 down-day volume and some down volume |
| `resistance_room` | at least2 ATR below prior60 high OR already above prior60 high |
| `no_range_shock` | today true range<=2 prior ATR14 |
| `above_vwap20` | close>rolling20 typical-price volume-weighted average (daily, not intraday VWAP) |
| `broad_participation` | at least10 watched names and >=50% aboveMA20 on signal date |
| `rs_vs_watchlist` | 20-session stock return>median same-day watched stock return; at least10 names |
| `down_day_resilience` | mean stock-minus-QQQ daily return on prior/current20 QQQ down-days>0; at least5 matched days |

두 상대강도 동시 충족과 이평선 교차 뒤 첫 눌림도 별도 표시한다. 결측은 탈락으로 확정하지 않고 원형과 보완형의 비교 가능한 날짜를 맞춘다. 신호 0건은 실패가 아니라 미관측이다.

## 마지막 보충 15개

모두 공통 연구 청산(-8%/+12%/20일 및 시장 청산, 다음 시가)과 비용 0.4%다. 기존 원형 대조군과 비교하며 12월 8일까지 정의를 고정한다.

| ID | 기준 신호 | 추가 조건 |
|---|---|---|
| `final_p_breakout_first_retest` | 돌파 가격 첫 재시험 지키기 | 없음 |
| `final_p_failed_breakout_reclaim` | 실패한 돌파 가격 회복 | 없음 |
| `final_p_outside_reversal` | 전일 저점 이탈 뒤 전일 고가 위 마감 | 없음 |
| `final_p_gap_first_retest` | 상승 갭 이후 첫 눌림 | 없음 |
| `final_p_shock_high_rebreak` | 대량 상승일 고점 재돌파 | 없음 |
| `final_p_confirmed_rsi_divergence` | 가격 저점 하락·RSI 저점 상승 | 없음 |
| `final_s1_few_distribution_days` | 1번 | 최근 대량 매도일이 적음 |
| `final_s2_fresh_ma_support` | 2번 | 최근 10일 접촉 없던 이평선 첫 반등 |
| `final_s2_intraday_supported_trend` | 2번 | 최근 20일 정규장 상승이 양수이고 야간 상승 이상 |
| `final_s2_weekly_uptrend` | 2번 | 완료 주봉이 10주선 위이고 10주선 상승 |
| `final_s3_intraday_supported_trend` | 3번 | 최근 20일 정규장 상승이 양수이고 야간 상승 이상 |
| `final_s3_nearby_price_support` | 3번 | 직전 5일 저점까지 거리 0 초과 5% 이하 |
| `final_s4_few_distribution_days` | 4번 | 최근 대량 매도일이 적음 |
| `final_s6_few_distribution_days` | 6번 | 최근 대량 매도일이 적음 |
| `final_s7_intraday_supported_trend` | 7번 | 최근 20일 정규장 상승이 양수이고 야간 상승 이상 |

### 추가 진단 정의

| 패턴 ID | 고정 정의 |
|---|---|
| `breakout_first_retest` | volume>=1.3 first20-high breakout2..10 sessions ago; first low retest within -3..+1% of frozen level, intervening closes hold it; bullish close above level and MA200 |
| `failed_breakout_reclaim` | same breakout anchor within10; first failure within3 sessions, no reclaim before today; close now reclaims frozen level above MA200, volume>=1.2 |
| `outside_reversal` | prior3-session return<0; today's low<prior low and close>prior high/open/MA200 |
| `gap_first_retest` | bullish gap>=3%,volume>=2 anchor2..10 sessions ago; first retest anchor low within -3..+1%; intervening closes hold low; close>anchor midpoint/open/MA200 |
| `shock_high_rebreak` | bullish >=4% day2..5 sessions ago,TR>=2 priorATR,volume>=1.5; later lows hold its low and closes stay below its high; close now>anchor high/MA200,volume>=1.2 |
| `confirmed_rsi_divergence` | two latest confirmed2+2 lows within40 sessions: lower price by<=10%,RSI improves>=5 from<35; first close above newer pivot high after confirmation, aboveMA200 |

| 보완 조건 ID | 고정 정의 |
|---|---|
| `fresh_ma_support` | current bullish bounce at MA20/50/120/200 with previous10 lows all above that MA*1.003 |
| `no_recent_failed_breakout` | no prior20-high volume1.3 breakout closing below frozen level within3 sessions in last10 sessions through D |
| `few_distribution_days` | prior10 sessions have at most1 day with return<=-1% and volume>=1.2 prior20 mean |
| `intraday_supported_trend` | last20 cumulative log(close/open)>0 and >= cumulative log(open/prior close) |
| `nearby_price_support` | distance from close to prior5-session low is >0 and <=5%; this is a signal filter, not a5% stop |
| `weekly_uptrend` | last completed Friday week close>10-week MA and that MA>four weeks earlier; conservative Friday labels |

전체 기록은 36개 패턴과 26개 단일 보완 조건, 기존 두 조합 조건을 포함한다. 신호가 희소하거나 결과가 약한 패턴도 삭제하지 않으며, 가상 매매로 채택하지 않은 조건도 통과·탈락·당시 수치를 남긴다.
