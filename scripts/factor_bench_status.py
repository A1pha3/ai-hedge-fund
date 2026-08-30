#!/usr/bin/env python3
"""板凳重评状态 (R70, 只读) — 把『数据增长后重跑 triage』触发器变为可观测。

R68/R69 确立 challenger 重评触发器 = court 数据增长; 但触发器只存在于文字
记录, 无人会在数据增长时记得重跑 — 不可观测的触发器等于不存在。本工具读
工厂/triege 两个预注册账本 + court 表, 输出每个 triage 候选的最新 verdict
与 re_eval_due 布尔:

    re_eval_due = (最新行 verdict == "deferred")
                  ∧ (生产对齐门内行数 ≥ 记账时 usable_rows × RE_EVAL_GROWTH)

challenger_ready 不设到期 (已就绪, 该走预注册提案=owner 决策点)。同名字候
选取最新记账行 (因子重建=内容指纹变化=新候选版本, 工厂 registry 语义)。
registry 缺失 = 记账面未初始化 = 类型化拒绝 (静默空输出是假信心)。

只读: 不写任何数据面文件。输出确定性 (同输入恒同输出, 候选按名字排序)。

用法 (uv run, 仓库根):
  uv run python scripts/factor_bench_status.py
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

from winrate_payoff_decomposition import production_aligned  # noqa: E402
from _btst_court_common import (  # noqa: E402
    load_regime_history,
    regime_drift_status,
)

REPO_ROOT = _SCRIPTS.parent
DEFAULT_FACTORY_REGISTRY = REPO_ROOT / "data/reports/factor_factory/registry.jsonl"
DEFAULT_TRIAGE_REGISTRY = REPO_ROOT / "data/reports/factor_factory/triage_registry.jsonl"
DEFAULT_COURT = REPO_ROOT / "data/research/btst_court/event_tables/event_table_v1.csv.gz"
DEFAULT_COURT_MANIFEST = DEFAULT_COURT.parent / "manifest_v1.json"
RE_EVAL_GROWTH = 1.2  # 门内样本较记账时增长 ≥20% → 重评到期 (预注册)


class BenchStatusError(RuntimeError):
    def __init__(self, code: str, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def _read_jsonl(path: Path, code: str) -> list[dict]:
    if not path.is_file():
        raise BenchStatusError(code, {"path": str(path)})
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise BenchStatusError("registry_corrupt",
                                       {"path": str(path), "error": str(exc)}) from exc
    return rows


def bench_status(*, factory_registry: Path, triage_registry: Path,
                 court_path: Path,
                 court_manifest: Path | None = None,
                 regime_history: dict[str, str] | None = None) -> dict:
    if not court_path.is_file():
        raise BenchStatusError("court_table_missing", {"path": str(court_path)})
    court = pd.read_csv(court_path, dtype={"signal_date": str, "ts_code": str})
    aligned = production_aligned(court)
    court_summary = {
        "aligned_rows": int(len(aligned)),
        "days": int(aligned["signal_date"].nunique()),
        "last_date": str(aligned["signal_date"].max()),
    }
    # R73: court 构建消费的 regime 输入 vs 当前 regime_history — 历史标签修订
    # 会静默重分类 gate_blocked → aligned 宇宙漂移; 在此响亮披露而非沉默.
    manifest_path = court_manifest or (court_path.parent / "manifest_v1.json")
    regime_drift: dict = {"checked": False, "drift": False, "changed_sessions": []}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BenchStatusError("court_manifest_corrupt",
                                   {"path": str(manifest_path), "error": str(exc)}) from exc
        history = (regime_history if regime_history is not None
                   else load_regime_history())
        regime_drift = regime_drift_status(manifest, history)
    _read_jsonl(factory_registry, "factory_registry_missing")  # fail-closed 存在性
    triage_rows = _read_jsonl(triage_registry, "triage_registry_missing")

    latest: dict[str, dict] = {}
    for row in triage_rows:  # append 序: 后行覆盖同名旧行
        name = row.get("name")
        if type(name) is str and name:
            latest[name] = row

    candidates = []
    for name in sorted(latest):
        row = latest[name]
        verdict = row.get("verdict")
        usable = row.get("usable_rows")
        # 口径纪律 (R70 Op3 修复): 到期判定必须同口径 — 当前生产对齐行数
        # 对比记账时的 aligned_rows。usable_rows 是 triage 门内行数 (剔除小日),
        # 与对齐全行数恒差一截, 拿来对比会永久假阳性 (Op2 真跑实锤)。
        row_aligned = row.get("aligned_rows")
        due = False
        metric = "legacy_row"
        if verdict == "deferred" and type(row_aligned) is int and row_aligned > 0:
            due = court_summary["aligned_rows"] >= row_aligned * RE_EVAL_GROWTH
            metric = "aligned_rows"
        candidates.append({
            "name": name,
            "verdict": verdict,
            "direction": row.get("direction"),
            "usable_rows": usable,
            "aligned_rows": row_aligned,
            "gated_days": row.get("gated_days"),
            "run_count": row.get("run_count"),
            "registered_at": row.get("registered_at"),
            "re_eval_metric": metric,
            "re_eval_due": bool(due),
        })

    return {
        "court": court_summary,
        "regime_drift": regime_drift,
        "re_eval_growth": RE_EVAL_GROWTH,
        "triage_candidates": candidates,
        "re_eval_due_any": any(c["re_eval_due"] for c in candidates),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--factory-registry", default=str(DEFAULT_FACTORY_REGISTRY))
    parser.add_argument("--triage-registry", default=str(DEFAULT_TRIAGE_REGISTRY))
    parser.add_argument("--court", default=str(DEFAULT_COURT))
    parser.add_argument("--court-manifest", default=None,
                        help="默认 <court 目录>/manifest_v1.json")
    args = parser.parse_args()
    try:
        payload = bench_status(factory_registry=Path(args.factory_registry),
                               triage_registry=Path(args.triage_registry),
                               court_path=Path(args.court),
                               court_manifest=(Path(args.court_manifest)
                                               if args.court_manifest else None))
    except BenchStatusError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
