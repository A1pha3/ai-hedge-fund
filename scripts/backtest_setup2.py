"""Setup-2 超跌反弹 30 天回测 — 与 Phase A (BTST) 同窗口对比。

Setup-2: 30 日跌幅 > 20% + 近 3 日主力净流入 > 0 + 放量 (量比 > 1.5)
数据: 300 ticker price + fund flow cached.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

_HARD_STOP = -0.08; _SLIPPAGE = 0.003; _HORIZON = 10
_POSITION_PCT = 0.10; _MAX_POSITIONS = 6

def _load():
    p, f = {}, {}
    for pf in Path("data/price_cache/").glob("*.csv"):
        df = pd.read_csv(pf, dtype={"date": str}); df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
        p[pf.stem] = df.sort_values("date").reset_index(drop=True)
    for ff in Path("data/fund_flow_cache/").glob("*.csv"):
        t = ff.stem; df = pd.read_csv(ff, dtype={"date": str})
        from src.screening.offensive.data.fund_flow_store import FundFlowRecord
        f[t] = [FundFlowRecord(ticker=t, date=str(r["date"]), close=float(r.get("close",0) or 0),
                pct_change=float(r.get("pct_change",0) or 0),
                main_net_inflow=float(r.get("main_net_inflow",0) or 0),
                main_net_pct=float(r.get("main_net_pct",0) or 0)) for _,r in df.iterrows()]
    return p, f

def _run(use_setup2, entry_days, trading_days, prices, flow):
    from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
    from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup
    setup = OversoldBounceSetup() if use_setup2 else BtstBreakoutSetup()
    nav,peak,md = 1.0,1.0,0.0; pos,closed = [],[]
    eset = set(entry_days)

    for today in trading_days:
        still = []
        for p in pos:
            tdf = prices.get(p["ticker"]); rw = tdf[tdf["date"]==today]
            if len(rw)==0: still.append(p); continue
            low,close = float(rw.iloc[0]["low"]), float(rw.iloc[0]["close"])
            p["days_held"]+=1; sp=p["entry_price"]*(1+_HARD_STOP)
            if low <= sp:
                p.update({"exit_date":today,"exit_price":sp*(1-_SLIPPAGE),"exit_reason":"hard_stop"})
                p["pnl"]=p["size"]*((p["exit_price"]/p["entry_price"])-1); nav*=(1+p["pnl"]); closed.append(p)
            elif p["days_held"]>=_HORIZON:
                p.update({"exit_date":today,"exit_price":close*(1-_SLIPPAGE),"exit_reason":"time_exit"})
                p["pnl"]=p["size"]*((p["exit_price"]/p["entry_price"])-1); nav*=(1+p["pnl"]); closed.append(p)
            else: still.append(p)
        pos=still
        if today not in eset or len(pos)>=_MAX_POSITIONS: continue
        slots=_MAX_POSITIONS-len(pos); nb=0
        for ticker,tdf in prices.items():
            if nb>=slots: break
            if any(p["ticker"]==ticker for p in pos): continue
            r=tdf.index[tdf["date"]==today].tolist()
            if not r or r[0]+1>=len(tdf): continue
            ti=r[0]; up=tdf.iloc[:ti+1].copy(); up["date"]=pd.to_datetime(up["date"],format="%Y%m%d")
            fu=[r for r in flow.get(ticker,[]) if r.date<=today]
            lp=float(up.iloc[-1].get("pct_change",0) or 0); ip=max(lp,3.0) if lp>=9.5 else lp
            ctx={"prices":up,"fund_flow_records":fu,"industry_day_pct":ip,"regime":"normal"}
            if not use_setup2: ctx["prices"]=up
            result=setup.detect(ticker,today,ctx)
            if result.hit:
                e=float(tdf.iloc[ti+1]["open"])*(1+_SLIPPAGE)
                pos.append({"ticker":ticker,"entry_date":today,"entry_price":e,"size":_POSITION_PCT,"days_held":0,"pnl":0.0})
                nb+=1
        peak=max(peak,nav); md=min(md,nav/peak-1)
    n=len(closed); w=sum(1 for p in closed if p["pnl"]>0)
    rets=[nav for nav in [nav]]
    from pathlib import Path
    return {"nav":nav,"ret":(nav-1)*100,"wr":w/n if n else 0,"md":md*100,"n":n,"sharpe":0,"wins":w,
            "exits":{r:sum(1 for p in closed if p["exit_reason"]==r) for r in set(p["exit_reason"] for p in closed)}}

def main():
    p,f=_load()
    ad=sorted(set(d for tdf in p.values() for d in tdf["date"].tolist()))
    ei=len(ad)-_HORIZON; si=ei-30; ed=ad[si:ei]; ta=ad[si:]
    print(f"窗口: {ed[0]}→{ed[-1]} ({len(ed)}天)")
    ra=_run(False,ed,ta,p,f)
    rb=_run(True,ed,ta,p,f)
    print(f"{'指标':<12} {'Phase A (BTST)':<18} {'Setup-2 (超跌反弹)':<18}")
    print("-"*56)
    for l,v1,v2 in [("交易数",ra["n"],rb["n"]),("胜率",f"{ra['wr']:.0%}",f"{rb['wr']:.0%}"),
                    ("总收益",f"{ra['ret']:+.2f}%",f"{rb['ret']:+.2f}%"),
                    ("最大回撤",f"{ra['md']:+.2f}%",f"{rb['md']:+.2f}%"),
                    ("Sharpe",f"{ra['sharpe']:.2f}",f"{rb['sharpe']:.2f}"),
                    ("退出",str(ra['exits']),str(rb['exits']))]:
        print(f"{l:<12} {v1:<18} {v2:<18}")
    if rb["ret"]>ra["ret"]: print(f"\n✅ Setup-2 总收益更高 → 与 Phase A 组合提升收益")
    else: print(f"\n⚠ Setup-2 低于 Phase A ({rb['ret']:+.2f}% vs {ra['ret']:+.2f}%)")

if __name__=="__main__": main()
