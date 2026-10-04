"""Causal daily research features; no operating strategy registration."""
from __future__ import annotations

import numpy as np
import pandas as pd

from calculator.indicators import add_indicators, rsi

PATTERNS = {
    "rsi2_pullback": "close>MA200; MA200 rising over20 sessions; RSI2<10",
    "pocket_pivot": "close>prior high and MA50>MA200; volume>maximum prior10 down-day volume",
    "strong_flag": "20-session gain ending D-4>=15%; D-4 to D-1 return -8..0%; close>prior high and open",
    "volume_climax_recovery": "prior day volume>=2 prior20 and TR>=2 previous ATR, close in bottom quarter; today holds prior low and closes above prior midpoint/open/MA200",
    "anchored_vwap_reclaim": "anchor at highest-volume prior20 bar, volume>=2 its prior20 mean; price crosses fixed-anchor typical-price VWAP; close>MA200, volume>=1.2 prior20",
    "regression_reclaim": "prior60 causal trend residual z crosses from<=-2 yesterday to>-1 today; close>open and MA200",
    "higher_low_breakout": "last two confirmed 2+2 pivots have rising highs and lows; first close above last confirmed high; above MA200; volume>=1.2",
    "breakout_acceptance": "D-5 first closes above prior20 high; five later closes hold fixed level; current close within8% above level and aboveMA200",
    "obv_leads_price": "OBV made a20-session high in last5 while price below20 high; close now crosses prior5 high aboveMA200; OBV rises over5",
    "ma_cross_first_pullback": "MA20 crosses aboveMA50 in prior10; first subsequent MA20 touch with bullish reclaim; aboveMA200",
    "breadth_followthrough": "same-day watchlist breadth aboveMA20>=50%, same members five sessions ago<=30%, at least10 paired names; QQQ3>1%; stock aboveMA20/MA200, volume>=1.2",
}
LEGACY_PATTERNS = {
    "range_breakout": "20-high breakout, volume>=1.5, close top quarter, aboveMA200",
    "squeeze_breakout": "prior BBwidth<.75 prior60 mean,20-high breakout,volume>=1.2,aboveMA200",
    "failed_breakdown": "low below prior20 low, close recovers it and open, close location>=.65",
    "panic_reversal": "prior3 return<=-8%, close>prior high/open,volume>=1.2",
    "gap_hold": "open gap>=3%,close>open,low>=prior close,volume>=1.5,aboveMA200",
    "market_divergence": "QQQ5<=-2%,stock5>=0,5-high breakout,volume>=1.2",
    "narrow_range_breakout": "prior range minimum7, close>prior high/MA200,volume>=1.3",
    "ma200_reclaim": "cross aboveMA200,close>open,volume>=1.3",
    "oversold_reversal": "prior RSI14<=30,close>prior high/open",
    "inside3_breakout": "prior3 bars inside D-4 range, close>D-4 high,volume>=1.3,aboveMA200",
    "dry_pullback": "prior3 volume<.7 prior20 mean, priorclose<=MA20, close>MA20/MA200,MA50>MA200",
    "rs_leader_pullback": "RS20vsQQQ>0,MA50>MA200,MA20 bullish touch/reclaim",
    "ma50_reclaim": "MA50 recross, aboveMA200 and MA200 rising20,volume>=1.2",
    "high252_breakout": "252-high breakout,volume>=1.3,aboveMA200",
    "high55_breakout": "55-high breakout,volume>=1.3,aboveMA200",
    "vcp_breakout": "prior10 range<.6 previous10 range,20-high breakout,volume>=1.3,aboveMA200",
    "gap_down_reclaim": "open gap<=-3%,close>priorclose/open/MA200,close location>=.7",
    "double_bottom_reclaim": "prior10 low within3% preceding10 low,5-high breakout,volume>=1.2,aboveMA200",
    "rs_first_breakout": "stock/QQQ ratio20 high before price20 high,close>prior high/MA200,volume>=1.2",
}
ALL_PATTERNS = {**LEGACY_PATTERNS, **PATTERNS}

FILTERS = {
    "efficient_trend": "positive20-return and 20-session efficiency ratio>=.3",
    "up_volume_dominates": "prior/current5 up-day volume>=1.5 down-day volume and some down volume",
    "resistance_room": "at least2 ATR below prior60 high OR already above prior60 high",
    "no_range_shock": "today true range<=2 prior ATR14",
    "above_vwap20": "close>rolling20 typical-price volume-weighted average (daily, not intraday VWAP)",
    "broad_participation": "at least10 watched names and >=50% aboveMA20 on signal date",
    "rs_vs_watchlist": "20-session stock return>median same-day watched stock return; at least10 names",
    "down_day_resilience": "mean stock-minus-QQQ daily return on prior/current20 QQQ down-days>0; at least5 matched days",
}


def feature_frame(frame, benchmark):
    f = add_indicators(frame.copy())
    c, h, l, o, v = (f[k] for k in ("Close", "High", "Low", "Open", "Volume"))
    ma20, ma50, ma200 = c.rolling(20).mean(), c.rolling(50).mean(), f.MA200
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    prior_volume = v.shift().rolling(20).mean()
    vol_ratio = v / prior_volume.replace(0, np.nan)
    clv = (c-l)/(h-l).replace(0, np.nan)
    high20 = h.shift().rolling(20).max()
    high5 = h.shift().rolling(5).max()
    typ = (h+l+c)/3
    vwap20 = (typ*v).rolling(20).sum()/v.rolling(20).sum().replace(0, np.nan)
    qr = benchmark.Close.pct_change().reindex(f.index)
    residual = (c.pct_change()-qr).where(qr<0)
    obv = (np.sign(c.diff()).fillna(0)*v).cumsum()
    efficiency = c.diff(20).abs()/c.diff().abs().rolling(20).sum().replace(0, np.nan)
    upvol = v.where(c>c.shift(), 0).rolling(5).sum()
    downvol = v.where(c<c.shift(), 0).rolling(5).sum()
    f['atr14'], f['rsi2'], f['volumePriorRatio'] = atr, rsi(c,2), vol_ratio
    f['ma20'], f['ma50'], f['ma200Prior20'] = ma20, ma50, ma200.shift(20)
    f['return20'], f['efficiency20'], f['vwap20'] = c.pct_change(20), efficiency, vwap20
    f['trueRangeRatio'] = tr/atr.shift().replace(0,np.nan)
    f['upDownVolumeRatio5'] = upvol/downvol.replace(0,np.nan)
    f['resilience20'] = residual.rolling(20,min_periods=5).mean()
    f['priorHigh60'] = h.shift().rolling(60).max()
    f['rsi2_pullback']=(c>ma200)&(ma200>ma200.shift(20))&(f.rsi2<10)
    f['pocket_pivot']=(c>h.shift())&(c>ma50)&(ma50>ma200)&(v>v.where(c<c.shift()).shift().rolling(10,min_periods=1).max())
    f['strong_flag']=(c.shift(4)/c.shift(24)-1>=.15)&(c.shift()/c.shift(4)-1).between(-.08,0)&(c>h.shift())&(c>o)
    f['volume_climax_recovery']=(vol_ratio.shift()>=2)&(tr.shift()>=2*atr.shift(2))&(clv.shift()<=.25)&(l>=l.shift())&(c>(h.shift()+l.shift())/2)&(c>o)&(c>ma200)
    f['anchored_vwap_reclaim']=False
    f['anchorVWAP']=np.nan;f['anchorSession']=None
    f['regressionZ']=np.nan;f['higher_low_breakout']=False
    highs=[];lows=[];f['confirmedPivotHigh']=np.nan;f['confirmedPivotLow']=np.nan
    f['ma_cross_first_pullback']=False;cross=None;used=False
    cv,hv,lv,vv,tv = [s.to_numpy() for s in (c,h,l,v,typ)]
    for i in range(len(f)):
        if i>=60 and np.isfinite(cv[i-60:i+1]).all():
            y=cv[i-60:i];x=np.arange(60);slope,intercept=np.polyfit(x,y,1)
            noise=np.std(y-(slope*x+intercept),ddof=2)
            if noise>0:f.loc[f.index[i],'regressionZ']=(cv[i]-(slope*60+intercept))/noise
        if i>=40:
            anchor=i-20+int(np.argmax(vv[i-20:i]));prior=vv[anchor-20:anchor].mean()
            weights=vv[anchor:i+1];prev_weights=vv[anchor:i]
            if weights.sum()>0 and prev_weights.sum()>0:
                av=(tv[anchor:i+1]*weights).sum()/weights.sum();pv=(tv[anchor:i]*prev_weights).sum()/prev_weights.sum()
                f.loc[f.index[i],'anchorVWAP']=av;f.loc[f.index[i],'anchorSession']=str(f.index[anchor])
                f.loc[f.index[i],'anchored_vwap_reclaim']=bool(prior>0 and vv[anchor]>=2*prior and cv[i-1]<=pv and cv[i]>av and cv[i]>ma200.iloc[i] and vol_ratio.iloc[i]>=1.2)
        if i>=4:
            j=i-2
            if hv[j]>max(hv[j-2:j]) and hv[j]>max(hv[j+1:i+1]):highs.append((j,hv[j]))
            if lv[j]<min(lv[j-2:j]) and lv[j]<min(lv[j+1:i+1]):lows.append((j,lv[j]))
            if highs:f.loc[f.index[i],'confirmedPivotHigh']=highs[-1][1]
            if lows:f.loc[f.index[i],'confirmedPivotLow']=lows[-1][1]
            if len(highs)>=2 and len(lows)>=2:
                level=highs[-1][1]
                f.loc[f.index[i],'higher_low_breakout']=bool(highs[-1][1]>highs[-2][1] and lows[-1][1]>lows[-2][1] and cv[i-1]<=level<cv[i] and cv[i]>ma200.iloc[i] and vol_ratio.iloc[i]>=1.2)
        if i>=50 and ma20.iloc[i]>ma50.iloc[i] and ma20.iloc[i-1]<=ma50.iloc[i-1]:cross=i;used=False
        if cross is not None and 0<i-cross<=10 and not used:
            passed=lv[i]<=ma20.iloc[i]*1.003 and cv[i]>ma20.iloc[i] and cv[i]>o.iloc[i] and cv[i]>cv[i-1]
            if passed:
                used=True;f.loc[f.index[i],'ma_cross_first_pullback']=bool(cv[i]>ma200.iloc[i])
    f['regression_reclaim']=(f.regressionZ.shift()<=-2)&(f.regressionZ> -1)&(c>o)&(c>ma200)
    level=high20.shift(5)
    first=(c.shift(5)>level)&(c.shift(6)<=level)
    holds=pd.concat([c.shift(k)>=level for k in range(5)],axis=1).all(axis=1)
    f['breakout_acceptance']=first&holds&(c<=level*1.08)&(c>ma200)
    leads=(obv>obv.shift().rolling(20).max())&(c<=high20)
    f['obv_leads_price']=leads.shift().rolling(5).max().eq(1)&(c>high5)&(c.shift()<=high5)&(c>ma200)&(obv>obv.shift(5))
    prior_high=h.shift();prior_low20=l.shift().rolling(20).min()
    stock5=c.pct_change(5);qqq5=benchmark.Close.pct_change(5).reindex(f.index)
    rs20=c.pct_change(20)-benchmark.Close.pct_change(20).reindex(f.index)
    gap=o/c.shift()-1;above=c>ma200
    width=f.BB_Width.shift();squeeze=width/width.rolling(60).mean().replace(0,np.nan)
    ranges=(h-l).shift()
    f['range_breakout']=(c>high20)&(vol_ratio>=1.5)&above&(clv>=.75)
    f['squeeze_breakout']=(squeeze<.75)&(c>high20)&(vol_ratio>=1.2)&above
    f['failed_breakdown']=(l<prior_low20)&(c>prior_low20)&(c>o)&(clv>=.65)
    f['panic_reversal']=(c.shift()/c.shift(4)-1<=-.08)&(c>prior_high)&(c>o)&(vol_ratio>=1.2)
    f['gap_hold']=(gap>=.03)&(c>o)&(l>=c.shift())&(vol_ratio>=1.5)&above
    f['market_divergence']=(qqq5<=-.02)&(stock5>=0)&(c>high5)&(vol_ratio>=1.2)
    f['narrow_range_breakout']=(ranges<=ranges.rolling(7).min())&(c>prior_high)&above&(vol_ratio>=1.3)
    f['ma200_reclaim']=(c.shift()<=ma200.shift())&above&(c>o)&(vol_ratio>=1.3)
    f['oversold_reversal']=(f.RSI.shift()<=30)&(c>prior_high)&(c>o)
    f['inside3_breakout']=(h.shift().rolling(3).max()<=h.shift(4))&(l.shift().rolling(3).min()>=l.shift(4))&(c>h.shift(4))&(vol_ratio>=1.3)&above
    f['dry_pullback']=(v.shift().rolling(3).mean()<.7*prior_volume)&(c.shift()<=ma20.shift())&(c>ma20)&above&(ma50>ma200)
    f['rs_leader_pullback']=(rs20>0)&(ma50>ma200)&(l<=ma20*1.003)&(c>ma20)&(c>o)&(c>c.shift())
    f['ma50_reclaim']=(c.shift()<=ma50.shift())&(c>ma50)&above&(ma200>ma200.shift(20))&(vol_ratio>=1.2)
    f['high252_breakout']=(c>h.shift().rolling(252).max())&above&(vol_ratio>=1.3)
    f['high55_breakout']=(c>h.shift().rolling(55).max())&above&(vol_ratio>=1.3)
    recent=h.shift().rolling(10).max()-l.shift().rolling(10).min()
    older=h.shift(11).rolling(10).max()-l.shift(11).rolling(10).min()
    f['vcp_breakout']=(recent<.6*older)&(c>high20)&above&(vol_ratio>=1.3)
    f['gap_down_reclaim']=(gap<=-.03)&(c>c.shift())&(c>o)&above&(clv>=.7)
    lowratio=l.shift().rolling(10).min()/l.shift(11).rolling(10).min()
    f['double_bottom_reclaim']=lowratio.between(.97,1.03)&(c>high5)&above&(vol_ratio>=1.2)
    ratio=c/benchmark.Close.reindex(f.index)
    f['rs_first_breakout']=(ratio>ratio.shift().rolling(20).max())&(c<=high20)&above&(c>prior_high)&(vol_ratio>=1.2)
    f['rs20']=rs20*100
    f['qqqAbove20']=(benchmark.Close>benchmark.Close.rolling(20).mean()).reindex(f.index)
    f['qqqMA20Rising']=(benchmark.Close.rolling(20).mean()>benchmark.Close.rolling(20).mean().shift(5)).reindex(f.index)
    f['rs60']=100*(c.pct_change(60)-benchmark.Close.pct_change(60).reindex(f.index))
    f['closeLocation']=clv
    f['efficient_trend']=(c.pct_change(20)>0)&(efficiency>=.3)
    f['up_volume_dominates']=(downvol>0)&(upvol>=1.5*downvol)
    f['resistance_room']=((f.priorHigh60-c)>=2*atr)|(c>f.priorHigh60)
    f['no_range_shock']=tr<=2*atr.shift()
    f['above_vwap20']=c>vwap20
    f['down_day_resilience']=f.resilience20>0
    f['qqqReturn3']=benchmark.Close.pct_change(3).reindex(f.index)
    f['breadth_followthrough']=False;f['broad_participation']=False;f['rs_vs_watchlist']=False
    return f


def watchlist_context(frames, members, day, prior_day):
    values=[];pairs=[];returns=[]
    for ticker in members:
        f=frames.get(ticker)
        if f is None or day not in f.index:continue
        r=f.loc[day]
        if pd.notna(r.ma20):values.append(bool(r.Close>r.ma20))
        if pd.notna(r.return20):returns.append(float(r.return20))
        if prior_day in f.index and pd.notna(r.ma20) and pd.notna(f.loc[prior_day,'ma20']):
            pairs.append((bool(r.Close>r.ma20),bool(f.loc[prior_day,'Close']>f.loc[prior_day,'ma20'])))
    return {'breadthCount':len(values),'breadth20':float(np.mean(values)) if len(values)>=10 else None,
            'breadthPairedCount':len(pairs),'breadthPairedNow':float(np.mean([p[0] for p in pairs])) if len(pairs)>=10 else None,
            'breadthPairedPrior5':float(np.mean([p[1] for p in pairs])) if len(pairs)>=10 else None,
            'returnCount':len(returns),'medianReturn20':float(np.median(returns)) if len(returns)>=10 else None}


def contextual_flags(r, ctx):
    broad=ctx['breadth20'] is not None and ctx['breadth20']>=.5
    relative=ctx['medianReturn20'] is not None and r.return20>ctx['medianReturn20']
    follow=(ctx['breadthPairedNow'] is not None and ctx['breadthPairedNow']>=.5 and ctx['breadthPairedPrior5']<=.3
            and r.qqqReturn3>.01 and r.Close>r.ma20 and r.Close>r.MA200 and r.volumePriorRatio>=1.2)
    return {'broad_participation':bool(broad),'rs_vs_watchlist':bool(relative),'breadth_followthrough':bool(follow)}
