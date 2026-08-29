#!/usr/bin/env python3
"""交互因子构建器 — 两输入日内秩乘积 (R63, 候选 #3).

factor(D, 票) = pct_rank(A) × pct_rank(−B)，A/B 均为 (signal_date, ts_code, factor)
形状的因子 csv 或 court 表数值列指定的日内横截面秩百分位 (秩在**日内**计算 —
跨日不可比是横截面因子的基本纪律)。

负号语义: `--neg-b` 声明「B 越小越好」的方向变换 (R63 结构假设: 个股延续力
在非过热行业更有效 → A=trigger_strength, B=industry_momentum, neg-b)。
方向在**候选名**中预注册 (build 前声明), 本工具不加任何自由参数。

缺行 (A 有 B 无) → NaN 行如实输出并计数, 不冒充中性值。

用法 (uv run, 仓库根):
  uv run python scripts/build_interaction_factor.py \
      --a-col trigger_strength \
      --b-csv data/research/btst_court/factors/industry_momentum_v0.csv \
      --neg-b --out data/research/btst_court/factors/strength_x_neg_indmom_v0.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COURT = REPO_ROOT / "data/research/btst_court/event_tables/event_table_v1.csv.gz"


class InteractionFactorError(RuntimeError):
    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _typed(code: str, details: dict | None = None):
    raise InteractionFactorError(code, details)


def _load_side(spec: str, court_path: Path | None) -> pd.DataFrame:
    """spec: 'col:NAME' (court 表列) 或 csv 路径 (signal_date,ts_code,factor)。"""
    if spec.startswith("col:"):
        column = spec[4:]
        if not court_path or not court_path.is_file():
            _typed("court_table_not_found", {"path": str(court_path)})
        frame = pd.read_csv(court_path, dtype={"signal_date": str})
        if column not in frame.columns:
            _typed("column_missing", {"column": column})
        out = frame[["signal_date", "ts_code", column]].rename(
            columns={column: "value"})
        out["ts_code"] = out["ts_code"].astype(str)
        return out
    path = Path(spec)
    if not path.is_file():
        _typed("factor_csv_not_found", {"path": spec})
    frame = pd.read_csv(path, dtype={"signal_date": str, "ts_code": str})
    for col in ("signal_date", "ts_code", "factor"):
        if col not in frame.columns:
            _typed("factor_csv_missing_columns", {"missing": [col], "path": spec})
    return frame.rename(columns={"factor": "value"})[
        ["signal_date", "ts_code", "value"]]


def build_interaction(
    *, a_spec: str, b_spec: str, court_path: Path | None, neg_b: bool,
) -> tuple[pd.DataFrame, dict]:
    a = _load_side(a_spec, court_path)
    b = _load_side(b_spec, court_path)
    merged = a.merge(b, on=["signal_date", "ts_code"], how="outer",
                     suffixes=("_a", "_b"), indicator=True)
    both = merged[merged["_merge"] == "both"].copy()
    both_only = int((merged["_merge"] != "both").sum())
    both = both.dropna(subset=["value_a", "value_b"])
    both["value_b_signed"] = -both["value_b"] if neg_b else both["value_b"]

    def pct_rank_series(sub: pd.DataFrame) -> pd.Series:
        return sub.rank(pct=True)

    both["rank_a"] = both.groupby("signal_date")["value_a"].transform(pct_rank_series)
    both["rank_b"] = both.groupby("signal_date")["value_b_signed"].transform(pct_rank_series)
    both["factor"] = both["rank_a"] * both["rank_b"]
    rows = both[["signal_date", "ts_code", "factor"]].reset_index(drop=True)
    summary = {
        "rows": int(len(rows)),
        "dropped_outer_rows": both_only,
        "neg_b": neg_b,
        "signal_days": int(rows["signal_date"].nunique()),
    }
    return rows, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--a-spec", required=True,
                        help="'col:NAME' (court 列) 或因子 csv 路径")
    parser.add_argument("--b-spec", required=True)
    parser.add_argument("--court", default=str(DEFAULT_COURT))
    parser.add_argument("--neg-b", action="store_true",
                        help="B 取负号 (方向在候选名中预注册)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    try:
        rows, summary = build_interaction(
            a_spec=args.a_spec, b_spec=args.b_spec,
            court_path=Path(args.court), neg_b=args.neg_b)
    except InteractionFactorError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(out, index=False)
    print(json.dumps({"ok": True, **summary, "out": str(out)},
                     ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
