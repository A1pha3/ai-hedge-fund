from pathlib import Path

import pytest

from scripts import batch_run_hedge_fund


def _write_stock_markdown(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "| ticker | name | change |",
                "| --- | --- | --- |",
                "| 600002.SH | Beta | 1.20% |",
                "| 688001.SH | Star | 0.50% |",
                "| 000001.SZ | Alpha | 2.50% |",
                "| 300001.SZ | Growth | 3.00% |",
            ]
        ),
        encoding="utf-8",
    )


def test_main_returns_error_for_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing_path = tmp_path / "missing.md"
    monkeypatch.setattr("sys.argv", ["batch_run_hedge_fund.py", "--file", str(missing_path)])

    exit_code = batch_run_hedge_fund.main()

    assert exit_code == 1
    assert "错误: 文件不存在" in capsys.readouterr().err


def test_main_filters_sorts_skips_existing_and_runs_remaining(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    markdown_path = tmp_path / "stocks.md"
    _write_stock_markdown(markdown_path)
    run_calls: list[list[str]] = []
    sleep_calls: list[int] = []

    monkeypatch.setattr(
        "sys.argv",
        [
            "batch_run_hedge_fund.py",
            "--file",
            str(markdown_path),
            "--model",
            "test-model",
            "--analysts-all",
            "--start-date",
            "2025-06-01",
            "--end-date",
            "2025-06-02",
            "--show-reasoning",
            "--exclude-boards",
            "科创板",
        ],
    )
    monkeypatch.setattr(batch_run_hedge_fund, "get_existing_tickers_from_reports", lambda report_dir, report_date: {"600002"})
    monkeypatch.setattr(batch_run_hedge_fund, "run_hedge_fund_analysis", lambda cmd: run_calls.append(cmd) or 0)
    monkeypatch.setattr(batch_run_hedge_fund.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    exit_code = batch_run_hedge_fund.main()

    assert exit_code == 0
    assert run_calls == [
        [
            str(Path(batch_run_hedge_fund.__file__).parent / "run-hedge-fund.sh"),
            "--ticker",
            "000001",
            "--model",
            "test-model",
            "--analysts-all",
            "--start-date",
            "2025-06-01",
            "--end-date",
            "2025-06-02",
            "--show-reasoning",
        ],
        [
            str(Path(batch_run_hedge_fund.__file__).parent / "run-hedge-fund.sh"),
            "--ticker",
            "300001",
            "--model",
            "test-model",
            "--analysts-all",
            "--start-date",
            "2025-06-01",
            "--end-date",
            "2025-06-02",
            "--show-reasoning",
        ],
    ]
    assert sleep_calls == [3]

    stdout = capsys.readouterr().out
    assert "已过滤 1 只股票（排除板块: 科创板），剩余 3 只" in stdout
    assert "跳过已完成: 600002 (Beta) - 涨幅: 1.2%" in stdout
    assert "正在分析: 000001 (Alpha) - 涨幅: 2.5%" in stdout
    assert "正在分析: 300001 (Growth) - 涨幅: 3.0%" in stdout


def test_main_reports_failed_analysis_without_model_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    markdown_path = tmp_path / "stocks.md"
    _write_stock_markdown(markdown_path)

    monkeypatch.setattr("sys.argv", ["batch_run_hedge_fund.py", "--file", str(markdown_path), "--exclude-boards", "科创板", "创业板"])
    monkeypatch.setattr(batch_run_hedge_fund, "get_existing_tickers_from_reports", lambda report_dir, report_date: set())
    monkeypatch.setattr(batch_run_hedge_fund, "run_hedge_fund_analysis", lambda cmd: 2)
    monkeypatch.setattr(batch_run_hedge_fund.time, "sleep", lambda seconds: None)

    exit_code = batch_run_hedge_fund.main()

    assert exit_code == 0
    assert "错误: 600002 分析仍然失败，返回码: 2" in capsys.readouterr().err
