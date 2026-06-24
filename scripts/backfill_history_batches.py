"""回测脚本：造多个历史批次的合成报告 → 回填真实 T+30 → 扩充 calibration 样本。

每个批次 = 一个历史日期 + N 只分散 A 股（score_b 覆盖各区间）。
价格是真实的 (tushare)，"推荐"是合成的，用于验证 calibration/reconcile。

用法: python scripts/backfill_history_batches.py
重复运行安全 (Phase 2 merge 不覆盖已有 realized 值, BH-008)。
"""
from dotenv import load_dotenv
load_dotenv()

import json
from datetime import datetime, timedelta
from pathlib import Path

# 分散的 A 股池 (不同行业/板块), 每只配一个合成 score_b
# 覆盖 0.3~0.9 各区间, 每区间多只让 calibration bucket 有样本
POOL = [
    # 高 (>0.8)
    ("600000", "浦发银行", "银行", 0.85), ("601398", "工商银行", "银行", 0.88), ("600276", "恒瑞医药", "医药", 0.82),
    # 中高 (0.7-0.8)
    ("000001", "平安银行", "银行", 0.78), ("688008", "澜起科技", "电子", 0.72), ("600519", "贵州茅台", "白酒", 0.75),
    # 中 (0.6-0.7)
    ("002222", "福晶科技", "电子", 0.65), ("600036", "招商银行", "银行", 0.62), ("002594", "比亚迪", "汽车", 0.68),
    # 中低 (0.5-0.6)
    ("300750", "宁德时代", "电池", 0.58), ("601318", "中国平安", "保险", 0.52), ("600887", "伊利股份", "食品", 0.55),
    # 低 (<0.5)
    ("000858", "五粮液", "白酒", 0.48), ("601012", "隆基绿能", "光伏", 0.42), ("300059", "东方财富", "券商", 0.38),
    ("601857", "中国石油", "石油", 0.45), ("600900", "长江电力", "电力", 0.35),
]

# 多个历史批次 (≥50 天前, 确保 T+30 可算)。每个批次用全部 POOL 的一个子集。
# 避免每批都用同一批票 (降低单一时段的市场偏差)
DAYS_AGO_BATCHES = [50, 60, 70, 80]  # 4 个批次, 约 5-7 月不同时点

rdir = Path("data/reports")
today = datetime.now().strftime("%Y%m%d")

from src.screening.recommendation_tracker import update_tracking_history
from src.screening.consecutive_recommendation import resolve_report_dir

reports_dir = resolve_report_dir()
total_added = 0

for days_ago in DAYS_AGO_BATCHES:
    rec_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y%m%d")
    # 每批次用全部 18 只 (让每个 bucket 在每个时段都有样本)
    recs = [{"ticker": t, "name": n, "industry_sw": ind, "score_b": sb,
             "strategy_signals": {}, "metrics": {}} for t, n, ind, sb in POOL]
    report = {"mode": "backtest", "date": rec_date, "recommendations": recs}
    rp = rdir / f"auto_screening_{rec_date}.json"
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Phase 1: 加入推荐
    n1 = update_tracking_history(reports_dir=reports_dir, trade_date=rec_date)
    # Phase 2: 回填真实收益 (用 today 触发 ≥6 天记录的回填)
    n2 = update_tracking_history(reports_dir=reports_dir, trade_date=today)
    print(f"批次 {rec_date} ({days_ago}天前): Phase1={n1} Phase2={n2}")
    total_added += n2

print(f"\n全部批次完成, 共更新 {total_added} 条 realized 收益")
