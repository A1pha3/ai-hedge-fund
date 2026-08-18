"""题材动量 Tier B2 — 东财概念成分快照 fetcher (计划 v3.4, 每 10 交易日采样).

PIT 纪律: 信号日消费"不晚于它的最近采样快照", 绝不用最新快照回填历史。
采样频率 10 交易日 (v3.4 从月度加密: 新题材首周是研究价值所在, 月度延迟
砍掉主要价值; 成本仅 ×2)。单日失败记 gaps 并继续; 重跑幂等 (已存在跳过)。

用法: uv run python scripts/theme_momentum_fetch_concept.py
产物: data/research/theme_momentum/raw/dc_member_{d}.csv + manifest_concept.json
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from src.tools.tushare_api import _get_pro  # noqa: E402
from src.utils.atomic_files import atomic_write_csv  # noqa: E402

RAW = Path("data/research/theme_momentum/raw")
LU_DIR = Path("data/research/btst_court/raw/limit_up")
SAMPLE_EVERY = 10  # 每 N 个交易日采样
PAGE = 8000


def main() -> None:
    pro = _get_pro()
    if pro is None:
        raise SystemExit("tushare token 不可用")
    lu_dates = sorted(p.stem.split("_")[1] for p in LU_DIR.glob("lu_*.csv"))
    samples = lu_dates[::SAMPLE_EVERY]
    if lu_dates[-1] not in samples:
        samples.append(lu_dates[-1])
    RAW.mkdir(parents=True, exist_ok=True)

    manifest = {"fetched_at": date.today().isoformat(), "sample_every_sessions": SAMPLE_EVERY,
                "samples": [], "gaps": []}
    for i, d in enumerate(samples):
        out = RAW / f"dc_member_{d}.csv"
        if out.exists() and out.stat().st_size > 100:
            manifest["samples"].append({"date": d, "rows": int(pd.read_csv(out).shape[0]), "cached": True})
            continue
        frames, offset = [], 0
        try:
            while True:
                df = pro.query("dc_member", trade_date=d, offset=offset)
                if df is None or len(df) == 0:
                    break
                frames.append(df)
                offset += len(df)
                if len(df) < PAGE:
                    break
                time.sleep(0.12)
        except Exception as exc:  # noqa: BLE001 - 单日失败记 gaps 继续
            manifest["gaps"].append({"date": d, "error": str(exc)[:80]})
            print(f"  {d} FAIL: {exc}")
            continue
        if not frames:
            manifest["gaps"].append({"date": d, "error": "empty"})
            continue
        full = pd.concat(frames, ignore_index=True)
        atomic_write_csv(out, full)
        manifest["samples"].append({"date": d, "rows": int(len(full)),
                                    "concepts": int(full["ts_code"].nunique())})
        print(f"  [{i+1}/{len(samples)}] {d}: {len(full)} rows, {full['ts_code'].nunique()} concepts")
    (RAW / "manifest_concept.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成: {len(manifest['samples'])} 快照, gaps={len(manifest['gaps'])}")


if __name__ == "__main__":
    main()
