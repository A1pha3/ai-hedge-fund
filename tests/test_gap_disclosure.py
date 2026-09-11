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


# --------------------- R141 Op3: 证据窗口穿透 ---------------------


def test_gap_reference_window_end_passthrough(tmp_path):
    """payload.court_window.end 穿透; 缺失/畸形 → None (不虚构覆盖)。"""
    base = tmp_path / "reports"
    base.mkdir()
    from scripts.winrate_payoff_decomposition import production_aligned  # noqa: F401

    payload = _minimal_payload()
    payload["universes"]["production_aligned"]["gap_anatomy"] = {
        "available": True,
        "buckets": [
            {"bucket": "5~10%", "n": 10, "expectancy": -0.5},
            {"bucket": "0~2%", "n": 30, "expectancy": 0.1},
        ],
    }
    # 窗口在场 → 穿透
    with_window = dict(payload)
    with_window["court_window"] = {"start": "20250701", "end": "20260904"}
    (base / "winrate_payoff_decomposition_20260904.json").write_text(
        json.dumps(with_window), encoding="utf-8")
    ref = gap_execution_reference(base)
    assert ref is not None
    assert ref["window_end"] == "20260904"
    assert ref["evidence_date"] == "20260904"

    # 畸形窗口 (非 8 位数字) → None
    (base / "winrate_payoff_decomposition_20260904.json").write_text(json.dumps({
        **payload, "court_window": {"start": "x", "end": "2026-09-04"}}), encoding="utf-8")
    ref = gap_execution_reference(base)
    assert ref is not None and ref["window_end"] is None

    # 旧报告 (无 court_window) → None
    (base / "winrate_payoff_decomposition_20260904.json").write_text(
        json.dumps(payload), encoding="utf-8")
    ref = gap_execution_reference(base)
    assert ref is not None and ref["window_end"] is None


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


# ---------- R181 Op1: 项 5 当期止损方向子句 (夜刷 exit_anatomy 的操作员面) ----------

def _exit_anatomy_payload():
    """非对称双 regime 夹具 (R180 P-l 教训: 对称值会掩盖桶互换/键互换)。

    crisis 桶最佳档 -5% (Δ+0.90pp); normal 桶最佳档 -8% 且 n/基准全不同 —
    桶互换、档互换、n 互换任一变异都必然改变断言读数。
    """
    return {
        "early": {"by_regime": {"crisis": {"n_included": 1}}},
        "production": {
            "by_regime": {
                "crisis": {
                    "n_included": 132,
                    "base": {"mean_net": -0.05506869208225434, "n": 132},
                    "stop_grid": {
                        "-5%": {
                            "delta_vs_base": 0.009027072247123666,
                            "mean_net": -0.04604161983513067,
                            "n": 132,
                            "n_stopped": 114,
                            "n_gap_through": 49,
                        },
                        "-8%": {
                            "delta_vs_base": -0.004216352983654442,
                            "mean_net": -0.05928504506590878,
                            "n": 132,
                            "n_stopped": 96,
                            "n_gap_through": 24,
                        },
                        "-10%": {
                            "delta_vs_base": -0.002180029415038906,
                            "mean_net": -0.057248721497293244,
                            "n": 132,
                            "n_stopped": 80,
                            "n_gap_through": 19,
                        },
                    },
                },
                "normal": {
                    "n_included": 217,
                    "base": {"mean_net": 0.0005123, "n": 217},
                    "stop_grid": {
                        "-5%": {
                            "delta_vs_base": -0.0104,
                            "mean_net": -0.0044,
                            "n": 217,
                            "n_stopped": 31,
                            "n_gap_through": 9,
                        },
                        "-8%": {
                            "delta_vs_base": 0.0027,
                            "mean_net": 0.0031,
                            "n": 217,
                            "n_stopped": 12,
                            "n_gap_through": 3,
                        },
                    },
                },
            }
        },
    }


def test_stop_direction_clause_exact_render():
    clause = gap_disclosure.stop_direction_clause(
        _exit_anatomy_payload(), "crisis", "20260910"
    )
    assert clause == (
        "当期方向（exit_anatomy 20260910 · 生产表/crisis/全候选，n=132）："
        "基准 -5.51% · 最佳止损档 -5%（Δ+0.90pp，档内 -4.60%，触发 114/132，"
        "跳空穿越 49）"
    )


def test_stop_direction_clause_regime_asymmetry_guard():
    """normal 桶读数与 crisis 逐值不同 — 桶互换变异必然被抓。"""
    clause = gap_disclosure.stop_direction_clause(
        _exit_anatomy_payload(), "normal", "20260910"
    )
    assert clause is not None
    assert "生产表/normal/全候选，n=217" in clause
    assert "基准 +0.05%" in clause
    assert "最佳止损档 -8%（Δ+0.27pp，档内 +0.31%，触发 12/217，跳空穿越 3）" in clause


def test_stop_direction_clause_unknown_and_missing_labels():
    payload = _exit_anatomy_payload()
    assert gap_disclosure.stop_direction_clause(payload, "unknown", "20260910") is None
    assert gap_disclosure.stop_direction_clause(payload, None, "20260910") is None
    assert gap_disclosure.stop_direction_clause(payload, "risk_off", "20260910") is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: "not-a-dict",
        lambda p: p.pop("production"),
        lambda p: p["production"].pop("by_regime"),
        lambda p: p["production"]["by_regime"].pop("crisis"),
        lambda p: p["production"]["by_regime"]["crisis"].pop("n_included"),
        lambda p: p["production"]["by_regime"]["crisis"].update(n_included=-1),
        lambda p: p["production"]["by_regime"]["crisis"].update(n_included="132"),
        lambda p: p["production"]["by_regime"]["crisis"].pop("base"),
        lambda p: p["production"]["by_regime"]["crisis"]["base"].update(
            mean_net=float("nan")
        ),
        lambda p: p["production"]["by_regime"]["crisis"].update(stop_grid={}),
        lambda p: p["production"]["by_regime"]["crisis"].update(stop_grid=[]),
        lambda p: p["production"]["by_regime"]["crisis"]["stop_grid"].update(
            {
                "-5%": {"delta_vs_base": float("nan")},
                "-8%": {"delta_vs_base": float("inf")},
                "-10%": {"delta_vs_base": None},
            }
        ),
    ],
)
def test_stop_direction_clause_shape_fail_open(mutate):
    payload = _exit_anatomy_payload()
    replaced = mutate(payload)
    result = gap_disclosure.stop_direction_clause(
        payload if replaced is None else replaced, "crisis", "20260910"
    )
    assert result is None


def test_stop_direction_clause_skips_malformed_tier_and_nonfinite_delta():
    """形状外键 (-7x%/bogus) 与非有限 Δ 档跳过; 最佳档在剩余有限档中选。"""
    payload = _exit_anatomy_payload()
    grid = payload["production"]["by_regime"]["crisis"]["stop_grid"]
    grid["-7x%"] = {"delta_vs_base": 9.9, "mean_net": 0.0}
    grid["bogus"] = {"delta_vs_base": 8.8, "mean_net": 0.0}
    grid["-5%"]["delta_vs_base"] = float("nan")
    clause = gap_disclosure.stop_direction_clause(payload, "crisis", "20260910")
    assert clause is not None
    # 剩余有限档中 -10% (Δ-0.22pp) 优于 -8% (Δ-0.42pp)
    assert "最佳止损档 -10%（Δ-0.22pp" in clause
    assert "-7x%" not in clause
    assert "bogus" not in clause


def test_stop_direction_clause_falsy_zero_rendered_not_dashed():
    """0.0 是读数不是缺位 (R158 家族): Δ+0.00pp / 基准 +0.00% 原样渲染。"""
    payload = {
        "production": {
            "by_regime": {
                "crisis": {
                    "n_included": 40,
                    "base": {"mean_net": 0.0},
                    "stop_grid": {
                        "-5%": {"delta_vs_base": -0.01, "mean_net": -0.01},
                        "-8%": {"delta_vs_base": 0.0, "mean_net": 0.0},
                    },
                }
            }
        }
    }
    clause = gap_disclosure.stop_direction_clause(payload, "crisis", "20260910")
    assert clause == (
        "当期方向（exit_anatomy 20260910 · 生产表/crisis/全候选，n=40）："
        "基准 +0.00% · 最佳止损档 -8%（Δ+0.00pp，档内 +0.00%）"
    )


def test_stop_direction_clause_optional_segments_omitted_gracefully():
    """档内均值/触发数/跳空缺位 → 对应段省略, 其余读数照常 (不渲染半假句)。"""
    payload = {
        "production": {
            "by_regime": {
                "crisis": {
                    "n_included": 55,
                    "base": {"mean_net": -0.02},
                    "stop_grid": {"-5%": {"delta_vs_base": 0.013}},
                }
            }
        }
    }
    clause = gap_disclosure.stop_direction_clause(payload, "crisis", "20260910")
    assert clause == (
        "当期方向（exit_anatomy 20260910 · 生产表/crisis/全候选，n=55）："
        "基准 -2.00% · 最佳止损档 -5%（Δ+1.30pp）"
    )


def _write_exit_anatomy(tmp_path, date_str, payload=None):
    path = tmp_path / f"exit_anatomy_{date_str}.json"
    path.write_text(
        json.dumps(_exit_anatomy_payload() if payload is None else payload),
        encoding="utf-8",
    )
    return path


def test_latest_exit_anatomy_report_selects_latest_dated(tmp_path):
    _write_exit_anatomy(tmp_path, "20260909")
    _write_exit_anatomy(tmp_path, "20260910")
    found = gap_disclosure.latest_exit_anatomy_report(tmp_path)
    assert found is not None
    assert found[0].name.endswith("20260910.json")
    assert isinstance(found[1], dict)


def test_latest_exit_anatomy_report_future_dated_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(
        gap_disclosure, "_today", lambda: dt.date(2026, 9, 10)
    )
    _write_exit_anatomy(tmp_path, "20260909")
    _write_exit_anatomy(tmp_path, "20990101")
    assert gap_disclosure.latest_exit_anatomy_report(tmp_path) is None


def test_stop_direction_clause_delta_tie_prefers_shallower_tier():
    """相等 Δ 平局取更浅档 (R181 Op2 P-a 钉住: 实现按档位深度升序遍历 +
    严格大于; `>=` 变异翻转为更深档必被抓)。"""
    payload = {
        "production": {
            "by_regime": {
                "crisis": {
                    "n_included": 60,
                    "base": {"mean_net": -0.03},
                    "stop_grid": {
                        "-12%": {"delta_vs_base": 0.005, "mean_net": -0.025},
                        "-5%": {"delta_vs_base": 0.005, "mean_net": -0.025},
                        "-8%": {"delta_vs_base": 0.005, "mean_net": -0.025},
                    },
                }
            }
        }
    }
    clause = gap_disclosure.stop_direction_clause(payload, "crisis", "20260910")
    assert clause is not None
    assert "最佳止损档 -5%（Δ+0.50pp" in clause
    assert "-12%" not in clause and "-8%" not in clause


def test_stop_direction_clause_unknown_bucket_in_payload_rejected():
    """payload 含真实形态的 unknown 桶 (夜刷 fillna('unknown') 可产出) 且
    as_of 标签为 unknown → None; 标签门删除变异在桶在场时必然误披露 (P-b 钉住)。"""
    payload = _exit_anatomy_payload()
    payload["production"]["by_regime"]["unknown"] = {
        "n_included": 7,
        "base": {"mean_net": -0.09, "n": 7},
        "stop_grid": {
            "-5%": {"delta_vs_base": 0.42, "mean_net": 0.33, "n": 7,
                    "n_stopped": 2, "n_gap_through": 1},
        },
    }
    assert gap_disclosure.stop_direction_clause(payload, "unknown", "20260910") is None
    assert gap_disclosure.stop_direction_clause(payload, "crisis", "20260910") is not None


def test_stop_direction_clause_zero_n_bucket_rejected():
    """n_included=0 (0 行桶不能冒充证据 — 0 行不产均值) → None (P-c 纵深)。"""
    payload = _exit_anatomy_payload()
    payload["production"]["by_regime"]["crisis"]["n_included"] = 0
    assert gap_disclosure.stop_direction_clause(payload, "crisis", "20260910") is None


def test_stop_direction_clause_empty_report_date_rejected():
    """report_date 空 (无日期的证据声明) → None (P-j 纵深: 渲染器保证日期段,
    纯函数契约独立成立)。"""
    payload = _exit_anatomy_payload()
    assert gap_disclosure.stop_direction_clause(payload, "crisis", "") is None


# ---------- R182 Op1: d1 重入邻近度当期读数子句 ----------


def _run_conditioning_payload():
    """非对称 fixture (R180 P-l 家族): run/blip 两侧读数逐值不同, 桶互换
    变异必然被抓; 数字取自真实夜刷 20260910 读数形态。"""
    return {
        "tables": {
            "t10": {
                "d1_run": {
                    "n": 341,
                    "expectancy": -0.057425,
                    "winrate": 0.30792,
                    "cluster_ci_low_90": -0.084515,
                },
                "d1_blip": {
                    "n": 460,
                    "expectancy": 0.017710,
                    "winrate": 0.536957,
                    "cluster_ci_low_90": -0.007072,
                },
            }
        },
        "run_deltas_t10": {
            "d1_run_vs_blip": {
                "ci_low": 0.024943,
                "ci_high": 0.119363,
                "n_blip": 460,
                "n_run": 341,
            }
        },
        "split_half_d1": {"consistent": True},
    }


def test_reentry_readings_clause_exact_render():
    clause = gap_disclosure.reentry_readings_clause(
        _run_conditioning_payload(), "20260910"
    )
    assert clause == (
        "当期读数（夜刷 regime_blocked_run_conditioning 20260910 · t10 净口径）："
        "d1_run E=-5.74%/胜率 30.8%（n=341）· d1_blip E=+1.77%/53.7%（n=460）· "
        "配对差 CI90 [+2.49%,+11.94%]（正值=run 罚分） · split-half 跨半一致"
    )


def test_reentry_readings_clause_bucket_swap_changes_render():
    """run/blip 两侧读数互换 → 渲染逐值不同 (R180 P-l 对称 fixture 盲区防)。"""
    payload = _run_conditioning_payload()
    t10 = payload["tables"]["t10"]
    t10["d1_run"], t10["d1_blip"] = t10["d1_blip"], t10["d1_run"]
    delta = payload["run_deltas_t10"]["d1_run_vs_blip"]
    delta["n_blip"], delta["n_run"] = delta["n_run"], delta["n_blip"]
    clause = gap_disclosure.reentry_readings_clause(payload, "20260910")
    assert clause is not None
    assert "d1_run E=+1.77%/胜率 53.7%（n=460）" in clause
    assert "d1_blip E=-5.74%/30.8%（n=341）" in clause


def test_reentry_readings_clause_ci_crossing_zero_rendered():
    """ci_low 越零 (罚分衰减/消失形态) 原样渲染 — 判定关键结构变化可见。"""
    payload = _run_conditioning_payload()
    payload["run_deltas_t10"]["d1_run_vs_blip"].update(
        ci_low=-0.012, ci_high=0.045
    )
    clause = gap_disclosure.reentry_readings_clause(payload, "20260910")
    assert clause is not None
    assert "配对差 CI90 [-1.20%,+4.50%]" in clause


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: "not-a-dict",
        lambda p: p.pop("tables"),
        lambda p: p["tables"].pop("t10"),
        lambda p: p["tables"].update(t10=[]),
        lambda p: p["tables"]["t10"].pop("d1_run"),
        lambda p: p["tables"]["t10"].pop("d1_blip"),
        lambda p: p["tables"]["t10"].update(d1_run=[]),
        lambda p: p["tables"]["t10"]["d1_run"].pop("n"),
        lambda p: p["tables"]["t10"]["d1_run"].update(n=0),
        lambda p: p["tables"]["t10"]["d1_run"].update(n=-1),
        lambda p: p["tables"]["t10"]["d1_run"].update(n=True),
        lambda p: p["tables"]["t10"]["d1_run"].update(n="341"),
        lambda p: p["tables"]["t10"]["d1_blip"].update(n=False),
        lambda p: p["tables"]["t10"]["d1_run"].pop("expectancy"),
        lambda p: p["tables"]["t10"]["d1_run"].update(expectancy=float("nan")),
        lambda p: p["tables"]["t10"]["d1_run"].update(winrate=float("inf")),
        lambda p: p["tables"]["t10"]["d1_blip"].update(expectancy=None),
        lambda p: p["tables"]["t10"]["d1_blip"].update(winrate="0.5"),
        lambda p: p.pop("run_deltas_t10"),
        lambda p: p["run_deltas_t10"].pop("d1_run_vs_blip"),
        lambda p: p["run_deltas_t10"].update(d1_run_vs_blip=[]),
        lambda p: p["run_deltas_t10"]["d1_run_vs_blip"].pop("ci_low"),
        lambda p: p["run_deltas_t10"]["d1_run_vs_blip"].update(ci_low=None),
        lambda p: p["run_deltas_t10"]["d1_run_vs_blip"].update(
            ci_high=float("nan")
        ),
        lambda p: p["run_deltas_t10"]["d1_run_vs_blip"].update(
            ci_low=0.13, ci_high=0.12
        ),
        lambda p: p["run_deltas_t10"]["d1_run_vs_blip"].update(n_run=340),
        lambda p: p["run_deltas_t10"]["d1_run_vs_blip"].update(n_blip=459),
        lambda p: p["run_deltas_t10"]["d1_run_vs_blip"].pop("n_run"),
    ],
)
def test_reentry_readings_clause_shape_fail_closed(mutate):
    payload = _run_conditioning_payload()
    replaced = mutate(payload)
    result = gap_disclosure.reentry_readings_clause(
        payload if replaced is None else replaced, "20260910"
    )
    assert result is None


def test_reentry_readings_clause_empty_report_date_rejected():
    """report_date 空 (无日期的证据声明) → None (R181 P-j 同族)。"""
    assert gap_disclosure.reentry_readings_clause(
        _run_conditioning_payload(), ""
    ) is None
    assert gap_disclosure.reentry_readings_clause(
        _run_conditioning_payload(), None
    ) is None


def test_reentry_readings_clause_split_half_optional_segments():
    """split-half 缺位/consistent 非 bool → 段省略其余照常; False → 翻转词。"""
    payload = _run_conditioning_payload()
    payload.pop("split_half_d1")
    clause = gap_disclosure.reentry_readings_clause(payload, "20260910")
    assert clause is not None
    assert "split-half" not in clause
    assert "配对差 CI90 [+2.49%,+11.94%]" in clause

    payload = _run_conditioning_payload()
    payload["split_half_d1"] = {"consistent": "true"}
    clause = gap_disclosure.reentry_readings_clause(payload, "20260910")
    assert clause is not None
    assert "split-half" not in clause

    payload = _run_conditioning_payload()
    payload["split_half_d1"] = {"consistent": False}
    clause = gap_disclosure.reentry_readings_clause(payload, "20260910")
    assert clause is not None
    assert clause.endswith("split-half 跨半翻转")


def test_latest_run_conditioning_report_selects_latest_dated(tmp_path):
    for date_str in ("20260909", "20260910"):
        path = tmp_path / f"regime_blocked_run_conditioning_{date_str}.json"
        path.write_text(
            json.dumps(_run_conditioning_payload()), encoding="utf-8"
        )
    found = gap_disclosure.latest_run_conditioning_report(tmp_path)
    assert found is not None
    assert found[0].name.endswith("20260910.json")
    assert isinstance(found[1], dict)


def test_latest_run_conditioning_report_future_dated_rejected(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(gap_disclosure, "_today", lambda: dt.date(2026, 9, 10))
    path = tmp_path / "regime_blocked_run_conditioning_20990101.json"
    path.write_text(
        json.dumps(_run_conditioning_payload()), encoding="utf-8"
    )
    assert gap_disclosure.latest_run_conditioning_report(tmp_path) is None


def test_latest_run_conditioning_report_corrupt_no_fallback(tmp_path):
    (tmp_path / "regime_blocked_run_conditioning_20260909.json").write_text(
        json.dumps(_run_conditioning_payload()), encoding="utf-8"
    )
    (tmp_path / "regime_blocked_run_conditioning_20260910.json").write_text(
        "{broken", encoding="utf-8"
    )
    assert gap_disclosure.latest_run_conditioning_report(tmp_path) is None


def test_reentry_readings_clause_bool_n_rejected_even_if_delta_consistent():
    """bool n 直接钉住 (R182 Op2 P-l): 池计数交叉守卫对 bool 计数天然失明
    (True == 1 时交叉可一致), 计数谓词的 bool 排除是独立防线 — 合成 payload
    n_run=True + delta.n_run=True 交叉一致, 唯 bool 守卫能拒。"""
    payload = _run_conditioning_payload()
    payload["tables"]["t10"]["d1_run"]["n"] = True
    payload["run_deltas_t10"]["d1_run_vs_blip"]["n_run"] = True
    assert gap_disclosure.reentry_readings_clause(payload, "20260910") is None


# ---------- R184 Op1: 重入决策锚时代外验当期读数子句 ----------


def _cross_era_payload():
    """最小 cross-era 报告形态 (数字取自 R178 时代外验真实读数形态)。"""
    return {
        "schema_version": 1,
        "verdict": {
            "d1_penalty_sign_consistent": False,
            "early_ci_excludes_current_point": None,
            "statement": (
                "d1 罚分仅当前时代可检 (早期 CI 跨零) — R168 d1 边界为时代条件"
                "证据, 不可单独据以外推"
            ),
        },
        "d1_point_penalty": {"current": -0.0751, "early": 0.0072},
    }


def test_cross_era_verdict_clause_renders_verdict_and_points():
    clause = gap_disclosure.cross_era_verdict_clause(_cross_era_payload(), "20260911")
    assert clause is not None
    assert "时代外验（夜刷 regime_run_cross_era_validation 20260911" in clause
    assert "当前点罚分 -7.51%" in clause
    assert "早期点罚分 +0.72%" in clause
    assert "两时代 方向不一致" in clause
    assert clause.endswith("不可单独据以外推") or "时代条件" in clause


def test_cross_era_verdict_clause_point_penalty_none_is_honest_dash():
    """点罚分 None (组 n<MIN_CELL_N) 合法 → '—' (工具 _fmt 同款诚实缺省)。"""
    payload = _cross_era_payload()
    payload["d1_point_penalty"] = {"current": None, "early": None}
    clause = gap_disclosure.cross_era_verdict_clause(payload, "20260911")
    assert clause is not None
    assert "当前点罚分 —" in clause
    assert "早期点罚分 —" in clause


def test_cross_era_verdict_clause_fail_closed_shapes():
    """五面畸形输入全拒 (R85/R115/R119/R182 家族): 不渲染部分垃圾。"""
    base = _cross_era_payload()
    assert gap_disclosure.cross_era_verdict_clause(base, "20260911") is not None

    # report_date 空 / 非 str
    assert gap_disclosure.cross_era_verdict_clause(base, "") is None
    assert gap_disclosure.cross_era_verdict_clause(base, None) is None
    # payload 非 dict
    assert gap_disclosure.cross_era_verdict_clause("nope", "20260911") is None
    assert gap_disclosure.cross_era_verdict_clause(None, "20260911") is None

    # verdict 缺失 / 非 dict
    payload = _cross_era_payload()
    payload.pop("verdict")
    assert gap_disclosure.cross_era_verdict_clause(payload, "20260911") is None
    payload = _cross_era_payload()
    payload["verdict"] = "x"
    assert gap_disclosure.cross_era_verdict_clause(payload, "20260911") is None

    # statement 非 str / 空
    payload = _cross_era_payload()
    payload["verdict"]["statement"] = ""
    assert gap_disclosure.cross_era_verdict_clause(payload, "20260911") is None
    payload = _cross_era_payload()
    payload["verdict"]["statement"] = 7
    assert gap_disclosure.cross_era_verdict_clause(payload, "20260911") is None

    # sign_consistent 非 bool (缺席 / None / str) — 判定谓词缺席不冒充
    for bad in (None, "false", 1):
        payload = _cross_era_payload()
        payload["verdict"]["d1_penalty_sign_consistent"] = bad
        assert gap_disclosure.cross_era_verdict_clause(payload, "20260911") is None

    # excludes 非 bool 且非 None
    payload = _cross_era_payload()
    payload["verdict"]["early_ci_excludes_current_point"] = "yes"
    assert gap_disclosure.cross_era_verdict_clause(payload, "20260911") is None

    # d1_point_penalty 缺失 / 非 dict
    payload = _cross_era_payload()
    payload.pop("d1_point_penalty")
    assert gap_disclosure.cross_era_verdict_clause(payload, "20260911") is None
    payload = _cross_era_payload()
    payload["d1_point_penalty"] = []
    assert gap_disclosure.cross_era_verdict_clause(payload, "20260911") is None

    # 点罚分非有限 / 非数值 / bool (True==1 会冒充 +100.00%)
    for bad in ("x", float("nan"), float("inf"), True):
        payload = _cross_era_payload()
        payload["d1_point_penalty"]["current"] = bad
        assert gap_disclosure.cross_era_verdict_clause(payload, "20260911") is None


def test_latest_cross_era_report_selects_latest_dated(tmp_path):
    for date_str in ("20260910", "20260911"):
        path = tmp_path / f"regime_run_cross_era_validation_{date_str}.json"
        path.write_text(json.dumps(_cross_era_payload()), encoding="utf-8")
    found = gap_disclosure.latest_cross_era_report(tmp_path)
    assert found is not None
    assert found[0].name.endswith("20260911.json")
    assert isinstance(found[1], dict)


def test_latest_cross_era_report_future_dated_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(gap_disclosure, "_today", lambda: dt.date(2026, 9, 11))
    path = tmp_path / "regime_run_cross_era_validation_20990101.json"
    path.write_text(json.dumps(_cross_era_payload()), encoding="utf-8")
    assert gap_disclosure.latest_cross_era_report(tmp_path) is None


def test_latest_cross_era_report_corrupt_no_fallback(tmp_path):
    (tmp_path / "regime_run_cross_era_validation_20260910.json").write_text(
        json.dumps(_cross_era_payload()), encoding="utf-8"
    )
    (tmp_path / "regime_run_cross_era_validation_20260911.json").write_text(
        "{broken", encoding="utf-8"
    )
    assert gap_disclosure.latest_cross_era_report(tmp_path) is None
