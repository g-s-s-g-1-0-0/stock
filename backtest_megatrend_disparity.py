"""
backtest_megatrend_disparity.py
===============================
질문: "이격도가 20% 가까이 높아도 오르는 종목이 많다. 메가트렌드 top5 산업군
종목은 이격도 매수 제한을 풀고 신호를 줬을 때 어떤가?"

- 메가트렌드 top5 (data/cache/market-trends.json 최근 주간 랭킹 일관 상위):
    1) AI 인프라(데이터센터·광통신·전력/냉각)  2) 반도체  3) 클라우드/AI SW
    4) 전기차/에너지  5) 핀테크/가상화폐
- 종목을 MEGA(top5 산업군) / OTHER(그 외)로 분류.
- 각 그룹에서 전략 A~G별로 '이격도 제한 ON(현행)' vs 'OFF(완화)'를 비교.
  → 이격도 완화가 MEGA 그룹에서만 유효한지(=강세 산업군 한정 가치) 확인.
- 이격도 제한 정의/격리/청산/지표는 backtest_disparity_removal 재사용.
"""
from __future__ import annotations
import os, sys, time, warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calculator.industry_classification import CURATED_BY_TICKER
import backtest_qqq_block_v2 as bt
import backtest_disparity_removal as dr

# 메가트렌드 top5 매칭 키워드(국문 산업 문자열 대상)
MEGA_KEYWORDS = (
    # AI 인프라 / 데이터센터 / 광통신 / 전력·냉각
    "AI 인프라", "데이터센터", "광통신", "트랜시버", "냉각", "UPS", "광부품",
    "인터커넥트", "광네트워크", "광섬유", "광송수신", "광인터커넥트", "스토리지", "HDD",
    "전력관리", "전력 인프라", "전력수요", "가스터빈", "발전",
    # 반도체
    "반도체", "GPU", "HBM", "DRAM", "NAND", "메모리", "파운드리", "포토마스크",
    "패키징", "패키지기판", "이온주입", "테스트 장비", "웨이퍼", "SiC", "메트롤로지",
    "프로브", "광전자", "포토닉스",
    # 클라우드 / AI 소프트웨어
    "클라우드", "소프트웨어", "AI", "빅데이터", "AIP", "Azure", "Copilot", "TPU",
    "CUDA", "AI 플랫폼", "AI 가속기", "AI 솔루션",
    # 전기차 / 에너지
    "전기차", "배터리", "2차전지", "양극재", "리튬", "에너지", "태양광", "수소",
    "연료전지", "원전", "SMR",
    # 핀테크 / 가상화폐
    "핀테크", "가상화폐", "암호화폐", "스테이블코인", "블록체인", "채굴", "비트코인",
    "브로커리지", "USDC",
)

# 큐레이션에 없는 나스닥100/다우 종목 중 메가트렌드 화이트리스트(반도체/AI/클라우드/EV/에너지/핀테크)
MEGA_EXTRA = {
    # 반도체
    "QCOM", "TXN", "AMAT", "ADI", "LRCX", "KLAC", "MCHP", "NXPI", "ASML", "MRVL",
    "SMCI", "ARM", "GFS", "TER", "PLAB", "SKYT", "FORM", "ONTO",
    # 소프트웨어/클라우드/AI
    "ORCL", "CRM", "NOW", "SNPS", "CDNS", "ADSK", "WDAY", "PANW", "CRWD", "FTNT",
    "ZS", "DDOG", "MDB", "TEAM", "ANSS", "TTD", "INTU", "META", "AMZN", "AAPL",
    # AI 인프라/전력/광
    "CEG", "CIEN", "SMTC", "VRT",
    # EV/소재
    "RIVN", "LCID",
    # 핀테크/크립토
    "COIN", "PYPL",
}
# 메가에서 명시적으로 제외(보더라인 유틸/소비/통신)
NOT_MEGA = {"NEE", "XEL", "KDP", "MDLZ", "KHC", "PEP", "KO"}


def is_mega(ticker: str) -> bool:
    t = ticker.upper()
    if t in NOT_MEGA:
        return False
    if t in MEGA_EXTRA:
        return True
    cur = CURATED_BY_TICKER.get(t)
    if cur:
        industry = cur[1]
        return any(k.lower() in industry.lower() for k in MEGA_KEYWORDS)
    return False


def build_groups():
    watch = dr.UNIVERSES.get("관심종목(US)", [])
    candidates = sorted(set(bt.NASDAQ100) | set(bt.SP_MEGA) | set(watch) | set(dr.DOW30)
                        | {t for t in CURATED_BY_TICKER if t.isalpha()})
    mega = [t for t in candidates if is_mega(t)]
    other = [t for t in candidates if not is_mega(t)]
    return mega, other


def main():
    t0 = time.time()
    mega, other = build_groups()
    print(f"MEGA(메가트렌드 top5 산업군) {len(mega)}종목:\n  {', '.join(mega)}")
    print(f"\nOTHER(그 외) {len(other)}종목:\n  {', '.join(other)}")

    print("\nQQQ / VIX (최대 기간) 로딩…")
    qqq = dr.get("QQQ"); vixdf = dr.get("^VIX")
    qstate = bt.build_qqq_state(qqq).dropna(subset=["premium"])
    vix = vixdf["Close"].reindex(qstate.index, method="ffill")
    eval_start = qstate.index[0]
    print(f"기간 {qstate.index[0].date()}~{qstate.index[-1].date()} ({len(qstate)}일)")

    res_mega = dr.run_universe("MEGA(메가트렌드 top5)", mega, qstate, vix, eval_start)
    res_other = dr.run_universe("OTHER(그 외, 대조군)", other, qstate, vix, eval_start)

    # 전략 합산(격리·중복가능) 헤드라인: 각 그룹 ON vs OFF
    print(f"\n{'='*150}\n전략 합산(격리, 중복 가능) — 그룹별 이격도 ON vs OFF 헤드라인\n{'='*150}")
    stocks_mega = dr.load_universe(mega, qstate, vix)
    stocks_other = dr.load_universe(other, qstate, vix)
    head = []
    for gname, stocks in (("MEGA", stocks_mega), ("OTHER", stocks_other)):
        for mode in ("ON", "OFF"):
            pool = []
            for s in dr.STRATS:
                for t, (d, rws, va, pk) in stocks.items():
                    pool += dr.simulate_single(d, rws, va, pk, eval_start, s, mode)
            mt = dr.metrics(pool)
            head.append({"그룹": gname, "이격도": mode, **mt})
    hdf = pd.DataFrame(head)
    pd.set_option("display.width", 240); pd.set_option("display.max_columns", 30)
    print(hdf.to_string(index=False))

    big = pd.concat([res_mega, res_other], ignore_index=True)
    out = os.path.join(dr.ROOT, "backtest_megatrend_disparity_summary.csv")
    big.to_csv(out, index=False)
    hdf.to_csv(os.path.join(dr.ROOT, "backtest_megatrend_disparity_headline.csv"), index=False)
    print(f"\n저장: {out}")
    print(f"총 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
