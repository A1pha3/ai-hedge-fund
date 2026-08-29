#!/usr/bin/env python3
"""封板质量证据审计 (R71, 只读) — challenger 候选 #1 的构建有效性门.

被检对象: seal_quality_v0 (R65 三腿等权秩平均; R66 因子级三重稳健门 qualifies;
R70 杠杆级近线 deferred)。R66 证明的是统计稳健, 从未证明的是**构建有效性**:
PIT 隔离只有 docstring 声明、腿语义只做过非正式首查、覆盖缺口 1395/1464 的
偏差从未量化。本工具在 owner 提案/重评消费该信号前补上这四块:

    1. pit_isolation   — 存储因子逐日独立重算 (rank-pct 用独立实现, 不复用
                         构建器代码) 与存储值精确比对: 逐日值可仅由 lu_D
                         复现 = 因子(D) 是 lu_D 的函数 (隔离性的经验证明;
                         结构保证另有 hermetic 毒化测试钉死)
    2. leg_semantics   — 三腿数值形状 (first_time∈[0,160000] HHMMSS /
                         open_times≥0 / fd_amount≥0) + 池化方向探测
                         (factor vs −first_time/−open_times/+fd_amount 同号)
    3. coverage        — 对齐宇宙逐行定因 (lu_file_missing / not_in_lu_universe
                         / all_legs_missing / unclassified) + covered vs
                         uncovered 净收益差的天聚类 bootstrap CI (per-call
                         seeded, R13 纪律) — 显著偏倚 → IC 解释须带选择效应警告
    4. ic_crosscheck   — 独立 Spearman 实现复算因子级日度 IC, 与工厂评估
                         报告值交叉 (±0.005); 评估机器口径漂移在此暴露

verdict: evidence_solid / coverage_bias_detected / defects_found。
只读: 不写任何数据面文件; 零时间戳输出 (同输入逐字节同输出)。

用法 (uv run, 仓库根; 需本地数据资产, 验证一律走 hermetic 测试):
  uv run python scripts/audit_seal_quality_evidence.py
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from winrate_payoff_decomposition import (  # noqa: E402
    production_aligned,
    net_returns,
)

REPO_ROOT = _SCRIPTS.parent
DEFAULT_COURT = REPO_ROOT / "data/research/btst_court/event_tables/event_table_v1.csv.gz"
DEFAULT_LU_DIR = REPO_ROOT / "data/research/btst_court/raw/limit_up"
DEFAULT_FACTOR = REPO_ROOT / "data/research/btst_court/factors/seal_quality_v0.csv"
DEFAULT_FACTORY_EVAL = REPO_ROOT / "data/reports/factor_factory/factor_eval_seal_quality_v0_20260829.json"
AUDIT_SEED = 20260830        # per-call seeded (R13): 同输入恒同输出
BOOT_REPS = 4000
IC_TOL = 0.005
MIN_IC_NAMES = 5             # 与 factor_factory_eval.MIN_IC_NAMES 同口径
MAX_FIRST_TIME = 160000      # HHMMSS 形状上界 (15:00 收盘 + 余量)


class SealAuditError(RuntimeError):
    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _typed(code: str, details: dict | None = None):
    raise SealAuditError(code, details)


# ---------------------------------------------------------------------------
# 独立数值基元 (不复用构建器/工厂的 rank / spearman 实现 — 被审对象不能自证)
# ---------------------------------------------------------------------------

def rank_pct_average(values: list[float | None]) -> list[float | None]:
    """平均秩百分比 (pandas rank(pct=True) 语义的独立实现): 并列取平均
    1-based 秩再除以非空数; None/NaN → None。"""
    valid = [i for i, v in enumerate(values)
             if v is not None and not (isinstance(v, float) and math.isnan(v))]
    out: list[float | None] = [None] * len(values)
    if not valid:
        return out
    keyed = sorted(valid, key=lambda i: values[i])
    ranks: dict[int, float] = {}
    i = 0
    while i < len(keyed):
        j = i
        while j + 1 < len(keyed) and values[keyed[j + 1]] == values[keyed[i]]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[keyed[k]] = avg
        i = j + 1
    n = len(valid)
    for idx in valid:
        out[idx] = ranks[idx] / n
    return out


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return float("nan")
    return sxy / math.sqrt(sxx * syy)


def spearman_independent(xs: list[float], ys: list[float]) -> float:
    """Spearman = 秩向量的 Pearson (独立实现)。"""
    rx = rank_pct_average(xs)
    ry = rank_pct_average(ys)
    pairs = [(a, b) for a, b in zip(rx, ry)
             if a is not None and b is not None]
    if len(pairs) < 2:
        return float("nan")
    return _pearson([p[0] for p in pairs], [p[1] for p in pairs])


# ---------------------------------------------------------------------------
# 逐日独立重算 (腿读取走独立路径, 不 import 构建器)
# ---------------------------------------------------------------------------

def _day_legs_independent(path: Path) -> dict[str, dict[str, float | None]]:
    if not path.is_file():
        _typed("lu_snapshot_not_found", {"path": str(path)})
    frame = pd.read_csv(path, dtype={"ts_code": str})
    missing = [c for c in ("first_time", "open_times", "fd_amount") if c not in frame.columns]
    if missing:
        _typed("lu_snapshot_missing_columns", {"path": str(path), "missing": missing})
    out: dict[str, dict[str, float | None]] = {}
    for ts_code, ft, ot, fd in zip(
        frame["ts_code"].astype(str),
        pd.to_numeric(frame["first_time"], errors="coerce"),
        pd.to_numeric(frame["open_times"], errors="coerce"),
        pd.to_numeric(frame["fd_amount"], errors="coerce"),
    ):
        out[ts_code] = {
            "first_time": None if pd.isna(ft) else float(ft),
            "open_times": None if pd.isna(ot) else float(ot),
            "fd_amount": None if pd.isna(fd) else float(fd),
        }
    return out


def recompute_day_factor(path: Path) -> dict[str, float]:
    """单日快照 → {ts_code: factor} (方向变换 + 逐腿独立 rank-pct + 可得腿均值)。"""
    legs = _day_legs_independent(path)
    codes = list(legs)
    cols = {
        "first_time": [legs[c]["first_time"] for c in codes],
        "open_times": [legs[c]["open_times"] for c in codes],
        "fd_amount": [legs[c]["fd_amount"] for c in codes],
    }
    ranked = {
        "first_time": rank_pct_average([-v if v is not None else None for v in cols["first_time"]]),
        "open_times": rank_pct_average([-v if v is not None else None for v in cols["open_times"]]),
        "fd_amount": rank_pct_average(cols["fd_amount"]),
    }
    factors: dict[str, float] = {}
    for i, c in enumerate(codes):
        vals = [ranked[leg][i] for leg in ranked if ranked[leg][i] is not None]
        if vals:
            factors[c] = sum(vals) / len(vals)
    return factors


# ---------------------------------------------------------------------------
# 四条审计腿
# ---------------------------------------------------------------------------

def audit_pit_isolation(factor_csv: Path, lu_dir: Path) -> dict:
    """存储因子逐日独立重算比对 — 可仅由 lu_D 复现 = 隔离性的经验证明。"""
    fac = pd.read_csv(factor_csv, dtype={"signal_date": str, "ts_code": str})
    stored: dict[str, dict[str, float]] = {}
    for day, ts, v in zip(fac["signal_date"], fac["ts_code"], fac["factor"]):
        stored.setdefault(str(day), {})[str(ts)] = float(v)
    checked_days = 0
    checked_rows = 0
    mismatches: list[dict] = []
    missing_lu: list[str] = []
    for day in sorted(stored):
        path = lu_dir / f"lu_{day}.csv"
        if not path.is_file():
            missing_lu.append(day)
            continue
        recomputed = recompute_day_factor(path)
        checked_days += 1
        for ts, v in stored[day].items():
            checked_rows += 1
            rv = recomputed.get(ts)
            if rv is None or abs(rv - v) > 1e-9:
                mismatches.append({"day": day, "ts": ts, "stored": v, "recomputed": rv})
    extra_rows = 0  # lu_D 有而存储无的行 (合法: 三腿全缺被构建器丢弃)
    for day in sorted(stored):
        path = lu_dir / f"lu_{day}.csv"
        if not path.is_file():
            continue
        recomputed = recompute_day_factor(path)
        extra_rows += len(set(recomputed) - set(stored[day]))
    return {
        "days_checked": checked_days,
        "rows_checked": checked_rows,
        "mismatch_rows": mismatches[:20],
        "mismatch_count": len(mismatches),
        "missing_lu_days": missing_lu[:20],
        "missing_lu_count": len(missing_lu),
        "extra_recomputable_rows": extra_rows,
        "ok": not mismatches and not missing_lu,
    }


def audit_leg_semantics(factor_csv: Path, lu_dir: Path, days: list[str]) -> dict:
    """三腿数值形状 + 池化方向探测。

    方向探测比较的是**存储因子** (下游消费的工件) 与原始腿 — 重算因子由腿
    构造而来方向恒成立 (循环论证), 对存储工件无判别力; 存储因子若以翻转
    方向构建 (或被人改写) 在此暴露。
    """
    fac = pd.read_csv(factor_csv, dtype={"signal_date": str, "ts_code": str})
    fac["factor"] = pd.to_numeric(fac["factor"], errors="coerce")
    stored: dict[str, dict[str, float]] = {}
    for day, ts, v in zip(fac["signal_date"], fac["ts_code"], fac["factor"]):
        if not pd.isna(v):
            stored.setdefault(str(day), {})[str(ts)] = float(v)
    malformed = {"first_time": 0, "open_times": 0, "fd_amount": 0}
    rows_total = 0
    fac_all: list[float] = []
    ft_all: list[float] = []
    ot_all: list[float] = []
    fd_all: list[float] = []
    days_probed = 0
    for day in days:
        path = lu_dir / f"lu_{day}.csv"
        if not path.is_file() or day not in stored:
            continue
        legs = _day_legs_independent(path)
        days_probed += 1
        rows_total += len(legs)
        for ts, l in legs.items():
            ft, ot, fd = l["first_time"], l["open_times"], l["fd_amount"]
            if ft is not None and not (0 <= ft <= MAX_FIRST_TIME):
                malformed["first_time"] += 1
            if ot is not None and ot < 0:
                malformed["open_times"] += 1
            if fd is not None and fd < 0:
                malformed["fd_amount"] += 1
            if ts in stored[day]:
                fac_all.append(stored[day][ts])
                ft_all.append(ft if ft is not None else float("nan"))
                ot_all.append(ot if ot is not None else float("nan"))
                fd_all.append(fd if fd is not None else float("nan"))
    # 方向探测: 因子高 ⇔ 首封早/炸板少/封单大 (存储工件 vs 原始腿)
    rho_ft = spearman_independent(fac_all, ft_all)
    rho_ot = spearman_independent(fac_all, ot_all)
    rho_fd = spearman_independent(fac_all, fd_all)
    direction_ok = (rho_ft < 0 and rho_ot < 0 and rho_fd > 0)
    return {
        "days_probed": days_probed,
        "rows_total": rows_total,
        "malformed_legs": malformed,
        "pooled_spearman": {
            "factor_vs_first_time": rho_ft,
            "factor_vs_open_times": rho_ot,
            "factor_vs_fd_amount": rho_fd,
        },
        "direction_ok": bool(direction_ok),
        "ok": bool(direction_ok and sum(malformed.values()) == 0),
    }


def classify_coverage(factor_csv: Path, court_path: Path, lu_dir: Path) -> dict:
    """对齐宇宙逐行定因 + covered vs uncovered 净收益差的天聚类 bootstrap。"""
    ev = pd.read_csv(court_path, dtype={"signal_date": str})
    aligned = production_aligned(ev)
    fac = pd.read_csv(factor_csv, dtype={"signal_date": str, "ts_code": str})
    fac["factor"] = pd.to_numeric(fac["factor"], errors="coerce")
    valid_fac = fac.dropna(subset=["factor"])
    covered_keys = {(str(d), str(t)) for d, t in zip(valid_fac["signal_date"], valid_fac["ts_code"])}

    lu_days: dict[str, dict[str, dict[str, float | None]] | None] = {}
    counts = {"covered": 0, "lu_file_missing": 0, "not_in_lu_universe": 0,
              "all_legs_missing": 0, "unclassified": 0}
    cov_rets: list[float] = []
    cov_days: list[str] = []
    unc_rets: list[float] = []
    unc_days: list[str] = []
    for row in aligned.itertuples(index=False):
        day = str(getattr(row, "signal_date"))
        ts = str(getattr(row, "ts_code"))
        gross = getattr(row, "gross_ret_t10")
        net = net_returns([gross])[0]
        if net is None or (isinstance(net, float) and math.isnan(net)):
            continue
        key = (day, ts)
        if key in covered_keys:
            counts["covered"] += 1
            cov_rets.append(float(net))
            cov_days.append(day)
            continue
        if day not in lu_days:
            path = lu_dir / f"lu_{day}.csv"
            lu_days[day] = None if not path.is_file() else _day_legs_independent(path)
        snap = lu_days[day]
        if snap is None:
            counts["lu_file_missing"] += 1
        elif ts not in snap:
            counts["not_in_lu_universe"] += 1
        elif all(snap[ts][leg] is None for leg in ("first_time", "open_times", "fd_amount")):
            counts["all_legs_missing"] += 1
        else:
            # 快照内有有效腿却无因子行 = 构建器丢行, 只能是缺陷
            counts["unclassified"] += 1
        unc_rets.append(float(net))
        unc_days.append(day)

    diff_ci = _clustered_diff_ci(cov_rets, cov_days, unc_rets, unc_days)
    cov_e = sum(cov_rets) / len(cov_rets) if cov_rets else None
    unc_e = sum(unc_rets) / len(unc_rets) if unc_rets else None
    cov_win = sum(1 for r in cov_rets if r > 0) / len(cov_rets) if cov_rets else None
    unc_win = sum(1 for r in unc_rets if r > 0) / len(unc_rets) if unc_rets else None
    ci_lo = diff_ci["ci90_low"]
    ci_hi = diff_ci["ci90_high"]
    bias_significant = bool(
        cov_rets and unc_rets and ci_lo is not None and ci_hi is not None
        and (ci_lo > 0 or ci_hi < 0)
    )
    return {
        "aligned_rows_with_net": counts["covered"] + sum(
            v for k, v in counts.items() if k not in ("covered", "unclassified")),
        "classification": counts,
        "covered": {"n": len(cov_rets), "expectancy": cov_e, "winrate": cov_win},
        "uncovered": {"n": len(unc_rets), "expectancy": unc_e, "winrate": unc_win},
        "diff_covered_minus_uncovered": {
            **diff_ci,
            "bias_significant": bias_significant,
        },
        "ok": not bias_significant and counts["unclassified"] == 0,
    }


def _clustered_diff_ci(
    a_rets: list[float], a_days: list[str],
    b_rets: list[float], b_days: list[str],
) -> dict:
    """mean(A) − mean(B) 的天聚类 bootstrap CI90 (per-call seeded, R13)。"""
    def _pools(rets: list[float], days: list[str]) -> list[np.ndarray]:
        by: dict[str, list[float]] = {}
        for r, d in zip(rets, days):
            by.setdefault(d, []).append(r)
        return [np.asarray(v) for v in by.values()]
    pa, pb = _pools(a_rets, a_days), _pools(b_rets, b_days)
    if not pa or not pb or len(set(a_days)) < 2 or len(set(b_days)) < 2:
        return {"mean_diff": None, "ci90_low": None, "ci90_high": None}
    rng = np.random.default_rng(AUDIT_SEED)
    ka, kb = len(pa), len(pb)
    reps = np.empty(BOOT_REPS)
    for i in range(BOOT_REPS):
        ia = rng.integers(0, ka, ka)
        ib = rng.integers(0, kb, kb)
        ma = np.concatenate([pa[j] for j in ia]).mean()
        mb = np.concatenate([pb[j] for j in ib]).mean()
        reps[i] = ma - mb
    lo, hi = (float(v) for v in np.quantile(reps, [0.05, 0.95]))
    obs = float(np.concatenate(pa).mean() - np.concatenate(pb).mean())
    return {"mean_diff": obs, "ci90_low": lo, "ci90_high": hi}


def audit_ic_crosscheck(factor_csv: Path, court_path: Path,
                        factory_eval_json: Path) -> dict:
    """独立 Spearman 复算日度 IC, 与工厂评估报告值交叉 (±IC_TOL)。"""
    ev = pd.read_csv(court_path, dtype={"signal_date": str})
    aligned = production_aligned(ev)
    fac = pd.read_csv(factor_csv, dtype={"signal_date": str, "ts_code": str})
    work = aligned.merge(
        fac.rename(columns={"factor": "cand"})[["signal_date", "ts_code", "cand"]],
        on=["signal_date", "ts_code"], how="inner")
    work["net"] = net_returns(work["gross_ret_t10"].tolist())
    work = work.dropna(subset=["cand", "net"])
    daily: list[float] = []
    days_used = 0
    for _, grp in work.groupby("signal_date"):
        if len(grp) < MIN_IC_NAMES:
            continue
        rho = spearman_independent(grp["cand"].tolist(), grp["net"].tolist())
        if not math.isnan(rho):
            daily.append(rho)
            days_used += 1
    ic_mean = sum(daily) / len(daily) if daily else None
    factory_ic = None
    if factory_eval_json.is_file():
        payload = json.loads(factory_eval_json.read_text(encoding="utf-8"))
        factory_ic = (payload.get("payload", payload).get("daily_ic", {})
                      .get("ic_mean"))
        if factory_ic is not None:
            factory_ic = float(factory_ic)
    consistent = (ic_mean is not None and factory_ic is not None
                  and abs(ic_mean - factory_ic) <= IC_TOL)
    return {
        "ic_mean_independent": ic_mean,
        "ic_days": days_used,
        "factory_eval_json": str(factory_eval_json.name),
        "ic_mean_factory": factory_ic,
        "abs_delta": (abs(ic_mean - factory_ic)
                      if ic_mean is not None and factory_ic is not None else None),
        "tolerance": IC_TOL,
        "ok": bool(consistent),
    }


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------

def run_audit(*, court_path: Path, lu_dir: Path, factor_csv: Path,
              factory_eval_json: Path) -> dict:
    if not factor_csv.is_file():
        _typed("factor_csv_not_found", {"path": str(factor_csv)})
    if not lu_dir.is_dir():
        _typed("lu_dir_not_found", {"path": str(lu_dir)})
    fac_days = sorted(set(pd.read_csv(factor_csv, dtype={"signal_date": str})["signal_date"].astype(str)))
    isolation = audit_pit_isolation(factor_csv, lu_dir)
    semantics = audit_leg_semantics(factor_csv, lu_dir, fac_days)
    coverage = classify_coverage(factor_csv, court_path, lu_dir)
    crosscheck = audit_ic_crosscheck(factor_csv, court_path, factory_eval_json)
    defects: list[str] = []
    if not isolation["ok"]:
        defects.append("pit_isolation")
    if not semantics["ok"]:
        defects.append("leg_semantics")
    if not crosscheck["ok"]:
        defects.append("ic_crosscheck")
    if defects:
        verdict = "defects_found"
    elif not coverage["ok"]:
        verdict = "coverage_bias_detected"
    else:
        verdict = "evidence_solid"
    return {
        "candidate": str(factor_csv.name),
        "verdict": verdict,
        "defects": defects,
        "pit_isolation": isolation,
        "leg_semantics": semantics,
        "coverage": coverage,
        "ic_crosscheck": crosscheck,
        "discipline": "纯诊断 (宪法 #2); 构建审计不改变预注册规格 — 改腿/改权=新候选重注册",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court", default=str(DEFAULT_COURT))
    parser.add_argument("--lu-dir", default=str(DEFAULT_LU_DIR))
    parser.add_argument("--factor-csv", default=str(DEFAULT_FACTOR))
    parser.add_argument("--factory-eval-json", default=str(DEFAULT_FACTORY_EVAL))
    args = parser.parse_args()
    try:
        payload = run_audit(
            court_path=Path(args.court), lu_dir=Path(args.lu_dir),
            factor_csv=Path(args.factor_csv),
            factory_eval_json=Path(args.factory_eval_json))
    except SealAuditError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False))
    return 0 if payload["verdict"] == "evidence_solid" else 2


if __name__ == "__main__":
    raise SystemExit(main())
