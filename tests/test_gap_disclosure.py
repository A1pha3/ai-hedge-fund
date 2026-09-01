"""gap_execution_reference — 执行面缺口披露 (R92 Op3).

钉死的正确性面:
- 聚合数学: 高开侧 = 5~10% ∪ >10% 两桶 n 加权池化 (Σn·E/Σn), 低开侧 = 其余非空桶;
- fail-open: 报告缺失/损坏/旧形态 available:False → None (不假装有证据);
- 渲染纪律: 仅披露参考, 不改变计划与执行决策; split 不稳定如实措辞;
- 单一实现: scripts 层 gap 常量与 gap_bucket 迁居 src, re-export 逐字节同行为。
"""

from __future__ import annotations

import json
import math

import pytest

from src.screening.offensive.gap_disclosure import (
    ALL_GAP_BUCKETS,
    GAP_HIGH_THRESHOLD,
    gap_bucket,
    gap_execution_reference,
)


def _report_json(e_hi_cell=(0.05, -0.0258), **overrides):
    """构造最小 gap_anatomy 报告形态 (数值非对称, R13 教训)。"""
    buckets = [
        {"bucket": "<-5%", "n": 2, "expectancy": 0.0805, "winrate": 0.6, "cluster_ci_low_90": None},
        {"bucket": "-5~0", "n": 100, "expectancy": 0.0125, "winrate": 0.475, "cluster_ci_low_90": -0.01},
        {"bucket": "0~2%", "n": 200, "expectancy": 0.0012, "winrate": 0.444, "cluster_ci_low_90": -0.013},
        {"bucket": "2~5%", "n": 150, "expectancy": -0.005, "winrate": 0.446, "cluster_ci_low_90": -0.02},
        {"bucket": "5~10%", "n": int(e_hi_cell[0] * 1e5), "expectancy": e_hi_cell[1], "winrate": 0.34, "cluster_ci_low_90": -0.043},
        {"bucket": ">10%", "n": 4, "expectancy": -0.0273, "winrate": 0.4, "cluster_ci_low_90": None},
    ]
    gap = {
        "gap_high_threshold": 0.05,
        "buckets": buckets,
        "gap_missing": {"n": 0},
        "within_strength": [],
        "slice_co_movement": [],
        "split_half": {
            "split_date": "20251125",
            "buckets": [],
            "judgable_count": 4,
            "consistent_count": overrides.pop("consistent_count", 4),
            "close_anchor_penalty_stable": True,
            "verdict_hint": "x",
        },
    }
    payload = {
        "universes": {
            "production_aligned": {
                "horizons": {"t10": [{"group": "ALL", "n": overrides.pop("total_n", 1921)}]},
                "gap_anatomy": gap,
            }
        }
    }
    payload["universes"]["production_aligned"]["gap_anatomy"]["split_half"]["judgable_count"] = 4
    return payload


def _write_report(reports_dir, date_str="20260901", payload=None):
    path = reports_dir / f"winrate_payoff_decomposition_{date_str}.json"
    path.write_text(json.dumps(payload if payload is not None else _report_json()), encoding="utf-8")
    return path


class TestSingleImplementationHome:
    """gap 常量/gap_bucket 单一定义迁居 src — scripts re-export 同一对象。"""

    def test_scripts_reexports_same_objects(self):
        import scripts.winrate_payoff_decomposition as deco
        assert deco.gap_bucket is gap_bucket
        assert deco.GAP_HIGH_THRESHOLD == GAP_HIGH_THRESHOLD
        assert deco.ALL_GAP_BUCKETS == ALL_GAP_BUCKETS

    def test_bucket_semantics_preserved(self):
        assert gap_bucket(0.049) == "2~5%"
        assert gap_bucket(0.05) == "5~10%"
        assert gap_bucket(None) == "unknown"
        assert gap_bucket(float("nan")) == "unknown"


class TestGapExecutionReference:
    def test_pooled_asymmetric_math(self, tmp_path):
        ref = gap_execution_reference(tmp_path)
        assert ref is None  # 空目录 fail-open
        _write_report(tmp_path)
        ref = gap_execution_reference(tmp_path)
        assert ref is not None
        assert ref["evidence_date"] == "20260901"
        assert ref["total_n"] == 1921
        # 高开侧 = 5~10% (n=5000) ∪ >10% (n=4): n 加权池化
        n_hi = 5000 + 4
        e_hi = (5000 * -0.0258 + 4 * -0.0273) / n_hi
        assert ref["n_hi"] == n_hi
        assert ref["e_hi"] == pytest.approx(e_hi, abs=1e-12)
        # 低开侧 = 其余非空桶
        n_lo = 2 + 100 + 200 + 150
        e_lo = (2 * 0.0805 + 100 * 0.0125 + 200 * 0.0012 + 150 * -0.005) / n_lo
        assert ref["n_lo"] == n_lo
        assert ref["e_lo"] == pytest.approx(e_lo, abs=1e-12)
        assert ref["split_stable"] is True

    def test_latest_file_wins(self, tmp_path):
        _write_report(tmp_path, "20260831", _report_json())
        _write_report(tmp_path, "20260901", _report_json())
        ref = gap_execution_reference(tmp_path)
        assert ref["evidence_date"] == "20260901"

    def test_missing_dir_fail_open(self, tmp_path):
        assert gap_execution_reference(tmp_path) is None

    def test_corrupt_json_fail_open(self, tmp_path):
        (tmp_path / "winrate_payoff_decomposition_20260901.json").write_text("{oops", encoding="utf-8")
        assert gap_execution_reference(tmp_path) is None

    def test_unavailable_old_form_fail_open(self, tmp_path):
        payload = {"universes": {"production_aligned": {"gap_anatomy": {"available": False}}}}
        _write_report(tmp_path, payload=payload)
        assert gap_execution_reference(tmp_path) is None

    def test_no_high_gap_cells_fail_open(self, tmp_path):
        payload = _report_json()
        buckets = payload["universes"]["production_aligned"]["gap_anatomy"]["buckets"]
        for b in buckets:
            if b["bucket"] in ("5~10%", ">10%"):
                b["n"] = 0
                b["expectancy"] = None
        _write_report(tmp_path, payload=payload)
        assert gap_execution_reference(tmp_path) is None

    def test_split_unstable_flag_extracted(self, tmp_path):
        payload = _report_json(consistent_count=2)
        _write_report(tmp_path, payload=payload)
        ref = gap_execution_reference(tmp_path)
        assert ref["split_stable"] is False


class TestRenderGapLine:
    def _line(self, tmp_path):
        from src.screening.offensive.daily_action import _render_gap_reference_line
        return _render_gap_reference_line(reports_dir=tmp_path)

    def test_line_present_with_discipline_note(self, tmp_path):
        _write_report(tmp_path)
        line = self._line(tmp_path)
        assert line is not None
        assert "执行面缺口参考" in line
        assert "20260901" in line
        assert "高开>5%" in line
        assert "仅披露" in line
        assert "不改变计划与执行决策" in line

    def test_line_absent_when_no_evidence(self, tmp_path):
        assert self._line(tmp_path) is None

    def test_unstable_split_wording_honest(self, tmp_path):
        _write_report(tmp_path, payload=_report_json(consistent_count=2))
        line = self._line(tmp_path)
        assert line is not None
        assert "跨半不一致" in line
