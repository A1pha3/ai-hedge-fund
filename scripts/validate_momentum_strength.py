#!/usr/bin/env python3
"""验证momentum_strength因子的IC，以及ic_optimized profile的改进效果。"""
import os, json, sys
import numpy as np
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# --- IC计算 ---
def spearman_ic(x, y):
    """纯numpy实现的Spearman rank correlation."""
    x, y = np.array(x, dtype=float), np.array(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 10:
        return np.nan
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    n = len(rx)
    d = rx - ry
    return 1.0 - 6.0 * np.sum(d**2) / (n * (n**2 - 1))


def compute_momentum_strength(prices):
    """模拟momentum_strength: subfactor_positive_strength(momentum)
    = clamp(max(0, 0.4*mom1m + 0.3*mom3m + 0.3*mom6m))
    """
    if len(prices) < 22:  # 至少需要1个月数据
        return np.nan
    close = prices['close'].values
    mom_1m = (close[-1] / close[-22] - 1) if len(close) >= 23 else 0
    mom_3m = (close[-1] / close[-66] - 1) if len(close) >= 67 else 0
    mom_6m = (close[-1] / close[-132] - 1) if len(close) >= 133 else 0

    # Normalize to 0-1 range (approximate what the trend agent does)
    mom_1m_norm = min(max(mom_1m / 0.3, 0), 1)
    mom_3m_norm = min(max(mom_3m / 0.5, 0), 1)
    mom_6m_norm = min(max(mom_6m / 0.8, 0), 1)

    # If we only have 1m data, use higher weight for that
    if len(close) >= 67:
        raw = 0.4 * mom_1m_norm + 0.3 * mom_3m_norm + 0.3 * mom_6m_norm
    elif len(close) >= 23:
        raw = 0.6 * mom_1m_norm + 0.4 * mom_3m_norm
    else:
        raw = mom_1m_norm
    return min(max(raw, 0), 1)


def main():
    import tushare as ts
    ts.set_token(os.getenv('TUSHARE_TOKEN'))
    pro = ts.pro_api()

    # 获取测试日期范围: 最近20个交易日 (排除最后1天无次日数据)
    end_date = '20260414'
    start_date = '20260220'
    cal = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=end_date, is_open='1')
    all_trade_dates = sorted(cal['cal_date'].tolist())
    # 取测试日期范围
    test_dates = [d for d in all_trade_dates if d <= '20260410']  # 最后一天必须有次日数据
    test_dates = test_dates[-20:]

    # 构建交易日映射: test_date -> next_trade_date
    next_date_map = {}
    for i, d in enumerate(all_trade_dates):
        if i + 1 < len(all_trade_dates):
            next_date_map[d] = all_trade_dates[i + 1]

    print(f"测试日期范围: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)}个交易日)")
    print("="*70)

    # 获取股票池
    sb = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')

    all_results = []

    for di, test_date in enumerate(test_dates):
        # 找到下一个交易日
        next_date = next_date_map.get(test_date)
        if not next_date:
            continue

        # 获取当日行情
        try:
            df = pro.daily(trade_date=test_date)
        except:
            continue
        if df is None or df.empty:
            continue

        # 基本过滤
        df = df.merge(sb, on='ts_code', how='left')
        df = df[df['amount'] >= 100000]  # 千元，约10万元
        df = df[~df['name'].str.contains('ST|退', na=False)]
        df = df[~df['ts_code'].str.startswith(('688', '8', '4'))]
        df = df[df['pct_chg'].between(-9.5, 9.5)]

        if len(df) < 100:
            continue

        # 获取次日收益
        try:
            dfn = pro.daily(trade_date=next_date)[['ts_code', 'pct_chg']].rename(columns={'pct_chg': 'next_ret'})
        except:
            continue
        df = df.merge(dfn, on='ts_code')

        # 获取历史价格计算动量
        codes = df['ts_code'].tolist()
        history = []
        for i in range(0, len(codes), 80):
            batch = codes[i:i+80]
            try:
                h = pro.daily(ts_code=','.join(batch), start_date='20250601', end_date=test_date)
                if h is not None and not h.empty:
                    history.append(h)
            except:
                continue

        if not history:
            continue

        hist = pd.concat(history, ignore_index=True)
        hist['trade_date'] = pd.to_datetime(hist['trade_date'], format='%Y%m%d')
        hist = hist.sort_values(['ts_code', 'trade_date'])

        # 计算momentum_strength
        mom_data = []
        for code, g in hist.groupby('ts_code'):
            if len(g) < 22:
                continue
            c = g.set_index('trade_date')['close'].sort_index()
            ms = compute_momentum_strength(g.sort_values('trade_date'))
            if np.isnan(ms):
                continue
            mom_data.append({'ts_code': code, 'momentum_strength': ms})

        if not mom_data:
            continue

        mom_df = pd.DataFrame(mom_data)
        result = df[['ts_code', 'pct_chg', 'next_ret', 'close', 'open']].merge(mom_df, on='ts_code', how='inner')
        result['is_bull'] = result['close'] > result['open']

        if len(result) < 50:
            continue

        # 计算IC
        ic_val = spearman_ic(result['momentum_strength'].values, result['next_ret'].values)
        if np.isnan(ic_val):
            continue

        # 分桶分析
        n_bins = min(5, result['momentum_strength'].nunique())
        if n_bins < 2:
            continue
        result['mom_q'] = pd.qcut(result['momentum_strength'], n_bins, labels=False, duplicates='drop')
        bucket_stats = result.groupby('mom_q').agg(
            count=('next_ret', 'count'),
            win_rate=('next_ret', lambda x: (x > 0).mean()),
            avg_ret=('next_ret', 'mean'),
            big_win=('next_ret', lambda x: (x > 3).mean()),
        )

        q_lo = bucket_stats.index.min()
        q_hi = bucket_stats.index.max()
        all_results.append({
            'date': test_date,
            'next_date': next_date,
            'n_stocks': len(result),
            'ic': ic_val,
            'q5_win': bucket_stats.loc[q_hi, 'win_rate'],
            'q1_win': bucket_stats.loc[q_lo, 'win_rate'],
            'q5_avg': bucket_stats.loc[q_hi, 'avg_ret'],
            'q1_avg': bucket_stats.loc[q_lo, 'avg_ret'],
        })

        print(f"[{di+1}/{len(test_dates)}] {test_date}→{next_date}: N={len(result)}, IC={ic_val:+.4f}")
        print(f"  Q_lo(win={bucket_stats.loc[q_lo,'win_rate']:.0%}, avg={bucket_stats.loc[q_lo,'avg_ret']:+.2f}%) "
              f"Q_hi(win={bucket_stats.loc[q_hi,'win_rate']:.0%}, avg={bucket_stats.loc[q_hi,'avg_ret']:+.2f}%) "
              f"Q_hi-Q_lo avg={bucket_stats.loc[q_hi,'avg_ret']-bucket_stats.loc[q_lo,'avg_ret']:+.2f}%")

    if not all_results:
        print("无有效数据")
        return

    # 汇总统计
    summary = pd.DataFrame(all_results)
    print(f"\n{'='*70}")
    print(f"汇总统计 ({len(summary)}个交易日)")
    print(f"{'='*70}")
    print(f"momentum_strength IC均值: {summary['ic'].mean():+.4f}")
    print(f"momentum_strength IC标准差: {summary['ic'].std():.4f}")
    print(f"ICIR (IC/IC_std): {summary['ic'].mean()/summary['ic'].std() if summary['ic'].std() > 0 else 0:+.2f}")
    print(f"IC>0的比例: {(summary['ic'] > 0).mean():.0%}")
    print(f"\nQ5(高动量) 平均胜率: {summary['q5_win'].mean():.0%}, 平均收益: {summary['q5_avg'].mean():+.2f}%")
    print(f"Q1(低动量) 平均胜率: {summary['q1_win'].mean():.0%}, 平均收益: {summary['q1_avg'].mean():+.2f}%")
    print(f"Q5-Q1 胜率差: {summary['q5_win'].mean()-summary['q1_win'].mean():+.0%}")
    print(f"Q5-Q1 收益差: {summary['q5_avg'].mean()-summary['q1_avg'].mean():+.2f}%")

    # 保存结果
    out_path = Path(__file__).resolve().parent.parent / "data" / "reports" / "momentum_strength_validation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump({
            'summary': {
                'mean_ic': round(summary['ic'].mean(), 4),
                'ic_std': round(summary['ic'].std(), 4),
                'icir': round(summary['ic'].mean()/summary['ic'].std(), 2) if summary['ic'].std() > 0 else 0,
                'ic_positive_rate': round(float((summary['ic'] > 0).mean()), 4),
                'q5_avg_win_rate': round(float(summary['q5_win'].mean()), 4),
                'q1_avg_win_rate': round(float(summary['q1_win'].mean()), 4),
                'q5_avg_return': round(float(summary['q5_avg'].mean()), 4),
                'q1_avg_return': round(float(summary['q1_avg'].mean()), 4),
                'n_test_dates': len(summary),
            },
            'daily_results': all_results,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到 {out_path}")


if __name__ == '__main__':
    main()
