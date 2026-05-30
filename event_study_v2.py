"""강한 모멘텀 종목-일을 QQQ 이격도 구간별로 묶어 선행수익(20/40/60일) 측정. 캐시 재사용."""
import os, sys, glob, warnings
warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calculator.indicators import add_indicators
from calculator import market_regime as mr

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bt_cache")
EVAL_START = pd.Timestamp("2010-06-01")


def weekly_rsi(close):
    wk = close.resample("W-FRI").last().dropna(); d = wk.diff()
    ag = d.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    al = (-d.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    return (100-100/(1+ag/al.replace(0,np.nan))).reindex(close.index, method="ffill")


def qstate():
    q = add_indicators(pd.read_pickle(os.path.join(CACHE,"v2_QQQ.pkl")))
    q["wrsi"] = weekly_rsi(q["Close"]); closes=q["Close"].tolist(); idx=q.index
    prem=[]; rec=[]
    for i in range(len(q)):
        if i<200 or pd.isna(q["MA200"].iloc[i]): prem.append(np.nan); rec.append(False); continue
        lo=max(0,i-59); ds=[(closes[j]/q["MA200"].iloc[j]-1)*100 for j in range(lo,i+1) if q["MA200"].iloc[j]>0]
        st=mr.build_qqq_market_state({"close":q["Close"].iloc[i],"ma200":q["MA200"].iloc[i],
            "rsi":q["RSI"].iloc[i],"rsiD1":q["RSI_D1"].iloc[i],"macdHist":q["MACD_Hist"].iloc[i],
            "macdHistD1":q["MACD_Hist_D1"].iloc[i],"macdHistD2":q["MACD_Hist_D2"].iloc[i]},
            recent_min_dist=min(ds) if ds else None, weekly_rsi=q["wrsi"].iloc[i])
        prem.append(st["premiumPercent"]); rec.append(st["isRecoveryMarket"])
    return pd.DataFrame({"premium":prem,"recovery":rec}, index=idx)


def main():
    qs = qstate()
    rows=[]
    for fp in glob.glob(os.path.join(CACHE,"v2_*.pkl")):
        tk=os.path.basename(fp)[3:-4]
        if tk in ("QQQ","_VIX"): continue
        try: df=add_indicators(pd.read_pickle(fp))
        except Exception: continue
        if len(df)<300: continue
        c=df["Close"]
        f20=c.shift(-20)/c-1; f40=c.shift(-40)/c-1; f60=c.shift(-60)/c-1
        d=df.join(qs,how="inner")
        # 강한 모멘텀 종목-일: MA200 위, RSI 55~80, PctB>60, MACD히스토 양수
        m=((d["Close"]>d["MA200"])&(d["RSI"].between(55,80))&(d["PctB"]>60)&(d["MACD_Hist"]>0))
        m&=(d.index>=EVAL_START)&d["premium"].notna()
        sub=d[m]
        if sub.empty: continue
        r=pd.DataFrame({"premium":sub["premium"],"recovery":sub["recovery"],
            "f20":f20.reindex(sub.index),"f40":f40.reindex(sub.index),"f60":f60.reindex(sub.index)})
        rows.append(r)
    A=pd.concat(rows).dropna(subset=["f20"])
    bins=[-100,0,9,18,100]; lab=["≤0%","0~9%","9~18%",">18%"]
    A["bucket"]=pd.cut(A["premium"],bins=bins,labels=lab)
    def agg(g):
        return pd.Series({"표본":len(g),
            "f20평균%":round(g["f20"].mean()*100,2),"f20승률%":round((g["f20"]>0).mean()*100,1),
            "f40평균%":round(g["f40"].mean()*100,2),"f60평균%":round(g["f60"].mean()*100,2)})
    print("="*100); print("강한 모멘텀 종목-일의 QQQ 이격도 구간별 선행수익 (전체 시장)"); print("="*100)
    print(A.groupby("bucket").apply(agg).to_string())
    print("\n"+"="*100); print("회복장 한정"); print("="*100)
    print(A[A["recovery"]].groupby("bucket").apply(agg).to_string())


if __name__=="__main__":
    main()
