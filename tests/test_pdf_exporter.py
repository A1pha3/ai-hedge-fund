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
        # BH-019: tracking_summary producer (recommendation_tracker._summarize_history)
        # uses ``win_rate_day{N}`` / ``avg_return_day{N}`` / ``tracked_count_day{N}``
        # keys, NOT ``t1_win_rate`` / ``total_observations``. Keep the fixture aligned
        # with the real producer schema so the renderer is tested against reality.
        "tracking_summary": {
            "total_recommendations": 287,
            "win_rate_day1": 0.53,
            "win_rate_day3": 0.51,
            "win_rate_day5": 0.48,
            "win_rate_day10": 0.44,
            "win_rate_day20": 0.41,
            "win_rate_day30": 0.39,
            "tracked_count_day1": 280,
            "tracked_count_day3": 250,
            "tracked_count_day5": 200,
            "tracked_count_day10": 150,
            "tracked_count_day20": 100,
            "tracked_count_day30": 40,
            "avg_return_day1": 0.0034,
            "avg_return_day3": 0.0071,
            "avg_return_day5": 0.0098,
            "avg_return_day10": 0.0142,
            "avg_return_day20": 0.0210,
            "avg_return_day30": 0.0305,
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


def test_tracking_summary_renders_real_producer_schema(tmp_path: Path) -> None:
    """BH-019: tracking_summary must render win rates from the real producer
    schema (``win_rate_day{N}``), not the never-populated ``t1_win_rate`` keys.

    Before the fix the renderer read ``t1_win_rate`` / ``total_observations`` /
    ``avg_t1_return``, which ``get_tracking_summary`` never writes — every rate
    rendered as ``n/a`` on real payloads. This regression captures emitted
    (key, value) lines via a _kv_line spy so it does not depend on PDF text
    extraction.
    """
    from src.reporting import pdf_exporter

    emitted: list[tuple[str, str]] = []
    report = _full_report()

    # Spy on _kv_line by wrapping the module-level render function with a
    # fake PDF whose _kv_line records every emitted (key, value) pair.
    import types

    class _SpyPDF:
        def __init__(self) -> None:
            self.config = pdf_exporter.PDFReportConfig(include_tracking_summary=True)
            self.font_name = "Helvetica"

        def _section(self, title: str) -> None:  # noqa: ARG002
            pass

        def _kv_line(self, key: str, value) -> None:  # noqa: ARG002
            emitted.append((key, "" if value is None else str(value)))

    spy = _SpyPDF()
    # _ScreeningPDF methods referenced as bound methods; attach a real _kv_line
    # by binding the spy's method via types.SimpleNamespace is insufficient
    # because the renderer calls ``pdf._kv_line(...)`` — duck typing works.
    pdf_exporter._render_tracking_summary(spy, report)  # type: ignore[arg-type]

    emitted_dict = dict(emitted)
    # Real producer keys must drive the output (not the old t1_win_rate path).
    assert emitted_dict["总推荐数"] == "287"
    assert emitted_dict["T+1 胜率 (280 样本)"] == "53.00%"
    assert emitted_dict["T+3 胜率 (250 样本)"] == "51.00%"
    assert emitted_dict["T+5 胜率 (200 样本)"] == "48.00%"
    # R51/R52 computed-but-hidden family: longer horizons must be surfaced too.
    assert emitted_dict["T+10 胜率 (150 样本)"] == "44.00%"
    assert emitted_dict["T+30 胜率 (40 样本)"] == "39.00%"
    assert emitted_dict["T+1 平均收益"] == "+0.34%"
    assert emitted_dict["T+30 平均收益"] == "+3.05%"
    # No line should fall back to n/a when the producer populated the value.
    assert not any(v == "n/a" for k, v in emitted if k.startswith("T+"))


def test_tracking_summary_handles_missing_horizon_gracefully(tmp_path: Path) -> None:
    """BH-019 robustness: when a horizon's win rate is None (data not mature),
    the renderer must show ``n/a`` instead of crashing on ``None:.2%``."""
    from src.reporting import pdf_exporter

    emitted: list[tuple[str, str]] = []
    report = _full_report()
    # Simulate long horizons not yet mature (None win_rate, None avg_return).
    report["tracking_summary"] = {
        "total_recommendations": 50,
        "win_rate_day1": 0.6,
        "tracked_count_day1": 45,
        "avg_return_day1": 0.01,
        "win_rate_day30": None,
        "tracked_count_day30": 0,
        "avg_return_day30": None,
    }

    class _SpyPDF:
        def __init__(self) -> None:
            self.config = pdf_exporter.PDFReportConfig(include_tracking_summary=True)
            self.font_name = "Helvetica"

        def _section(self, title: str) -> None:  # noqa: ARG002
            pass

        def _kv_line(self, key: str, value) -> None:  # noqa: ARG002
            emitted.append((key, "" if value is None else str(value)))

    pdf_exporter._render_tracking_summary(_SpyPDF(), report)  # type: ignore[arg-type]
    emitted_dict = dict(emitted)
    assert emitted_dict["T+1 胜率 (45 样本)"] == "60.00%"
    # No tracked sample → no sample tag and n/a rate (not a crash).
    assert emitted_dict["T+30 胜率"] == "n/a"
    assert emitted_dict["T+30 平均收益"] == "n/a"


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


def test_render_recommendations_tolerates_null_score_b(tmp_path: Path) -> None:
    """R76 same-class drain: recommendations JSON 里部分 rec 的 score_b 为 null
    (candidate_pool 进了但未完成 composite scoring 的标的 / agent 输出 null /
    部分写入) 时, --export-pdf 推荐 section 不应崩溃 (R76 已为 --why-not /
    --top / --top-picks / --daily-brief 修了同型 bare-coercion crash, pdf 路径漏)。

    bug 复现: pdf_exporter._render_recommendations 用裸 float(rec.get('score_b', 0)),
    key 存在但 value=null 时 .get 返回 None, float(None) TypeError 中断整个 PDF
    推荐 section 渲染 (line 418 + line 427 row_color 判断两处都会崩)。
    """
    report = {
        "mode": "auto_screening",
        "date": "20260607",
        "recommendations": [
            {
                "ticker": "000001",
                "name": "正常票",
                "industry_sw": "银行",
                "score_b": 0.72,
                "decision": "buy",
                "consecutive_days": 3,
            },
            {
                "ticker": "000002",
                "name": "残缺票",
                "industry_sw": "电子",
                "score_b": None,  # JSON null — R76 确认的 active reachable path
                "decision": "neutral",
                "consecutive_days": 0,
            },
        ],
    }
    out = tmp_path / "null_score_b.pdf"
    config = PDFReportConfig(max_recommendations=10)
    # Should NOT raise TypeError; null score_b degrades to 0.0.
    result = generate_screening_pdf(report, out, config=config)
    assert result.exists()
    assert result.stat().st_size > 0


def test_render_industry_rotation_tolerates_null_numeric_fields(tmp_path: Path) -> None:
    """R76 same-class drain (industry_rotation path): momentum_score / avg_score_b
    在 industry_rotation JSON 为 null (部分写入 / 手改 / 上游 compute 异常) 时,
    --export-pdf 行业轮动 section 不应崩溃。同 _render_recommendations 的 score_b
    同根因 (bare float(.get(...)) 在 null 上 TypeError)。
    """
    report = {
        "mode": "auto_screening",
        "date": "20260607",
        "industry_rotation": [
            {"industry_name": "正常行业", "momentum_score": 25.3, "avg_score_b": 0.42, "candidate_count": 12},
            {"industry_name": "残缺行业", "momentum_score": None, "avg_score_b": None, "candidate_count": 5},
        ],
    }
    out = tmp_path / "null_rotation.pdf"
    config = PDFReportConfig(include_recommendations=False)
    result = generate_screening_pdf(report, out, config=config)
    assert result.exists()
    assert result.stat().st_size > 0


def test_render_recommendations_null_score_b_shows_na_not_zero(tmp_path: Path) -> None:
    """R92 / Campaign 1 Stage 3 trust-calibration family: when score_b is null,
    the PDF cell must show 'n/a' (not '+0.0000') so the user can distinguish
    'genuinely zero score' from 'data-missing degraded to 0'. A degraded 0.0
    formatted as a real score would silently mislead trust calibration.

    verification: spy on _ScreeningPDF._table to capture the rows passed to
    the recommendations table, then assert the null rec's score_b cell shows
    'n/a' while the normal rec shows its formatted '+0.7200'.
    """
    from src.reporting.pdf_exporter import _ScreeningPDF

    captured_tables: list = []

    real_table = _ScreeningPDF._table

    def _spy_table(self, headers, widths, rows, row_colors=None):
        captured_tables.append({"headers": list(headers), "rows": [list(r) for r in rows]})
        return real_table(self, headers, widths, rows, row_colors=row_colors)

    report = {
        "mode": "auto_screening",
        "date": "20260607",
        "recommendations": [
            {
                "ticker": "000001",
                "name": "正常票",
                "industry_sw": "银行",
                "score_b": 0.72,
                "decision": "buy",
                "consecutive_days": 3,
            },
            {
                "ticker": "000002",
                "name": "残缺票",
                "industry_sw": "电子",
                "score_b": None,  # degraded — must show n/a, not +0.0000
                "decision": "neutral",
                "consecutive_days": 0,
            },
        ],
    }
    out = tmp_path / "na_score_b.pdf"
    config = PDFReportConfig(max_recommendations=10)

    import unittest.mock as _mock
    with _mock.patch.object(_ScreeningPDF, "_table", _spy_table):
        result = generate_screening_pdf(report, out, config=config)
    assert result.exists()

    # Find the recommendations table (has score_b header).
    rec_table = next(
        (t for t in captured_tables if "score_b" in t["headers"]),
        None,
    )
    assert rec_table is not None, f"recommendations table not captured; got tables={[t['headers'] for t in captured_tables]}"
    # 2 recs rendered.
    assert len(rec_table["rows"]) == 2
    # Find the row for the 残缺票 (null score_b).
    null_row = next(r for r in rec_table["rows"] if "残缺" in str(r[1]))
    normal_row = next(r for r in rec_table["rows"] if "正常" in str(r[1]))
    # score_b is the 4th column (index 3) per headers: 代码/名称/行业/score_b/...
    assert null_row[3] == "n/a", f"null score_b should display 'n/a'; got {null_row[3]!r}"
    assert normal_row[3] == "+0.7200", f"normal score_b should format as +0.7200; got {normal_row[3]!r}"


def test_render_recommendations_section_title_shows_total_when_truncated(tmp_path: Path) -> None:
    """Feature: when recommendations count exceeds max_recommendations, the
    PDF section title must disclose the total so the user sharing/archiving
    the PDF knows it contains a truncated subset, not the full recommendation
    set. Ambiguous 'Top 30' could be misread as '30 total'.

    verification: spy on _ScreeningPDF._section to capture the title passed
    when recs=50 and max_recommendations=30; assert title contains both
    '30' (rendered) and '50' (total).
    """
    from src.reporting.pdf_exporter import _ScreeningPDF

    captured_sections: list = []
    real_section = _ScreeningPDF._section

    def _spy_section(self, title, *args, **kwargs):
        captured_sections.append(str(title))
        return real_section(self, title, *args, **kwargs)

    recs = _make_recs(50)
    report = {
        "mode": "auto_screening",
        "date": "20260607",
        "recommendations": recs,
    }
    out = tmp_path / "truncated.pdf"
    config = PDFReportConfig(max_recommendations=30)

    import unittest.mock as _mock
    with _mock.patch.object(_ScreeningPDF, "_section", _spy_section):
        result = generate_screening_pdf(report, out, config=config)
    assert result.exists()

    # Find the recommendations section title.
    rec_titles = [t for t in captured_sections if "推荐" in t or "Top" in t]
    assert rec_titles, f"recommendations section title not captured; got {captured_sections}"
    title = rec_titles[0]
    # When truncated (50 > 30), title must disclose both rendered and total.
    assert "30" in title, f"title should show rendered count 30; got {title!r}"
    assert "50" in title, f"title should show total count 50 (truncation disclosure); got {title!r}"


def test_render_recommendations_section_title_no_total_when_not_truncated(tmp_path: Path) -> None:
    """Feature companion: when recs count <= max_recommendations (no truncation),
    the title should NOT add a misleading '/ 共 N' suffix (would imply truncation
    that isn't happening). Keeps the title clean for the common case.
    """
    from src.reporting.pdf_exporter import _ScreeningPDF

    captured_sections: list = []
    real_section = _ScreeningPDF._section

    def _spy_section(self, title, *args, **kwargs):
        captured_sections.append(str(title))
        return real_section(self, title, *args, **kwargs)

    recs = _make_recs(10)
    report = {
        "mode": "auto_screening",
        "date": "20260607",
        "recommendations": recs,
    }
    out = tmp_path / "not_truncated.pdf"
    config = PDFReportConfig(max_recommendations=30)

    import unittest.mock as _mock
    with _mock.patch.object(_ScreeningPDF, "_section", _spy_section):
        result = generate_screening_pdf(report, out, config=config)
    assert result.exists()

    rec_titles = [t for t in captured_sections if "推荐" in t or "Top" in t]
    assert rec_titles, f"recommendations section title not captured; got {captured_sections}"
    title = rec_titles[0]
    assert "10" in title, f"title should show count 10; got {title!r}"
    # No truncation -> no '共' suffix that would imply truncation.
    assert "共" not in title, f"non-truncated title should not imply truncation; got {title!r}"
