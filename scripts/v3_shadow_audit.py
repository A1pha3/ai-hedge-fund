#!/usr/bin/env python3
"""Plan 06 Task 5/8: v2↔v3 shadow 一致性审计 CLI.

读取 v2 与 v3 shadow 的决策记录 (JSON 行或数组), 逐字段分类差异并执行
runbook 门禁: 存在 DATA_MISMATCH | KERNEL_BUG | UNKNOWN 即非零退出.

用法:
  uv run python scripts/v3_shadow_audit.py --v2 v2.json --v3 v3.json \
      --expect exit:T+10:T+1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from src.screening.offensive.v3.migration.shadow_audit import (
    ExpectedDifferencePolicy,
    ShadowAuditReport,
    assert_no_blocking_differences,
    audit_shadow_parity,
)


def _load(path: Path) -> list[dict[str, object]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        return list(json.loads(text))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _parse_expected(items: list[str]) -> ExpectedDifferencePolicy:
    triples: list[tuple[str, str, str]] = []
    for item in items:
        field, v2_value, v3_value = item.split(":", 2)
        triples.append((field, v2_value, v3_value))
    return ExpectedDifferencePolicy(expected=tuple(triples))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v3_shadow_audit")
    parser.add_argument("--v2", type=Path, required=True)
    parser.add_argument("--v3", type=Path, required=True)
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="FIELD:V2:V3",
        help="register a known policy change (repeatable)",
    )
    parser.add_argument("--enforce-gate", action="store_true")
    args = parser.parse_args(argv)

    report: ShadowAuditReport = audit_shadow_parity(
        v2_records=_load(args.v2),
        v3_records=_load(args.v3),
        policy=_parse_expected(args.expect),
    )
    print(
        json.dumps(
            {
                "differences": [
                    {
                        "ticker": difference.ticker,
                        "field": difference.field,
                        "v2": difference.v2_value,
                        "v3": difference.v3_value,
                        "category": difference.category.value,
                    }
                    for difference in report.differences
                ],
                "blocking": len(report.blocking()),
                "canonical_hash": report.canonical_hash,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if args.enforce_gate:
        assert_no_blocking_differences(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
