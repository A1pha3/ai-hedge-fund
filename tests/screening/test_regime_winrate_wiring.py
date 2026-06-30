"""NS-5 wiring tests — production reads recomputed JSON when available.

C234 (2026-06-28) 加了 as_of + staleness 诚实披露 + daily scheduling 重算脚本
(``run_daily_regime_refresh`` writes ``regime_winrates_recomputed_<date>.json``).
但生产代码仍读 hardcoded ``REGIME_HISTORICAL_WINRATES`` /
``REGIME_MULTIHORIZON_MEDIANS`` — JSON artifact 写了但从不消费, 重算半环
断裂 (daily 重算白跑).

本测试覆盖 wiring 半环:
- :func:`load_latest_regime_recompute` — 找最新 ``regime_winrates_recomputed_*.json``
  artifact 并解析 (无 artifact / 损坏 JSON → ``None``).
- :func:`compute_regime_winrate_summary` 优先读 JSON, fallback 到 hardcoded.
- :func:`render_regime_multihorizon_line` 优先读 JSON, fallback 到 hardcoded.
- ``RegimeWinrateSummary.source`` 标注数据来源 (``recomputed_json`` |
  ``hardcoded_fallback``) — 让 owner 一眼看出数据是否 fresh.

测试策略: 写合成 JSON 到 ``tmp_path``, 通过 ``reports_dir=tmp_path`` 注入,
绕过 conftest autouse fixture (默认 disable JSON loading 保 existing tests
deterministic).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.screening.regime_winrate import (
    compute_regime_winrate_summary,
    render_regime_multihorizon_line,
    load_latest_regime_recompute,
)


# ---------------------------------------------------------------------------
# 测试辅助: 合成 JSON artifact + 显式恢复 loader
# ---------------------------------------------------------------------------


def _restore_real_loader(monkeypatch: pytest.MonkeyPatch):
    """撤销 conftest autouse fixture 对 ``load_latest_regime_recompute`` 的 patch.

    conftest 默认把 ``load_latest_regime_recompute`` patch 成返回 ``None``
    (让 existing fallback 测试保持 deterministic). 本测试文件的 case 需要
    真实 loader 行为, 因此显式恢复.
    """
    import src.screening.regime_winrate as rw

    # conftest 把真实 loader 存到 _real_load_latest_regime_recompute
    real = getattr(rw, "_real_load_latest_regime_recompute", None)
    if real is None:
        # conftest 未 patch (或 fixture 未运行), 用模块原始 loader
        real = rw.__dict__.get("load_latest_regime_recompute")
    if real is not None:
        monkeypatch.setattr(rw, "load_latest_regime_recompute", real)


def _write_synthetic_json(
    tmp_path: Path,
    *,
    as_of: str = "2026-06-30",
    crisis_winrate: float = 0.531,
    crisis_median: float = 1.73,
    crisis_sample: int = 1762,
    normal_winrate: float = 0.444,
    risk_off_winrate: float = 0.340,
    t15_crisis_median: float = 3.67,
    t20_crisis_median: float = 4.19,
    t25_crisis_median: float = 5.47,
    t30_crisis_median: float = 1.73,
    t30_crisis_n: int = 1762,
) -> Path:
    """写一个合成 ``regime_winrates_recomputed_<date>.json`` 到 ``tmp_path``."""
    payload = {
        "regime_winrates": {
            "crisis": {
                "winrate": crisis_winrate,
                "avg_return": 10.16,
                "median_return": crisis_median,
                "sample_count": crisis_sample,
            },
            "normal": {
                "winrate": normal_winrate,
                "avg_return": 5.22,
                "median_return": -3.09,
                "sample_count": 5610,
            },
            "risk_off": {
                "winrate": risk_off_winrate,
                "avg_return": -1.33,
                "median_return": -9.78,
                "sample_count": 620,
            },
        },
        "regime_multihorizon_medians": {
            "crisis": {
                "t5":  {"median": 3.98, "winrate": 0.689, "n": 1763},
                "t10": {"median": 4.66, "winrate": 0.646, "n": 1763},
                "t15": {"median": t15_crisis_median, "winrate": 0.607, "n": 1763},
                "t20": {"median": t20_crisis_median, "winrate": 0.587, "n": 1763},
                "t25": {"median": t25_crisis_median, "winrate": 0.607, "n": 1763},
                "t30": {"median": t30_crisis_median, "winrate": 0.531, "n": t30_crisis_n},
            },
            "normal": {
                "t5":  {"median": 1.12, "winrate": 0.567, "n": 5610},
                "t10": {"median": 1.78, "winrate": 0.565, "n": 5610},
                "t15": {"median": 1.49, "winrate": 0.543, "n": 5610},
                "t20": {"median": 0.11, "winrate": 0.502, "n": 5610},
                "t25": {"median": -2.03, "winrate": 0.461, "n": 5610},
                "t30": {"median": -3.09, "winrate": 0.444, "n": 5610},
            },
            "risk_off": {
                "t5":  {"median": 0.80, "winrate": 0.527, "n": 620},
                "t10": {"median": 4.91, "winrate": 0.692, "n": 620},
                "t15": {"median": 0.32, "winrate": 0.506, "n": 620},
                "t20": {"median": -2.80, "winrate": 0.415, "n": 620},
                "t25": {"median": -5.41, "winrate": 0.403, "n": 620},
                "t30": {"median": -9.78, "winrate": 0.340, "n": 620},
            },
        },
        "as_of": as_of,
        "total_records": 8003,
        "matched_records": 8003,
        "min_samples_threshold": 10,
        "reports_dir": str(tmp_path),
    }
    out = tmp_path / f"regime_winrates_recomputed_{as_of.replace('-', '')}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# load_latest_regime_recompute — loader 纯函数
# ---------------------------------------------------------------------------


class TestLoadLatestRegimeRecompute:
    """loader: 找最新 ``regime_winrates_recomputed_*.json`` 并解析."""

    def test_returns_none_when_no_artifact(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """目录无 artifact → 返回 None."""
        _restore_real_loader(monkeypatch)
        result = load_latest_regime_recompute(reports_dir=tmp_path)
        assert result is None

    def test_returns_none_when_dir_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """reports_dir 不存在 → 返回 None (不 raise)."""
        _restore_real_loader(monkeypatch)
        result = load_latest_regime_recompute(reports_dir=Path("/nonexistent/path/xyz"))
        assert result is None

    def test_parses_latest_artifact_by_date_suffix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """多 artifact 时按文件名日期后缀选最新 (20260630 > 20260625)."""
        _restore_real_loader(monkeypatch)
        # 写两个 artifact, 旧的 + 新的
        _write_synthetic_json(tmp_path, as_of="2026-06-25", crisis_winrate=0.40)
        _write_synthetic_json(tmp_path, as_of="2026-06-30", crisis_winrate=0.531)

        result = load_latest_regime_recompute(reports_dir=tmp_path)
        assert result is not None
        # 应返回 20260630 的 (crisis_winrate=0.531, 不是 0.40)
        crisis = result["regime_winrates"]["crisis"]
        assert crisis["winrate"] == pytest.approx(0.531, abs=0.001)

    def test_returns_none_on_malformed_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """损坏 JSON → 返回 None (不 raise)."""
        _restore_real_loader(monkeypatch)
        bad = tmp_path / "regime_winrates_recomputed_20260630.json"
        bad.write_text("{not valid json", encoding="utf-8")
        result = load_latest_regime_recompute(reports_dir=tmp_path)
        assert result is None

    def test_returns_payload_with_expected_fields(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """返回的 dict 含 regime_winrates / regime_multihorizon_medians / as_of."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path)
        result = load_latest_regime_recompute(reports_dir=tmp_path)
        assert result is not None
        assert "regime_winrates" in result
        assert "regime_multihorizon_medians" in result
        assert result["as_of"] == "2026-06-30"

    def test_ignores_non_matching_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """非 ``regime_winrates_recomputed_*.json`` 文件忽略."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path, as_of="2026-06-30")
        # 干扰文件
        (tmp_path / "regime_winrates_other.json").write_text("{}", encoding="utf-8")
        (tmp_path / "auto_screening_20260630.json").write_text("{}", encoding="utf-8")
        result = load_latest_regime_recompute(reports_dir=tmp_path)
        assert result is not None


# ---------------------------------------------------------------------------
# compute_regime_winrate_summary — JSON override path
# ---------------------------------------------------------------------------


class TestComputeRegimeWinrateSummaryJsonOverride:
    """compute_regime_winrate_summary: 优先读 JSON, fallback 到 hardcoded."""

    def test_json_overrides_hardcoded_winrate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """有 JSON 时 crisis winrate 用 JSON 的 0.531 (非 hardcoded 0.468)."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path, crisis_winrate=0.531)
        s = compute_regime_winrate_summary("crisis", reports_dir=tmp_path)
        assert s.has_data is True
        assert s.winrate == pytest.approx(0.531, abs=0.001)
        # 显著不同于 hardcoded 0.468
        assert abs(s.winrate - 0.468) > 0.05

    def test_json_overrides_hardcoded_sample_count(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON sample_count (1762) 替代 hardcoded (119)."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path, crisis_sample=1762)
        s = compute_regime_winrate_summary("crisis", reports_dir=tmp_path)
        assert s.sample_count == 1762

    def test_json_overrides_as_of_date(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """as_of 用 JSON 的 (2026-06-30), 非 hardcoded (2026-06-25)."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path, as_of="2026-06-30")
        s = compute_regime_winrate_summary("crisis", reports_dir=tmp_path)
        assert s.as_of == date(2026, 6, 30)

    def test_source_marks_recomputed_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON 命中时 source='recomputed_json'."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path)
        s = compute_regime_winrate_summary("crisis", reports_dir=tmp_path)
        assert s.source == "recomputed_json"

    def test_source_marks_hardcoded_fallback_when_no_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 JSON 时 source='hardcoded_fallback' (conftest 默认 disable loader)."""
        # conftest autouse fixture 已经把 loader patch 成返回 None
        # 不调用 _restore_real_loader, 保留 fallback
        s = compute_regime_winrate_summary("crisis")
        assert s.has_data is True
        assert s.source == "hardcoded_fallback"

    def test_unknown_regime_still_no_data_with_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """未知 regime 即使有 JSON 也 has_data=False."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path)
        s = compute_regime_winrate_summary("bogus_regime", reports_dir=tmp_path)
        assert s.has_data is False
        assert s.as_of is None

    def test_normal_regime_uses_json_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """normal regime 优先用 JSON (winrate 0.444, sample 5610)."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path, normal_winrate=0.444)
        s = compute_regime_winrate_summary("normal", reports_dir=tmp_path)
        assert s.winrate == pytest.approx(0.444, abs=0.001)
        assert s.sample_count == 5610

    def test_risk_off_regime_uses_json_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """risk_off regime 优先用 JSON (winrate 0.340, sample 620)."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path, risk_off_winrate=0.340)
        s = compute_regime_winrate_summary("risk_off", reports_dir=tmp_path)
        assert s.winrate == pytest.approx(0.340, abs=0.001)
        assert s.sample_count == 620


# ---------------------------------------------------------------------------
# render_regime_multihorizon_line — JSON override path
# ---------------------------------------------------------------------------


class TestRenderRegimeMultihorizonLineJsonOverride:
    """render_regime_multihorizon_line: 优先读 JSON medians."""

    def test_json_medians_override_hardcoded(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON t15/t20/t25/t30 median 替代 hardcoded."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(
            tmp_path,
            t15_crisis_median=3.67,
            t20_crisis_median=4.19,
            t25_crisis_median=5.47,
            t30_crisis_median=1.73,
        )
        line = render_regime_multihorizon_line("crisis", reports_dir=tmp_path)
        assert line != ""
        # JSON t15=3.67 应出现 (hardcoded 是 -0.0)
        assert "3.7%" in line or "3.67" in line
        # JSON t30=1.73 应出现 (hardcoded 是 -1.6)
        assert "+1.7%" in line or "1.73" in line

    def test_json_as_of_shown_in_render(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """渲染输出含 JSON 的 as_of (2026-06-30), 非 hardcoded (2026-06-25)."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path, as_of="2026-06-30")
        line = render_regime_multihorizon_line("crisis", reports_dir=tmp_path)
        assert "2026-06-30" in line
        assert "2026-06-25" not in line

    def test_json_sample_count_in_render(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """渲染输出含 JSON 的 n= (1762+), 非 hardcoded (163+)."""
        _restore_real_loader(monkeypatch)
        _write_synthetic_json(tmp_path, t30_crisis_n=1762)
        line = render_regime_multihorizon_line("crisis", reports_dir=tmp_path)
        assert "n=1762" in line

    def test_fresh_json_no_stale_warning(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """JSON as_of=today → 无 ⚠ 过时提示."""
        _restore_real_loader(monkeypatch)
        # as_of = today, 不 stale
        _write_synthetic_json(tmp_path, as_of=date.today().isoformat())
        line = render_regime_multihorizon_line(
            "crisis", reports_dir=tmp_path, today=date.today()
        )
        assert "过时" not in line


# ---------------------------------------------------------------------------
# 集成: 从 None → hardcoded fallback 行为
# ---------------------------------------------------------------------------


class TestHardcodedFallbackIntact:
    """wiring 上线后, 无 JSON 时 fallback 行为保持不变 (existing tests 兼容)."""

    def test_crisis_fallback_uses_hardcoded_winrate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 JSON → crisis winrate = hardcoded 0.468 (conftest 默认 disable loader)."""
        s = compute_regime_winrate_summary("crisis")
        assert s.winrate == pytest.approx(0.468, abs=0.01)
        assert s.source == "hardcoded_fallback"

    def test_fallback_as_of_uses_hardcoded_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 JSON → as_of = hardcoded 2026-06-25."""
        s = compute_regime_winrate_summary("crisis")
        assert s.as_of == date(2026, 6, 25)

    def test_fallback_render_uses_hardcoded_date(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无 JSON → 渲染输出含 hardcoded 2026-06-25."""
        line = render_regime_multihorizon_line("crisis")
        assert "2026-06-25" in line
