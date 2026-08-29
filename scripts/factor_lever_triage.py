#!/usr/bin/env python3
"""候选因子杠杆级 triage (R68, 只读) — challenger 预注册提案的决策级门。

因子级稳健 (R66 三重门: split-half/winsorize/正交) 只证明横截面信息存在;
可部署杠杆还必须证明「把信息变成持仓差异」之后经济增量稳定。本工具对门内
(trigger_strength ≥ GATE_TS, 现行生产阈值) 的三种杠杆各跑一个合取判定:

    uplift > 0  ∧  split-half 双半 uplift 严格同正  ∧  日度聚类 bootstrap
    (per-call seeded, R13 纪律——与进程历史/行序无关) CI90 下界 > 0

levers:
    topk_composite  — 门内按 日内秩均值(strength, inverted_factor) 取前 K
    topk_factor     — 门内按 inverted_factor 取前 K
    gate_tilt       — 门内再留 inverted_factor 日内前 KEEP_Q 分位 (基线=门内全过)

任一杠杆全过 → challenger_ready (够格起草预注册提案, owner 决策点);
全部不过 → deferred (提案缓议; 重评触发器 = court 数据增长后重跑本工具)。
只读: 不写任何数据面文件。

用法 (uv run, 仓库根):
  uv run python scripts/factor_lever_triage.py \
      --factor-csv data/research/btst_court/factors/seal_quality_v0.csv \
      --factor-direction invert
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from winrate_payoff_decomposition import (  # noqa: E402
    BOOT_SEED,
    net_returns,
    production_aligned,
)
from factor_factory_eval import _register_candidate  # noqa: E402  (单一实现)

REPO_ROOT = _SCRIPTS.parent
DEFAULT_COURT = REPO_ROOT / "data/research/btst_court/event_tables/event_table_v1.csv.gz"
DEFAULT_FACTOR = REPO_ROOT / "data/research/btst_court/factors/seal_quality_v0.csv"
DEFAULT_TRIAGE_REGISTRY = (REPO_ROOT
                           / "data/reports/factor_factory/triage_registry.jsonl")
GATE_TS = 0.50          # 现行生产阈值 (daily_action._MIN_TRIGGER_STRENGTH)
TOP_K = 3
KEEP_Q = 0.5
BOOT_REPS = 4000
CI_LO, CI_HI = 0.05, 0.95
MIN_DAY_ROWS = 5
MIN_USABLE_ROWS = 50


class LeverTriageError(RuntimeError):
    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _typed(code: str, details: dict | None = None):
    raise LeverTriageError(code, details)


def _load_factor_work(factor_csv: Path, factor_direction: str):
    if factor_direction not in ("invert", "straight"):
        _typed("invalid_factor_direction", {"value": factor_direction})
    fac = pd.read_csv(factor_csv, dtype={"signal_date": str, "ts_code": str})
    for col in ("signal_date", "ts_code", "factor"):
        if col not in fac.columns:
            _typed("factor_csv_column_missing", {"column": col})
    if fac.duplicated(["signal_date", "ts_code"]).any():
        # merge 扇出会伪造样本量 — 拒绝而非静默重复计数
        _typed("factor_csv_duplicate_keys")
    fac = fac.rename(columns={"factor": "cand"}).copy()
    if factor_direction == "invert":
        fac["cand"] = -fac["cand"]
    return fac[["signal_date", "ts_code", "cand"]]


def _gate_work(court_path: Path, factor_csv: Path, factor_direction: str) -> pd.DataFrame:
    if not court_path.is_file():
        _typed("court_table_not_found", {"path": str(court_path)})
    if not factor_csv.is_file():
        _typed("factor_csv_not_found", {"path": str(factor_csv)})
    ev = pd.read_csv(court_path, dtype={"signal_date": str})
    aligned = production_aligned(ev)
    fac = _load_factor_work(factor_csv, factor_direction)
    work = aligned.merge(fac, on=["signal_date", "ts_code"], how="inner")
    work["net"] = net_returns(work["gross_ret_t10"].tolist())
    work = work.dropna(subset=["cand", "net", "trigger_strength"])
    gate = work[work["trigger_strength"] >= GATE_TS].copy()
    if len(work) < MIN_USABLE_ROWS:
        _typed("usable_rows_too_few", {"rows": int(len(work))})
    gate["r_strength"] = gate.groupby("signal_date")["trigger_strength"].rank(pct=True)
    gate["r_cand"] = gate.groupby("signal_date")["cand"].rank(pct=True)
    gate["composite"] = (gate["r_strength"] + gate["r_cand"]) / 2
    return gate


def _day_sets(gate: pd.DataFrame) -> list[dict]:
    """逐日 (基线, 各杠杆) 的 net 值集合。少于 MIN_DAY_ROWS 的日剔除。"""
    days = []
    for day, grp in gate.groupby("signal_date"):
        if len(grp) < MIN_DAY_ROWS:
            continue
        k = min(TOP_K, len(grp))
        base_topk = grp.nlargest(k, "trigger_strength")["net"].to_numpy()
        thr = grp["cand"].quantile(1 - KEEP_Q)
        days.append({
            "day": day,
            "topk_composite": (
                base_topk,
                grp.nlargest(k, "composite")["net"].to_numpy(),
            ),
            "topk_factor": (base_topk, grp.nlargest(k, "cand")["net"].to_numpy()),
            "gate_tilt": (grp["net"].to_numpy(), grp.loc[grp["cand"] >= thr, "net"].to_numpy()),
        })
    return days


def _uplift_stats(days: list[dict], lever: str) -> dict:
    base = np.concatenate([d[lever][0] for d in days])
    lev = np.concatenate([d[lever][1] for d in days])
    uplift = float(lev.mean() - base.mean())
    half = len(days) // 2
    halves = []
    for part in (days[:half], days[half:]):
        b = np.concatenate([d[lever][0] for d in part])
        l = np.concatenate([d[lever][1] for d in part])
        halves.append(float(l.mean() - b.mean()))
    # 聚类 bootstrap: 日为重采样单位, per-call seeded (R13)
    bs = np.array([d[lever][0] for d in days], dtype=object)
    ls = np.array([d[lever][1] for d in days], dtype=object)
    b_sums = np.array([x.sum() for x in bs])
    b_cnts = np.array([len(x) for x in bs])
    l_sums = np.array([x.sum() for x in ls])
    l_cnts = np.array([len(x) for x in ls])
    rng = np.random.default_rng(BOOT_SEED)
    idx = rng.integers(0, len(days), size=(BOOT_REPS, len(days)))
    rep = l_sums[idx].sum(axis=1) / l_cnts[idx].sum(axis=1) - \
        b_sums[idx].sum(axis=1) / b_cnts[idx].sum(axis=1)
    lo, hi = (float(v) for v in np.quantile(rep, [CI_LO, CI_HI]))
    return {
        "uplift": uplift,
        "split_half": {"h1": halves[0], "h2": halves[1],
                       "same_sign": bool(halves[0] > 0 and halves[1] > 0)},
        "bootstrap": {"mean": float(rep.mean()), "ci90_low": lo, "ci90_high": hi},
        "qualifies": bool(uplift > 0 and halves[0] > 0 and halves[1] > 0 and lo > 0),
    }


def run_triage(*, court_path: Path, factor_csv: Path,
               factor_direction: str = "invert") -> dict:
    gate = _gate_work(court_path, factor_csv, factor_direction)
    days = _day_sets(gate)
    if not days:
        _typed("gated_days_too_few", {"days": 0})
    levers = {name: _uplift_stats(days, name)
              for name in ("topk_composite", "topk_factor", "gate_tilt")}
    ready = any(v["qualifies"] for v in levers.values())
    return {
        "candidate_factor": str(factor_csv.name),
        "direction": factor_direction,
        "usable_rows": int(len(gate)),
        "gated_days": len(days),
        "gate_ts": GATE_TS,
        "levers": levers,
        "verdict": "challenger_ready" if ready else "deferred",
        "re_evaluate_trigger": "court 数据增长后重跑本工具; 任一杠杆 split-half 同正且 CI90 下界>0 才起草预注册提案",
    }


def register_triage(registry_path: Path, payload: dict) -> dict:
    """预注册账本 (R70): 复用工厂 _register_candidate 单一实现, 追加 triage
    verdict 与门内样本事实 (usable_rows/gated_days) — bench 重评到期判定的
    事实依据 (scripts/factor_bench_status.py)。"""
    name = Path(payload["candidate_factor"]).stem
    return _register_candidate(
        registry_path, name,
        fingerprint=f"triage:{name}:{payload['direction']}",
        extra={
            "verdict": payload["verdict"],
            "usable_rows": payload["usable_rows"],
            "gated_days": payload["gated_days"],
        },
    )


def main_with_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court", default=str(DEFAULT_COURT))
    parser.add_argument("--factor-csv", default=str(DEFAULT_FACTOR))
    parser.add_argument("--factor-direction", default="invert",
                        choices=["invert", "straight"])
    parser.add_argument("--registry", default=str(DEFAULT_TRIAGE_REGISTRY))
    args = parser.parse_args(argv)
    try:
        payload = run_triage(court_path=Path(args.court), factor_csv=Path(args.factor_csv),
                             factor_direction=args.factor_direction)
    except LeverTriageError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False))
        return 1
    entry = register_triage(Path(args.registry), payload)
    payload["registry"] = {k: entry[k] for k in
                           ("name", "first_seen", "unique_candidate_ordinal",
                            "run_count", "verdict")}
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=1))
    return 0 if payload["verdict"] == "challenger_ready" else 2


def main() -> int:
    return main_with_argv(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
