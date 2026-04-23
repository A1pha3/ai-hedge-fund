#!/usr/bin/env python3
"""多日动量因子分析：用真实历史数据量化mom5/mom10的最优阈值。"""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import tushare as ts
from dotenv import load_dotenv

try:
    from scripts.btst_data_utils import build_beijing_exchange_mask
except ModuleNotFoundError:
    from btst_data_utils import build_beijing_exchange_mask

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
ts.set_token(os.getenv('TUSHARE_TOKEN'))
pro = ts.pro_api()
sb = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')

for test_date, label in [('20260408','Apr08'), ('20260410','Apr10')]:
    cal = pro.trade_cal(exchange='SSE', start_date=test_date, end_date='20260414', is_open='1')
    dates_after = sorted(cal['cal_date'].tolist())
    idx = dates_after.index(test_date)
    next1 = dates_after[idx+1]

    df = pro.daily(trade_date=test_date).merge(sb, on='ts_code', how='left')
    df = df[df['amount']>=100000]
    df = df[~df['name'].str.contains('ST|退',na=False)]
    df = df[~build_beijing_exchange_mask(df['ts_code'])]
    df = df[df['pct_chg'].between(-9.5,9.5)]
    dfn = pro.daily(trade_date=next1)[['ts_code','pct_chg']].rename(columns={'pct_chg':'next1_pct'})
    df = df.merge(dfn, on='ts_code')

    codes = df['ts_code'].tolist()
    history = []
    for i in range(0, len(codes), 80):
        batch = codes[i:i+80]
        try:
            h = pro.daily(ts_code=','.join(batch), start_date='20260201', end_date=test_date)
            if h is not None and not h.empty: history.append(h)
        except: continue

    hist = pd.concat(history, ignore_index=True)
    hist['trade_date'] = pd.to_datetime(hist['trade_date'], format='%Y%m%d')
    hist = hist.sort_values(['ts_code','trade_date'])

    mom_data = []
    for code, g in hist.groupby('ts_code'):
        if len(g) < 11: continue
        c = g.set_index('trade_date')['close'].sort_index()
        mom_data.append({'ts_code': code, 'mom5': (c.iloc[-1]/c.iloc[-6]-1)*100, 'mom10': (c.iloc[-1]/c.iloc[-11]-1)*100})

    mom_df = pd.DataFrame(mom_data)
    result = df[['ts_code','pct_chg','next1_pct','close','open']].merge(mom_df, on='ts_code', how='inner')
    result['is_bull'] = result['close'] > result['open']

    print(f'\n{"="*70}')
    print(f'{label} ({test_date}→{next1}) N={len(result)}')
    print(f'{"="*70}')
    print(f'整体: 胜率={((result["next1_pct"]>0).mean()):.0%} 大涨={((result["next1_pct"]>3).mean()):.0%} 均收={result["next1_pct"].mean():>+.2f}%')

    print('\n按mom10分桶:')
    for lo, hi in [(-20,-5),(-5,0),(0,3),(3,5),(5,10),(10,20)]:
        b = result[result['mom10'].between(lo,hi)]
        if len(b)<20: continue
        w=(b['next1_pct']>0).mean(); bg=(b['next1_pct']>3).mean(); avg=b['next1_pct'].mean()
        print(f'  {lo:>+3.0f}%~{hi:>+3.0f}%: {len(b):>4}只 | 胜率={w:.0%} 大涨={bg:.0%} 均收={avg:>+.2f}%')

    print('\n组合策略:')
    combos = [
        ('当日-2~+1% & mom10>3%',    (result['pct_chg'].between(-2,1)) & (result['mom10']>3)),
        ('当日-2~+1% & mom5>2%',     (result['pct_chg'].between(-2,1)) & (result['mom5']>2)),
        ('mom10>5% & 当日<3%',       (result['mom10']>5) & (result['pct_chg']<3)),
        ('mom10>5% & 阳线',          (result['mom10']>5) & result['is_bull']),
        ('mom5>3%&mom10>3%&阳线',    (result['mom5']>3) & (result['mom10']>3) & result['is_bull']),
        ('mom5>3% & 当日-2~+2%',     (result['mom5']>3) & result['pct_chg'].between(-2,2)),
        ('当日-2~0% & mom10>5%',     result['pct_chg'].between(-2,0) & (result['mom10']>5)),
        ('当日0~2% & mom10>5% & 阳线', result['pct_chg'].between(0,2) & (result['mom10']>5) & result['is_bull']),
    ]
    for name, mask in combos:
        b = result[mask]
        if len(b)<10: continue
        w=(b['next1_pct']>0).mean(); bg=(b['next1_pct']>3).mean(); avg=b['next1_pct'].mean()
        print(f'  {name:<32}: {len(b):>4}只 | 胜率={w:.0%} 大涨={bg:.0%} 均收={avg:>+.2f}%')
