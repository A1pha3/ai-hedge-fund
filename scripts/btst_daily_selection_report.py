#!/usr/bin/env python3
"""
BTST选股分析报告：基于最近交易日数据，使用ic_optimized profile选择次日候选。

输出：
1. 完整候选池分析
2. 各因子分布
3. 推荐买入列表（selected + near_miss）
4. 涨停股专项分析
5. 风险提示
"""
import os
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def spearman_ic(x, y):
    x, y = np.array(x, dtype=float), np.array(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 10:
        return np.nan
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    n = len(rx)
    d = rx - ry
    return 1.0 - 6.0 * np.sum(d ** 2) / (n * (n ** 2 - 1))


def compute_factors(g):
    """从历史价格数据计算各因子。"""
    g = g.sort_values('trade_date')
    close = g['close'].values
    vol_col = 'vol' if 'vol' in g.columns else 'volume'
    volume = g[vol_col].values
    amount = g['amount'].values
    open_price = g['open'].values
    n = len(close)
    if n < 22:
        return None

    last_close = close[-1]
    prev_close = close[-2] if n >= 2 else close[-1]
    last_open = open_price[-1]

    # momentum_strength
    mom_1m = (close[-1] / close[-22] - 1) if n >= 23 else 0
    mom_3m = (close[-1] / close[-min(66, n - 1)] - 1) if n >= 67 else mom_1m
    mom_1m_n = min(max(mom_1m / 0.3, 0), 1)
    mom_3m_n = min(max(mom_3m / 0.5, 0), 1)
    if n >= 133:
        mom_6m = close[-1] / close[-132] - 1
        mom_6m_n = min(max(mom_6m / 0.8, 0), 1)
        momentum_strength = min(max(0.4 * mom_1m_n + 0.3 * mom_3m_n + 0.3 * mom_6m_n, 0), 1)
    elif n >= 67:
        momentum_strength = min(max(0.6 * mom_1m_n + 0.4 * mom_3m_n, 0), 1)
    else:
        momentum_strength = mom_1m_n

    # volume_expansion_quality
    avg_vol_20 = np.mean(volume[-min(20, n):])
    avg_vol_5 = np.mean(volume[-5:]) if n >= 5 else 1
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1.0
    volume_expansion = min(max((vol_ratio - 1.0) / 1.5, 0), 1)

    # close_strength
    high_20 = np.max(close[-min(20, n):])
    low_20 = np.min(close[-min(20, n):])
    price_range = high_20 - low_20 if high_20 > low_20 else 1
    close_strength = (last_close - low_20) / price_range

    # breakout_freshness
    ret_5d = (close[-1] / close[-min(6, n)] - 1) if n >= 6 else 0
    daily_return = (last_close / prev_close - 1) if prev_close > 0 else 0
    breakout_raw = 0.5 * min(max(ret_5d / 0.15, 0), 1) + 0.5 * min(max(daily_return / 0.05, 0), 1)
    breakout_freshness = min(max(breakout_raw, 0), 1)

    # trend_acceleration
    if n >= 44:
        mom_2w = close[-1] / close[-10] - 1
        mom_prev_2w = close[-11] / close[-21] - 1 if n >= 22 else 0
        accel = mom_2w - mom_prev_2w
        trend_acceleration = min(max(accel / 0.1, 0), 1)
    else:
        trend_acceleration = 0.5 * momentum_strength

    # sector_resonance (中性)
    sector_resonance = 0.5

    # catalyst_freshness
    last_amount = amount[-1]
    avg_amount_20 = np.mean(amount[-min(20, n):])
    amount_ratio = last_amount / avg_amount_20 if avg_amount_20 > 0 else 1.0
    catalyst_freshness = min(max(0.6 * min(amount_ratio / 3.0, 1) + 0.4 * breakout_freshness, 0), 1)

    # layer_c_alignment
    is_bull = last_close > last_open
    layer_c_alignment = min(max(0.5 * float(is_bull) + 0.5 * min(max(daily_return / 0.03, 0), 1), 0), 1)

    # short_term_reversal: 近期下跌 + 当日反弹
    ret_5d_raw = close[-1] / close[-6] - 1 if n >= 6 else 0
    mean_rev_proxy = min(max(-ret_5d_raw / 0.08, 0), 1)  # 5日跌幅越大，proxy越高
    short_term_reversal = mean_rev_proxy * (1 - momentum_strength)

    return {
        'momentum_strength': momentum_strength,
        'volume_expansion_quality': volume_expansion,
        'close_strength': close_strength,
        'breakout_freshness': breakout_freshness,
        'trend_acceleration': trend_acceleration,
        'sector_resonance': sector_resonance,
        'catalyst_freshness': catalyst_freshness,
        'layer_c_alignment': layer_c_alignment,
        'short_term_reversal': short_term_reversal,
        'daily_return': daily_return,
        'vol_ratio': vol_ratio,
        'ret_5d': ret_5d,
        'is_bull': is_bull,
        'amount': last_amount,
    }


# ic_optimized profile weights (sum=1.18, normalized)
PROFILE = {
    'name': 'ic_optimized',
    'select_threshold': 0.40,
    'near_miss_threshold': 0.28,
    'weights': {
        'breakout_freshness': 0.06,
        'trend_acceleration': 0.06,
        'volume_expansion_quality': 0.16,
        'close_strength': 0.26,
        'sector_resonance': 0.14,
        'catalyst_freshness': 0.18,
        'layer_c_alignment': 0.14,
        'momentum_strength': 0.10,
        'short_term_reversal': 0.08,
    },
}


def normalize_weights(weights):
    total = sum(max(0.0, v) for v in weights.values())
    if total <= 0:
        return {k: 1.0 / len(weights) for k in weights}
    return {k: max(0.0, v) / total for k, v in weights.items()}


def compute_score(factors, weights):
    nw = normalize_weights(weights)
    score = sum(nw.get(k, 0) * factors.get(k, 0) for k in nw)
    return min(max(score, 0), 1)


def main():
    import tushare as ts
    ts.set_token(os.getenv('TUSHARE_TOKEN'))
    pro = ts.pro_api()

    # 确定交易日
    cal = pro.trade_cal(exchange='SSE', start_date='20260410', end_date='20260416', is_open='1')
    all_dates = sorted(cal['cal_date'].tolist())
    next_map = {d: all_dates[i + 1] for i, d in enumerate(all_dates) if i + 1 < len(all_dates)}

    # 找最新有数据的交易日
    trade_date = None
    for d in reversed(all_dates):
        df = pro.daily(trade_date=d)
        if df is not None and not df.empty:
            trade_date = d
            break

    if not trade_date:
        print("无法获取交易数据")
        return

    next_date = next_map.get(trade_date, 'N/A')
    print(f"=" * 80)
    print(f"  BTST选股分析报告")
    print(f"  信号日: {trade_date}  |  目标日: {next_date}")
    print(f"  Profile: {PROFILE['name']}  |  选入阈值: {PROFILE['select_threshold']}  |  近_miss阈值: {PROFILE['near_miss_threshold']}")
    print(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"=" * 80)

    # 获取基础数据
    sb = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,industry,list_date')
    df = pro.daily(trade_date=trade_date)
    df = df.merge(sb, on='ts_code', how='left')

    total = len(df)
    df = df[df['amount'] >= 100000]
    df = df[~df['name'].str.contains('ST|退', na=False)]
    df = df[~df['ts_code'].str.startswith(('688', '8', '4'))]
    # 不排除涨停股（新策略）
    print(f"\n候选池: 全市场{total}只 → 过滤后{len(df)}只 (含涨停股)")

    # 获取涨停股列表
    try:
        limit_df = pro.limit_list(trade_date=trade_date, limit_type='U')
        limit_codes = set(limit_df['ts_code'].tolist()) if limit_df is not None and not limit_df.empty else set()
    except:
        limit_codes = set()

    # 获取历史价格
    codes = df['ts_code'].tolist()
    history = []
    for i in range(0, len(codes), 80):
        batch = codes[i:i + 80]
        try:
            h = pro.daily(ts_code=','.join(batch), start_date='20250601', end_date=trade_date)
            if h is not None and not h.empty:
                history.append(h)
        except:
            continue

    if not history:
        print("无法获取历史数据")
        return

    hist = pd.concat(history, ignore_index=True)
    hist['trade_date'] = pd.to_datetime(hist['trade_date'], format='%Y%m%d')
    hist = hist.sort_values(['ts_code', 'trade_date'])

    # 计算因子
    stock_factors = {}
    for code, g in hist.groupby('ts_code'):
        f = compute_factors(g)
        if f is not None:
            stock_factors[code] = f

    results = df[df['ts_code'].isin(stock_factors.keys())].copy()
    print(f"因子计算完成: {len(results)}只 (历史数据不足{len(df) - len(results)}只)")

    # 计算score
    scores = []
    for _, row in results.iterrows():
        f = stock_factors.get(row['ts_code'])
        scores.append(compute_score(f, PROFILE['weights']) if f else 0)
    results['score'] = scores

    # 市场概况
    print(f"\n{'─' * 80}")
    print(f"  市场概况 ({trade_date})")
    print(f"{'─' * 80}")
    avg_ret = results['pct_chg'].mean()
    pos_rate = (results['pct_chg'] > 0).mean()
    limit_up = len(set(results['ts_code']) & limit_codes)
    print(f"  候选池均涨幅: {avg_ret:+.2f}%  上涨比例: {pos_rate:.0%}  涨停: {limit_up}只")
    print(f"  成交额分布: 25%={results['amount'].quantile(0.25) / 10000:.0f}亿  "
          f"中位数={results['amount'].median() / 10000:.0f}亿  "
          f"75%={results['amount'].quantile(0.75) / 10000:.0f}亿")

    # 因子分布
    print(f"\n{'─' * 80}")
    print(f"  因子分布 (候选池 {len(results)} 只)")
    print(f"{'─' * 80}")
    factor_cols = ['momentum_strength', 'volume_expansion_quality', 'close_strength',
                   'breakout_freshness', 'trend_acceleration', 'catalyst_freshness',
                   'layer_c_alignment', 'short_term_reversal']
    factor_names = ['动量强度', '成交量扩张', '收盘强度', '突破新鲜度', '趋势加速', '催化剂新鲜度', 'LayerC一致性', '短期反转']

    for col, name in zip(factor_cols, factor_names):
        vals = [stock_factors[c].get(col, 0) for c in results['ts_code']]
        print(f"  {name:12}: mean={np.mean(vals):.3f}  std={np.std(vals):.3f}  "
              f">0.5: {np.mean([v > 0.5 for v in vals]):.0%}  "
              f">0.8: {np.mean([v > 0.8 for v in vals]):.0%}")

    # 选股结果
    print(f"\n{'=' * 80}")
    print(f"  ★ 选股结果 ★")
    print(f"{'=' * 80}")

    selected = results[results['score'] >= PROFILE['select_threshold']].sort_values('score', ascending=False)
    near_miss = results[(results['score'] >= PROFILE['near_miss_threshold']) &
                        (results['score'] < PROFILE['select_threshold'])].sort_values('score', ascending=False)

    print(f"\n  ┌─ SELECTED (score >= {PROFILE['select_threshold']}) ─ {len(selected)}只")
    print(f"  │")
    if len(selected) > 0:
        print(f"  │ {'代码':12} {'名称':10} {'行业':8} {'得分':>6} {'日涨%':>6} {'动量':>5} {'量扩':>5} {'收强':>5} {'催化':>5} {'反转':>5} {'涨停':>4}")
        print(f"  │ {'─' * 80}")
        for _, row in selected.head(30).iterrows():
            f = stock_factors.get(row['ts_code'], {})
            is_limit = '★' if row['ts_code'] in limit_codes else ''
            print(f"  │ {row['ts_code'][:6]:12} {(str(row.get('name',''))[:8]):10} {(str(row.get('industry',''))[:6]):8} "
                  f"{row['score']:>6.4f} {row['pct_chg']:>+5.1f}% "
                  f"{f.get('momentum_strength', 0):>5.2f} {f.get('volume_expansion_quality', 0):>5.2f} "
                  f"{f.get('close_strength', 0):>5.2f} {f.get('catalyst_freshness', 0):>5.2f} "
                  f"{f.get('short_term_reversal', 0):>5.2f} {is_limit:>4}")
    else:
        print(f"  │ (无)")

    print(f"  │")
    print(f"  └─ 共{len(selected)}只 ─────────────────────────────────────────────────────────")

    print(f"\n  ┌─ NEAR MISS ({PROFILE['near_miss_threshold']} <= score < {PROFILE['select_threshold']}) ─ {len(near_miss)}只")
    print(f"  │")
    if len(near_miss) > 0:
        print(f"  │ {'代码':12} {'名称':10} {'行业':8} {'得分':>6} {'日涨%':>6} {'动量':>5} {'量扩':>5} {'收强':>5} {'催化':>5} {'反转':>5} {'涨停':>4}")
        print(f"  │ {'─' * 80}")
        for _, row in near_miss.head(20).iterrows():
            f = stock_factors.get(row['ts_code'], {})
            is_limit = '★' if row['ts_code'] in limit_codes else ''
            print(f"  │ {row['ts_code'][:6]:12} {(str(row.get('name',''))[:8]):10} {(str(row.get('industry',''))[:6]):8} "
                  f"{row['score']:>6.4f} {row['pct_chg']:>+5.1f}% "
                  f"{f.get('momentum_strength', 0):>5.2f} {f.get('volume_expansion_quality', 0):>5.2f} "
                  f"{f.get('close_strength', 0):>5.2f} {f.get('catalyst_freshness', 0):>5.2f} "
                  f"{f.get('short_term_reversal', 0):>5.2f} {is_limit:>4}")
    else:
        print(f"  │ (无)")
    print(f"  │")
    print(f"  └─ 共{len(near_miss)}只 ─────────────────────────────────────────────────────────")

    # 涨停股专项
    limit_in_pool = results[results['ts_code'].isin(limit_codes)]
    if len(limit_in_pool) > 0:
        print(f"\n{'─' * 80}")
        print(f"  涨停股专项分析 ({len(limit_in_pool)}只)")
        print(f"{'─' * 80}")
        limit_sorted = limit_in_pool.sort_values('score', ascending=False)
        print(f"  {'代码':12} {'名称':10} {'得分':>6} {'日涨%':>6} {'量扩':>5} {'收强':>5} {'反转':>5}")
        for _, row in limit_sorted.head(20).iterrows():
            f = stock_factors.get(row['ts_code'], {})
            print(f"  {row['ts_code'][:6]:12} {(str(row.get('name',''))[:8]):10} "
                  f"{row['score']:>6.4f} {row['pct_chg']:>+5.1f}% "
                  f"{f.get('volume_expansion_quality', 0):>5.2f} "
                  f"{f.get('close_strength', 0):>5.2f} "
                  f"{f.get('short_term_reversal', 0):>5.2f}")
        limit_selected = len(limit_in_pool[limit_in_pool['score'] >= PROFILE['select_threshold']])
        print(f"  → 其中{limit_selected}只入选SELECTED")

    # 短期反转机会
    reversal_stocks = results.copy()
    reversal_stocks['str_val'] = [stock_factors.get(c, {}).get('short_term_reversal', 0) for c in reversal_stocks['ts_code']]
    reversal_top = reversal_stocks[reversal_stocks['str_val'] > 0.3].sort_values('str_val', ascending=False)
    if len(reversal_top) > 0:
        print(f"\n{'─' * 80}")
        print(f"  短期反转机会 (short_term_reversal > 0.3, {len(reversal_top)}只)")
        print(f"{'─' * 80}")
        print(f"  {'代码':12} {'名称':10} {'得分':>6} {'日涨%':>6} {'反转':>5} {'5日%':>7} {'决策':>10}")
        for _, row in reversal_top.head(15).iterrows():
            f = stock_factors.get(row['ts_code'], {})
            decision = 'SELECTED' if row['score'] >= PROFILE['select_threshold'] else (
                'NEAR_MISS' if row['score'] >= PROFILE['near_miss_threshold'] else 'watch')
            print(f"  {row['ts_code'][:6]:12} {(str(row.get('name',''))[:8]):10} "
                  f"{row['score']:>6.4f} {row['pct_chg']:>+5.1f}% "
                  f"{f.get('short_term_reversal', 0):>5.2f} "
                  f"{f.get('ret_5d', 0) * 100:>+6.1f}% "
                  f"{decision:>10}")

    # 行业分布
    print(f"\n{'─' * 80}")
    print(f"  行业分布 (SELECTED + NEAR_MISS)")
    print(f"{'─' * 80}")
    combined = pd.concat([selected, near_miss])
    if len(combined) > 0 and 'industry' in combined.columns:
        industry_counts = combined['industry'].value_counts().head(15)
        for ind, cnt in industry_counts.items():
            print(f"  {str(ind):12}: {cnt:>3}只")

    # 风险提示
    print(f"\n{'=' * 80}")
    print(f"  风险提示")
    print(f"{'=' * 80}")
    print(f"  1. 本报告基于因子近似评分，未包含LLM agent分析(score_c)")
    print(f"  2. 因子回测胜率约42%，需配合实际pipeline的LLM层提升至60%+")
    print(f"  3. 涨停股次日高开但可能冲高回落，注意止盈纪律")
    print(f"  4. 市场状态: {trade_date} 均涨幅{avg_ret:+.2f}%, {'偏强' if avg_ret > 0.5 else '偏弱' if avg_ret < -0.5 else '中性'}")
    print(f"  5. 建议: SELECTED中优先选择close_strength>0.7且catalyst_freshness>0.5的标的")

    # 保存JSON报告
    report = {
        'trade_date': trade_date,
        'next_date': next_date,
        'profile': PROFILE['name'],
        'pool_size': len(results),
        'selected_count': len(selected),
        'near_miss_count': len(near_miss),
        'limit_up_count': len(limit_in_pool),
        'selected': [{
            'ticker': row['ts_code'][:6],
            'name': str(row.get('name', '')),
            'industry': str(row.get('industry', '')),
            'score': round(float(row['score']), 4),
            'pct_chg': round(float(row['pct_chg']), 2),
            'is_limit_up': row['ts_code'] in limit_codes,
            'factors': {k: round(float(v), 4) for k, v in stock_factors.get(row['ts_code'], {}).items()
                        if k in factor_cols},
        } for _, row in selected.iterrows()],
        'near_miss': [{
            'ticker': row['ts_code'][:6],
            'name': str(row.get('name', '')),
            'score': round(float(row['score']), 4),
            'pct_chg': round(float(row['pct_chg']), 2),
        } for _, row in near_miss.head(30).iterrows()],
    }

    out_path = Path(__file__).resolve().parent.parent / "data" / "reports" / f"btst_selection_{trade_date}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n报告已保存: {out_path}")
    print(f"{'=' * 80}")


if __name__ == '__main__':
    main()
