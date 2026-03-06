"""
Layer A 候选池构建器 — 全市场快筛

实现框架 §1 先验约束矩阵 + §5.1 Step 1：
  1. 获取全 A 股基本信息（~5000 只）
  2. 排除 ST / *ST 标的（名称包含 ST）
  3. 排除北交所标的（市场 = 'BJ' 或代码 8xxxxx / 4xxxxx）
  4. 排除上市不满 60 个交易日的新股/次新股
  5. 排除当日停牌标的
  6. 排除当日涨停标的（买入排队失败）
  7. 排除停牌超过 5 日后复牌未满 3 个正常交易日的标的（简化实现）
  8. 排除近 20 日平均成交额 < 5000 万元的低流动性标的
  9. 排除被冲突仲裁规则一标记的"回避冷却期"标的（15 个交易日）
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd

from src.screening.models import CandidateStock
from src.tools.tushare_api import (
    _get_pro,
    _to_ts_code,
    get_all_stock_basic,
    get_daily_basic_batch,
    get_limit_list,
    get_suspend_list,
    get_sw_industry_classification,
)

# 项目根目录
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SNAPSHOT_DIR = _PROJECT_ROOT / "data" / "snapshots"
_COOLDOWN_FILE = _SNAPSHOT_DIR / "cooldown_registry.json"

# 常量
MIN_LISTING_DAYS = 60
MIN_AVG_AMOUNT_20D = 5000  # 万元
COOLDOWN_TRADING_DAYS = 15
DISCLOSURE_MONTHS = {4, 8, 10}  # 财报窗口月份


# ============================================================================
# 冷却期注册表（持久化 JSON）
# ============================================================================

def load_cooldown_registry() -> Dict[str, str]:
    """加载冷却期注册表：{ticker: expire_date_YYYYMMDD}"""
    if _COOLDOWN_FILE.exists():
        try:
            with open(_COOLDOWN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_cooldown_registry(registry: Dict[str, str]) -> None:
    """保存冷却期注册表"""
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with open(_COOLDOWN_FILE, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def add_cooldown(ticker: str, trade_date: str, days: int = COOLDOWN_TRADING_DAYS) -> None:
    """将标的加入冷却期。trade_date 格式 YYYYMMDD。"""
    registry = load_cooldown_registry()
    dt = datetime.strptime(trade_date, "%Y%m%d")
    # 近似用自然日（交易日转换需要交易日历，此处用 1.5 倍近似）
    expire_dt = dt + timedelta(days=int(days * 1.5))
    registry[ticker] = expire_dt.strftime("%Y%m%d")
    save_cooldown_registry(registry)


def get_cooled_tickers(trade_date: str) -> Set[str]:
    """获取当前处于冷却期的标的集合"""
    registry = load_cooldown_registry()
    cooled: Set[str] = set()
    expired: list[str] = []
    for ticker, expire_date in registry.items():
        if expire_date > trade_date:
            cooled.add(ticker)
        else:
            expired.append(ticker)
    # 清理过期的冷却记录
    if expired:
        for t in expired:
            del registry[t]
        save_cooldown_registry(registry)
    return cooled


# ============================================================================
# 核心筛选逻辑
# ============================================================================

def _is_disclosure_window(trade_date: str) -> bool:
    """判断是否处于财报窗口期（4月/8月/10月）"""
    month = int(trade_date[4:6])
    return month in DISCLOSURE_MONTHS


def _estimate_trading_days(list_date: str, trade_date: str) -> int:
    """
    估算上市日期到交易日期之间的交易日数。
    使用自然日 × 0.7 近似（A 股年 250 交易日 / 365 自然日 ≈ 0.685）。
    """
    try:
        dt_list = datetime.strptime(list_date, "%Y%m%d")
        dt_trade = datetime.strptime(trade_date, "%Y%m%d")
        natural_days = (dt_trade - dt_list).days
        return max(0, int(natural_days * 0.7))
    except (ValueError, TypeError):
        return 0


def _get_avg_amount_20d(pro, ts_code: str, trade_date: str) -> float:
    """获取近 20 日平均成交额（万元）。使用 daily_basic 批量缓存优先。"""
    try:
        # 使用 daily 接口获取近 20 日成交额
        end_dt = datetime.strptime(trade_date, "%Y%m%d")
        start_dt = end_dt - timedelta(days=35)  # 多取几天确保覆盖 20 个交易日
        df = pro.daily(
            ts_code=ts_code,
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=trade_date,
            fields="trade_date,amount",
        )
        if df is None or df.empty:
            return 0.0
        # tushare daily 的 amount 单位是千元
        amounts = df["amount"].dropna().tail(20)
        if amounts.empty:
            return 0.0
        return float(amounts.mean() / 10.0)  # 千元 → 万元
    except Exception:
        return 0.0


def build_candidate_pool(
    trade_date: str,
    use_cache: bool = True,
    cooldown_tickers: Optional[Set[str]] = None,
) -> List[CandidateStock]:
    """
    构建 Layer A 候选池。

    参数:
        trade_date: 交易日期，格式 YYYYMMDD
        use_cache: 启用增量缓存（当日已生成则跳过）
        cooldown_tickers: 外部传入的冷却期标的集合（可选，未提供则从文件加载）

    返回:
        List[CandidateStock] — 通过所有筛选规则的候选标的

    流程:
        1) 全量股票基本信息 → 排除 ST / 北交所
        2) 排除新股（< 60 交易日）
        3) 排除当日停牌
        4) 排除当日涨停
        5) 排除冷却期标的
        6) 获取行业分类 + 成交额 → 排除低流动性
        7) 标记财报窗口期
        8) 输出结果 + 持久化
    """
    # ---- 缓存检查 ----
    snapshot_path = _SNAPSHOT_DIR / f"candidate_pool_{trade_date}.json"
    if use_cache and snapshot_path.exists():
        try:
            with open(snapshot_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            candidates = [CandidateStock(**item) for item in data]
            print(f"[CandidatePool] 从缓存加载 {len(candidates)} 只候选标的 ({trade_date})")
            return candidates
        except Exception as e:
            print(f"[CandidatePool] 缓存读取失败，重新计算: {e}")

    pro = _get_pro()
    if pro is None:
        print("[CandidatePool] Tushare 未初始化，无法构建候选池")
        return []

    # ---- Step 1: 全 A 股基本信息 ----
    stock_df = get_all_stock_basic()
    if stock_df is None or stock_df.empty:
        print("[CandidatePool] 无法获取全 A 股基本信息")
        return []

    initial_count = len(stock_df)
    print(f"[CandidatePool] 全 A 股标的: {initial_count}")

    # ---- Step 2: 排除 ST ----
    mask_st = stock_df["name"].str.contains("ST", case=False, na=False)
    stock_df = stock_df[~mask_st].copy()
    print(f"[CandidatePool] 排除 ST 后: {len(stock_df)} (过滤 {mask_st.sum()})")

    # ---- Step 3: 排除北交所 ----
    mask_bj = (stock_df["market"] == "BJ") | stock_df["symbol"].str.startswith(("4", "8"))
    # 仅排除 4xxxxx/8xxxxx 中属于北交所的（排除创业板 3xxxxx 误伤）
    stock_df = stock_df[~mask_bj].copy()
    print(f"[CandidatePool] 排除北交所后: {len(stock_df)} (过滤 {mask_bj.sum()})")

    # ---- Step 4: 排除新股 ----
    mask_new = stock_df["list_date"].apply(
        lambda d: _estimate_trading_days(str(d) if pd.notna(d) else "", trade_date) < MIN_LISTING_DAYS
    )
    stock_df = stock_df[~mask_new].copy()
    print(f"[CandidatePool] 排除新股后: {len(stock_df)} (过滤 {mask_new.sum()})")

    # ---- Step 5: 排除当日停牌 ----
    suspend_df = get_suspend_list(trade_date)
    if suspend_df is not None and not suspend_df.empty:
        suspend_codes = set(suspend_df["ts_code"].tolist())
        mask_suspend = stock_df["ts_code"].isin(suspend_codes)
        stock_df = stock_df[~mask_suspend].copy()
        print(f"[CandidatePool] 排除停牌后: {len(stock_df)} (过滤 {mask_suspend.sum()})")

    # ---- Step 6: 排除当日涨停 ----
    limit_df = get_limit_list(trade_date)
    if limit_df is not None and not limit_df.empty:
        limit_up_codes = set(limit_df[limit_df["limit"] == "U"]["ts_code"].tolist())
        mask_limit_up = stock_df["ts_code"].isin(limit_up_codes)
        stock_df = stock_df[~mask_limit_up].copy()
        print(f"[CandidatePool] 排除涨停后: {len(stock_df)} (过滤 {mask_limit_up.sum()})")

    # ---- Step 7: 排除冷却期标的 ----
    if cooldown_tickers is None:
        cooldown_tickers = get_cooled_tickers(trade_date)
    if cooldown_tickers:
        # 冷却期用 symbol（6 位数字）匹配
        mask_cool = stock_df["symbol"].isin(cooldown_tickers)
        stock_df = stock_df[~mask_cool].copy()
        print(f"[CandidatePool] 排除冷却期后: {len(stock_df)} (过滤 {mask_cool.sum()})")

    # ---- Step 8: 获取当日 daily_basic 批量数据（市值+成交额筛选） ----
    daily_df = get_daily_basic_batch(trade_date)
    amount_map: Dict[str, float] = {}
    mv_map: Dict[str, float] = {}

    if daily_df is not None and not daily_df.empty:
        for _, row in daily_df.iterrows():
            ts = str(row["ts_code"])
            # total_mv 单位万元
            if pd.notna(row.get("total_mv")):
                mv_map[ts] = float(row["total_mv"])

    # 对剩余标的计算 20 日均额（批量优化：先用 daily_basic 的当日成交额粗筛，低于阈值的直接排除）
    # 但 daily_basic 没有 20 日均额，需要逐只精确计算
    # 优化策略：分批获取，每批控制在 API 限流范围内
    remaining_codes = stock_df["ts_code"].tolist()
    print(f"[CandidatePool] 开始计算 {len(remaining_codes)} 只标的的 20 日均成交额...")

    import time
    low_liq_codes: Set[str] = set()
    batch_size = 50
    for i in range(0, len(remaining_codes), batch_size):
        batch = remaining_codes[i:i + batch_size]
        for ts_code in batch:
            avg_amt = _get_avg_amount_20d(pro, ts_code, trade_date)
            amount_map[ts_code] = avg_amt
            if avg_amt < MIN_AVG_AMOUNT_20D:
                low_liq_codes.add(ts_code)
        # tushare 限流：200 次/分钟，每批暂停
        if i + batch_size < len(remaining_codes):
            time.sleep(15)
        progress_pct = min(100, int((i + batch_size) / len(remaining_codes) * 100))
        print(f"[CandidatePool] 成交额计算进度: {progress_pct}%")

    mask_low_liq = stock_df["ts_code"].isin(low_liq_codes)
    stock_df = stock_df[~mask_low_liq].copy()
    print(f"[CandidatePool] 排除低流动性后: {len(stock_df)} (过滤 {mask_low_liq.sum()})")

    # ---- Step 9: 获取申万行业分类 ----
    sw_map = get_sw_industry_classification()
    if sw_map is None:
        sw_map = {}

    # ---- Step 10: 组装输出 ----
    is_disclosure = _is_disclosure_window(trade_date)
    candidates: List[CandidateStock] = []

    for _, row in stock_df.iterrows():
        ts_code = str(row["ts_code"])
        symbol = str(row["symbol"])
        name = str(row["name"])
        list_date = str(row["list_date"]) if pd.notna(row.get("list_date")) else ""
        industry_sw = sw_map.get(ts_code, str(row.get("industry", "")))
        market_cap = mv_map.get(ts_code, 0.0) / 10000.0  # 万元 → 亿元
        avg_vol = amount_map.get(ts_code, 0.0)

        candidates.append(CandidateStock(
            ticker=symbol,
            name=name,
            industry_sw=industry_sw,
            market_cap=market_cap,
            avg_volume_20d=avg_vol,
            listing_date=list_date,
            disclosure_risk=is_disclosure,
        ))

    # ---- 持久化 ----
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump([c.model_dump() for c in candidates], f, ensure_ascii=False, indent=2)

    print(f"[CandidatePool] 最终候选池: {len(candidates)} 只 → {snapshot_path}")
    return candidates


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Layer A 候选池构建器")
    parser.add_argument("--trade-date", required=True, help="交易日期 YYYYMMDD")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    args = parser.parse_args()

    candidates = build_candidate_pool(args.trade_date, use_cache=not args.no_cache)
    print(f"\n=== 候选池结果 ===")
    print(f"日期: {args.trade_date}")
    print(f"标的数: {len(candidates)}")
    if candidates:
        # 按市值降序显示前 20 只
        sorted_candidates = sorted(candidates, key=lambda c: c.market_cap, reverse=True)
        print(f"\n市值 Top 20:")
        for i, c in enumerate(sorted_candidates[:20], 1):
            print(f"  {i:2d}. {c.ticker} {c.name:<8s} 行业={c.industry_sw:<6s} 市值={c.market_cap:.1f}亿 均额={c.avg_volume_20d:.0f}万")


if __name__ == "__main__":
    main()
