from __future__ import annotations

from pathlib import Path

import scripts.generate_report_summary as generate_report_summary


class _FixedDateTime:
    @classmethod
    def now(cls):
        class _FixedNow:
            def strftime(self, fmt: str) -> str:
                mapping = {
                    "%Y%m%d_%H%M%S": "20260410_055001",
                    "%Y-%m-%d %H:%M:%S": "2026-04-10 05:50:01",
                }
                return mapping[fmt]

        return _FixedNow()


def _write_report(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_generate_summary_aggregates_reports_and_classifies_files(tmp_path, monkeypatch, capsys):
    project_root = tmp_path
    reports_dir = project_root / "data" / "reports"
    scripts_dir = project_root / "scripts"
    reports_dir.mkdir(parents=True)
    scripts_dir.mkdir()

    _write_report(
        reports_dir / "000001_buy.md",
        "\n".join(
            [
                "| 代码 | 名称 | 涨幅 | 昨日收盘价 | 今日收盘价 | 地域 | 所属行业 | 市场类型 | 上市日期 | 操作 | 置信度 |",
                "| 000001 | 平安银行 | 1.5 | 10.0 | 10.15 | 深圳 | 银行 | 主板 | 19910403 | BUY | 0.91 |",
            ]
        ),
    )
    _write_report(
        reports_dir / "300001_hold.md",
        "\n".join(
            [
                "| 代码 | 名称 | 操作 | 置信度 |",
                "| 300001 | 特锐德 | HOLD | 0.55 |",
            ]
        ),
    )

    monkeypatch.setattr(generate_report_summary, "__file__", str(scripts_dir / "generate_report_summary.py"))
    monkeypatch.setattr(generate_report_summary, "datetime", _FixedDateTime)
    monkeypatch.setattr(
        generate_report_summary,
        "_fetch_details_with_retry",
        lambda ticker: {
            "name": "特锐德补全",
            "pct_chg": "2.1",
            "pre_close": "20.0",
            "close": "20.42",
            "area": "青岛",
            "industry": "电气设备",
            "market": "创业板",
            "list_date": "20091030",
        },
    )
    monkeypatch.setattr(generate_report_summary.time, "sleep", lambda _: None)

    generate_report_summary.generate_summary()

    summary_path = reports_dir / "summary_20260410_055001.md"
    assert summary_path.exists()
    summary_text = summary_path.read_text(encoding="utf-8")
    assert "## 1. BUY (买入建议) - 共 1 只" in summary_text
    assert "## 2. HOLD (观望建议) - 共 1 只" in summary_text
    assert "| 000001 | 平安银行 | 1.5 | 10.0 | 10.15 | 深圳 | 银行 | 主板 | 19910403 | BUY | 0.91 |" in summary_text
    assert "| 300001 | 特锐德补全 | 2.1 | 20.0 | 20.42 | 青岛 | 电气设备 | 创业板 | 20091030 | **HOLD** | 0.55 |" in summary_text
    assert (reports_dir / "buy" / "000001_buy.md").exists()
    assert (reports_dir / "hold" / "300001_hold.md").exists()
    assert not (reports_dir / "000001_buy.md").exists()
    assert not (reports_dir / "300001_hold.md").exists()

    captured = capsys.readouterr().out
    assert "成功生成汇总报告" in captured
    assert "报告文件分类完成: buy/1份, hold/1份, short/0份" in captured


def test_generate_summary_prints_error_when_reports_dir_missing(tmp_path, monkeypatch, capsys):
    project_root = tmp_path
    scripts_dir = project_root / "scripts"
    scripts_dir.mkdir()

    monkeypatch.setattr(generate_report_summary, "__file__", str(scripts_dir / "generate_report_summary.py"))

    generate_report_summary.generate_summary()

    captured = capsys.readouterr().out
    assert "错误: 目录" in captured
