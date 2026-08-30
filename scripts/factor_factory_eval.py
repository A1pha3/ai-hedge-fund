#!/usr/bin/env python3
"""因子工厂 v0 — 标准因子评估面 (R59, owner 数据效率工作线②③).

任何候选因子 → 一张标准报告, 杀灭决策从「写一天脚本」变「看一张报告」:
  1. production_aligned 宇宙 (复用 winrate_payoff_decomposition 单一实现, 绝不复制口径)
  2. 总体 n/胜率/avg_win/avg_loss/payoff/E + 按信号日聚类 CI90 (扣费口径)
  3. 日度横截面 Spearman IC (每日 ≥MIN_IC_NAMES 票才计) — mean + bootstrap CI,
     这就是「每天找出未来最可能涨的票」的排序质量北极星
  4. 日内五分位桶 (按日秩): 各桶 E/胜率/赔付/CI + 桶序-E Spearman 单调性
  5. 衰减: top−bottom 净收益 spread 按 T+3/5/8/10
  6. regime 切分: 各 regime 的 top−bottom spread
  7. 预注册账本 (项③决策落地): registry.jsonl 追加候选名+内容指纹,
     报告如实披露「第 N 个唯一候选」与重复运行 (同一宇宙测 100 个因子会有
     ~5 个假显著 — 记账让多重比较可见, 不限速但不可抵赖)

输入:
  --factor-col NAME   评估事件表自带数值列 (如 trigger_strength)
  --factor-csv PATH   外部因子 (signal_date,ts_code,factor), --name NAME 必填
类型化失败: court 表缺失 / 因子列缺失或非数值 / 对齐行覆盖率 <50% (fail-closed,
因子和宇宙对不上号时沉默出报告 = 最危险的假噪音)。
随机性全部经 seeded cluster_boot_ci_low (R13 纪律: 同输入恒同输出)。

用法:
  uv run python scripts/factor_factory_eval.py --factor-col trigger_strength
  uv run python scripts/factor_factory_eval.py --factor-csv f.csv --name my_factor
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from winrate_payoff_decomposition import (  # noqa: E402
    cluster_boot_ci_low,
    net_returns,
    production_aligned,
    win_loss_stats,
)

REPO_ROOT = _SCRIPTS.parent
DEFAULT_COURT = REPO_ROOT / "data/research/btst_court/event_tables/event_table_v1.csv.gz"
DEFAULT_OUT_DIR = REPO_ROOT / "data/reports/factor_factory"
DEFAULT_REGISTRY = DEFAULT_OUT_DIR / "registry.jsonl"

HORIZONS = ["t3", "t5", "t8", "t10"]
N_BUCKETS = 5
MIN_IC_NAMES = 5          # 日度 IC 的最小横截面宽度
MIN_COVERAGE = 0.5        # 因子对齐行覆盖率下限 (低于即类型化拒绝)
MIN_BUCKET_MONO_SPAN = 3  # 单调性至少需要的非空桶数


class FactorEvalError(RuntimeError):
    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _typed(code: str, details: dict | None = None):
    raise FactorEvalError(code, details)


def _load_aligned(court_path: Path) -> pd.DataFrame:
    if not court_path.is_file():
        _typed("court_table_not_found", {"path": str(court_path)})
    ev = pd.read_csv(court_path)
    return production_aligned(ev)


def _attach_factor(aligned: pd.DataFrame, args) -> tuple[pd.DataFrame, str, str | None]:
    """返回 (带 factor 列的 aligned, 因子名, 因子文件指纹或 None)。"""
    if bool(args.factor_col) == bool(args.factor_csv):
        _typed("factor_source_ambiguous",
               {"hint": "恰选一: --factor-col 或 --factor-csv"})
    if args.factor_col:
        name = args.factor_col
        if name not in aligned.columns:
            _typed("factor_column_missing", {"column": name})
        col = pd.to_numeric(aligned[name], errors="coerce")
        fingerprint = None
    else:
        name = args.name or ""
        if not name:
            _typed("factor_name_required", {"hint": "--factor-csv 需配 --name"})
        fp = Path(args.factor_csv)
        if not fp.is_file():
            _typed("factor_csv_not_found", {"path": str(fp)})
        raw = fp.read_bytes()
        fingerprint = hashlib.sha256(raw).hexdigest()
        fac = pd.read_csv(fp)
        missing = [c for c in ("signal_date", "ts_code", "factor") if c not in fac.columns]
        if missing:
            _typed("factor_csv_missing_columns", {"missing": missing})
        fac = fac.dropna(subset=["factor"])
        fac["signal_date"] = fac["signal_date"].astype(str)
        dup = fac.duplicated(subset=["signal_date", "ts_code"]).sum()
        if dup:
            # 重复键使 left merge 膨胀 → 行数错位 → 位置回填污染: fail-closed
            _typed("factor_csv_duplicate_keys", {"duplicates": int(dup)})
        aligned = aligned.copy()
        aligned["signal_date"] = aligned["signal_date"].astype(str)
        merged = aligned.merge(
            fac[["signal_date", "ts_code", "factor"]],
            on=["signal_date", "ts_code"], how="left",
        )
        col = pd.to_numeric(merged["factor"], errors="coerce")
    coverage = float(col.notna().mean()) if len(col) else 0.0
    if coverage < MIN_COVERAGE:
        _typed("factor_coverage_too_low",
               {"coverage": round(coverage, 4), "threshold": MIN_COVERAGE})
    out = aligned.copy()
    # csv 路径经 left merge (保左序) — 按位置回填, 列索引语义两路一致
    out["factor"] = col.to_numpy()
    return out, name, fingerprint


def _register_candidate(registry_path: Path, name: str,
                        fingerprint: str | None,
                        extra: dict | None = None) -> dict:
    """预注册账本 (append-only JSONL): 第 N 个唯一候选 + 重复运行如实披露。"""
    entry_fingerprint = fingerprint or f"column:{name}"
    records = []
    if registry_path.is_file():
        for line in registry_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    seen = {r["fingerprint"] for r in records if r.get("fingerprint")}
    prior = [r for r in records if r.get("fingerprint") == entry_fingerprint]
    entry = {
        "fingerprint": entry_fingerprint,
        "name": name,
        "first_seen": not prior,
        "unique_candidate_ordinal": (max((r["unique_candidate_ordinal"]
                                          for r in records), default=0)
                                     + (1 if not prior else 0)),
        "run_count": (prior[-1]["run_count"] + 1) if prior else 1,
        "registered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if extra:
        entry.update(extra)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _daily_ic(df: pd.DataFrame) -> dict:
    """日度横截面 Spearman IC (≥MIN_IC_NAMES 票的日才计)。"""
    ics: dict[str, float] = {}
    for day, grp in df.groupby("signal_date"):
        if len(grp) < MIN_IC_NAMES:
            continue
        ic = grp["factor"].rank().corr(grp["net_t10"].rank())
        if pd.notna(ic):
            ics[str(day)] = float(ic)
    values = list(ics.values())
    if not values:
        return {"ic_mean": None, "ic_ci_low_90": None, "ic_days": 0}
    days = list(ics.keys())
    return {
        "ic_mean": sum(values) / len(values),
        "ic_ci_low_90": cluster_boot_ci_low(values, days),
        "ic_days": len(values),
    }


def _bucket_stats(df: pd.DataFrame) -> dict:
    """日内五分位桶 (按日秩): 各桶 win_loss_stats + 桶序单调性。"""
    work = df.dropna(subset=["factor"]).copy()
    # 按日秩百分位 → 桶 (日内横截面秩, 跨日池化)
    work["pct_rank"] = work.groupby("signal_date")["factor"].rank(pct=True)
    work["bucket"] = ((work["pct_rank"] * N_BUCKETS)
                      .clip(upper=N_BUCKETS - 0.001).astype(int) + 1)
    buckets = {}
    for b in range(1, N_BUCKETS + 1):
        sub = work[work["bucket"] == b]
        buckets[str(b)] = win_loss_stats(
            sub["net_t10"].tolist(), sub["signal_date"].astype(str).tolist())
    # 单调性: 桶序 vs 桶 E 的 Spearman (非空桶 ≥3 才算)
    e_series = [(int(k), v["expectancy"]) for k, v in buckets.items()
                if v["expectancy"] is not None]
    mono = None
    if len(e_series) >= MIN_BUCKET_MONO_SPAN:
        xs = pd.Series([x for x, _ in e_series])
        ys = pd.Series([y for _, y in e_series])
        mono = float(xs.rank().corr(ys.rank()))
    top = buckets[str(N_BUCKETS)]
    bottom = buckets["1"]
    spread = None
    if top["expectancy"] is not None and bottom["expectancy"] is not None:
        spread = top["expectancy"] - bottom["expectancy"]
    return {"buckets": buckets, "bucket_monotonicity_spearman": mono,
            "top_minus_bottom_spread_t10": spread}


def _decay_and_regime(work: pd.DataFrame) -> dict:
    """top−bottom spread 按 horizon; regime 分组 spread (top−bottom)。"""
    work = work.dropna(subset=["factor"]).copy()
    work["pct_rank"] = work.groupby("signal_date")["factor"].rank(pct=True)
    decay = {}
    for h in HORIZONS:
        col = f"net_{h}"
        if col not in work.columns:
            continue
        vals = {}
        for label, hi in (("top", True), ("bottom", False)):
            q = work["pct_rank"]
            sel = work[q >= 0.8] if hi else work[q < 0.2]
            rets = sel[col].dropna().tolist()
            vals[label] = (sum(rets) / len(rets)) if rets else None
        if vals["top"] is not None and vals["bottom"] is not None:
            decay[h] = {"top_e": vals["top"], "bottom_e": vals["bottom"],
                        "spread": vals["top"] - vals["bottom"]}
    regimes = {}
    if "regime" in work.columns:
        for reg, grp in work.groupby("regime"):
            q = grp["pct_rank"]
            top = grp[q >= 0.8]["net_t10"].dropna()
            bot = grp[q < 0.2]["net_t10"].dropna()
            if len(top) and len(bot):
                regimes[str(reg)] = {
                    "top_e": float(top.mean()), "bottom_e": float(bot.mean()),
                    "spread": float(top.mean() - bot.mean()),
                    "top_n": int(len(top)), "bottom_n": int(len(bot)),
                }
    return {"decay_spread": decay, "regime_spread": regimes}


def evaluate(*, court_path: Path, factor_col: str | None, factor_csv: str | None,
             name: str | None, registry_path: Path) -> dict:
    aligned = _load_aligned(court_path)
    if "gross_ret_t10" not in aligned.columns:
        _typed("court_missing_horizon", {"column": "gross_ret_t10"})
    work, factor_name, fingerprint = _attach_factor(aligned, argparse.Namespace(
        factor_col=factor_col, factor_csv=factor_csv, name=name))
    # 扣费口径: 各 horizon gross → net (None 透传)
    for h in HORIZONS:
        if f"gross_ret_{h}" in work.columns:
            work[f"net_{h}"] = net_returns(work[f"gross_ret_{h}"].tolist())
    usable = work.dropna(subset=["factor", "net_t10"])
    if len(usable) < 10:
        _typed("usable_rows_too_few", {"rows": int(len(usable))})
    overall = win_loss_stats(usable["net_t10"].tolist(),
                             usable["signal_date"].astype(str).tolist())
    entry = _register_candidate(registry_path, factor_name, fingerprint)
    payload = {
        "factor": factor_name,
        "source": "column" if factor_col else "csv",
        "fingerprint": entry["fingerprint"],
        "registry": {k: entry[k] for k in
                     ("first_seen", "unique_candidate_ordinal", "run_count")},
        "rows": {
            "court_rows": int(len(aligned)),
            "factor_non_null": int(work["factor"].notna().sum()),
            "coverage": round(float(work["factor"].notna().mean()), 4),
            "usable_rows": int(len(usable)),
            "signal_days": int(usable["signal_date"].nunique()),
        },
        "overall_t10_net": overall,
        "daily_ic": _daily_ic(usable),
        "buckets_t10_net": _bucket_stats(usable),
        **_decay_and_regime(usable),
    }
    return payload


def render_md(payload: dict) -> str:
    L = [f"# 因子工厂评估 — {payload['factor']}", ""]
    reg = payload["registry"]
    L.append(f"预注册: 第 {reg['unique_candidate_ordinal']} 个唯一候选"
             f" · 第 {reg['run_count']} 次运行"
             f" · {'新候选' if reg['first_seen'] else '重复运行 (多重比较照旧计入)'}")
    r = payload["rows"]
    L.append(f"覆盖: {r['usable_rows']}/{r['court_rows']} 行"
             f" (coverage={r['coverage']}, {r['signal_days']} 个信号日)")
    o = payload["overall_t10_net"]
    ci = o["cluster_ci_low_90"]
    L.append(f"总体 T+10 净: E={o['expectancy']:.4f} 胜率={o['winrate']:.4f}"
             f" payoff={o['payoff'] if o['payoff'] is not None else '—'}"
             f" CI90low={f'{ci:.4f}' if ci is not None else '—'} (n={o['n']})")
    ic = payload["daily_ic"]
    if ic["ic_mean"] is not None:
        L.append(f"日度 IC: mean={ic['ic_mean']:.4f}"
                 f" CI90low={ic['ic_ci_low_90']:.4f} ({ic['ic_days']} 日)")
    b = payload["buckets_t10_net"]
    mono = b["bucket_monotonicity_spearman"]
    spread = b["top_minus_bottom_spread_t10"]
    spread_s = f"{spread:.4f}" if spread is not None else "—"
    L.append(f"桶单调性 (Spearman): {mono if mono is not None else '—'}"
             f" · top−bottom spread T+10: {spread_s}")
    for k, v in b["buckets"].items():
        e, w = v["expectancy"], v["winrate"]
        if e is None:
            L.append(f"  Q{k}: E=— 胜率=— n={v['n']}")
        else:
            L.append(f"  Q{k}: E={e:.4f} 胜率={w:.4f} n={v['n']}")
    for h, d in payload.get("decay_spread", {}).items():
        L.append(f"  衰减 {h}: spread={d['spread']:.4f} (top={d['top_e']:.4f}"
                 f" bottom={d['bottom_e']:.4f})")
    for reg_name, d in payload.get("regime_spread", {}).items():
        L.append(f"  regime {reg_name}: spread={d['spread']:.4f}"
                 f" (top_n={d['top_n']}, bottom_n={d['bottom_n']})")
    L.append("")
    L.append("纪律: 纯诊断 (宪法 #2 — 不替代组合路径证据); 桶级结论需前向确认;")
    L.append("任何据此改阈值/仓位 = 新证据世代 owner 决策。")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court", default=str(DEFAULT_COURT))
    parser.add_argument("--factor-col", default=None)
    parser.add_argument("--factor-csv", default=None)
    parser.add_argument("--name", default=None)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--date", default=time.strftime("%Y%m%d"))
    args = parser.parse_args(argv)

    try:
        payload = evaluate(court_path=Path(args.court),
                           factor_col=args.factor_col, factor_csv=args.factor_csv,
                           name=args.name, registry_path=Path(args.registry))
    except FactorEvalError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False))
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"factor_eval_{args.name or args.factor_col}_{args.date}"
    (out_dir / f"{stem}.json").write_text(
        json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    md = render_md(payload)
    (out_dir / f"{stem}.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
