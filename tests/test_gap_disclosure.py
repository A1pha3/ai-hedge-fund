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
