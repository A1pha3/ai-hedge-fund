from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_0422_baseline_freeze import build_btst_0422_baseline_freeze


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_build_btst_0422_baseline_freeze_extracts_core_metrics_and_field_inventory(tmp_path: Path) -> None:
    evidence_doc = _write_text(
        tmp_path / "01.md",
        """
## 二、长期历史回测数据

### 2.1 20 日精选池汇总（btst_precision_v2，8485 样本）

| 指标 | 数值 |
|------|------|
| T+1 收盘胜率 | **47.27%**（< 50%）|
| 盈亏比 | **1.282:1** |
| 期望收益 | **-0.0448%** |

### 2.3 按行情类型汇总（核心发现）

| 市场类型 | 天数 | 平均收盘胜率 | 平均盈亏比 | 期望利润贡献（相对单位） |
|---------|------|------------|----------|----------------------|
| **强势日** (wr>60%) | 7 | **76.0%** | **1.66** | **+6,749** |
| **弱势日** (wr<35%) | 8 | **22.6%** | **0.93** | **-7,502** |
| 中性日 (35–60%) | 5 | 46.4% | 1.29 | +≈500 |

### 2.4 Selected vs Near-miss 的选股超额（20 日均值）

| 池 | 平均收盘胜率 | 平均盈亏比 |
|---|------------|----------|
| selected（精选） | 47.2% | 1.27 |
| near_miss（候补） | 45.2% | 1.28 |
| **超额** | **+2.0%** | **-0.01** |
""".strip(),
    )
    output_json = tmp_path / "p0_btst_0422_baseline_freeze.json"
    output_markdown = tmp_path / "p0_btst_0422_baseline_freeze.md"

    report = build_btst_0422_baseline_freeze(
        evidence_doc_path=evidence_doc,
        output_json_path=output_json,
        output_markdown_path=output_markdown,
    )

    assert report["baseline_metrics"]["selected_close_win_rate"] == 47.27
    assert report["baseline_metrics"]["post_fee_expectation_low"] == -0.16
    assert report["baseline_metrics"]["regime_breakdown"]["strong"]["day_count"] == 7
    assert report["baseline_metrics"]["near_miss_comparison"]["selected_win_rate"] == 47.2
    assert "trade_date" in report["field_inventory"]["selection_snapshot"]["fields"]
    assert "plan_generation" in report["field_inventory"]["session_summary"]["fields"]
    assert report["feature_flag_injection_points"]["p1_regime_gate_shadow"]["default_mode"] == "off"
    assert output_json.exists()
    assert output_markdown.exists()
    persisted = json.loads(output_json.read_text(encoding="utf-8"))
    assert persisted["report_names"]["baseline_json"] == "p0_btst_0422_baseline_freeze.json"
    assert "P0 BTST 0422 Baseline Freeze" in output_markdown.read_text(encoding="utf-8")
