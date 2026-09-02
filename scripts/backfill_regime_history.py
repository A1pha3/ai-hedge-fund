"""backfill 2020-2026 每个交易日的 regime_gate_level → regime_history.json.

背景: regime 标签此前只来自 84 个 auto_screening 报告日期 (2024-03 起, 稀疏).
regime 分层评判需要覆盖完整历史 (含 2020-2023 + OversoldBounce 的 2022 熊市样本).
tushare 5 端点全部可用, detect_market_state(date) 是自包含单日函数.

幂等: 已有标签的日期 (auto_screening 报告 + 上次 backfill) 跳过.
可中断: 每 50 日存盘, 中断后重跑从断点继续.
端点: 默认昨日 (--end 覆盖, ≥今日拒绝 — 当日标签是 --auto 收盘后的职责,
半日数据回填会制造伪标签, 与空窗同为 court 证据的对偶污染面).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_REGIME_HISTORY_PATH = Path("data/reports/regime_history.json")
_REPORTS_DIR = Path("data/reports/")
_START_DATE = "20200101"
_SAVE_EVERY = 50  # 每 50 日存盘一次 (防中断)
_SLEEP_PER_DAY = 0.3  # 限频 (tushare)


def _resolve_end_date(raw_end: str | None, *, today: "date | None" = None) -> str:
    """回填端点解析: 默认昨日; 显式 --end 尊重; end≥今日一律拒绝.

    当日 regime 是 --auto 生产写入者的职责 (收盘后 detect_market_state 定型);
    回填在盘中跑会用半日数据算出伪标签 — 这是 2026-07-08..16 空窗教训的
    对偶面: 空窗使 court 整日剔除, 半日伪标签则会污染 regime 分层证据。
    """
    from datetime import date as _date, timedelta as _timedelta

    today = today or _date.today()
    yesterday = (today - _timedelta(days=1)).strftime("%Y%m%d")
    resolved = str(raw_end or "").strip() or yesterday
    if len(resolved) != 8 or not resolved.isdigit():
        raise SystemExit(f"invalid --end: {raw_end!r} (期望 YYYYMMDD)")
    if resolved >= today.strftime("%Y%m%d"):
        raise SystemExit(
            f"--end {resolved} >= 今日 {today.strftime('%Y%m%d')} — "
            "当日标签由 --auto 收盘后写入, 回填拒绝半日数据"
        )
    return resolved


def _load_existing_history() -> dict[str, str]:
    """加载已持久化的 regime_history.json (幂等基底线)."""
    if not _REGIME_HISTORY_PATH.exists():
        return {}
    try:
        data = json.loads(_REGIME_HISTORY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("regime_history 损坏, 从空重建: %s", exc)
    return {}


def _load_existing_map() -> dict[str, str]:
    """合并 regime_history.json + auto_screening 报告里的 regime 标签 (全量已有标签)."""
    from src.screening.regime_winrate_recompute import build_date_to_regime_map

    history = _load_existing_history()
    report_map = build_date_to_regime_map(_REPORTS_DIR)
    # 报告标签优先 (它是 market_state 实际跑出来的), 其次历史文件
    merged = {**history, **report_map}
    return merged


def _fetch_trading_days(end: str = "20260707") -> list[str]:
    """拉 2020-2026 交易日列表 (tushare trade_cal)."""
    from src.tools.tushare_api import _get_pro

    pro = _get_pro()
    df = pro.trade_cal(exchange="", start_date=_START_DATE, end_date=end, is_open=1)
    if df is None or len(df) == 0:
        return []
    return sorted(df["cal_date"].astype(str).tolist())


def _classify_one_day(trade_date: str) -> str | None:
    """对单日跑 detect_market_state → regime_gate_level. 失败返回 None.

    性能要点: detect_market_state 的 P2-9 macro 集成会调 cn_m2/cn_sf 等 6 个
    宏观端点, 这些端点需要较高 tushare 积分, 我们账号无权限 → 每个报"请指定
    正确的接口名"并重试 2 次, 单日浪费 ~7.4s. 而 regime_gate_level 完全由
    index/breadth/limit/northbound/daily_basic 决定, macro 只是
    state.macro_context 的附加注释 (market_state.py:93-106 是 best-effort).
    本函数 monkey-patch fetch_macro_snapshot 返回空快照, 单日从 ~7.4s 降到
    ~0.2s (1576 天从 ~5h 降到 ~5 分钟). 通过 REGIME_BACKFILL_MACRO=1 可关掉
    此优化 (用于诊断 macro 是否影响结果).
    """
    import os

    from src.screening.market_state import detect_market_state

    skip_macro = os.environ.get("REGIME_BACKFILL_MACRO", "0") != "1"
    if skip_macro:
        # 在函数内部 patch (仅影响 backfill 进程, 不污染其他模块的导入),
        # 避免每次调用都重复 import.
        from src.data.macro_data import MacroSnapshot, fetch_macro_snapshot as _orig

        # NS-17 family: 不静默 — 在 logger 显式记录一次 patch 应用 (首次调用时).
        import src.data.macro_data as _macro_mod

        if not getattr(_classify_one_day, "_macro_patched", False):
            logger.info(
                "REGIME_BACKFILL_MACRO 未启用 → 跳过 cn_m2/cn_sf 等 6 个宏观端点 "
                "(账号无权限, 每日省 ~7.4s; regime_gate_level 不受影响). "
                "设 REGIME_BACKFILL_MACRO=1 可恢复 macro 调用 (诊断用)."
            )
            _classify_one_day._macro_patched = True  # type: ignore[attr-defined]

        _macro_mod.fetch_macro_snapshot = lambda **_: MacroSnapshot()

    try:
        state = detect_market_state(trade_date)
        regime = str(state.regime_gate_level or "normal").strip().lower()
        return regime if regime in {"normal", "crisis", "risk_off"} else "normal"
    except Exception as exc:
        logger.warning("detect_market_state(%s) 失败: %s", trade_date, exc)
        return None


def _save_history(mapping: dict[str, str]) -> None:
    """原子写 regime_history.json (tmp → replace)."""
    _REGIME_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _REGIME_HISTORY_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(_REGIME_HISTORY_PATH)


def backfill(
    *,
    max_days: int | None = None,
    sleep: float = _SLEEP_PER_DAY,
    end: str | None = None,
) -> dict[str, str]:
    """backfill regime 历史. 返回完整 date→regime 映射.

    幂等: 交易日中已有标签的日子 (regime_history + auto_screening 报告)
    不重算不覆盖 — 只补缺标签日。

    Args:
        max_days: 最多 backfill 多少天 (None=全部; 测试/调试用)
        sleep: 每日 sleep 秒数 (限频)
        end: 回填端点 YYYYMMDD (默认昨日; ≥今日被 _resolve_end_date 拒绝)

    Returns:
        ``{YYYYMMDD: regime}`` (含已有 + 本次新增)
    """
    resolved_end = _resolve_end_date(end)
    existing = _load_existing_map()
    trading_days = _fetch_trading_days(resolved_end)
    pending = [d for d in trading_days if d not in existing]
    logger.info(
        "regime backfill: 端点 %s, 交易日 %d, 已有标签 %d, 待 backfill %d",
        resolved_end, len(trading_days), len(existing), len(pending),
    )
    print(f"交易日 {len(trading_days)}, 已有标签 {len(existing)}, 待 backfill {len(pending)}")

    if max_days is not None:
        pending = pending[:max_days]
        print(f"  (max_days={max_days} 限制, 实际处理 {len(pending)})")

    mapping = dict(existing)  # 复制已有, 增量添加
    done_this_run = 0
    for i, date_str in enumerate(pending, 1):
        regime = _classify_one_day(date_str)
        if regime is not None:
            mapping[date_str] = regime
            done_this_run += 1
        time.sleep(sleep)
        if i % 10 == 0:
            print(f"  进度 {i}/{len(pending)} (本次+{done_this_run}), 累计 {len(mapping)}")
        if i % _SAVE_EVERY == 0:
            _save_history(mapping)
            print(f"  💾 存盘 ({len(mapping)} 日)")

    _save_history(mapping)
    print(f"\n完成: 本次 backfill {done_this_run}, 累计 {len(mapping)} 日")
    return mapping


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="backfill regime_history 缺标签日 (幂等, 只补缺不覆盖)")
    parser.add_argument("--end", default=None, help="回填端点 YYYYMMDD (默认昨日; ≥今日拒绝)")
    parser.add_argument("--max-days", type=int, default=None, help="最多回填天数 (测试/调试)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    backfill(max_days=args.max_days, end=args.end)


if __name__ == "__main__":
    main()
