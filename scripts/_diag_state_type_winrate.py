"""R-5.F Phase 0 一次性诊断 runner: 跑三问 → 打印 + 保存 JSON 报告.

用法:
    .venv/bin/python scripts/_diag_state_type_winrate.py [--lookback-days N] [--reports-dir PATH]

诊断结论 (1A/1B/STOP) 决定 R-5.F Phase 1 走哪条路. 诊断完结论沉淀进产品文档后
可删本脚本 (``_`` 前缀 = 一次性分析工具, 惯例同 _r5a_regime_winrate.py /
_backtest_light_stage_universe.py). 核心统计逻辑在 src/screening/state_type_calibration.py.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from src.screening.state_type_calibration import run_state_type_diagnosis


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--reports-dir", type=Path, default=None)
    parser.add_argument(
        "--out", type=Path, default=Path("outputs/diag_state_type_winrate.json")
    )
    args = parser.parse_args()

    q1, q2_rows, q3, verdict = run_state_type_diagnosis(
        reports_dir=args.reports_dir, lookback_days=args.lookback_days
    )

    print("=" * 64)
    print("R-5.F Phase 0 诊断 — state_type 条件胜率")
    print("=" * 64)

    print("\n[问1] state_type 总体区分度 (TREND vs 震荡):")
    for r in q1.rows:
        wr = f"{r.t30_win_rate:.0%}" if r.t30_win_rate is not None else "—"
        med = f"{r.t30_median_return:+.1f}%" if r.t30_median_return is not None else "—"
        print(
            f"  {r.state_type:<8} winrate={wr:<6} median={med:<8} "
            f"(mature n={r.mature_t30_count}, all n={r.sample_count})"
        )
    if q1.unknown_state_type_count:
        print(f"  ({q1.unknown_state_type_count} 条 recommended_date 无对应报告)")

    print("\n[问2] 震荡市内 score-bucket 细分 (target RANGE/MIXED):")
    if not q2_rows:
        print("  (无 RANGE/MIXED 日样本)")
    for r in q2_rows:
        wr = f"{r.t30_win_rate:.0%}" if r.t30_win_rate is not None else "—"
        flag = "  ⚠ evidence_insufficient (n<20)" if r.mature_t30_count < 20 else ""
        print(f"  {r.state_type:<8} {r.bucket:<10} winrate={wr:<6} (n={r.mature_t30_count}){flag}")

    print(
        f"\n[问3] 留一时段样本外验证: robust={q3.robust} "
        f"maintained_rate={q3.rediscovered_winner_rate:.0%} "
        f"({q3.heldout_periods} periods)"
    )

    print(f"\n>>> 裁决: Phase 1 = {verdict.phase1_branch}")
    print(f"    {verdict.reason}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "q1": [asdict(r) for r in q1.rows],
        "q2": [asdict(r) for r in q2_rows],
        "q3": asdict(q3),
        "verdict": asdict(verdict),
    }
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n报告已保存: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
