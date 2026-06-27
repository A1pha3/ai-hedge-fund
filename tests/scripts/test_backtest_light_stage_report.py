"""NS-8: 回测标准化报告持久化测试.

owner 的 _backtest_light_stage_universe.py 只 print stdout, 无持久化报告.
NS-8 切片: 加 _save_report (CSV/JSON) + --output 参数, 让 owner 重跑回测后
能保存汇总供持续验证 + 版本对比 (design packet evidence gap: owner 应重跑
刷新 regime 胜率). 向后兼容 (默认 output_path=None 不持久化).
"""
from __future__ import annotations

import json

import pandas as pd

from scripts._backtest_light_stage_universe import _save_report


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"trade_date": "20260101", "mr_ic": 0.05, "top_new_win": 0.6, "top_new_ret": 1.2},
            {"trade_date": "20260102", "mr_ic": -0.03, "top_new_win": 0.5, "top_new_ret": -0.5},
        ]
    )


def test_save_report_csv(tmp_path):
    out = tmp_path / "report.csv"
    result = _save_report(_sample_df(), str(out))
    assert result == str(out)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "trade_date" in content
    assert "20260101" in content
    assert "20260102" in content


def test_save_report_json(tmp_path):
    out = tmp_path / "report.json"
    result = _save_report(_sample_df(), str(out))
    assert result == str(out)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["trade_date"] == "20260101"
    assert data[1]["top_new_win"] == 0.5


def test_save_report_creates_parent_dirs(tmp_path):
    out = tmp_path / "subdir" / "nested" / "report.csv"
    result = _save_report(_sample_df(), str(out))
    assert result == str(out)
    assert out.exists()


def test_save_report_none_no_write(tmp_path):
    result = _save_report(_sample_df(), None)
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_save_report_empty_string_no_write(tmp_path):
    """空 output_path (默认) → 不写, 保持向后兼容."""
    result = _save_report(_sample_df(), "")
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_save_report_unknown_suffix_defaults_csv(tmp_path):
    """未知后缀 (如 .txt) → 默认 CSV 格式."""
    out = tmp_path / "report.txt"
    result = _save_report(_sample_df(), str(out))
    assert result == str(out)
    assert out.exists()
    assert "trade_date" in out.read_text(encoding="utf-8")
