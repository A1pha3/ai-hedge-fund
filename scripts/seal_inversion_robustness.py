#!/usr/bin/env python3
"""封板反转候选的稳健性三连诊断 (R66, 只读).

被检对象: 换手板偏好候选 (seal_inverted = −封板质量复合因子), R65 发现
(IC=−0.106/单调性 −0.90 的反转形态)。**提交 challenger 预注册提案前的三重
稳健门 (合取判定, 镜像 R15 Kelly 评估纪律——单看一项稳定是误导)**:

  1. split_half   — 信号日按时间对半切, 两半日度 IC 同号 (时段翻转即死)
  2. winsorized   — net_t10 按 1%/99% 分位 winsorize 后整体 IC 同号 (离群驱动即死)
  3. orthogonal   — 对主因子 (trigger_strength) 逐日秩回归取残差后 IC 同号
                    (只是主因子影子即死 — 增量是存在价值的唯一理由)

三项全 true → verdict=qualifies (够格提交 owner 预注册提案); 任一 false →
verdict=rejected (含逐项明细)。只读: 不写任何数据面文件。

用法 (uv run, 仓库根):
  uv run python scripts/seal_inversion_robustness.py \
      --seal-csv data/research/btst_court/factors/seal_quality_v0.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from winrate_payoff_decomposition import (  # noqa: E402
    cluster_boot_ci_low,
    net_returns,
    production_aligned,
)

REPO_ROOT = _SCRIPTS.parent
DEFAULT_COURT = REPO_ROOT / "data/research/btst_court/event_tables/event_table_v1.csv.gz"
DEFAULT_SEAL = REPO_ROOT / "data/research/btst_court/factors/seal_quality_v0.csv"
WINSOR_Q = 0.01


class RobustnessError(RuntimeError):
    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _typed(code: str, details: dict | None = None):
    raise RobustnessError(code, details)


def daily_ics(df: pd.DataFrame, value_col: str) -> pd.Series:
    """日度横截面 Spearman IC (value vs net_t10), ≥5 票的日。"""
    out = {}
    for day, grp in df.groupby("signal_date"):
        if len(grp) < 5:
            continue
        ic = grp[value_col].rank().corr(grp["net_t10"].rank())
        if pd.notna(ic):
            out[str(day)] = float(ic)
    return pd.Series(out)


def _orthogonalize_within_day(df: pd.DataFrame, value_col: str,
                              main_col: str) -> pd.Series:
    """逐日秩回归残差: value 对 main 的线性残差 (秩空间, 消主因子)。"""
    out = pd.Series(index=df.index, dtype=float)
    for day, grp in df.groupby("signal_date"):
        x = grp[main_col].rank(pct=True)
        y = grp[value_col].rank(pct=True)
        if x.nunique() < 2 or y.nunique() < 2:
            out.loc[grp.index] = y
            continue
        beta = x.cov(y) / x.var()
        e = y - (y.mean() + beta * (x - x.mean()))
        if e.std() < 1e-10:
            # 浮点尘埃残差 (候选与主因子共线): 无离散度 = 无正交信息, 置零
            # (置零后该日 rank 为全并列, corr=NaN 被跳过)
            out.loc[grp.index] = 0.0
        else:
            out.loc[grp.index] = e
    return out


def run_triage(*, court_path: Path, seal_csv: Path,
               main_col: str = "trigger_strength") -> dict:
    if not court_path.is_file():
        _typed("court_table_not_found", {"path": str(court_path)})
    if not seal_csv.is_file():
        _typed("seal_csv_not_found", {"path": str(seal_csv)})
    ev = pd.read_csv(court_path, dtype={"signal_date": str})
    aligned = production_aligned(ev)
    if main_col not in aligned.columns:
        _typed("main_column_missing", {"column": main_col})
    seal = pd.read_csv(seal_csv, dtype={"signal_date": str, "ts_code": str})
    work = aligned.merge(seal, on=["signal_date", "ts_code"], how="left")
    work["seal_inverted"] = -work["factor"]          # 候选方向: 换手板偏好
    work["net_t10"] = net_returns(work["gross_ret_t10"].tolist())
    usable = work.dropna(subset=["seal_inverted", "net_t10", main_col])
    if len(usable) < 50:
        _typed("usable_rows_too_few", {"rows": int(len(usable))})

    # 1. split-half (按信号日时间对半)
    ics = daily_ics(usable, "seal_inverted")
    days = sorted(ics.index)
    half = len(days) // 2
    ic_h1, ic_h2 = ics.iloc[:half].mean(), ics.iloc[half:].mean()
    split_half = bool(ic_h1 > 0 and ic_h2 > 0)

    # 2. 离群/极端日敏感: ①returns 1%/99% winsorize 后 IC 同号
    #    (因子列不变, 只截尾收益列——传 "net_t10" 会自相关恒 1.0, false-pass);
    #    ②日度 IC 中位数 > 0 (少数极端日撑起整体均值 = 集中依赖, 判死)
    lo, hi = usable["net_t10"].quantile(WINSOR_Q), usable["net_t10"].quantile(1 - WINSOR_Q)
    clipped = usable["net_t10"].clip(lo, hi)
    ic_raw = ics.mean()
    ic_winsor = daily_ics(usable.assign(net_t10=clipped), "seal_inverted").mean()
    ic_median = float(ics.median())
    winsorized = bool(ic_winsor > 0 and ic_median > 0)

    # 3. 正交增量 IC (对主因子逐日秩残差)
    work2 = usable.copy()
    work2["resid"] = _orthogonalize_within_day(work2, "seal_inverted", main_col)
    resid_ics = daily_ics(work2.dropna(subset=["resid"]), "resid")
    # 完全共线 → 残差为浮点尘埃 (秩随机): 有效日不足下限 = 无正交信息, 判 false
    MIN_ORTH_DAYS = 10
    ic_orth = float(resid_ics.mean()) if len(resid_ics) else float("nan")
    orthogonal = bool(len(resid_ics) >= MIN_ORTH_DAYS and ic_orth > 0)

    # 主因子与候选的日内秩相关 (披露用)
    corr = usable.groupby("signal_date").apply(
        lambda g: g["seal_inverted"].rank().corr(g[main_col].rank())
        if len(g) >= 5 else pd.NA, include_groups=False).dropna()
    qualifies = split_half and winsorized and orthogonal
    return {
        "candidate": "seal_inverted (换手板偏好)",
        "rows": int(len(usable)),
        "signal_days": int(usable["signal_date"].nunique()),
        "ic_mean": float(ic_raw),
        "checks": {
            "split_half": {"ic_first_half": float(ic_h1), "ic_second_half": float(ic_h2),
                           "same_sign": split_half},
            "winsorized": {"ic_winsorized": float(ic_winsor),
                           "ic_median": ic_median,
                           "same_sign": winsorized,
                           "clip_bounds": [float(lo), float(hi)]},
            "orthogonal_vs_main": {"ic_orthogonal": float(ic_orth),
                                   "valid_days": int(len(resid_ics)),
                                   "still_positive": orthogonal,
                                   "mean_rank_corr_with_main": float(corr.mean())},
        },
        "verdict": "qualifies" if qualifies else "rejected",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court", default=str(DEFAULT_COURT))
    parser.add_argument("--seal-csv", default=str(DEFAULT_SEAL))
    args = parser.parse_args()
    try:
        payload = run_triage(court_path=Path(args.court), seal_csv=Path(args.seal_csv))
    except RobustnessError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=1))
    return 0 if payload["verdict"] == "qualifies" else 2


if __name__ == "__main__":
    raise SystemExit(main())
