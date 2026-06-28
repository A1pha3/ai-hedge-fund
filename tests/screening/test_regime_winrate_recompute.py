"""Tests for src.screening.regime_winrate_recompute — NS-5 daily scheduling 重算.

NS-5 (C237, 2026-06-29): daily scheduling 触发的 regime 历史胜率重算纯函数.
C234 已加 as_of + staleness 诚实披露; 本切片补 "重算" 半环 — 把硬编码
REGIME_HISTORICAL_WINRATES / REGIME_MULTIHORIZON_MEDIANS 从 tracking_history
records + auto_screening reports 重算出来, 让 owner 能 daily scheduling 刷新.

纯函数 + 真实数据 loader 分离:
- ``compute_regime_historical_winrates_from_records`` 纯函数 (本模块测试)
- ``build_date_to_regime_map`` 从 auto_screening_*.json 报告构建 date→regime 映射
- CLI ``--refresh-regime-winrates`` 串联两者 + 输出 JSON 供 owner 审阅/替换

数据流: tracking_history records (recommended_date + next_Nday_return) +
date_to_regime map (YYYYMMDD → normal/crisis/risk_off) → 按 regime 分组算
per-horizon winrate/avg/median → 匹配 REGIME_HISTORICAL_WINRATES /
REGIME_MULTIHORIZON_MEDIANS 结构 (让 owner 可直接替换硬编码值).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from src.screening.regime_winrate_recompute import (
    RegimeRecomputeResult,
    build_date_to_regime_map,
    compute_regime_historical_winrates_from_records,
    run_refresh_cli,
)


# ---------------------------------------------------------------------------
# 纯函数测试 — compute_regime_historical_winrates_from_records
# ---------------------------------------------------------------------------


def _rec(
    *,
    ticker: str = "000001",
    date_str: str = "20260601",
    t5: float | None = None,
    t10: float | None = None,
    t30: float | None = None,
) -> dict:
    """Build a minimal tracking_history record dict for tests."""
    return {
        "ticker": ticker,
        "recommended_date": date_str,
        "next_5day_return": t5,
        "next_10day_return": t10,
        "next_30day_return": t30,
    }


class TestComputeRegimeHistoricalWinratesFromRecords:
    """NS-5 重算纯函数 — 输入 records + date_to_regime, 输出 per-regime × per-horizon stats."""

    def test_empty_records_returns_empty_result(self) -> None:
        """空 records → 空 result (无 regime, 无 winrate)."""
        result = compute_regime_historical_winrates_from_records(
            records=[],
            date_to_regime={},
        )
        assert result.regime_winrates == {}
        assert result.regime_multihorizon_medians == {}
        assert result.total_records == 0
        assert result.matched_records == 0

    def test_single_regime_single_horizon_winrate(self) -> None:
        """单 regime (crisis) + 4 records (3 win + 1 loss) → T+30 winrate=75%."""
        records = [
            _rec(date_str="20260601", t30=+2.0),
            _rec(date_str="20260601", t30=+1.5),
            _rec(date_str="20260601", t30=+0.5),
            _rec(date_str="20260601", t30=-1.0),
        ]
        date_to_regime = {"20260601": "crisis"}

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
        )

        assert "crisis" in result.regime_winrates
        crisis = result.regime_winrates["crisis"]
        assert crisis["winrate"] == pytest.approx(0.75, abs=0.01)
        assert crisis["sample_count"] == 4
        # avg = (2.0 + 1.5 + 0.5 + (-1.0)) / 4 = 0.75
        assert crisis["avg_return"] == pytest.approx(0.75, abs=0.01)
        # median of [2.0, 1.5, 0.5, -1.0] = (1.5 + 0.5) / 2 = 1.0
        assert crisis["median_return"] == pytest.approx(1.0, abs=0.01)

    def test_multiple_regimes_grouped_correctly(self) -> None:
        """3 regimes (normal/crisis/risk_off) → 各自独立分组."""
        records = [
            _rec(date_str="20260601", t30=+1.0),  # crisis
            _rec(date_str="20260602", t30=-1.0),  # normal
            _rec(date_str="20260603", t30=-2.0),  # risk_off
        ]
        date_to_regime = {
            "20260601": "crisis",
            "20260602": "normal",
            "20260603": "risk_off",
        }

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
        )

        assert set(result.regime_winrates.keys()) == {"crisis", "normal", "risk_off"}
        assert result.regime_winrates["crisis"]["winrate"] == pytest.approx(1.0)
        assert result.regime_winrates["normal"]["winrate"] == pytest.approx(0.0)
        assert result.regime_winrates["risk_off"]["winrate"] == pytest.approx(0.0)
        assert result.matched_records == 3

    def test_record_without_regime_mapping_skipped(self) -> None:
        """record 的 recommended_date 不在 date_to_regime → 跳过 (matched < total)."""
        records = [
            _rec(date_str="20260601", t30=+1.0),  # 有 regime 映射
            _rec(date_str="20260602", t30=+1.0),  # 无 regime 映射
        ]
        date_to_regime = {"20260601": "crisis"}

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
        )

        assert result.total_records == 2
        assert result.matched_records == 1
        assert "crisis" in result.regime_winrates
        assert result.regime_winrates["crisis"]["sample_count"] == 1

    def test_multihorizon_medians_computed(self) -> None:
        """T+5/T+10/T+30 三 horizon 的 median/winrate/n 都计算."""
        records = [
            _rec(date_str="20260601", t5=+1.0, t10=+2.0, t30=+3.0),
            _rec(date_str="20260601", t5=-1.0, t10=-2.0, t30=-3.0),
        ]
        date_to_regime = {"20260601": "crisis"}

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
        )

        crisis_multi = result.regime_multihorizon_medians["crisis"]
        assert "t5" in crisis_multi
        assert "t10" in crisis_multi
        assert "t30" in crisis_multi
        # T+5: [+1.0, -1.0] → median=0.0, winrate=0.5, n=2
        assert crisis_multi["t5"]["median"] == pytest.approx(0.0, abs=0.01)
        assert crisis_multi["t5"]["winrate"] == pytest.approx(0.5)
        assert crisis_multi["t5"]["n"] == 2
        # T+10: [+2.0, -2.0] → median=0.0, winrate=0.5, n=2
        assert crisis_multi["t10"]["median"] == pytest.approx(0.0, abs=0.01)
        # T+30: [+3.0, -3.0] → median=0.0, winrate=0.5, n=2
        assert crisis_multi["t30"]["median"] == pytest.approx(0.0, abs=0.01)

    def test_min_samples_gate_returns_insufficient(self) -> None:
        """n < min_samples → 该 regime 不入 result (insufficient)."""
        records = [
            _rec(date_str="20260601", t30=+1.0),
            _rec(date_str="20260601", t30=+1.0),
        ]
        date_to_regime = {"20260601": "risk_off"}

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
            min_samples=5,  # n=2 < 5 → insufficient
        )

        # risk_off 不入 regime_winrates (n < min_samples)
        assert "risk_off" not in result.regime_winrates
        # 但 multihorizon_medians 也不应含 risk_off
        assert "risk_off" not in result.regime_multihorizon_medians

    def test_record_with_none_return_skipped_for_that_horizon(self) -> None:
        """record 的某 horizon return=None → 该 horizon 跳过此 record (其他 horizon 仍算)."""
        records = [
            _rec(date_str="20260601", t5=+1.0, t10=None, t30=+3.0),
            _rec(date_str="20260601", t5=+2.0, t10=+4.0, t30=+6.0),
        ]
        date_to_regime = {"20260601": "crisis"}

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
        )

        crisis_multi = result.regime_multihorizon_medians["crisis"]
        # T+5: 2 records (both have t5)
        assert crisis_multi["t5"]["n"] == 2
        # T+10: 1 record (first has t10=None)
        assert crisis_multi["t10"]["n"] == 1
        # T+30: 2 records (both have t30)
        assert crisis_multi["t30"]["n"] == 2

    def test_as_of_set_to_today_by_default(self) -> None:
        """as_of 默认 = date.today() (重算时点)."""
        records = [_rec(date_str="20260601", t30=+1.0)]
        date_to_regime = {"20260601": "crisis"}

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
        )

        assert result.as_of == date.today()

    def test_as_of_injectable_for_testing(self) -> None:
        """as_of 可注入固定日期 (测试用, 避免时间漂移)."""
        records = [_rec(date_str="20260601", t30=+1.0)]
        date_to_regime = {"20260601": "crisis"}

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
            as_of=date(2026, 6, 29),
        )

        assert result.as_of == date(2026, 6, 29)

    def test_regime_case_insensitive(self) -> None:
        """regime 值大小写不敏感 ('Crisis' == 'crisis')."""
        records = [_rec(date_str="20260601", t30=+1.0)]
        date_to_regime = {"20260601": "Crisis"}  # 大写

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
        )

        assert "crisis" in result.regime_winrates  # 归一化到小写

    def test_unknown_regime_value_skipped(self) -> None:
        """regime 值不在 {normal, crisis, risk_off} → 跳过 (不污染 result)."""
        records = [
            _rec(date_str="20260601", t30=+1.0),
            _rec(date_str="20260602", t30=+1.0),
        ]
        date_to_regime = {
            "20260601": "crisis",
            "20260602": "unknown_regime",  # 非法值
        }

        result = compute_regime_historical_winrates_from_records(
            records=records,
            date_to_regime=date_to_regime,
        )

        # 只 crisis 入 result, unknown_regime 跳过
        assert set(result.regime_winrates.keys()) == {"crisis"}
        assert result.matched_records == 1  # 只 crisis 那条算 matched


# ---------------------------------------------------------------------------
# Loader 测试 — build_date_to_regime_map
# ---------------------------------------------------------------------------


class TestBuildDateToRegimeMap:
    """从 auto_screening_*.json 报告构建 date→regime 映射."""

    def test_empty_dir_returns_empty_map(self, tmp_path: Path) -> None:
        """空目录 → 空 map."""
        result = build_date_to_regime_map(tmp_path)
        assert result == {}

    def test_single_report_extracts_date_and_regime(self, tmp_path: Path) -> None:
        """单 auto_screening 报告 → 提取 date + regime_gate_level."""
        report = {
            "date": "20260601",
            "market_state": {"regime_gate_level": "crisis"},
        }
        (tmp_path / "auto_screening_20260601.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

        result = build_date_to_regime_map(tmp_path)

        assert result == {"20260601": "crisis"}

    def test_multiple_reports_built_into_map(self, tmp_path: Path) -> None:
        """多 auto_screening 报告 → 全部提取."""
        for d, r in [
            ("20260601", "crisis"),
            ("20260602", "normal"),
            ("20260603", "risk_off"),
        ]:
            report = {"date": d, "market_state": {"regime_gate_level": r}}
            (tmp_path / f"auto_screening_{d}.json").write_text(
                json.dumps(report), encoding="utf-8"
            )

        result = build_date_to_regime_map(tmp_path)

        assert result == {
            "20260601": "crisis",
            "20260602": "normal",
            "20260603": "risk_off",
        }

    def test_report_missing_regime_defaults_to_normal(self, tmp_path: Path) -> None:
        """报告缺 regime_gate_level → 默认 'normal' (与 market_state_helpers 一致)."""
        report = {"date": "20260601", "market_state": {}}  # 无 regime_gate_level
        (tmp_path / "auto_screening_20260601.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

        result = build_date_to_regime_map(tmp_path)

        assert result == {"20260601": "normal"}

    def test_non_auto_screening_files_ignored(self, tmp_path: Path) -> None:
        """非 auto_screening_*.json 文件 → 忽略."""
        (tmp_path / "rebalance_20260601.json").write_text(
            json.dumps({"date": "20260601", "market_state": {"regime_gate_level": "crisis"}}),
            encoding="utf-8",
        )
        (tmp_path / "random.json").write_text("{}", encoding="utf-8")

        result = build_date_to_regime_map(tmp_path)

        assert result == {}

    def test_malformed_json_skipped(self, tmp_path: Path) -> None:
        """损坏 JSON 文件 → 跳过 (不 raise)."""
        (tmp_path / "auto_screening_20260601.json").write_text(
            "not valid json {{{", encoding="utf-8"
        )
        # 一个有效文件仍能处理
        valid = {"date": "20260602", "market_state": {"regime_gate_level": "normal"}}
        (tmp_path / "auto_screening_20260602.json").write_text(
            json.dumps(valid), encoding="utf-8"
        )

        result = build_date_to_regime_map(tmp_path)

        assert result == {"20260602": "normal"}


# ---------------------------------------------------------------------------
# Result dataclass 测试
# ---------------------------------------------------------------------------


class TestRegimeRecomputeResultSerialization:
    """RegimeRecomputeResult 支持 to_dict 序列化 (CLI 输出 JSON 用)."""

    def test_to_dict_round_trip(self) -> None:
        """to_dict 输出可 JSON 序列化."""
        result = RegimeRecomputeResult(
            regime_winrates={"crisis": {"winrate": 0.5, "avg_return": 1.0, "median_return": 0.5, "sample_count": 10}},
            regime_multihorizon_medians={"crisis": {"t5": {"median": 0.5, "winrate": 0.6, "n": 10}}},
            as_of=date(2026, 6, 29),
            total_records=100,
            matched_records=95,
        )
        d = result.to_dict()
        # 可 JSON 序列化
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed["regime_winrates"]["crisis"]["winrate"] == 0.5
        assert parsed["as_of"] == "2026-06-29"


# ---------------------------------------------------------------------------
# CLI runner 测试 — run_refresh_cli (端到端: load records + build map + compute + output)
# ---------------------------------------------------------------------------


def _write_tracking_history(reports_dir: Path, records: list[dict]) -> None:
    """写入 tracking_history.json (与 recommendation_tracker._save_history 结构一致)."""
    payload = {"records": records, "updated_at": "20260629000000"}
    (reports_dir / "tracking_history.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_auto_screening_report(
    reports_dir: Path, date_str: str, regime: str
) -> None:
    """写入最小 auto_screening_{date}.json (含 date + market_state.regime_gate_level)."""
    payload = {
        "date": date_str,
        "market_state": {"regime_gate_level": regime},
    }
    (reports_dir / f"auto_screening_{date_str}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


class TestRunRefreshCli:
    """NS-5 CLI runner — 端到端流程: load + build + compute + output JSON."""

    def test_end_to_end_outputs_json_to_stdout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """合成 reports_dir + tracking_history.json → stdout 输出 JSON."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()

        # 写入 2 个 auto_screening 报告 (不同 regime)
        _write_auto_screening_report(reports_dir, "20260601", "crisis")
        _write_auto_screening_report(reports_dir, "20260602", "normal")

        # 写入 tracking_history records (12 条 crisis + 12 条 normal, 都 t30 mature)
        crisis_recs = [
            _rec(date_str="20260601", t5=+1.0, t10=+2.0, t30=+3.0) for _ in range(12)
        ]
        normal_recs = [
            _rec(date_str="20260602", t5=-1.0, t10=-2.0, t30=-3.0) for _ in range(12)
        ]
        _write_tracking_history(reports_dir, crisis_recs + normal_recs)

        rc = run_refresh_cli(reports_dir=reports_dir, min_samples=10)

        assert rc == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        # crisis 12 条全胜 (t30=+3.0 > 0) → winrate=1.0
        assert parsed["regime_winrates"]["crisis"]["winrate"] == pytest.approx(1.0)
        assert parsed["regime_winrates"]["crisis"]["sample_count"] == 12
        # normal 12 条全败 (t30=-3.0 < 0) → winrate=0.0
        assert parsed["regime_winrates"]["normal"]["winrate"] == pytest.approx(0.0)
        assert parsed["regime_winrates"]["normal"]["sample_count"] == 12
        # multihorizon 也填充
        assert "t5" in parsed["regime_multihorizon_medians"]["crisis"]
        assert "t10" in parsed["regime_multihorizon_medians"]["crisis"]
        assert "t30" in parsed["regime_multihorizon_medians"]["crisis"]
        # as_of 是 ISO 字符串
        assert "as_of" in parsed
        # reports_dir 也回显
        assert parsed["reports_dir"] == str(reports_dir)
        assert parsed["min_samples_threshold"] == 10

    def test_output_to_file(self, tmp_path: Path) -> None:
        """--output=path → 写入文件 + stdout 仅输出摘要."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        _write_auto_screening_report(reports_dir, "20260601", "crisis")
        recs = [_rec(date_str="20260601", t30=+1.0) for _ in range(12)]
        _write_tracking_history(reports_dir, recs)

        output_path = tmp_path / "out" / "regime_winrates.json"
        rc = run_refresh_cli(
            reports_dir=reports_dir,
            output_path=output_path,
            min_samples=10,
        )

        assert rc == 0
        assert output_path.exists()
        parsed = json.loads(output_path.read_text(encoding="utf-8"))
        assert parsed["regime_winrates"]["crisis"]["sample_count"] == 12

    def test_returns_1_when_no_tracking_history(self, tmp_path: Path) -> None:
        """tracking_history.json 缺失 → 返回 1 (优雅降级, 不崩溃)."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        _write_auto_screening_report(reports_dir, "20260601", "crisis")
        # 不写 tracking_history.json

        rc = run_refresh_cli(reports_dir=reports_dir, min_samples=10)
        assert rc == 1

    def test_returns_1_when_no_auto_screening_reports(
        self, tmp_path: Path
    ) -> None:
        """auto_screening_*.json 缺失 → date_to_regime 空 → 返回 1."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        # 只写 tracking_history, 不写 auto_screening
        _write_tracking_history(
            reports_dir,
            [_rec(date_str="20260601", t30=+1.0)],
        )

        rc = run_refresh_cli(reports_dir=reports_dir, min_samples=10)
        assert rc == 1

    def test_returns_1_when_reports_dir_not_exist(self, tmp_path: Path) -> None:
        """reports_dir 不存在 → 返回 1."""
        rc = run_refresh_cli(
            reports_dir=tmp_path / "nonexistent",
            min_samples=10,
        )
        assert rc == 1

    def test_min_samples_filter_applied(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """min_samples=20 → n=12 的 regime 被过滤掉 (regime_winrates 为空)."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        _write_auto_screening_report(reports_dir, "20260601", "crisis")
        recs = [_rec(date_str="20260601", t30=+1.0) for _ in range(12)]
        _write_tracking_history(reports_dir, recs)

        rc = run_refresh_cli(reports_dir=reports_dir, min_samples=20)

        assert rc == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        # n=12 < min_samples=20 → crisis 不入 result
        assert "crisis" not in parsed["regime_winrates"]
        assert parsed["matched_records"] == 12  # records 仍 matched, 只是 regime 被过滤
        assert parsed["total_records"] == 12
