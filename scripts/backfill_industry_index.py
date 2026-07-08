"""backfill 31 个 SW L1 行业指数日线 → data/industry_index_cache/{industry_code}.csv.

为 SectorRotation setup 提供 industry_2d_pct (行业 2 日累计涨幅).
实测: 31 行业 × 2020-2026 全量 = 3.9 秒 (48856 行).

幂等: 已有 CSV 且日期覆盖完整则跳过.
可中断: 原子写 (tmp → replace).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_DIR = Path("data/industry_index_cache")
_START_DATE = "20200101"


def _ensure_token_in_env() -> None:
    """项目的 _get_pro() 只读 os.environ['TUSHARE_TOKEN'], 注入 .env token."""
    import os

    if os.environ.get("TUSHARE_TOKEN"):
        return
    env_path = Path(".env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("TUSHARE_TOKEN="):
                token = line.split("=", 1)[1].strip().strip("'\"")
                if token:
                    os.environ["TUSHARE_TOKEN"] = token
                    return


def _fetch_industry_codes() -> list[tuple[str, str]]:
    """拉 SW L1 行业列表 → [(index_code, industry_name), ...].

    industry_name 是中文 (如 '农林牧渔'), 与 get_sw_industry_classification 的映射值一致.
    """
    _ensure_token_in_env()
    import tushare as ts

    pro = ts.pro_api()
    idx_df = pro.index_classify(level="L1", src="SW2021")
    if idx_df is None or len(idx_df) == 0:
        # 回退到旧版分类
        idx_df = pro.index_classify(level="L1", src="SW2014")
    if idx_df is None or len(idx_df) == 0:
        raise RuntimeError("无法获取 SW L1 行业列表")
    return [(str(r["index_code"]), str(r["industry_name"])) for _, r in idx_df.iterrows()]


def _resolve_end_date(end_date: str | None = None) -> str:
    if end_date:
        return end_date.replace("-", "").strip()
    return datetime.now().strftime("%Y%m%d")


def _cache_covers_end_date(path: Path, end_date: str) -> tuple[bool, int]:
    try:
        existing = pd.read_csv(path, dtype={"trade_date": str})
    except Exception:
        return False, 0
    if len(existing) == 0 or "trade_date" not in existing.columns:
        return False, len(existing)
    latest = max(str(value).replace("-", "") for value in existing["trade_date"].dropna())
    return latest >= end_date, len(existing)


def _fetch_industry_daily(index_code: str, end_date: str | None = None) -> pd.DataFrame:
    """拉单个行业指数的全量日线 (含 pct_chg)."""
    _ensure_token_in_env()
    import tushare as ts

    pro = ts.pro_api()
    df = pro.index_daily(ts_code=index_code, start_date=_START_DATE, end_date=_resolve_end_date(end_date))
    if df is None or len(df) == 0:
        return pd.DataFrame()
    return df


def backfill(end_date: str | None = None) -> dict[str, int]:
    """backfill 全部 SW L1 行业指数. 返回 {industry_name: 行数}."""
    resolved_end_date = _resolve_end_date(end_date)
    codes = _fetch_industry_codes()
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 保存 index_code → industry_name 映射 (供 load_industry_2d_pct 用)
    mapping = {code: name for code, name in codes}
    (_CACHE_DIR / "_industry_codes.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    result: dict[str, int] = {}
    for i, (index_code, industry_name) in enumerate(codes, 1):
        out_path = _CACHE_DIR / f"{index_code}.csv"
        if out_path.exists():
            covers_end_date, row_count = _cache_covers_end_date(out_path, resolved_end_date)
            if covers_end_date:
                result[industry_name] = row_count
                continue

        df = _fetch_industry_daily(index_code, resolved_end_date)
        if len(df) == 0:
            logger.warning("行业 %s (%s) 返回空", index_code, industry_name)
            result[industry_name] = 0
            continue

        # 原子写
        tmp = out_path.with_suffix(".tmp")
        df.to_csv(tmp, index=False)
        tmp.replace(out_path)
        result[industry_name] = len(df)
        if i % 10 == 0:
            print(f"  进度 {i}/{len(codes)}, 累计 {sum(result.values())} 行")

    print(f"\n完成: {len(result)} 行业, 总 {sum(result.values())} 行")
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    backfill()


if __name__ == "__main__":
    main()
