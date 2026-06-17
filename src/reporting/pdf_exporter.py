"""选股报告 PDF 导出 — 将 ``--auto`` 报告生成为结构化 PDF。

P1-7 目标: 每次 ``--auto`` 跑完后, 除了 JSON / Markdown 报告外, 还能输出
可直接分享给同事 / 客户 / 自归档的 PDF 报告。

库选择: ``fpdf2`` (纯 Python, 无 wkhtmltopdf / cairo 等系统依赖)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF

# ---------------------------------------------------------------------------
# 颜色 (RGB 0-255) — 使用低饱和度, 适合打印 + 屏幕
# ---------------------------------------------------------------------------

_COLOR_HEADER_BG = (220, 230, 241)  # 浅灰蓝 — 表头底色
_COLOR_ROW_ALT = (248, 250, 252)  # 浅灰白 — 表格交替行
_COLOR_BORDER = (180, 188, 200)  # 表格边框
_COLOR_TEXT = (40, 50, 65)  # 主文字
_COLOR_MUTED = (110, 120, 135)  # 次要文字
_COLOR_BUY = (16, 122, 87)  # 买入 — 绿色
_COLOR_AVOID = (198, 40, 40)  # 回避 — 红色
_COLOR_WATCH = (180, 130, 0)  # 观望 — 琥珀色
_COLOR_BANNER = (32, 86, 139)  # 标题色
_COLOR_FOOTER = (130, 140, 155)  # 页脚色

# 行高 (mm)
_LINE_H = 6.0
_TABLE_HEADER_H = 7.5
_TABLE_ROW_H = 6.5
# 边距 (mm)
_MARGIN = 12.0


# ---------------------------------------------------------------------------
# 决策颜色映射 — 与 CLI ``_print_auto_screening_table`` 一致
# ---------------------------------------------------------------------------


def _decision_color(decision: str) -> tuple[int, int, int]:
    """根据决策字符串返回 RGB 颜色。"""
    d = (decision or "").lower()
    if d in ("strong_buy", "buy", "bullish"):
        return _COLOR_BUY
    if d in ("strong_sell", "sell", "bearish", "avoid"):
        return _COLOR_AVOID
    return _COLOR_WATCH  # neutral / watch / fallback


# ---------------------------------------------------------------------------
# 公共配置
# ---------------------------------------------------------------------------


@dataclass
class PDFReportConfig:
    """PDF 报告生成配置。"""

    title: str = "AI 选股日报"
    subtitle: str = ""
    include_market_state: bool = True
    include_industry_rotation: bool = True
    include_recommendations: bool = True
    include_tracking_summary: bool = True
    max_recommendations: int = 30
    author: str = "AI Hedge Fund Research"

    # 字号 (pt)
    title_size: int = 18
    section_size: int = 14
    body_size: int = 10
    table_header_size: int = 9
    table_row_size: int = 8.5


# ---------------------------------------------------------------------------
# 字体处理 — fpdf2 内置 Helvetica 不支持中文, 我们采用 unicode-safe 方式
# ---------------------------------------------------------------------------


def _register_cjk_font(pdf: FPDF) -> str | None:
    """尝试注册一个支持 CJK 的 Unicode 字体 (dejavu / noto / wqy)。

    找不到时返回 ``None`` — 调用者会回退到 ASCII-only 输出。
    字体必须注册在目标 ``pdf`` 实例上, fpdf2 不跨实例共享字体表。

    同时注册 ``<name>`` 与 ``<name>B`` (粗体变体) — fpdf2 在 ``set_font(name, "B", size)``
    时会查找 ``<name>B`` 而不是从 regular 自动加粗。
    """
    candidates = [
        # macOS 自带
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "ArialUni"),
        ("/Library/Fonts/Arial.ttf", "ArialLocal"),
        # Linux 常见
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVu"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVu"),
    ]
    # 单文件 TTC — 第一个 face 通常是 regular, 第二个是 bold
    ttc_candidates = [
        ("/System/Library/Fonts/PingFang.ttc", "PingFang"),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "WQY"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "NotoCJK"),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "NotoCJK2"),
    ]
    seen = set()
    for path, name in candidates + ttc_candidates:
        if (path, name) in seen:
            continue
        seen.add((path, name))
        if not Path(path).exists():
            continue
        try:
            # ``uni`` 在 fpdf2 >= 2.5.1 已被弃用但仍可用 — 静默 warning
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                pdf.add_font(name, "", path, uni=True)
                try:
                    pdf.add_font(name, "B", path, uni=True)
                except Exception:
                    pass
            return name
        except Exception:
            continue
    return None


def _safe_text(text: str, font_name: str | None) -> str:
    """在没有 CJK 字体时, 把非 latin-1 字符替换为 ``?``。

    这样能保证 PDF 不会因为字符编码问题崩溃, 代价是中文显示为 ``?``。
    """
    if not text:
        return ""
    if font_name is not None:
        return text
    return text.encode("latin-1", errors="replace").decode("latin-1")


# ---------------------------------------------------------------------------
# PDF 渲染器
# ---------------------------------------------------------------------------


class _ScreeningPDF(FPDF):
    """继承 FPDF, 自动处理页眉 / 页脚 / 分页。"""

    def __init__(self, config: PDFReportConfig, font_name: str | None) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.config = config
        self.font_name = font_name
        self.set_auto_page_break(auto=True, margin=_MARGIN + 5)
        self.set_margins(_MARGIN, _MARGIN + 4, _MARGIN)
        # fpdf2 默认字是 Helvetica (latin-1 only)。若找到 CJK 字体则切换。
        if font_name is not None:
            self.set_font(font_name, "", config.body_size)
        else:
            self.set_font("Helvetica", "", config.body_size)
        self._report_date = ""

    def header(self) -> None:  # noqa: D401 - FPDF 回调
        if self.page_no() == 1:
            return  # 标题页不画页眉
        self._draw_header_footer_header()

    def _draw_header_footer_header(self) -> None:
        self.set_y(_MARGIN - 2)
        self.set_text_color(*_COLOR_MUTED)
        if self.font_name is not None:
            self.set_font(self.font_name, "", 8)
        else:
            self.set_font("Helvetica", "", 8)
        date_text = self._report_date or ""
        self.cell(0, 5, _safe_text(f"AI 选股日报 | {date_text}", self.font_name), align="L")
        self.set_text_color(*_COLOR_TEXT)
        self.ln(6)

    def footer(self) -> None:  # noqa: D401 - FPDF 回调
        self.set_y(-_MARGIN)
        self.set_text_color(*_COLOR_FOOTER)
        if self.font_name is not None:
            self.set_font(self.font_name, "", 8)
        else:
            self.set_font("Helvetica", "", 8)
        self.cell(0, 6, _safe_text(f"{self.config.author}  |  第 {self.page_no()} / {{nb}} 页", self.font_name), align="C")
        self.set_text_color(*_COLOR_TEXT)

    # ---- 文本工具 ----------------------------------------------------

    def _set_font(self, style: str = "", size: float | None = None) -> None:
        size = size or self.config.body_size
        self.font_name or ("Helvetica" if not self.font_name else self.font_name)
        # Helvetica 不支持 B 之外的样式, fpdf2 内部对 "" 会回退到 Regular
        if self.font_name is None:
            self.set_font("Helvetica", style, size)
        else:
            self.set_font(self.font_name, style, size)

    def _section(self, title: str) -> None:
        self.ln(2)
        self._set_font("B", self.config.section_size)
        self.set_text_color(*_COLOR_BANNER)
        self.cell(0, 8, _safe_text(title, self.font_name), new_x="LMARGIN", new_y="NEXT")
        # 分隔线
        y = self.get_y()
        self.set_draw_color(*_COLOR_BORDER)
        self.line(_MARGIN, y, self.w - _MARGIN, y)
        self.ln(3)
        self.set_text_color(*_COLOR_TEXT)
        self._set_font("", self.config.body_size)

    def _kv_line(self, key: str, value: Any) -> None:
        """打印一个 key: value 行, key 加粗灰色。"""
        self._set_font("B", self.config.body_size)
        self.set_text_color(*_COLOR_MUTED)
        self.cell(45, _LINE_H, _safe_text(key, self.font_name))
        self.set_text_color(*_COLOR_TEXT)
        self._set_font("", self.config.body_size)
        value_str = "" if value is None else str(value)
        self.cell(0, _LINE_H, _safe_text(value_str, self.font_name), new_x="LMARGIN", new_y="NEXT")

    def _paragraph(self, text: str) -> None:
        self._set_font("", self.config.body_size)
        self.set_text_color(*_COLOR_TEXT)
        self.multi_cell(0, _LINE_H, _safe_text(text, self.font_name))
        self.ln(1)

    def _table(self, headers: list[str], widths: list[float], rows: list[list[Any]], row_colors: list[tuple[int, int, int]] | None = None) -> None:
        """绘制带表头 + 交替行底色的表格。"""
        if not rows:
            self._set_font("", self.config.body_size)
            self.set_text_color(*_COLOR_MUTED)
            self.cell(0, _LINE_H, _safe_text("（无数据）", self.font_name), new_x="LMARGIN", new_y="NEXT")
            return

        page_w = self.w - 2 * _MARGIN
        total_w = sum(widths)
        # 等比缩放
        if total_w > page_w:
            scale = page_w / total_w
            widths = [w * scale for w in widths]

        # 表头
        self._set_font("B", self.config.table_header_size)
        self.set_fill_color(*_COLOR_HEADER_BG)
        self.set_draw_color(*_COLOR_BORDER)
        self.set_text_color(*_COLOR_TEXT)
        for i, h in enumerate(headers):
            self.cell(widths[i], _TABLE_HEADER_H, _safe_text(h, self.font_name), border=1, fill=True, align="C")
        self.ln(_TABLE_HEADER_H)

        # 数据行
        self._set_font("", self.config.table_row_size)
        for idx, row in enumerate(rows):
            # 分页检查
            if self.get_y() + _TABLE_ROW_H > self.h - _MARGIN - 6:
                self.add_page()
                # 重画表头
                self._set_font("B", self.config.table_header_size)
                self.set_fill_color(*_COLOR_HEADER_BG)
                self.set_draw_color(*_COLOR_BORDER)
                self.set_text_color(*_COLOR_TEXT)
                for i, h in enumerate(headers):
                    self.cell(widths[i], _TABLE_HEADER_H, _safe_text(h, self.font_name), border=1, fill=True, align="C")
                self.ln(_TABLE_HEADER_H)
                self._set_font("", self.config.table_row_size)

            use_alt = (idx % 2 == 1)
            for i, cell in enumerate(row):
                if use_alt:
                    self.set_fill_color(*_COLOR_ROW_ALT)
                else:
                    self.set_fill_color(255, 255, 255)
                color = row_colors[idx][i] if row_colors and i < len(row_colors[idx]) else _COLOR_TEXT
                self.set_text_color(*color)
                text = _safe_text("" if cell is None else str(cell), self.font_name)
                # 数字列右对齐
                align = "R" if i > 0 and any(ch.isdigit() for ch in text) and not any('一' <= c <= '鿿' for c in text) else "C"
                # 第一列 (ticker / 行业名) 左对齐
                if i == 0:
                    align = "L"
                self.cell(widths[i], _TABLE_ROW_H, text, border=1, fill=use_alt, align=align)
            self.ln(_TABLE_ROW_H)
        self.set_text_color(*_COLOR_TEXT)
        self.ln(1)


# ---------------------------------------------------------------------------
# 区块渲染
# ---------------------------------------------------------------------------


def _render_title_page(pdf: _ScreeningPDF, report_data: dict) -> None:
    pdf.add_page()
    pdf._report_date = _format_date_display(report_data.get("date", ""))

    # 顶部留白
    pdf.ln(20)
    pdf._set_font("B", pdf.config.title_size + 4)
    pdf.set_text_color(*_COLOR_BANNER)
    pdf.cell(0, 14, _safe_text(pdf.config.title, pdf.font_name), align="C", new_x="LMARGIN", new_y="NEXT")

    if pdf.config.subtitle:
        pdf._set_font("", pdf.config.body_size + 1)
        pdf.set_text_color(*_COLOR_MUTED)
        pdf.cell(0, 8, _safe_text(pdf.config.subtitle, pdf.font_name), align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(15)

    # 元数据卡片
    pdf._set_font("B", pdf.config.body_size + 1)
    pdf.set_text_color(*_COLOR_BANNER)
    pdf.cell(0, 7, _safe_text("报告元数据", pdf.font_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*_COLOR_BORDER)
    y = pdf.get_y()
    pdf.line(_MARGIN, y, pdf.w - _MARGIN, y)
    pdf.ln(2)

    pdf.set_text_color(*_COLOR_TEXT)
    pdf._kv_line("报告日期", _format_date_display(report_data.get("date", "")))
    pdf._kv_line("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    pdf._kv_line("作者", pdf.config.author)
    pdf._kv_line("模式", str(report_data.get("mode", "auto_screening")))

    layer_a = report_data.get("layer_a_count", "n/a")
    total_scored = report_data.get("total_scored", "n/a")
    high_pool = report_data.get("high_pool_count", "n/a")
    top_n = report_data.get("top_n", "n/a")
    pdf._kv_line("Layer A 候选池", f"{layer_a} 只")
    pdf._kv_line("Layer B 评分", f"{total_scored} 只 (high_pool: {high_pool})")
    pdf._kv_line("Top N", f"{top_n}")

    pdf.ln(4)
    pdf._section("免责声明")
    pdf._paragraph(
        "本报告由 AI 模型自动生成, 仅供研究 / 学习用途, 不构成任何投资建议。"
        "报告中所有信号、评分、决策均为模型输出, 实际投资需结合个人风险承受能力与最新市场情况。"
        "历史回测表现不代表未来收益。"
    )


def _render_market_state(pdf: _ScreeningPDF, report_data: dict) -> None:
    if not pdf.config.include_market_state:
        return
    state = report_data.get("market_state") or {}
    if not state:
        return
    pdf._section("市场状态概览")
    pdf._kv_line("状态类型", str(state.get("state_type", "n/a")))
    pdf._kv_line("仓位系数", f"{state.get('position_scale', 0):.2f}")
    pdf._kv_line("ADX (趋势强度)", f"{state.get('adx', 0):.2f}")
    pdf._kv_line("ATR (波动率)", f"{state.get('atr', 0):.4f}")
    pdf._kv_line("市场宽度", f"{state.get('breadth', 0):+.2%}" if isinstance(state.get("breadth"), (int, float)) else "n/a")
    pdf._kv_line("北向资金 (亿)", f"{state.get('north_flow', 0):+.2f}" if state.get("north_flow") is not None else "n/a")
    pdf._kv_line("涨跌停比", f"{state.get('limit_up', 0)} / {state.get('limit_down', 0)}")
    pdf._kv_line("Regime Gate", str(state.get("regime_gate", "n/a")))


def _render_industry_rotation(pdf: _ScreeningPDF, report_data: dict) -> None:
    if not pdf.config.include_industry_rotation:
        return
    rotation = report_data.get("industry_rotation") or []
    if not rotation:
        return
    pdf._section("行业轮动信号")
    headers = ["行业", "动量", "平均 score_b", "候选数"]
    widths = [60.0, 30.0, 35.0, 25.0]
    rows: list[list[Any]] = []
    row_colors: list[list[tuple[int, int, int]]] = []
    for sig in rotation[:15]:
        momentum = float(sig.get("momentum_score", 0))
        color = _COLOR_BUY if momentum > 5 else (_COLOR_AVOID if momentum < -5 else _COLOR_WATCH)
        rows.append([
            sig.get("industry_name", ""),
            f"{momentum:+.1f}",
            f"{float(sig.get('avg_score_b', 0)):+.2f}",
            int(sig.get("candidate_count", 0)),
        ])
        row_colors.append([_COLOR_TEXT, color, _COLOR_TEXT, _COLOR_TEXT])
    pdf._table(headers, widths, rows, row_colors=row_colors)


def _render_recommendations(pdf: _ScreeningPDF, report_data: dict) -> None:
    if not pdf.config.include_recommendations:
        return
    recs = report_data.get("recommendations") or []
    if not recs:
        return
    pdf._section(f"推荐标的 (Top {min(len(recs), pdf.config.max_recommendations)})")
    headers = ["代码", "名称", "行业", "score_b", "决策", "连续天数", "信号衰减"]
    widths = [22.0, 38.0, 28.0, 18.0, 22.0, 18.0, 24.0]
    rows: list[list[Any]] = []
    row_colors: list[list[tuple[int, int, int]]] = []
    for rec in recs[: pdf.config.max_recommendations]:
        decision = rec.get("decision", "neutral")
        decision_color = _decision_color(decision)
        decay = rec.get("decay") or {}
        decay_level = decay.get("level", "none")
        decay_color = _COLOR_AVOID if decay_level in ("strong", "moderate") else (_COLOR_WATCH if decay_level == "mild" else _COLOR_MUTED)
        decay_text = {
            "strong": "强衰减",
            "moderate": "中衰减",
            "mild": "弱衰减",
            "none": "无",
        }.get(decay_level, decay_level)
        rows.append([
            rec.get("ticker", ""),
            rec.get("name", "") or "-",
            rec.get("industry_sw", "") or "-",
            f"{float(rec.get('score_b', 0)):+.4f}",
            decision,
            int(rec.get("consecutive_days", 0) or 0),
            decay_text,
        ])
        row_colors.append([
            _COLOR_TEXT,
            _COLOR_TEXT,
            _COLOR_MUTED,
            _COLOR_BUY if float(rec.get("score_b", 0)) > 0 else _COLOR_AVOID,
            decision_color,
            _COLOR_BUY if int(rec.get("consecutive_days", 0) or 0) >= 3 else _COLOR_TEXT,
            decay_color,
        ])
    pdf._table(headers, widths, rows, row_colors=row_colors)

    # 因子贡献度 (Top 3 因子)
    pdf.ln(2)
    pdf._set_font("B", pdf.config.body_size)
    pdf.set_text_color(*_COLOR_BANNER)
    pdf.cell(0, 6, _safe_text("Top 3 因子贡献度 (按推荐前 3 名)", pdf.font_name), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_COLOR_TEXT)
    pdf._set_font("", pdf.config.body_size - 0.5)
    for idx, rec in enumerate(recs[:3], 1):
        ticker = rec.get("ticker", "")
        name = rec.get("name", "") or "-"
        strategy_signals = rec.get("strategy_signals", {}) or {}
        factors: list[str] = []
        for strat_name, signal in list(strategy_signals.items())[:4]:
            if isinstance(signal, dict):
                direction = signal.get("direction", 0)
                confidence = signal.get("confidence", 0)
                factors.append(f"{strat_name}(d={direction}, c={confidence:.0f})")
            else:
                factors.append(str(strat_name))
        line = f"  {idx}. {ticker} {name}: " + ", ".join(factors) if factors else f"  {idx}. {ticker} {name}: (无信号细节)"
        pdf.cell(0, 5, _safe_text(line, pdf.font_name), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)


_TRACKING_HORIZONS: tuple[int, ...] = (1, 3, 5, 10, 20, 30)


def _render_tracking_summary(pdf: _ScreeningPDF, report_data: dict) -> None:
    if not pdf.config.include_tracking_summary:
        return
    summary = report_data.get("tracking_summary") or {}
    if not summary or summary.get("total_recommendations", 0) == 0:
        return
    pdf._section("追踪总结 (近 30 天胜率)")
    pdf._kv_line("总推荐数", summary.get("total_recommendations", 0))
    # BH-019: tracking_summary producer (recommendation_tracker._summarize_history /
    # get_tracking_summary) populates the full 6-horizon ladder under keys
    # ``win_rate_day{N}`` / ``avg_return_day{N}`` / ``tracked_count_day{N}``
    # (N in DEFAULT_HORIZONS = 1/3/5/10/20/30). The previous reader used the
    # non-existent ``t1_win_rate`` / ``total_observations`` / ``avg_t1_return``
    # keys, so every rate rendered as ``n/a`` on real payloads. Read the real
    # schema keys and surface the complete horizon ladder (R51/R52 computed-but-
    # hidden family: T+10/T+20/T+30 no longer dropped).
    def _fmt_pct(value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{value:.2%}"
        return "n/a"

    def _fmt_ret(value: Any) -> str:
        if isinstance(value, (int, float)):
            return f"{value:+.2%}"
        return "n/a"

    for day in _TRACKING_HORIZONS:
        win_rate = summary.get(f"win_rate_day{day}")
        tracked = summary.get(f"tracked_count_day{day}")
        avg_ret = summary.get(f"avg_return_day{day}")
        tracked_tag = f" ({tracked} 样本)" if isinstance(tracked, int) and tracked > 0 else ""
        pdf._kv_line(f"T+{day} 胜率{tracked_tag}", _fmt_pct(win_rate))
        pdf._kv_line(f"T+{day} 平均收益", _fmt_ret(avg_ret))


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _format_date_display(raw: Any) -> str:
    """把 ``YYYYMMDD`` 格式化成 ``YYYY-MM-DD``。"""
    s = str(raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def generate_screening_pdf(
    report_data: dict,
    output_path: Path,
    config: PDFReportConfig | None = None,
) -> Path:
    """将 ``auto_screening_*.json`` 报告数据生成为 PDF。

    Args:
        report_data: 来自 ``compute_auto_screening_results`` 或 ``auto_screening_*.json`` 的 dict。
        output_path: PDF 输出路径 (含文件名)。父目录不存在会自动创建。
        config: PDF 配置; 缺省使用 ``PDFReportConfig()``。

    Returns:
        ``output_path`` 本身 (供链式调用)。

    Raises:
        ImportError: 未安装 ``fpdf2`` (但 ``pyproject.toml`` 不包含此依赖, 运行时需
            ``uv pip install fpdf2``)。
    """
    config = config or PDFReportConfig()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = _ScreeningPDF(config=config, font_name=None)
    # 字体必须在目标 PDF 实例上注册 (fpdf2 不共享字体表)。
    font_name = _register_cjk_font(pdf)
    if font_name is not None:
        pdf.font_name = font_name
        pdf.set_font(font_name, "", config.body_size)

    pdf.alias_nb_pages()  # 使页脚中的 {nb} 生效
    pdf._report_date = _format_date_display(report_data.get("date", ""))

    _render_title_page(pdf, report_data)
    _render_market_state(pdf, report_data)
    _render_industry_rotation(pdf, report_data)
    _render_recommendations(pdf, report_data)
    _render_tracking_summary(pdf, report_data)

    pdf.output(str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# CLI / 集成辅助
# ---------------------------------------------------------------------------


def find_latest_report(report_dir: Path) -> Path | None:
    """返回 ``report_dir`` 下最新的 ``auto_screening_*.json`` 路径。"""
    if not report_dir.exists():
        return None
    files = sorted(report_dir.glob("auto_screening_*.json"), reverse=True)
    return files[0] if files else None


def load_report(report_path: Path) -> dict:
    """读取 ``auto_screening_*.json`` 报告, 失败时抛 ``ValueError``。"""
    try:
        with open(report_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法加载报告 {report_path}: {exc}") from exc


__all__ = [
    "PDFReportConfig",
    "generate_screening_pdf",
    "find_latest_report",
    "load_report",
]
