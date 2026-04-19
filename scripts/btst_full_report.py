#!/usr/bin/env python3
"""
BTST完整分析报告：2026-04-13信号日 → 04-14目标日
包含：候选池构建、因子评分、行业分析、历史回测验证、Top候选深度分析
"""
import argparse
import os, json, sys
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

def spearman_ic(x, y):
    x, y = np.array(x, dtype=float), np.array(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 10: return np.nan
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    n = len(rx)
    d = rx - ry
    return 1.0 - 6.0 * np.sum(d**2) / (n * (n**2 - 1))


def compute_factors(g):
    g = g.sort_values('trade_date')
    close = g['close'].values
    vol_col = 'vol' if 'vol' in g.columns else 'volume'
    volume = g[vol_col].values
    amount = g['amount'].values
    open_p = g['open'].values
    high = g['high'].values
    low = g['low'].values
    n = len(close)
    if n < 22: return None
    last_close, prev_close, last_open = close[-1], close[-2], open_p[-1]
    last_high, last_low = high[-1], low[-1]

    # 基础指标
    daily_return = (last_close / prev_close - 1) if prev_close > 0 else 0
    is_bull = last_close > last_open
    upper_shadow = (last_high - max(last_close, last_open)) / last_close if last_close > 0 else 0
    lower_shadow = (min(last_close, last_open) - last_low) / last_close if last_close > 0 else 0
    body_ratio = abs(last_close - last_open) / (last_high - last_low) if (last_high - last_low) > 0 else 0

    # 动量因子
    mom_1w = close[-1] / close[-min(6, n)] - 1 if n >= 6 else 0
    mom_2w = close[-1] / close[-min(11, n)] - 1 if n >= 11 else mom_1w
    mom_1m = close[-1] / close[-22] - 1 if n >= 23 else mom_2w
    mom_3m = close[-1] / close[-min(66, n-1)] - 1 if n >= 67 else mom_1m
    mom_1m_n = min(max(mom_1m / 0.3, 0), 1)
    mom_3m_n = min(max(mom_3m / 0.5, 0), 1)
    if n >= 133:
        mom_6m_n = min(max((close[-1]/close[-132]-1) / 0.8, 0), 1)
        momentum_strength = min(max(0.4*mom_1m_n + 0.3*mom_3m_n + 0.3*mom_6m_n, 0), 1)
    elif n >= 67:
        momentum_strength = min(max(0.6*mom_1m_n + 0.4*mom_3m_n, 0), 1)
    else:
        momentum_strength = mom_1m_n

    # 成交量因子
    avg_vol_20 = max(np.mean(volume[-min(20, n):]), 1)
    avg_vol_5 = np.mean(volume[-5:]) if n >= 5 else 1
    vol_ratio = avg_vol_5 / avg_vol_20
    volume_expansion = min(max((vol_ratio - 1.0) / 1.5, 0), 1)

    # 收盘强度 (价格位置)
    high_20 = np.max(close[-min(20, n):])
    low_20 = np.min(close[-min(20, n):])
    price_range = high_20 - low_20 if high_20 > low_20 else 1
    close_strength = (last_close - low_20) / price_range

    # 突破新鲜度
    ret_5d = close[-1] / close[-6] - 1 if n >= 6 else 0
    breakout_raw = 0.5 * min(max(ret_5d / 0.15, 0), 1) + 0.5 * min(max(daily_return / 0.05, 0), 1)
    breakout_freshness = min(max(breakout_raw, 0), 1)

    # 趋势加速
    if n >= 44:
        accel = (close[-1]/close[-10]-1) - (close[-11]/close[-21]-1)
        trend_acceleration = min(max(accel / 0.1, 0), 1)
    else:
        trend_acceleration = 0.5 * momentum_strength

    # 催化剂新鲜度 (量价组合)
    last_amount = amount[-1]
    avg_amount_20 = max(np.mean(amount[-min(20, n):]), 1)
    amount_ratio = last_amount / avg_amount_20
    catalyst_freshness = min(max(0.6 * min(amount_ratio / 3.0, 1) + 0.4 * breakout_freshness, 0), 1)

    # Layer C 一致性
    layer_c_alignment = min(max(0.5 * float(is_bull) + 0.5 * min(max(daily_return / 0.03, 0), 1), 0), 1)

    # 短期反转
    mean_rev_proxy = min(max(-ret_5d / 0.08, 0), 1)
    short_term_reversal = mean_rev_proxy * (1 - momentum_strength)

    # 波动率
    if n >= 20:
        returns = np.diff(close[-21:]) / close[-21:-1]
        volatility = np.std(returns) if len(returns) > 0 else 0
    else:
        volatility = 0

    return {
        'momentum_strength': round(momentum_strength, 4),
        'volume_expansion_quality': round(volume_expansion, 4),
        'close_strength': round(close_strength, 4),
        'breakout_freshness': round(breakout_freshness, 4),
        'trend_acceleration': round(trend_acceleration, 4),
        'sector_resonance': 0.5,
        'catalyst_freshness': round(catalyst_freshness, 4),
        'layer_c_alignment': round(layer_c_alignment, 4),
        'short_term_reversal': round(short_term_reversal, 4),
        # 额外指标
        'daily_return': round(daily_return, 4),
        'ret_5d': round(ret_5d, 4),
        'ret_10d': round(mom_2w, 4),
        'ret_20d': round(mom_1m, 4),
        'vol_ratio': round(vol_ratio, 4),
        'is_bull': is_bull,
        'body_ratio': round(body_ratio, 4),
        'upper_shadow': round(upper_shadow, 4),
        'lower_shadow': round(lower_shadow, 4),
        'volatility': round(float(volatility), 6),
        'amount': float(last_amount),
    }


PROFILE_WEIGHTS = {
    'breakout_freshness': 0.06, 'trend_acceleration': 0.06,
    'volume_expansion_quality': 0.16, 'close_strength': 0.26,
    'sector_resonance': 0.14, 'catalyst_freshness': 0.18,
    'layer_c_alignment': 0.14, 'momentum_strength': 0.10,
    'short_term_reversal': 0.08,
}
SELECT_THRESHOLD = 0.40
NEAR_MISS_THRESHOLD = 0.28


def normalize_weights(w):
    total = sum(max(0, v) for v in w.values())
    return {k: max(0, v)/total for k, v in w.items()} if total > 0 else {k: 1/len(w) for k in w}


def compute_score(factors, weights):
    nw = normalize_weights(weights)
    return min(max(sum(nw.get(k, 0) * factors.get(k, 0) for k in nw), 0), 1)


def score_contributions(factors, weights):
    """返回各因子的加权贡献"""
    nw = normalize_weights(weights)
    return {k: round(nw.get(k, 0) * factors.get(k, 0), 4) for k in nw}


def parse_args():
    parser = argparse.ArgumentParser(description="Generate BTST full report for a specific signal date or the latest usable trade date.")
    parser.add_argument("--trade-date", default=None, help="Signal date in YYYYMMDD format. Omit to auto-resolve the latest usable trade date.")
    return parser.parse_args()


def resolve_trade_dates(pro, requested_trade_date=None):
    if requested_trade_date:
        trade_dt = datetime.strptime(requested_trade_date, "%Y%m%d")
        cal_start = (trade_dt - timedelta(days=20)).strftime("%Y%m%d")
        cal_end = (trade_dt + timedelta(days=15)).strftime("%Y%m%d")
    else:
        today = datetime.now()
        cal_start = (today - timedelta(days=30)).strftime("%Y%m%d")
        cal_end = (today + timedelta(days=15)).strftime("%Y%m%d")

    cal = pro.trade_cal(exchange='SSE', start_date=cal_start, end_date=cal_end, is_open='1')
    all_dates = sorted(cal['cal_date'].tolist())
    next_map = {d: all_dates[i+1] for i, d in enumerate(all_dates) if i+1 < len(all_dates)}

    if requested_trade_date:
        if requested_trade_date not in all_dates:
            raise SystemExit(f"指定信号日不是上交所开市日: {requested_trade_date}")
        df_test = pro.daily(trade_date=requested_trade_date)
        if df_test is None or df_test.empty:
            raise SystemExit(f"指定信号日暂无收盘数据: {requested_trade_date}")
        trade_date = requested_trade_date
    else:
        trade_date = None
        for d in reversed(all_dates):
            df_test = pro.daily(trade_date=d)
            if df_test is not None and not df_test.empty:
                trade_date = d
                break
        if trade_date is None:
            raise SystemExit("未找到可用的收盘数据日期")

    next_date = next_map.get(trade_date, 'N/A')
    return trade_date, next_date, all_dates


def main():
    import tushare as ts
    args = parse_args()
    ts.set_token(os.getenv('TUSHARE_TOKEN'))
    pro = ts.pro_api()

    trade_date, next_date, all_dates = resolve_trade_dates(pro, args.trade_date)
    next_map = {d: all_dates[i+1] for i, d in enumerate(all_dates) if i+1 < len(all_dates)}
    trade_dt = datetime.strptime(trade_date, "%Y%m%d")

    # ====== 获取最近5日数据用于历史回测验证 ======
    lookback_dates = [d for d in all_dates if d <= trade_date][-5:]
    prev_5d = lookback_dates[0] if lookback_dates else trade_date

    R = []  # report lines
    def p(s=''):
        R.append(s)
        print(s)

    p(f'{"="*90}')
    p(f'  BTST完整分析报告')
    p(f'  信号日: {trade_date}  →  目标日: {next_date}')
    p(f'  Profile: ic_optimized (9因子)  选入≥{SELECT_THRESHOLD}  近_miss≥{NEAR_MISS_THRESHOLD}')
    p(f'  生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    p(f'{"="*90}')

    # ====== 第1部分: 候选池 ======
    sb = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,industry,list_date')
    df = pro.daily(trade_date=trade_date)
    df = df.merge(sb, on='ts_code', how='left')
    total = len(df)
    df_st = df[df['name'].str.contains('ST|退', na=False)]
    df_bj = df[df['ts_code'].str.startswith(('688','8','4'))]
    df_low = df[(df['amount'] < 100000) & ~df['name'].str.contains('ST|退', na=False) & ~df['ts_code'].str.startswith(('688','8','4'))]
    df = df[df['amount'] >= 100000]
    df = df[~df['name'].str.contains('ST|退', na=False)]
    df = df[~df['ts_code'].str.startswith(('688','8','4'))]

    p(f'\n{"─"*90}')
    p(f'  第1部分: 候选池构建')
    p(f'{"─"*90}')
    p(f'  全市场:        {total:>5}只')
    p(f'  排除ST/退:     {len(df_st):>5}只 (剩{total-len(df_st)})')
    p(f'  排除科创/北交: {len(df_bj):>5}只 (剩{total-len(df_st)-len(df_bj)})')
    p(f'  排除低额(<1亿): {len(df_low):>5}只 (剩{len(df)})')
    p(f'  最终候选池:    {len(df):>5}只 (含涨停股)')

    # 涨停股
    try:
        limit_df = pro.limit_list(trade_date=trade_date, limit_type='U')
        limit_codes = set(limit_df['ts_code'].tolist()) if limit_df is not None and not limit_df.empty else set()
    except:
        limit_codes = set()
    limit_in_pool = len(set(df['ts_code']) & limit_codes)

    # 涨跌停数据
    try:
        limit_d = pro.limit_list(trade_date=trade_date, limit_type='D')
        limit_down = len(limit_d) if limit_d is not None else 0
    except:
        limit_down = 0

    p(f'  涨停: {limit_in_pool}只  跌停: {limit_down}只')
    p(f'  市场均涨幅: {df["pct_chg"].mean():+.2f}%  上涨占比: {(df["pct_chg"]>0).mean():.0%}')
    p(f'  成交额: 中位数{df["amount"].median()/10000:.0f}亿  均值{df["amount"].mean()/10000:.0f}亿')

    # ====== 第2部分: 因子评分 ======
    p(f'\n{"─"*90}')
    p(f'  第2部分: 因子评分')
    p(f'{"─"*90}')

    codes = df['ts_code'].tolist()
    history = []
    history_start_date = (trade_dt - timedelta(days=320)).strftime("%Y%m%d")
    for i in range(0, len(codes), 80):
        batch = codes[i:i+80]
        try:
            h = pro.daily(ts_code=','.join(batch), start_date=history_start_date, end_date=trade_date)
            if h is not None and not h.empty: history.append(h)
        except: continue

    hist = pd.concat(history, ignore_index=True)
    hist['trade_date'] = pd.to_datetime(hist['trade_date'], format='%Y%m%d')
    hist = hist.sort_values(['ts_code', 'trade_date'])

    stock_factors = {}
    for code, g in hist.groupby('ts_code'):
        f = compute_factors(g)
        if f is not None: stock_factors[code] = f

    results = df[df['ts_code'].isin(stock_factors.keys())].copy()
    scores, contributions = [], []
    for _, row in results.iterrows():
        f = stock_factors.get(row['ts_code'], {})
        scores.append(compute_score(f, PROFILE_WEIGHTS))
        contributions.append(score_contributions(f, PROFILE_WEIGHTS))

    results['score'] = scores
    results['contributions'] = contributions
    p(f'  因子计算: {len(results)}/{len(df)}只 (数据不足{len(df)-len(results)}只)')

    # 因子统计
    factor_cols = ['momentum_strength','volume_expansion_quality','close_strength',
                   'breakout_freshness','trend_acceleration','catalyst_freshness',
                   'layer_c_alignment','short_term_reversal']
    factor_names = ['动量强度','量扩张','收盘强度','突破鲜度','趋势加速','催化剂','LayerC','短期反转']
    p(f'\n  {"因子":10} {"均值":>6} {"标准差":>6} {"偏度":>6} {"IC(与日收益)":>12}')
    p(f'  {"─"*50}')
    for col, name in zip(factor_cols, factor_names):
        vals = [stock_factors[c].get(col, 0) for c in results['ts_code']]
        daily_rets = results['pct_chg'].values
        ic = spearman_ic(vals, daily_rets)
        p(f'  {name:10} {np.mean(vals):>6.3f} {np.std(vals):>6.3f} {pd.Series(vals).skew():>+6.2f} {ic:>+12.4f}')

    # ====== 第3部分: 选股结果 ======
    p(f'\n{"="*90}')
    p(f'  第3部分: 选股结果')
    p(f'{"="*90}')

    selected = results[results['score'] >= SELECT_THRESHOLD].sort_values('score', ascending=False)
    near_miss = results[(results['score'] >= NEAR_MISS_THRESHOLD) & (results['score'] < SELECT_THRESHOLD)].sort_values('score', ascending=False)
    rejected = results[results['score'] < NEAR_MISS_THRESHOLD]

    p(f'\n  SELECTED: {len(selected):>4}只 ({len(selected)/len(results):.0%})  score ≥ {SELECT_THRESHOLD}')
    p(f'  NEAR_MISS: {len(near_miss):>4}只 ({len(near_miss)/len(results):.0%})  {NEAR_MISS_THRESHOLD} ≤ score < {SELECT_THRESHOLD}')
    p(f'  WATCH:     {len(rejected):>4}只 ({len(rejected)/len(results):.0%})  score < {NEAR_MISS_THRESHOLD}')

    # Selected详情
    p(f'\n  ┌─ SELECTED Top 40 ─────────────────────────────────────────────────────────')
    p(f'  │ {"排名":>4} {"代码":8} {"名称":8} {"行业":6} {"得分":>6} {"日涨%":>6} {"5日%":>7} {"量比":>5} {"涨停":>3}')
    p(f'  │ {"─"*70}')
    for rank, (_, row) in enumerate(selected.head(40).iterrows(), 1):
        f = stock_factors.get(row['ts_code'], {})
        lim = '★' if row['ts_code'] in limit_codes else ''
        p(f'  │ {rank:>4} {row["ts_code"][:6]:8} {str(row.get("name",""))[:6]:8} {str(row.get("industry",""))[:4]:6} '
          f'{row["score"]:>6.4f} {row["pct_chg"]:>+5.1f}% {f.get("ret_5d",0)*100:>+6.1f}% '
          f'{f.get("vol_ratio",0):>5.2f} {lim:>3}')
    p(f'  └─ 共{len(selected)}只')

    # Near Miss详情
    p(f'\n  ┌─ NEAR MISS Top 20 ────────────────────────────────────────────────────────')
    p(f'  │ {"代码":8} {"名称":8} {"得分":>6} {"日涨%":>6} {"5日%":>7} {"缺口":>6}')
    p(f'  │ {"─"*55}')
    for _, row in near_miss.head(20).iterrows():
        f = stock_factors.get(row['ts_code'], {})
        gap = SELECT_THRESHOLD - row['score']
        p(f'  │ {row["ts_code"][:6]:8} {str(row.get("name",""))[:6]:8} {row["score"]:>6.4f} '
          f'{row["pct_chg"]:>+5.1f}% {f.get("ret_5d",0)*100:>+6.1f}% {gap:>+5.4f}')
    p(f'  └─ 共{len(near_miss)}只')

    # ====== 第4部分: 行业分析 ======
    p(f'\n{"─"*90}')
    p(f'  第4部分: 行业分析')
    p(f'{"─"*90}')

    combined = pd.concat([selected, near_miss])
    if 'industry' in combined.columns:
        ind_stats = []
        for ind, grp in combined.groupby('industry'):
            s = grp[grp['score'] >= SELECT_THRESHOLD]
            nm = grp[grp['score'] < SELECT_THRESHOLD]
            ind_stats.append({
                'industry': ind,
                'total': len(grp),
                'selected': len(s),
                'near_miss': len(nm),
                'avg_score': grp['score'].mean(),
                'avg_ret': grp['pct_chg'].mean(),
            })
        ind_df = pd.DataFrame(ind_stats).sort_values('selected', ascending=False)
        p(f'\n  {"行业":12} {"总数":>4} {"选入":>4} {"近miss":>5} {"均分":>6} {"均涨%":>7}')
        p(f'  {"─"*50}')
        for _, r in ind_df.head(20).iterrows():
            p(f'  {str(r["industry"]):12} {r["total"]:>4} {r["selected"]:>4} {r["near_miss"]:>5} {r["avg_score"]:>6.3f} {r["avg_ret"]:>+6.2f}%')

    # ====== 第5部分: 涨停股+反转股专项 ======
    p(f'\n{"─"*90}')
    p(f'  第5部分: 涨停股 & 反转股专项')
    p(f'{"─"*90}')

    # 涨停股
    if limit_in_pool > 0:
        limit_pool = results[results['ts_code'].isin(limit_codes)].sort_values('score', ascending=False)
        p(f'\n  涨停股 ({len(limit_pool)}只在候选池中):')
        p(f'  {"代码":8} {"名称":8} {"得分":>6} {"日涨%":>6} {"5日%":>7} {"量比":>5} {"决策":>10}')
        p(f'  {"─"*60}')
        for _, row in limit_pool.head(15).iterrows():
            f = stock_factors.get(row['ts_code'], {})
            dec = 'SELECTED' if row['score'] >= SELECT_THRESHOLD else ('NEAR_MISS' if row['score'] >= NEAR_MISS_THRESHOLD else 'watch')
            p(f'  {row["ts_code"][:6]:8} {str(row.get("name",""))[:6]:8} {row["score"]:>6.4f} '
              f'{row["pct_chg"]:>+5.1f}% {f.get("ret_5d",0)*100:>+6.1f}% {f.get("vol_ratio",0):>5.2f} {dec:>10}')
        lim_sel = len(limit_pool[limit_pool['score'] >= SELECT_THRESHOLD])
        p(f'  → {lim_sel}只入选SELECTED, 历史涨停股次日胜率53%、大涨率33%')
    else:
        p(f'\n  涨停股: 今日无涨停 (市场偏弱或中性)')

    # 反转股
    rev_pool = results.copy()
    rev_pool['str_val'] = [stock_factors.get(c, {}).get('short_term_reversal', 0) for c in rev_pool['ts_code']]
    rev_high = rev_pool[rev_pool['str_val'] >= 0.2].sort_values('str_val', ascending=False)
    p(f'\n  短期反转信号 (reversal ≥ 0.2, {len(rev_high)}只):')
    p(f'  {"代码":8} {"名称":8} {"得分":>6} {"日涨%":>6} {"5日%":>7} {"反转":>5} {"决策":>10}')
    p(f'  {"─"*65}')
    for _, row in rev_high.head(15).iterrows():
        f = stock_factors.get(row['ts_code'], {})
        dec = 'SELECTED' if row['score'] >= SELECT_THRESHOLD else ('NEAR_MISS' if row['score'] >= NEAR_MISS_THRESHOLD else 'watch')
        p(f'  {row["ts_code"][:6]:8} {str(row.get("name",""))[:6]:8} {row["score"]:>6.4f} '
          f'{row["pct_chg"]:>+5.1f}% {f.get("ret_5d",0)*100:>+6.1f}% {row["str_val"]:>5.3f} {dec:>10}')

    # ====== 第6部分: Top候选深度分析 ======
    p(f'\n{"─"*90}')
    p(f'  第6部分: Top 10候选深度分析')
    p(f'{"─"*90}')

    for rank, (_, row) in enumerate(selected.head(10).iterrows(), 1):
        f = stock_factors.get(row['ts_code'], {})
        c = score_contributions(f, PROFILE_WEIGHTS)
        p(f'\n  #{rank} {row["ts_code"][:6]} {row.get("name","")} ({row.get("industry","")})')
        p(f'  得分: {row["score"]:.4f}  日涨幅: {row["pct_chg"]:+.2f}%  涨停: {"是" if row["ts_code"] in limit_codes else "否"}')
        p(f'  因子贡献:')
        sorted_contribs = sorted(c.items(), key=lambda x: -x[1])
        for k, v in sorted_contribs[:5]:
            p(f'    {k:28}: {v:.4f} (因子值={f.get(k,0):.3f})')
        p(f'  技术特征: 5日={f.get("ret_5d",0)*100:+.1f}% 10日={f.get("ret_10d",0)*100:+.1f}%  '
          f'量比={f.get("vol_ratio",0):.2f}  阳线={"是" if f.get("is_bull") else "否"}  '
          f'波动率={f.get("volatility",0):.4f}')

    # ====== 第7部分: 历史验证 ======
    p(f'\n{"─"*90}')
    p(f'  第7部分: 近5日历史验证')
    p(f'{"─"*90}')

    for hist_date in lookback_dates[:-1]:  # 排除当天
        hist_next = next_map.get(hist_date)
        if not hist_next: continue
        try:
            hd = pro.daily(trade_date=hist_date)
            hn = pro.daily(trade_date=hist_next)
            if hd is None or hn is None or hd.empty or hn.empty: continue
        except: continue

        hd = hd.merge(sb[['ts_code','name']], on='ts_code', how='left')
        hd = hd[hd['amount'] >= 100000]
        hd = hd[~hd['name'].str.contains('ST|退', na=False)]
        hd = hd[~hd['ts_code'].str.startswith(('688','8','4'))]
        hn_ret = hn[['ts_code','pct_chg']].rename(columns={'pct_chg':'next_ret'})
        hd = hd.merge(hn_ret, on='ts_code', how='left')

        # 用当日涨幅+量比简单筛选top候选
        top_by_ret = hd.nlargest(20, 'pct_chg')
        top_by_vol = hd.nlargest(20, 'amount')

        wr_ret = (top_by_ret['next_ret'] > 0).mean() if len(top_by_ret) > 0 else 0
        avg_ret = top_by_ret['next_ret'].mean() if len(top_by_ret) > 0 else 0
        big_ret = (top_by_ret['next_ret'] > 3).mean() if len(top_by_ret) > 0 else 0

        p(f'  {hist_date}→{hist_next}: 涨幅Top20 胜率={wr_ret:.0%} 大涨={big_ret:.0%} 均收={avg_ret:+.2f}%')

    # ====== 第8部分: 综合建议 ======
    p(f'\n{"="*90}')
    p(f'  第8部分: 综合建议')
    p(f'{"="*90}')

    # 高确信标的: score高 + close_strength高 + catalyst_freshness高
    high_conf = selected.copy()
    high_conf['cs'] = [stock_factors.get(c, {}).get('close_strength', 0) for c in high_conf['ts_code']]
    high_conf['cf'] = [stock_factors.get(c, {}).get('catalyst_freshness', 0) for c in high_conf['ts_code']]
    high_conf = high_conf[(high_conf['cs'] >= 0.7) & (high_conf['cf'] >= 0.5)].sort_values('score', ascending=False)

    p(f'\n  ★ 高确信标的 (close_strength≥0.7 + catalyst≥0.5): {len(high_conf)}只')
    p(f'  {"排名":>4} {"代码":8} {"名称":8} {"得分":>6} {"日涨%":>6} {"收强":>5} {"催化":>5} {"量扩":>5}')
    p(f'  {"─"*55}')
    for rank, (_, row) in enumerate(high_conf.head(15).iterrows(), 1):
        f = stock_factors.get(row['ts_code'], {})
        p(f'  {rank:>4} {row["ts_code"][:6]:8} {str(row.get("name",""))[:6]:8} {row["score"]:>6.4f} '
          f'{row["pct_chg"]:>+5.1f}% {f.get("close_strength",0):>5.2f} {f.get("catalyst_freshness",0):>5.2f} '
          f'{f.get("volume_expansion_quality",0):>5.2f}')

    p(f'\n  交易建议:')
    p(f'  1. 优先从高确信标的中选择, score≥0.60的标的更有把握')
    p(f'  2. 反转信号标的(5日跌>8%)适合博反弹, 但需控制仓位')
    p(f'  3. 涨停股次日高开概率大, 但需注意冲高回落风险')
    p(f'  4. 市场状态: {trade_date}均涨{results["pct_chg"].mean():+.2f}%, '
      f'{"偏强→可适当进攻" if results["pct_chg"].mean() > 0.5 else "中性→精选为主" if results["pct_chg"].mean() > -0.5 else "偏弱→控制仓位"}')
    p(f'  5. 因子评分仅为第一层筛选, 最终决策需结合LLM agent分析(score_c)')

    # 保存完整报告
    report_text = '\n'.join(R)
    out_dir = Path(__file__).resolve().parent.parent / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / f"btst_full_report_{trade_date}.md"
    with open(md_path, 'w') as f:
        f.write(f'# BTST完整分析报告 {trade_date}→{next_date}\n\n')
        f.write(f'生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n\n')
        f.write('```\n' + report_text + '\n```\n')
    p(f'\n报告已保存: {md_path}')

    # JSON结构化数据
    json_data = {
        'trade_date': trade_date, 'next_date': next_date,
        'pool_size': len(results),
        'selected_count': len(selected), 'near_miss_count': len(near_miss),
        'limit_up_count': limit_in_pool,
        'high_confidence': [{
            'ticker': r['ts_code'][:6], 'name': str(r.get('name','')),
            'score': round(float(r['score']),4), 'pct_chg': round(float(r['pct_chg']),2),
            'close_strength': round(float(r.get('cs',0)),4),
            'catalyst_freshness': round(float(r.get('cf',0)),4),
        } for _, r in high_conf.head(20).iterrows()],
        'reversal_candidates': [{
            'ticker': r['ts_code'][:6], 'name': str(r.get('name','')),
            'score': round(float(r['score']),4), 'reversal': round(float(r.get('str_val',0)),4),
            'ret_5d': round(float(stock_factors.get(r['ts_code'],{}).get('ret_5d',0))*100,2),
        } for _, r in rev_high.head(20).iterrows()],
    }
    json_path = out_dir / f"btst_full_report_{trade_date}.json"
    with open(json_path, 'w') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    p(f'数据已保存: {json_path}')
    p(f'{"="*90}')


if __name__ == '__main__':
    main()
