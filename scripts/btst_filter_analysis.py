#!/usr/bin/env python3
"""分析候选池过滤器：各层过滤对次日大涨股票的影响。"""
import os
import numpy as np
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

try:
    from scripts.btst_data_utils import build_beijing_exchange_mask
except ModuleNotFoundError:
    from btst_data_utils import build_beijing_exchange_mask

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def main():
    import tushare as ts
    ts.set_token(os.getenv('TUSHARE_TOKEN'))
    pro = ts.pro_api()

    # 分析最近的几个交易日
    cal = pro.trade_cal(exchange='SSE', start_date='20260401', end_date='20260414', is_open='1')
    all_dates = sorted(cal['cal_date'].tolist())
    next_map = {d: all_dates[i + 1] for i, d in enumerate(all_dates) if i + 1 < len(all_dates)}

    # 用3个日期做分析
    analysis_dates = [d for d in all_dates if d <= '20260409'][-5:]

    print("候选池过滤器效率分析")
    print("=" * 90)

    sb = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,list_date')

    for test_date in analysis_dates:
        next_date = next_map.get(test_date)
        if not next_date:
            continue

        df = pro.daily(trade_date=test_date)
        if df is None or df.empty:
            continue

        df = df.merge(sb, on='ts_code', how='left')
        total = len(df)

        # 获取次日收益
        try:
            dfn = pro.daily(trade_date=next_date)[['ts_code', 'pct_chg']].rename(columns={'pct_chg': 'next_ret'})
        except:
            continue
        df = df.merge(dfn, on='ts_code', how='left')

        # 基准：所有股票的次日表现
        base_win = (df['next_ret'] > 0).mean()
        base_big = (df['next_ret'] > 3).mean()
        base_avg = df['next_ret'].mean()

        print(f"\n{test_date}→{next_date}: 全市场 {total} 只")
        print(f"  基准: 胜率={base_win:.0%} 大涨={base_big:.0%} 均收={base_avg:+.2f}%")

        # 逐层过滤
        filters = [
            ("1.ST排除", lambda d: d['name'].str.contains('ST|退', na=False)),
            ("2.北交所排除", lambda d: build_beijing_exchange_mask(d['ts_code'])),
            ("3.次新股(<60天)", lambda d: _is_new_stock(d, test_date)),
            ("4.涨跌停排除", lambda d: ~d['pct_chg'].between(-9.5, 9.5)),
            ("5.低额过滤(<10万千元=10万)", lambda d: d['amount'] < 100000),
            ("6.中额过滤(<3000万)", lambda d: d['amount'] < 30000),  # 3000万 = 30000千元
            ("7.高额过滤(<5000万)", lambda d: d['amount'] < 50000),  # 5000万 = 50000千元
        ]

        filtered = df.copy()
        for fname, fmask in filters:
            mask = fmask(filtered)
            removed = filtered[mask]
            kept = filtered[~mask]

            if len(removed) > 0:
                r_win = (removed['next_ret'] > 0).mean()
                r_big = (removed['next_ret'] > 3).mean()
                r_avg = removed['next_ret'].mean()
                # 被过滤掉的大涨股
                big_removed = removed[removed['next_ret'] > 3]

                print(f"  {fname}: 过滤{len(removed):>4}只 "
                      f"胜率={r_win:.0%} 大涨={r_big:.0%} 均收={r_avg:+.2f}% "
                      f"(含{len(big_removed)}只大涨股)", end="")

                # 标记：如果过滤掉的胜率 > 保留的胜率，说明过滤有问题
                k_win = (kept['next_ret'] > 0).mean() if len(kept) > 0 else 0
                if r_win > k_win and len(removed) >= 20:
                    print(f" ⚠️ 被过滤胜率({r_win:.0%})>保留胜率({k_win:.0%})", end="")

                print()

            filtered = kept

        # 最终候选池的表现
        if len(filtered) > 0:
            f_win = (filtered['next_ret'] > 0).mean()
            f_big = (filtered['next_ret'] > 3).mean()
            f_avg = filtered['next_ret'].mean()
            print(f"  最终候选池: {len(filtered)}只 胜率={f_win:.0%} 大涨={f_big:.0%} 均收={f_avg:+.2f}%")

        # 分析：amount阈值对大涨股的影响
        print(f"\n  === amount阈值敏感性分析 ===")
        for threshold_k in [0, 50000, 30000, 10000, 5000]:
            # 千元单位
            pool = df[df['amount'] >= threshold_k]
            if len(pool) < 10:
                continue
            p_win = (pool['next_ret'] > 0).mean()
            p_big = (pool['next_ret'] > 3).mean()
            p_avg = pool['next_ret'].mean()
            big_stocks = pool[pool['next_ret'] > 3]
            print(f"    amount>={threshold_k:>6}千元({threshold_k/10000:.0f}万): {len(pool):>4}只 "
                  f"胜率={p_win:.0%} 大涨={len(big_stocks):>3}只({p_big:.0%}) 均收={p_avg:+.2f}%")


def _is_new_stock(df, trade_date):
    """标记次新股（上市不足60个交易日）"""
    if 'list_date' not in df.columns:
        return pd.Series([False] * len(df), index=df.index)
    td = pd.to_datetime(trade_date, format='%Y%m%d')
    list_d = pd.to_datetime(df['list_date'], format='%Y%m%d', errors='coerce')
    trading_days = (td - list_d).dt.days / 1.5  # 粗略估算交易日
    return trading_days < 60


if __name__ == '__main__':
    main()
