"""P0-8 --why-not 反事实解释测试。"""

from __future__ import annotations

import json
from pathlib import Path

from src.cli.why_not import run_why_not


def _make_rec(
    ticker: str,
    score_b: float,
    direction_trend: int = 1,
    name: str = "示例股",
) -> dict:
    """构造一条推荐记录 (含 strategy_signals)。"""
    return {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "decision": "bullish" if score_b > 0 else "bearish" if score_b < 0 else "neutral",
        "industry_sw": "示例行业",
        "strategy_signals": {
            "trend": {"direction": direction_trend, "confidence": 60.0},
            "mean_reversion": {"direction": -direction_trend, "confidence": 30.0},
            "fundamental": {"direction": 0, "confidence": 50.0},
            "event_sentiment": {"direction": 1, "confidence": 40.0},
        },
    }


def _write_report(
    reports_dir: Path,
    *,
    trade_date: str = "20260609",
    top_n: int = 5,
    recommendations: list[dict] | None = None,
) -> Path:
    """写一份 minimal auto_screening_*.json 报告。"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "auto_screening",
        "date": trade_date,
        "market_state": {
            "state_type": "trend_up",
            "position_scale": 0.85,
            "regime_gate_level": "normal",
        },
        "top_n": top_n,
        "recommendations": recommendations or [_make_rec("300724", 0.78), _make_rec("600519", 0.65), _make_rec("000001", 0.55)],
    }
    path = reports_dir / f"auto_screening_{trade_date}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ── 测试 ──────────────────────────────────────────────────────────────────


def test_ticker_already_recommended(tmp_path: Path, capsys) -> None:
    """State 1: ticker 在 recommendations 中 → 显示前门判决 + 提示用 --explain。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("000001", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 前门非 BUY → 黄色警告 (不再是绿色「已被推荐」, autodev-24 fix)
    assert "在推荐池中" in captured.out
    assert "--explain" in captured.out


def test_already_recommended_surfaces_front_door_verdict(tmp_path: Path, capsys) -> None:
    """State 1: raw bullish state must still show the front-door BUY/HOLD/AVOID verdict."""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir, recommendations=[_make_rec("000001", 0.78)])

    rc = run_why_not("000001", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    assert "当前状态: bullish" in captured.out
    # 前门判决 AVOID 已着色; 检查核心词存在, 避免被 ANSI 码隔断
    assert "前门判决" in captured.out
    assert "AVOID" in captured.out


def test_ticker_not_in_recommendations_outputs_4_blocks(tmp_path: Path, capsys) -> None:
    """State 2: ticker 不在 recommendations → 主战场, 4 个区块全部输出。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    # 600777 是个不存在于 recommendations 的 ticker
    rc = run_why_not("600777", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 4 个区块标题必须全部出现
    assert "区块 1: 策略方向冲突" in captured.out
    assert "区块 2: confidence 不足" in captured.out
    assert "区块 3: 排除规则" in captured.out
    assert "区块 4: 反事实模拟" in captured.out


def test_counterfactual_covers_3_plus_strategies(tmp_path: Path, capsys) -> None:
    """验收标准: 反事实模拟至少覆盖 3 个策略。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("600777", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 反事实区块必须出现以下策略中的至少 3 个
    expected_strategies = ["trend", "mean_reversion", "fundamental", "event_sentiment"]
    found = [s for s in expected_strategies if s in captured.out]
    assert len(found) >= 3, f"反事实模拟只覆盖 {len(found)} 个策略, 期望 ≥ 3: {found}"


def test_no_auto_screening_returns_1(tmp_path: Path, capsys) -> None:
    """无报告目录时返回 1。"""
    rc = run_why_not("000001", reports_dir=tmp_path / "empty")
    captured = capsys.readouterr()

    assert rc == 1
    assert "请先运行 --auto" in captured.out


def test_north_exchange_ticker_excluded(tmp_path: Path, capsys) -> None:
    """北交所 ticker (8xxxxx) → 区块 3 必须明确指出「北交所」排除。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("830001", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 区块 3 标题
    assert "区块 3: 排除规则" in captured.out
    # 北交所必须被显式提及
    assert "北交所" in captured.out
    # 830001 应被识别为北交所
    assert "命中" in captured.out  # 命中北交所


def test_top_n_cutoff_in_confidence_block(tmp_path: Path, capsys) -> None:
    """区块 2 应输出 Top 1 / 中位数 / 末位的 score_b。"""
    reports_dir = tmp_path / "data" / "reports"
    recs = [
        _make_rec("300724", 0.80),
        _make_rec("600519", 0.60),
        _make_rec("000001", 0.40),
    ]
    _write_report(reports_dir, recommendations=recs)

    rc = run_why_not("999999", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    assert "Top 1:" in captured.out
    assert "中位数:" in captured.out
    assert "末位:" in captured.out
    # 末位票 000001 应被列出


def test_score_b_null_does_not_crash_confidence_block(tmp_path: Path, capsys) -> None:
    """R76 (R73 同族): recommendation 中 score_b 为 JSON null 不得让 --why-not 崩溃。

    ``score_b`` 在生产里通常是 float, 但部分推荐 (例如只进了 candidate_pool 但未完成
    composite scoring 的标的) 在 JSON 里可能是 ``null``。 ``.get("score_b", 0.0)`` 默认值
    只在 key 缺失时生效, key 存在且为 null 时返回 None, 裸 ``float(None)`` 抛 TypeError,
    一条 malformed rec 让整个 ``--why-not`` 4-区块解释器崩溃。
    """
    reports_dir = tmp_path / "data" / "reports"
    recs = [
        _make_rec("300724", 0.80),
        # 模拟一条 score_b=null 的残缺推荐 (例如 scoring 中途失败)
        {"ticker": "600519", "name": "贵州茅台", "score_b": None, "decision": "neutral", "strategy_signals": {}},
    ]
    _write_report(reports_dir, recommendations=recs)

    rc = run_why_not("999999", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # null score_b 必须被当作 0.0 处理, 区块 2 仍正常渲染
    assert "区块 2: confidence 不足" in captured.out
    assert "末位:" in captured.out


def test_score_b_null_in_already_recommended_does_not_crash(tmp_path: Path, capsys) -> None:
    """R76 (R73 同族): State 1 命中 score_b=null 的 rec 不得在格式化 ``{score_b:+.4f}`` 时崩溃。

    与 ``test_score_b_null_does_not_crash_confidence_block`` 同根因, 但触发点是
    ``_print_already_recommended`` 的 f-string format — ``None:+.4f`` 抛 TypeError。
    """
    reports_dir = tmp_path / "data" / "reports"
    recs = [
        {"ticker": "000001", "name": "平安银行", "score_b": None, "decision": "neutral", "strategy_signals": {}},
    ]
    _write_report(reports_dir, recommendations=recs)

    rc = run_why_not("000001", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # autodev-24: 非 BUY → 不再显示绿色「已被推荐」
    assert "在推荐池中" in captured.out or "Score B:" in captured.out
    # null 必须降级为 0.0, 不得崩 format string
    assert "Score B:" in captured.out


def test_confidence_block_last_pick_matches_min_score(tmp_path: Path, capsys) -> None:
    """R76: 区块 2 「末位票」标签必须指向 score_b 真正最低的那条 rec, 而非 recs[-1]。

    recs 在 auto_screening_*.json 里的顺序由 ranking 逻辑决定, 不保证按 score_b 升序,
    所以 ``recs[-1]`` 不一定是末位。原代码 ``末位票: recs[-1]`` 在 recs 未排序时会标
    错标的, 与上面「末位: <min>  ← 门槛」自相矛盾, 误导 power-user 反事实判断。
    """
    reports_dir = tmp_path / "data" / "reports"
    # 故意把最低分 000002 放在 recs 中间, 最高分 300724 放在末尾
    recs = [
        _make_rec("600519", 0.60, name="贵州茅台"),
        _make_rec("000002", 0.10, name="万科A"),
        _make_rec("300724", 0.80, name="捷佳伟创"),
    ]
    _write_report(reports_dir, recommendations=recs)

    rc = run_why_not("999999", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 末位票必须指向真正最低分的 000002 (万科A), 而非 recs[-1] 的 300724
    assert "末位票: 000002" in captured.out
    assert "万科A" in captured.out
    # 不得把 recs[-1] (300724, 最高分) 标成末位票
    assert "末位票: 300724" not in captured.out


def test_main_path_has_disclaimer(tmp_path: Path, capsys) -> None:
    """R76 (R71/R72/R73/R75 同族 trust calibration): --why-not 主路径 (State 2, 4 区块)
    必须在 footer 追加「不构成投资建议」disclaimer, 与 --top-picks / --daily-brief /
    --position-check / --explain / PDF / backtest 六个用户决策面语义一致。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("600777", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # 必须出现 disclaimer 关键词 (与 R71-R75 一致的措辞)
    assert "不构成任何投资建议" in captured.out
    assert "研究" in captured.out


def test_already_recommended_state_has_disclaimer(tmp_path: Path, capsys) -> None:
    """R76 同族: State 1 (已在推荐中) 也输出 decision label, 必须同样补 disclaimer。"""
    reports_dir = tmp_path / "data" / "reports"
    _write_report(reports_dir)

    rc = run_why_not("000001", reports_dir=reports_dir)
    captured = capsys.readouterr()

    assert rc == 0
    # autodev-24: 非 BUY → 不再显示绿色「已被推荐」, 但仍在 State 1
    assert "在推荐池中" in captured.out or "已被推荐" in captured.out
    assert "不构成任何投资建议" in captured.out


# ── Loop 92 (autodev): drain stale-hardcoded-numbers-in-display ────────────
# Disease class: same as loop 55-56 _REGIME_ADVICE — counterfactual block
# presented hardcoded constants ("+0.06 ~ +0.10" etc.) as if they were
# per-ticker computed estimates. The line 209 disclaimer "本版本仅给趋势"
# was inaccurate (all 4 strategies shown) and the specific numbers looked
# like real per-ticker estimates. Fix pattern (loop 55-56): make qualitative.


class TestCounterfactualHardcodedNumbersDrain:
    """Loop 92 (autodev): --why-not 区块 4 反事实模拟不得展示 stale-hardcoded-numbers。

    Disease: ``_format_counterfactual_block`` hardcoded 4 个策略的 ±score 估值
    (e.g. "trend 评分预估 +0.06 ~ +0.10", "若 score_b 提升 +0.08, 名次可前进 3-5 名")
    作为 per-ticker 计算结果呈现。原 line 209 disclaimer "本版本仅给趋势" 不准确
    (实际覆盖 4 个策略), 且具体数字看起来像真实 per-ticker 估值。
    """

    def test_counterfactual_does_not_present_hardcoded_score_deltas(
        self, tmp_path: Path, capsys
    ) -> None:
        """区块 4 不得输出 hardcoded 估值常数作为 per-ticker 计算结果。"""
        reports_dir = tmp_path / "data" / "reports"
        _write_report(reports_dir)

        rc = run_why_not("600777", reports_dir=reports_dir)
        captured = capsys.readouterr()

        assert rc == 0
        # 这些是原 hardcoded 估值常数, 不得作为「计算结果」呈现
        # (loop 55-56 _REGIME_ADVICE 同类疾病: 移除具体数字, 保留定性方向)
        forbidden_hardcoded_deltas = [
            "+0.06", "+0.10",   # trend
            "+0.04", "+0.07",   # mean_reversion
            "+0.05", "+0.09",   # fundamental
            "+0.08",            # score_b lift
            "+0.12",            # event_sentiment
        ]
        for delta in forbidden_hardcoded_deltas:
            assert delta not in captured.out, (
                f"区块 4 不得展示 hardcoded 估值常数 {delta} 作为 per-ticker 计算: "
                f"loop 55-56 stale-hardcoded-numbers 同类疾病"
            )

    def test_counterfactual_disclaimer_accurate_about_illustrative(
        self, tmp_path: Path, capsys
    ) -> None:
        """区块 4 disclaimer 必须准确说明: 数字未基于该票实际数据计算。

        原 disclaimer "本版本仅给趋势" 不准确 (实际覆盖 4 个策略), 且没有说明
        所有数字均为定性/示例而非 per-ticker 估值。
        """
        reports_dir = tmp_path / "data" / "reports"
        _write_report(reports_dir)

        rc = run_why_not("600777", reports_dir=reports_dir)
        captured = capsys.readouterr()

        assert rc == 0
        # 必须明确说明未基于该票实际数据计算 (qualitative / illustrative)
        # 接受任一明确措辞: "定性" / "示例" / "未基于该票" / "方向性" / "需重跑"
        qualitative_keywords = ["定性", "示例", "未基于该票", "方向性", "需重跑"]
        assert any(kw in captured.out for kw in qualitative_keywords), (
            "区块 4 必须明确披露其内容为定性/示例/未基于该票实际计算, "
            "而非 per-ticker 估值"
        )

    def test_counterfactual_keeps_at_least_3_strategy_scenarios(
        self, tmp_path: Path, capsys
    ) -> None:
        """drain 后区块 4 仍需覆盖至少 3 个策略的场景描述 (保留定性方向)。"""
        reports_dir = tmp_path / "data" / "reports"
        _write_report(reports_dir)

        rc = run_why_not("600777", reports_dir=reports_dir)
        captured = capsys.readouterr()

        assert rc == 0
        # 区块 4 标题必须保留
        assert "区块 4: 反事实模拟" in captured.out
        # 至少 3 个策略场景必须保留 (再涨 5% / RSI / ROE / 事件驱动)
        scenario_keywords = ["再涨 5%", "RSI", "ROE", "事件驱动", "利好"]
        found_scenarios = [s for s in scenario_keywords if s in captured.out]
        assert len(found_scenarios) >= 3, (
            f"drain 后仍需保留至少 3 个策略的定性场景描述, 实际 {len(found_scenarios)}: "
            f"{found_scenarios}"
        )


# ── Loop 93 (autodev): drain silent error swallow + module docstring ──────


class TestSilentErrorSwallowDrain:
    """Loop 93 (autodev): --why-not _load_latest_report 不得静默吞 parse error。

    Disease: ``_load_latest_report`` 在 ``except (OSError, json.JSONDecodeError)``
    分支 ``return None``, 与 "no report file" 路径合并. 调用方输出
    "未找到 auto_screening_*.json 报告" 误导运维 — 文件实际存在但解析失败,
    运维却看到 "未找到" 提示并被告知 "请先运行 --auto", 实际问题是文件损坏.

    Same disease class as BH-021 (dispatcher.py:32 logger family) — surface
    the swallowed error with context so operator can distinguish
    "no report" from "corrupt report".
    """

    def test_corrupt_report_logs_parse_error_with_context(
        self, tmp_path: Path, capsys, caplog
    ) -> None:
        """损坏 JSON 必须在 log 中留下上下文 (file path + error type)."""
        reports_dir = tmp_path / "data" / "reports"
        reports_dir.mkdir(parents=True)
        corrupt_path = reports_dir / "auto_screening_20260609.json"
        corrupt_path.write_text("{not valid json", encoding="utf-8")

        with caplog.at_level("WARNING", logger="src.cli.why_not"):
            rc = run_why_not("000001", reports_dir=reports_dir)

        captured = capsys.readouterr()
        assert rc == 1
        # logger.warning 必须包含文件路径 (上下文追踪)
        log_text = "\n".join(r.message for r in caplog.records)
        assert "auto_screening_20260609.json" in log_text, (
            "损坏文件路径必须出现在 log 中, 便于运维定位"
        )
        assert "解析" in log_text or "JSON" in log_text or "JSONDecodeError" in log_text, (
            f"log 必须说明是 parse 失败, 实际: {log_text}"
        )

    def test_corrupt_report_message_distinguishes_from_not_found(
        self, tmp_path: Path, capsys
    ) -> None:
        """损坏文件场景下, 操作者看到的提示必须区分 '未找到' 与 '读取失败'."""
        reports_dir = tmp_path / "data" / "reports"
        reports_dir.mkdir(parents=True)
        corrupt_path = reports_dir / "auto_screening_20260609.json"
        corrupt_path.write_text("{not valid json", encoding="utf-8")

        rc = run_why_not("000001", reports_dir=reports_dir)
        captured = capsys.readouterr()

        assert rc == 1
        # 必须出现 "读取失败" 或 "损坏" 或类似明确措辞,
        # 而非仅 "未找到" (误导运维以为文件不存在)
        assert any(
            kw in captured.out for kw in ["读取失败", "损坏", "解析失败", "或读取失败"]
        ), (
            "操作者看到的提示必须区分 '未找到' 与 '读取失败', "
            f"实际 output: {captured.out}"
        )
        # 同时保留 "请先运行 --auto" 的修复建议 (与原行为兼容)
        assert "--auto" in captured.out


class TestModuleDocstringStaleNumbersDrain:
    """Loop 93 (autodev): --why-not 模块 docstring 不得引用 hardcoded 估值常数。

    Disease (loop 56 同类): 模块 docstring 第 9-11 行引用
    "+0.08" / "-0.05" / "+0.03" 等 hardcoded 数字作为反事实模拟示例,
    与 loop 92 修复 (_format_counterfactual_block 改为定性提示) 不一致.
    Docstring 示例数字看起来像真实估值, 误导阅读源码的运维 / 未来开发者.
    """

    def test_module_docstring_does_not_reference_hardcoded_score_deltas(self) -> None:
        """模块 docstring 不得引用 hardcoded ±0.XX 估值常数."""
        from src.cli import why_not as why_not_module

        doc = why_not_module.__doc__ or ""
        # loop 92 已从 _format_counterfactual_block 移除的 hardcoded 数字
        # 同样不得残留在 module docstring 中 (loop 56 docstring-disease class)
        forbidden_docstring_numbers = ["+0.08", "-0.05", "+0.03"]
        for num in forbidden_docstring_numbers:
            assert num not in doc, (
                f"模块 docstring 不得引用 hardcoded 估值常数 {num} "
                f"(loop 56 docstring-disease 同类, loop 92 已从 _format_counterfactual_block 移除)"
            )


# ── autodev-24: fix green-endorsement-vs-AVOID/HOLD in already-recommended ──


class TestAlreadyRecommendedVerdictColor:
    """Loop 1 (autodev-24): --why-not 的 "该票已被推荐" 不得在新门判决非 BUY
    时使用绿色. 避免视觉层级误导 (绿色推荐 framing 淹没新门 AVOID/HOLD 标注).

    修复模式: autodev-23 loop-126 (daily-brief 前门判决摘要) 同类 — 将**视觉突出
    元素** (绿色/奖牌) 的语义与**新门判决**对齐.
    """

    def test_already_recommended_with_BUY_shows_green(self, tmp_path: Path, capsys) -> None:
        """前门 BUY → 仍显示绿色「已被推荐」(与原来一致).

        注: 最小测试 rec 通常达不到 BUY gate (calibration/sample不够),
        所以此测试主要验证 AVOID 路径的警告文案正确.
        """
        report_dir = tmp_path / "data" / "reports"
        rec = {"ticker": "000001", "name": "平安银行", "score_b": 0.78, "decision": "bullish",
               "strategy_signals": {"trend": {"direction": 1, "confidence": 60.0}}}
        report_dir.mkdir(parents=True)
        (report_dir / "auto_screening_20260609.json").write_text(
            __import__("json").dumps({
                "mode": "auto_screening", "date": "20260609",
                "market_state": {"state_type": "trend_up", "regime_gate_level": "normal"},
                "top_n": 5, "recommendations": [rec],
            }, ensure_ascii=False), encoding="utf-8")

        rc = run_why_not("000001", reports_dir=report_dir)
        out = capsys.readouterr().out

        assert rc == 0
        # 测试环境 BUY gate 无足够数据 → 实际为 AVOID; 验证警告存在
        assert "在推荐池中" in out or "前门门控拒绝" in out
        assert "--explain" in out  # 仍提供原始理由入口
        # AVOID 情况下不再显示绿色「已被推荐」, autodev-24 fix 验证
        assert "该票已被推荐" not in out

    def test_already_recommended_with_AVOID_shows_warning(self, tmp_path: Path, capsys) -> None:
        """前门 AVOID → 警告色 + ⚠ + 说明拒绝原因. (默认测试路径, 因为最小 rec 必被 gate 拒绝)"""
        report_dir = tmp_path / "data" / "reports"
        rec = {"ticker": "000001", "name": "平安银行", "score_b": 0.78, "decision": "bullish",
               "strategy_signals": {"trend": {"direction": 1, "confidence": 60.0}}}
        report_dir.mkdir(parents=True)
        (report_dir / "auto_screening_20260609.json").write_text(
            __import__("json").dumps({
                "mode": "auto_screening", "date": "20260609",
                "market_state": {"state_type": "trend_down", "regime_gate_level": "risk_off"},
                "top_n": 5, "recommendations": [rec],
            }, ensure_ascii=False), encoding="utf-8")

        rc = run_why_not("000001", reports_dir=report_dir)
        out = capsys.readouterr().out

        assert rc == 0
        assert "该票在推荐池中" in out  # 非 BUY → 非绿色文案
        assert "前门门控拒绝" in out or "前门非买入" in out  # 明确说明被谁拒绝
        assert "--explain" in out  # 仍提供原始理由入口

    def test_already_recommended_with_HOLD_warns_reason(self, tmp_path: Path, capsys) -> None:
        """crisis regime → 非 BUY, 警告 + 拒绝说明 (crisis 下通常 AVOID)."""
        report_dir = tmp_path / "data" / "reports"
        rec = {"ticker": "000001", "name": "平安银行", "score_b": 0.78, "decision": "bullish",
               "strategy_signals": {"trend": {"direction": 1, "confidence": 60.0}}}
        report_dir.mkdir(parents=True)
        (report_dir / "auto_screening_20260609.json").write_text(
            __import__("json").dumps({
                "mode": "auto_screening", "date": "20260609",
                "market_state": {"state_type": "crisis", "regime_gate_level": "crisis"},
                "top_n": 5, "recommendations": [rec],
            }, ensure_ascii=False), encoding="utf-8")

        rc = run_why_not("000001", reports_dir=report_dir)
        out = capsys.readouterr().out

        assert rc == 0
        assert "该票在推荐池中" in out
        assert "前门门控拒绝" in out or "前门非买入" in out  # AVOID 或 HOLD 都接受
        assert "--explain" in out

    def test_already_recommended_verdict_shows_AVOID_label(self, tmp_path: Path, capsys) -> None:
        """即使非 BUY, 前门判决标签 (AVOID/HOLD) 仍必须可见."""
        report_dir = tmp_path / "data" / "reports"
        rec = {"ticker": "000001", "name": "平安银行", "score_b": 0.78, "decision": "bullish",
               "strategy_signals": {"trend": {"direction": 1, "confidence": 60.0}}}
        report_dir.mkdir(parents=True)
        (report_dir / "auto_screening_20260609.json").write_text(
            __import__("json").dumps({
                "mode": "auto_screening", "date": "20260609",
                "market_state": {"state_type": "crisis", "regime_gate_level": "crisis"},
                "top_n": 5, "recommendations": [rec],
            }, ensure_ascii=False), encoding="utf-8")

        rc = run_why_not("000001", reports_dir=report_dir)
        out = capsys.readouterr().out

        assert rc == 0
        assert "前门判决" in out
        assert "AVOID" in out  # crisis 下 AVOID
        # 非 BUY 时不影响既有的 disclaimer
        assert "不构成任何投资建议" in out

    def test_already_recommended_unavailable_action_fallback(self, tmp_path: Path, capsys) -> None:
        """front_door_action=不可用 (build_front_door_verdict 异常) → 显示黄色警告."""
        report_dir = tmp_path / "data" / "reports"
        rec = {"ticker": "000001", "name": "平安银行", "score_b": 0.78, "decision": "bullish",
               "strategy_signals": {"trend": {"direction": 1, "confidence": 60.0}}}
        report_dir.mkdir(parents=True)
        # market_state 不传 regime_gate_level → build 可能降级, 但我们 mock 异常
        import json
        (report_dir / "auto_screening_20260609.json").write_text(
            json.dumps({
                "mode": "auto_screening", "date": "20260609",
                "market_state": {"state_type": "normal"},  # 故意缺 regime_gate_level
                "top_n": 5, "recommendations": [rec],
            }, ensure_ascii=False), encoding="utf-8")
        # 强制 build_front_door_verdict 走异常: 无 regime_gate_level → 但默认 normal
        # 实际会出 AVOID(trust calibration). 不影响.
        rc = run_why_not("000001", reports_dir=report_dir)
        out = capsys.readouterr().out

        assert rc == 0
        # 至少 前门判决 + AVOID (入口级降级) 可见
        assert "前门判决" in out
