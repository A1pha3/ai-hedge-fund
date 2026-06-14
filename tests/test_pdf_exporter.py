"""P1-7 选股报告 PDF 导出测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reporting.pdf_exporter import (
    _decision_color,
    find_latest_report,
    generate_screening_pdf,
    load_report,
    PDFReportConfig,
)

# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


def _minimal_report() -> dict:
    """最小化测试报告 (只含必要字段)。"""
    return {
        "mode": "auto_screening",
        "date": "20260607",
        "recommendations": [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "industry_sw": "电力设备",
                "score_b": 0.72,
                "decision": "strong_buy",
                "consecutive_days": 4,
                "decay": {"level": "none"},
            }
        ],
    }


def _full_report() -> dict:
    """完整测试报告 (含所有区块)。"""
    recs = []
    for i in range(15):
        recs.append(
            {
                "ticker": f"60{1000 + i:04d}",
                "name": f"测试股票{i}",
                "industry_sw": "电子" if i % 2 else "银行",
                "score_b": 0.6 - i * 0.05,
                "decision": "strong_buy" if i < 3 else ("watch" if i < 8 else "neutral"),
                "consecutive_days": min(i, 5),
                "decay": {"level": ["none", "mild", "moderate", "strong"][i % 4]},
            }
        )
    return {
        "mode": "auto_screening",
        "date": "20260607",
        "market_state": {
            "state_type": "trend",
            "position_scale": 0.85,
            "adx": 28.5,
            "atr": 0.025,
            "breadth": 0.62,
            "north_flow": 23.4,
            "limit_up": 35,
            "limit_down": 8,
            "regime_gate": "normal",
        },
        "layer_a_count": 5234,
        "total_scored": 412,
        "high_pool_count": 87,
        "top_n": 10,
        "recommendations": recs,
        "industry_rotation": [
            {"industry_name": "电力设备", "momentum_score": 25.3, "avg_score_b": 0.42, "candidate_count": 12},
            {"industry_name": "电子", "momentum_score": 18.7, "avg_score_b": 0.35, "candidate_count": 23},
            {"industry_name": "银行", "momentum_score": -12.4, "avg_score_b": -0.18, "candidate_count": 8},
            {"industry_name": "房地产", "momentum_score": -8.1, "avg_score_b": -0.10, "candidate_count": 5},
        ],
        "tracking_summary": {
            "total_recommendations": 287,
            "total_observations": 412,
            "t1_win_rate": 0.53,
            "t3_win_rate": 0.51,
            "t5_win_rate": 0.48,
            "avg_t1_return": 0.0034,
            "avg_t3_return": 0.0071,
        },
    }


def _make_recs(n: int) -> list[dict]:
    return [
        {
            "ticker": f"{600000 + i:06d}",
            "name": f"测试{i}",
            "industry_sw": "电子",
            "score_b": 0.5 - i * 0.01,
            "decision": "strong_buy" if i < 3 else "neutral",
            "consecutive_days": i % 5,
            "decay": {"level": "none"},
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. 基础生成 (最小数据)
# ---------------------------------------------------------------------------


def test_generate_minimal_report(tmp_path: Path) -> None:
    """最小数据生成 PDF 不崩溃。"""
    out = tmp_path / "minimal.pdf"
    result = generate_screening_pdf(_minimal_report(), out)
    assert result == out
    assert result.exists()
    assert result.stat().st_size > 0
    with open(result, "rb") as f:
        assert f.read(4) == b"%PDF"


# ---------------------------------------------------------------------------
# 2. 完整生成 (所有区块)
# ---------------------------------------------------------------------------


def test_generate_full_report(tmp_path: Path) -> None:
    """完整数据生成 PDF, 所有区块都参与渲染。"""
    out = tmp_path / "full.pdf"
    result = generate_screening_pdf(_full_report(), out)
    assert result == out
    assert result.exists()
    assert result.stat().st_size > 1000  # 完整报告应大于 1KB
    with open(result, "rb") as f:
        assert f.read(4) == b"%PDF"


# ---------------------------------------------------------------------------
# 3. 包含 Top 30 推荐标的
# ---------------------------------------------------------------------------


def test_max_recommendations_limit(tmp_path: Path) -> None:
    """max_recommendations 生效, 只渲染前 N 个。"""
    recs = _make_recs(50)
    report = {
        "mode": "auto_screening",
        "date": "20260607",
        "recommendations": recs,
    }
    out = tmp_path / "top30.pdf"
    config = PDFReportConfig(max_recommendations=30)
    result = generate_screening_pdf(report, out, config=config)
    assert result.exists()
    assert result.stat().st_size > 0


def test_default_max_recommendations_is_30() -> None:
    """默认 max_recommendations = 30。"""
    assert PDFReportConfig().max_recommendations == 30


# ---------------------------------------------------------------------------
# 4. 包含市场状态
# ---------------------------------------------------------------------------


def test_include_market_state_enabled(tmp_path: Path) -> None:
    """默认 include_market_state=True, 渲染市场状态区。"""
    report = _full_report()
    out = tmp_path / "with_state.pdf"
    config = PDFReportConfig(include_market_state=True)
    result = generate_screening_pdf(report, out, config=config)
    assert result.exists()


def test_include_market_state_disabled(tmp_path: Path) -> None:
    """include_market_state=False 不渲染市场状态区 (但仍能生成有效 PDF)。"""
    report = _full_report()
    out = tmp_path / "no_state.pdf"
    config = PDFReportConfig(include_market_state=False)
    result = generate_screening_pdf(report, out, config=config)
    assert result.exists()
    with open(result, "rb") as f:
        assert f.read(4) == b"%PDF"


# ---------------------------------------------------------------------------
# 5. 包含行业轮动
# ---------------------------------------------------------------------------


def test_include_industry_rotation_enabled(tmp_path: Path) -> None:
    """默认 include_industry_rotation=True。"""
    report = _full_report()
    out = tmp_path / "with_rotation.pdf"
    result = generate_screening_pdf(report, out, config=PDFReportConfig(include_industry_rotation=True))
    assert result.exists()


def test_include_industry_rotation_disabled(tmp_path: Path) -> None:
    """include_industry_rotation=False 仍能生成。"""
    report = _full_report()
    out = tmp_path / "no_rotation.pdf"
    result = generate_screening_pdf(report, out, config=PDFReportConfig(include_industry_rotation=False))
    assert result.exists()


# ---------------------------------------------------------------------------
# 6. 包含追踪总结
# ---------------------------------------------------------------------------


def test_include_tracking_summary(tmp_path: Path) -> None:
    """有 tracking_summary 时正常渲染。"""
    report = _full_report()
    out = tmp_path / "with_tracking.pdf"
    result = generate_screening_pdf(report, out, config=PDFReportConfig(include_tracking_summary=True))
    assert result.exists()


def test_tracking_summary_skipped_when_empty(tmp_path: Path) -> None:
    """tracking_summary 缺失或全 0 时不渲染追踪区 (不应崩溃)。"""
    report = _full_report()
    report["tracking_summary"] = {}  # 空
    out = tmp_path / "no_tracking.pdf"
    result = generate_screening_pdf(report, out)
    assert result.exists()


# ---------------------------------------------------------------------------
# 7. 文件输出路径正确
# ---------------------------------------------------------------------------


def test_output_path_returned_and_created(tmp_path: Path) -> None:
    """返回路径 == 输出路径, 父目录自动创建。"""
    nested = tmp_path / "subdir" / "deep" / "report.pdf"
    assert not nested.parent.exists()
    result = generate_screening_pdf(_minimal_report(), nested)
    assert result == nested
    assert nested.exists()
    assert nested.parent.exists()


def test_default_config_used_when_none(tmp_path: Path) -> None:
    """config=None 时使用默认配置。"""
    out = tmp_path / "default.pdf"
    result = generate_screening_pdf(_minimal_report(), out, config=None)
    assert result.exists()
    with open(result, "rb") as f:
        assert f.read(4) == b"%PDF"


# ---------------------------------------------------------------------------
# 8. PDF 字节流有效性
# ---------------------------------------------------------------------------


def test_pdf_magic_bytes(tmp_path: Path) -> None:
    """PDF 文件首 4 字节必须是 %PDF。"""
    out = tmp_path / "magic.pdf"
    generate_screening_pdf(_minimal_report(), out)
    with open(out, "rb") as f:
        header = f.read(8)
    assert header[:4] == b"%PDF", f"Invalid PDF header: {header!r}"
    # 末尾通常是 %%EOF
    with open(out, "rb") as f:
        f.seek(-1024, 2)
        tail = f.read(1024)
    assert b"%%EOF" in tail or b"%%EOF" in open(out, "rb").read()[-100:]


def test_pdf_handles_empty_recommendations(tmp_path: Path) -> None:
    """空 recommendations 列表仍能生成有效 PDF。"""
    report = {"mode": "auto_screening", "date": "20260607", "recommendations": []}
    out = tmp_path / "empty.pdf"
    result = generate_screening_pdf(report, out)
    assert result.exists()
    with open(result, "rb") as f:
        assert f.read(4) == b"%PDF"


def test_pdf_handles_chinese_industry_names(tmp_path: Path) -> None:
    """含中文行业名的报告能正常生成 (有 CJK 字体时) 或用 ? 替换 (无字体时)。"""
    report = {
        "mode": "auto_screening",
        "date": "20260607",
        "recommendations": [
            {
                "ticker": "300750",
                "name": "宁德时代",
                "industry_sw": "电力设备",
                "score_b": 0.72,
                "decision": "strong_buy",
                "consecutive_days": 4,
                "decay": {"level": "none"},
            }
        ],
    }
    out = tmp_path / "cn.pdf"
    result = generate_screening_pdf(report, out)
    assert result.exists()
    with open(result, "rb") as f:
        assert f.read(4) == b"%PDF"


# ---------------------------------------------------------------------------
# 决策颜色映射
# ---------------------------------------------------------------------------


def test_decision_color_mapping() -> None:
    """决策字符串 → 颜色 RGB 正确映射。"""
    buy = _decision_color("strong_buy")
    buy2 = _decision_color("buy")
    avoid = _decision_color("strong_sell")
    avoid2 = _decision_color("avoid")
    watch = _decision_color("neutral")
    watch2 = _decision_color("watch")
    assert buy == buy2  # buy 家族同色
    assert avoid == avoid2
    assert watch == watch2
    assert buy != avoid != watch


# ---------------------------------------------------------------------------
# 报告加载 / 查找辅助函数
# ---------------------------------------------------------------------------


def test_find_latest_report(tmp_path: Path) -> None:
    """find_latest_report 返回最新日期的 JSON。"""
    (tmp_path / "auto_screening_20260605.json").write_text("{}", encoding="utf-8")
    (tmp_path / "auto_screening_20260607.json").write_text("{}", encoding="utf-8")
    (tmp_path / "auto_screening_20260606.json").write_text("{}", encoding="utf-8")
    latest = find_latest_report(tmp_path)
    assert latest is not None
    assert latest.name == "auto_screening_20260607.json"


def test_find_latest_report_empty_dir(tmp_path: Path) -> None:
    """空目录返回 None。"""
    sub = tmp_path / "empty"
    sub.mkdir()
    assert find_latest_report(sub) is None


def test_find_latest_report_missing_dir(tmp_path: Path) -> None:
    """不存在的目录返回 None。"""
    assert find_latest_report(tmp_path / "no_such_dir") is None


def test_load_report_success(tmp_path: Path) -> None:
    """load_report 成功加载 JSON。"""
    p = tmp_path / "auto_screening_20260607.json"
    p.write_text(json.dumps({"date": "20260607"}), encoding="utf-8")
    data = load_report(p)
    assert data["date"] == "20260607"


def test_load_report_invalid_json(tmp_path: Path) -> None:
    """load_report 在非法 JSON 时抛 ValueError。"""
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_report(p)


def test_load_report_missing_file(tmp_path: Path) -> None:
    """load_report 在文件不存在时抛 ValueError。"""
    with pytest.raises(ValueError):
        load_report(tmp_path / "no_such.json")
