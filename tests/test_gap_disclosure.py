"""gap_execution_reference — 执行面缺口披露 (R92 Op3).

钉死的正确性面:
- 聚合数学: 高开侧 = 5~10% ∪ >10% 两桶 n 加权池化 (Σn·E/Σn), 低开侧 = 其余非空桶;
- fail-open: 报告缺失/损坏/旧形态 available:False → None (不假装有证据);
- 渲染纪律: 仅披露参考, 不改变计划与执行决策; split 不稳定如实措辞;
- 单一实现: scripts 层 gap 常量与 gap_bucket 迁居 src, re-export 逐字节同行为。
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import pytest

from src.screening.offensive import gap_disclosure
from src.screening.offensive.gap_disclosure import (
    ALL_GAP_BUCKETS,
    GAP_HIGH_THRESHOLD,
    gap_bucket,
    gap_execution_reference,
    latest_decomposition_report,
    latest_signal_day_cohort_report,
    report_filename_date,
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


def test_gap_reference_ignores_non_dated_lookalike_files(tmp_path):
    """R109 Op2: 形状守卫 — 非日期同前缀文件不参与『最新』选择 (劫持 PoC 修复面).

    修复前: glob + sorted[-1] 使 winrate_payoff_decomposition_backup.json
    (合法 payload, 'backup' > '2' 字典序靠后) 被当作最新报告,
    evidence_date 渲染为 'backup'。修复后只有 \\d{8} 日期段命名参与。
    """
    base = tmp_path
    junk_payload = {
        "universes": {"production_aligned": {
            "gap_anatomy": {"available": True, "buckets": [
                {"bucket": "5~10%", "n": 10, "expectancy": -0.5},
                {"bucket": "0~2%", "n": 10, "expectancy": 0.1},
            ]},
            "horizons": {"t10": [{"group": "ALL", "n": 99}]},
        }},
    }
    (base / "winrate_payoff_decomposition_backup.json").write_text(
        json.dumps(junk_payload), encoding="utf-8")
    # 无日期命名文件时: 垃圾文件被忽略 → 返回 None (不假装有证据)
    assert gap_execution_reference(base) is None

    # 有日期命名文件时: 垃圾文件被忽略, 取日期文件
    real = dict(junk_payload)
    real["universes"]["production_aligned"]["gap_anatomy"] = {
        "available": True,
        "buckets": [
            {"bucket": "5~10%", "n": 10, "expectancy": -0.5},
            {"bucket": "0~2%", "n": 30, "expectancy": 0.1},
        ],
    }
    (base / "winrate_payoff_decomposition_20260904.json").write_text(
        json.dumps(real), encoding="utf-8")
    ref = gap_execution_reference(base)
    assert ref is not None
    assert ref["evidence_date"] == "20260904"


# --------------------- R137 Op1: 共享读取体未来日期守卫 ---------------------


def _minimal_payload(expectancy=0.005):
    """最小可读报告形态 (数值非对称, R13 教训)。"""
    return {
        "universes": {
            "production_aligned": {
                "horizons": {
                    "t10": [{"group": "ALL", "expectancy": expectancy}],
                }
            }
        },
        "court_rows": 100,
    }


class TestReportFilenameDate:
    """单一日期提取谓词 (R137 Op1): 读取体形状守卫与 scripts 侧 typed reason 共用。"""

    def test_dated_suffix_extracted(self):
        assert report_filename_date(
            Path("winrate_payoff_decomposition_20260907.json")
        ) == "20260907"

    def test_non_dated_suffix_none(self):
        assert report_filename_date(
            Path("winrate_payoff_decomposition_backup.json")
        ) is None
        assert report_filename_date(Path("x_2026090.json")) is None  # 7 位不足

    def test_embedded_date_not_suffix_no_match(self):
        # 形状守卫要求 _\d{8} 在 stem 末尾; .bak 尾缀使 stem 不以 8 位结束
        assert report_filename_date(Path("x_20260907.json.bak")) is None


class TestSharedReaderFutureDateGuard:
    """未来日期守卫下沉共享读取体 (R137 Op1, R136 Op2 登记开放项收口)。

    RED 实锤 (修复前): 合法 20260901 报告 + 20990101 毒报告 (E=0.99) 同目录,
    sorted[-1] 选中毒文件喂给 daily-action 先验漂移行/强度桶行/gap 参考行/
    cohort 行与跨窗口对比 — 假证据冒充当前证据。合法管道只在当日写报告,
    未来日期只能来自手工放置/时钟错乱; 拒绝且不回退次新 (镜像『损坏最新
    报告不回退』纪律: 目录异常时静默展示旧证据 = 以陈旧数字冒充当前)。
    """

    def _patch_today(self, monkeypatch, y=2026, m=9, d=7):
        monkeypatch.setattr(gap_disclosure, "_today", lambda: dt.date(y, m, d))

    def test_future_dated_poison_rejected_without_fallback(self, tmp_path, monkeypatch):
        self._patch_today(monkeypatch)
        (tmp_path / "winrate_payoff_decomposition_20260901.json").write_text(
            json.dumps(_minimal_payload(0.005)), encoding="utf-8"
        )
        (tmp_path / "winrate_payoff_decomposition_20990101.json").write_text(
            json.dumps(_minimal_payload(0.99)), encoding="utf-8"
        )
        # 拒绝毒报告, 且不回退次新 — 行缺席示警, 不以旧报告冒充当前
        assert latest_decomposition_report(tmp_path) is None
        assert gap_execution_reference(tmp_path) is None

    def test_future_dated_only_dir_returns_none(self, tmp_path, monkeypatch):
        self._patch_today(monkeypatch)
        (tmp_path / "winrate_payoff_decomposition_20990101.json").write_text(
            json.dumps(_minimal_payload(0.99)), encoding="utf-8"
        )
        assert latest_decomposition_report(tmp_path) is None

    def test_today_dated_report_selected_boundary_inclusive(self, tmp_path, monkeypatch):
        self._patch_today(monkeypatch, 2026, 9, 7)
        (tmp_path / "winrate_payoff_decomposition_20260907.json").write_text(
            json.dumps(_minimal_payload()), encoding="utf-8"
        )
        found = latest_decomposition_report(tmp_path)
        assert found is not None
        assert found[0].name.endswith("20260907.json")

    def test_cohort_reader_future_guard_same_body(self, tmp_path, monkeypatch):
        self._patch_today(monkeypatch)
        (tmp_path / "signal_day_cohort_20260901.json").write_text(
            json.dumps({"any": "shape"}), encoding="utf-8"
        )
        (tmp_path / "signal_day_cohort_20990101.json").write_text(
            json.dumps({"any": "shape"}), encoding="utf-8"
        )
        assert latest_signal_day_cohort_report(tmp_path) is None

    def test_real_clock_past_reports_unaffected(self, tmp_path):
        """不注入钟: 真实今日 (2026-09) 下历史报告选择行为不变 (零回归锚)。"""
        (tmp_path / "winrate_payoff_decomposition_20260901.json").write_text(
            json.dumps(_minimal_payload()), encoding="utf-8"
        )
        found = latest_decomposition_report(tmp_path)
        assert found is not None
        assert found[0].name.endswith("20260901.json")
