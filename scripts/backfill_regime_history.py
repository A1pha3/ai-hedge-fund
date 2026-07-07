"""backfill 2020-2026 每个交易日的 regime_gate_level → regime_history.json.

背景: regime 标签此前只来自 84 个 auto_screening 报告日期 (2024-03 起, 稀疏).
regime 分层评判需要覆盖完整历史 (含 2020-2023 + OversoldBounce 的 2022 熊市样本).
tushare 5 端点全部可用, detect_market_state(date) 是自包含单日函数.

幂等: 已有标签的日期 (auto_screening 报告 + 上次 backfill) 跳过.
可中断: 每 50 日存盘, 中断后重跑从断点继续.
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
_END_DATE = "20260707"
_SAVE_EVERY = 50  # 每 50 日存盘一次 (防中断)
_SLEEP_PER_DAY = 0.3  # 限频 (tushare)


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


def _ensure_token_in_env() -> None:
    """项目的 _get_pro() 只读 os.environ['TUSHARE_TOKEN'], 不读 .env 文件.

    backfill 脚本必须把 .env 的 token 注入 os.environ, 否则 detect_market_state
    调用的 get_index_daily/get_daily_price_batch 等全返回空 → regime 全误判 normal.
    """
    import os

    if os.environ.get("TUSHARE_TOKEN"):
        return  # 已有
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("TUSHARE_TOKEN="):
                token = line.split("=", 1)[1].strip().strip("'\"")
                if token:
                    os.environ["TUSHARE_TOKEN"] = token
                    return


def _fetch_trading_days() -> list[str]:
    """拉 2020-2026 交易日列表 (tushare trade_cal)."""
    _ensure_token_in_env()
    import tushare as ts

    pro = ts.pro_api()
    df = pro.trade_cal(exchange="", start_date=_START_DATE, end_date=_END_DATE, is_open=1)
    if df is None or len(df) == 0:
        return []
    return sorted(df["cal_date"].astype(str).tolist())


def _classify_one_day(trade_date: str) -> str | None:
    """对单日跑 detect_market_state → regime_gate_level. 失败返回 None."""
    from src.screening.market_state import detect_market_state

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


def backfill(*, max_days: int | None = None, sleep: float = _SLEEP_PER_DAY) -> dict[str, str]:
    """backfill regime 历史. 返回完整 date→regime 映射.

    Args:
        max_days: 最多 backfill 多少天 (None=全部; 测试/调试用)
        sleep: 每日 sleep 秒数 (限频)

    Returns:
        ``{YYYYMMDD: regime}`` (含已有 + 本次新增)
    """
    existing = _load_existing_map()
    trading_days = _fetch_trading_days()
    pending = [d for d in trading_days if d not in existing]
    logger.info(
        "regime backfill: 交易日 %d, 已有标签 %d, 待 backfill %d",
        len(trading_days), len(existing), len(pending),
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


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    backfill()


if __name__ == "__main__":
    main()
