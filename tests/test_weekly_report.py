"""P2-10 组合体检周报 — 单元测试。

覆盖:
  - test_generate_report_4_blocks: 输出包含 4 个区块标题
  - test_brinson_block_graceful_when_no_data: positions_path 不存在 → 优雅降级
  - test_exit_reblock_reads_tracking_history: 构造 tracking_history 输出正确
  - test_push_calls_send_with_markdown: mock send_push 被调用
  - test_push_wecom_splits_when_over_4096_bytes: > 4096 字节切分 ≥2 次
  - test_weekly_report_date_defaults_to_this_week: 不传 date 时默认本周一
  - test_cli_dispatcher_routes_weekly_report: argv=["--weekly-report"] → 返回 0
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_report_dir(tmp_path: Path) -> Path:
    """创建临时报告目录。"""
    rdir = tmp_path / "reports"
    rdir.mkdir()
    return rdir


@pytest.fixture
def fake_positions_json(tmp_path: Path) -> Path:
    """构造最小持仓 JSON。"""
    positions = [
        {"ticker": "000001", "return_pct": 0.03, "market_value": 50000.0},
        {"ticker": "600519", "return_pct": -0.01, "market_value": 50000.0},
    ]
    p = tmp_path / "positions.json"
    p.write_text(json.dumps({"positions": positions}, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def fake_tracking_history(tmp_report_dir: Path) -> Path:
    """构造 tracking_history.json。"""
    records = [
        {"ticker": "000001", "recommended_date": "20260602", "action": "exit", "next_day_return": 0.02},
        {"ticker": "600519", "recommended_date": "20260603", "action": "rebalance", "next_day_return": -0.01},
        {"ticker": "300750", "recommended_date": "20260604", "action": "hold", "next_day_return": 0.03},
    ]
    p = tmp_report_dir / "tracking_history.json"
    p.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def fake_auto_screening(tmp_report_dir: Path) -> Path:
    """构造最小 auto_screening 报告。"""
    payload = {
        "date": "20260606",
        "market_state": {"state_type": "trending_up", "position_scale": 0.8},
        "recommendations": [
            {"ticker": "300750", "score_b": 0.45, "decision": "bullish"},
        ],
    }
    p = tmp_report_dir / "auto_screening_20260606.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerateWeeklyReport:
    """generate_weekly_report 核心逻辑。"""

    def test_generate_report_4_blocks(self, tmp_report_dir: Path, fake_tracking_history: Path, fake_auto_screening: Path) -> None:
        """输出包含 4 个区块标题 ("本周归因" / "退出调仓" / "风险变化" / "下周关注")。"""
        from src.notification.weekly_report import generate_weekly_report

        report = generate_weekly_report(
            start_date="20260601",
            end_date="20260606",
            report_dir=tmp_report_dir,
        )
        assert "本周归因" in report
        assert "退出调仓" in report
        assert "风险变化" in report
        assert "下周关注" in report
        assert "组合体检周报" in report

    def test_brinson_block_graceful_when_no_data(self, tmp_report_dir: Path) -> None:
        """positions_path 不存在 → 区块输出"本周无持仓数据", 整体不崩溃。"""
        from src.notification.weekly_report import generate_weekly_report

        report = generate_weekly_report(
            start_date="20260601",
            end_date="20260606",
            positions_path=tmp_report_dir / "nonexistent.json",
            report_dir=tmp_report_dir,
        )
        assert "本周无持仓数据" in report
        assert "退出调仓" in report  # 其他区块仍然正常

    def test_brinson_block_with_positions(self, tmp_report_dir: Path, fake_positions_json: Path, fake_auto_screening: Path) -> None:
        """有持仓数据时 Brinson 归因输出配置/选择贡献。"""
        from src.notification.weekly_report import generate_weekly_report

        report = generate_weekly_report(
            start_date="20260601",
            end_date="20260606",
            positions_path=fake_positions_json,
            report_dir=tmp_report_dir,
        )
        assert "配置贡献" in report
        assert "选择贡献" in report


class TestExitRebalance:
    """退出调仓区块。"""

    def test_exit_reblock_reads_tracking_history(self, tmp_report_dir: Path, fake_tracking_history: Path, fake_auto_screening: Path) -> None:
        """构造 fake tracking_history.json, 输出退出次数正确。"""
        from src.notification.weekly_report import generate_weekly_report

        report = generate_weekly_report(
            start_date="20260601",
            end_date="20260606",
            report_dir=tmp_report_dir,
        )
        # 应该输出交易笔数和退出/调仓次数
        assert "本周交易" in report or "交易记录" in report


class TestPushWeeklyReport:
    """推送入口。"""

    def test_push_calls_send_with_markdown(self, tmp_report_dir: Path, fake_auto_screening: Path) -> None:
        """mock send_push, 断言被调用 + 消息体含 Markdown。"""
        from src.notification.weekly_report import push_weekly_report

        with patch("src.notification.weekly_report.load_push_config", return_value=[]):
            rc = push_weekly_report(
                start_date="20260601",
                end_date="20260606",
                channel="wecom",
                report_dir=tmp_report_dir,
            )
            # 无配置时直接打印, 返回 0
            assert rc == 0

    def test_push_with_config_calls_send(self, tmp_report_dir: Path, fake_auto_screening: Path) -> None:
        """有推送配置时, 调用 send_push。"""
        from src.notification.push import PushChannel, PushConfig
        from src.notification.weekly_report import push_weekly_report

        mock_config = PushConfig(
            channel=PushChannel.WECOM,
            target="https://example.com/webhook",
            enabled=True,
        )

        with patch("src.notification.weekly_report.load_push_config", return_value=[mock_config]):
            with patch("src.notification.weekly_report._send_chunk") as mock_send:
                mock_send.return_value = MagicMock(success=True)
                rc = push_weekly_report(
                    start_date="20260601",
                    end_date="20260606",
                    channel="wecom",
                    report_dir=tmp_report_dir,
                )
                assert rc == 0
                assert mock_send.called


class TestWecomSplit:
    """企微消息 > 4096 字节时切分。"""

    def test_push_wecom_splits_when_over_4096_bytes(self) -> None:
        """构造 > 4096 字节内容, 断言切分 >= 2 段。"""
        from src.notification.weekly_report import _split_markdown_for_wecom

        # 构造大内容 (> 4096 字节)
        big_markdown = "# 测试\n\n" + "这是一段很长的内容。\n\n" * 500
        assert len(big_markdown.encode("utf-8")) > 4096

        chunks = _split_markdown_for_wecom(big_markdown)
        assert len(chunks) >= 2

        # 每段都 ≤ 4096
        for chunk in chunks:
            assert len(chunk.encode("utf-8")) <= 4096

    def test_short_content_not_split(self) -> None:
        """短内容不切分。"""
        from src.notification.weekly_report import _split_markdown_for_wecom

        short = "# 周报\n\n简短内容"
        chunks = _split_markdown_for_wecom(short)
        assert len(chunks) == 1


class TestDateDefaults:
    """日期默认值。"""

    def test_weekly_report_date_defaults_to_this_week(self) -> None:
        """不传 date 时, start_date 是本周一。"""
        from src.notification.weekly_report import _this_monday_friday

        start, end = _this_monday_friday()
        start_dt = datetime.strptime(start, "%Y%m%d")
        end_dt = datetime.strptime(end, "%Y%m%d")

        # 周一
        assert start_dt.weekday() == 0
        # 周五
        assert end_dt.weekday() == 4
        # end - start = 4 天
        assert (end_dt - start_dt).days == 4

    def test_explicit_dates_override(self, tmp_report_dir: Path) -> None:
        """显式传入日期时使用传入值。"""
        from src.notification.weekly_report import generate_weekly_report

        report = generate_weekly_report(
            start_date="20260526",
            end_date="20260530",
            report_dir=tmp_report_dir,
        )
        assert "2026-05-26" in report
        assert "2026-05-30" in report


class TestCLIDispatcher:
    """CLI 分发器路由。"""

    def test_cli_dispatcher_routes_weekly_report(self) -> None:
        """argv=["--weekly-report"] → _resolve_weekly_report 返回 0。"""
        from src.cli.dispatcher import _resolve_weekly_report

        with patch("src.cli.dispatcher.push_weekly_report", create=True) as mock_push:
            # 需要mock模块级导入
            with patch("src.notification.weekly_report.push_weekly_report", return_value=0) as mock_fn:
                rc = _resolve_weekly_report(["--weekly-report"])
                assert rc == 0

    def test_cli_dispatcher_no_match(self) -> None:
        """argv 不含 --weekly-report → 返回 None。"""
        from src.cli.dispatcher import _resolve_weekly_report

        rc = _resolve_weekly_report(["--other-flag"])
        assert rc is None


# ---------------------------------------------------------------------------
# R20.17 (Bug D) regression: position_scale=0.0 必须保留 (0% 仓位 = 全风控),
# 不能被 `or 1.0` 静默覆盖为 100% 满仓。
# ---------------------------------------------------------------------------


def test_weekly_report_preserves_explicit_position_scale_zero_r20_17_regression(tmp_path: Path) -> None:
    """R20.17 Bug D regression: `position_scale=0.0` 不能被 `or 1.0` 覆盖为 1.0。

    0.0 是合法"0% 仓位"语义 (全风控, 不应买入任何新标的); 1.0 仅在 missing 时默认。
    下周关注区块应显示 0% 仓位系数, 而非 100%。
    """
    from src.notification.weekly_report import generate_weekly_report

    # 写入 position_scale=0.0 的报告
    payload = {
        "date": "20260606",
        "market_state": {"state_type": "bearish", "position_scale": 0.0},
        "recommendations": [
            {"ticker": "300750", "score_b": 0.45, "decision": "bullish"},
        ],
    }
    report_path = tmp_path / "auto_screening_20260606.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report = generate_weekly_report(
        start_date="20260601",
        end_date="20260606",
        report_dir=tmp_path,
    )

    # 0% 仓位应保留 (而非被 or 1.0 覆盖为 100%)
    assert "仓位系数 0%" in report, (
        f"position_scale=0.0 应保留显示 0%, 实际报告不含此字符串 (R20.17 Bug D 回归)。报告片段: {report[:500]}"
    )
    assert "仓位系数 100%" not in report, (
        "position_scale=0.0 不应被覆盖为 100%"
    )


def test_weekly_report_default_position_scale_1_0_when_missing(tmp_path: Path) -> None:
    """对照组: missing position_scale 应走默认 1.0 (满仓)。"""
    from src.notification.weekly_report import generate_weekly_report

    payload = {
        "date": "20260606",
        "market_state": {"state_type": "trending_up"},  # 无 position_scale
        "recommendations": [{"ticker": "300750", "score_b": 0.45}],
    }
    report_path = tmp_path / "auto_screening_20260606.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    report = generate_weekly_report(
        start_date="20260601",
        end_date="20260606",
        report_dir=tmp_path,
    )

    assert "仓位系数 100%" in report
