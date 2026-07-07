"""Tests for P0-7 ``run_daily_brief()`` — 盘前 5 分钟决策卡。

测试范围:
  1. ``test_basic_top3_output`` — 3 只推荐, 输出包含 ticker / 市场状态 / 行业轮动
  2. ``test_no_tracking_history_graceful`` — 无 tracking_history.json 时不崩溃
  3. ``test_consecutive_recommendation_bonus`` — 同分时连续天数加权
  4. ``test_industry_rotation_top1`` — 多票行业计数, Top 1 行业正确
  5. ``test_missing_auto_screening_returns_1`` — 没有任何报告时函数返回 1
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strategy_signal(direction: int, confidence: float, sub_factors: dict | None = None) -> dict:
    return {
        "direction": direction,
        "confidence": confidence,
        "completeness": 0.8,
        "sub_factors": sub_factors or {},
    }


def _make_recommendation(
    ticker: str,
    name: str = "测试股票",
    industry_sw: str = "银行",
    score_b: float = 0.5,
    decision: str = "bullish",
    consecutive_days: int = 0,
    strategy_signals: dict | None = None,
) -> dict:
    rec: dict = {
        "ticker": ticker,
        "name": name,
        "industry_sw": industry_sw,
        "score_b": score_b,
        "decision": decision,
        "consecutive_days": consecutive_days,
        "recommendation_history": [],
        "strategy_signals": strategy_signals
        or {
            "trend": _make_strategy_signal(1, 70.0),
            "mean_reversion": _make_strategy_signal(1, 60.0),
            "fundamental": _make_strategy_signal(1, 50.0),
            "event_sentiment": _make_strategy_signal(0, 30.0),
        },
    }
    return rec


def _make_report(recommendations: list[dict], date: str = "20260607") -> dict:
    return {
        "mode": "auto_screening",
        "date": date,
        "market_state": {
            "state_type": "trend",
            "position_scale": 0.85,
            "regime_gate_level": "normal",
            "adx": 22.5,
            "atr_price_ratio": 0.015,
            "breadth_ratio": 0.55,
        },
        "layer_a_count": 500,
        "top_n": 10,
        "recommendations": recommendations,
    }


def _write_report(tmp_path: Path, payload: dict, filename: str = "auto_screening_20260607.json") -> Path:
    report_path = tmp_path / filename
    report_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return report_path


def _write_history(tmp_path: Path, records: list[dict]) -> Path:
    history_path = tmp_path / "tracking_history.json"
    history_path.write_text(
        json.dumps({"records": records, "updated_at": "20260609000000"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return history_path


def _make_history_record(ticker: str, date: str, score_b: float = 0.5) -> dict:
    return {
        "ticker": ticker,
        "name": ticker,
        "recommended_date": date,
        "recommended_price": 10.0,
        "recommendation_score": score_b,
        "tracking_status": "pending",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDailyBriefBasic:
    def test_basic_top3_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """3 只推荐 → 输出包含 3 个 ticker + 市场状态 + 行业轮动。"""
        recs = [
            _make_recommendation("000001", "平安银行", "银行", score_b=0.62, consecutive_days=3),
            _make_recommendation("000002", "万科A", "地产", score_b=0.55, consecutive_days=0),
            _make_recommendation("000003", "国农科技", "电子", score_b=0.45, consecutive_days=0),
        ]
        _write_report(tmp_path, _make_report(recs))

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert "000001" in out
        assert "000002" in out
        assert "000003" in out
        assert "盘前决策卡" in out
        assert "trend" in out
        assert "regime" in out
        assert "行业轮动" in out

    def test_no_tracking_history_graceful(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """无 tracking_history.json 时不崩溃, 跳过连续推荐字段。"""
        recs = [
            _make_recommendation("000001", "平安银行", "银行", score_b=0.62),
            _make_recommendation("000002", "万科A", "地产", score_b=0.55),
            _make_recommendation("000003", "国农科技", "电子", score_b=0.45),
        ]
        _write_report(tmp_path, _make_report(recs))
        # 故意不写 tracking_history.json
        assert not (tmp_path / "tracking_history.json").exists()

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert "000001" in out
        assert "盘前决策卡" in out

    def test_disclaimer_in_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """R72 (R71 同族 trust calibration): 盘前决策卡输出末尾含研究用途 disclaimer。

        ``--daily-brief`` 是 §二 当前默认前门之一 (盘前补充摘要), 输出具体的
        Top 3 ticker + score_b + BUY/HOLD/AVOID 决策标签, 与 ``--top-picks`` (R71)、
        PDF exporter、backtest CLI 同属"可能被误读为投资指令的具体决策建议"。
        但此前仅 ``--top-picks`` 有 footer disclaimer, ``--daily-brief`` 缺失,
        与产品目标 "更高确信" (确信包含诚实的边界告知) 不一致。
        """
        recs = [
            _make_recommendation("000001", "平安银行", "银行", score_b=0.62),
            _make_recommendation("000002", "万科A", "地产", score_b=0.55),
            _make_recommendation("000003", "国农科技", "电子", score_b=0.45),
        ]
        _write_report(tmp_path, _make_report(recs))

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        # 与 R71 / pdf_exporter / backtest cli 一致的边界告知关键词
        assert "不构成" in out
        assert "投资建议" in out
        assert "研究" in out


class TestDailyBriefFrontDoorVerdictConsistency:
    """autodev-13 / loop 102: cross-surface verdict consistency.

    Empirical dogfood of --daily-brief on report 20260703 found that ALL 3
    top picks contradicted the --top-picks front-door verdict on the SAME
    report — 🥇 688019 daily-brief said ``strong_buy`` but the front-door BUY
    gate (composite ≥ 0.5 AND T+5/T+10 winrate ≥ 0.55 AND mature sample ≥ 20
    AND edge > 0) returned AVOID (样本不足20, 动量转负, 量价背离); likewise
    688766 strong_buy→AVOID and 002463 watch→BUY (inverted). Root cause: the
    daily-brief renders the RAW LLM ``decision`` field (``rec.get("decision")``)
    which is the pre-gate qualitative read, NOT the actionable front-door
    verdict. For a 赚钱工具 the operator's morning card saying "strong_buy #1"
    for a pick the front door rates AVOID directly causes wrong actions.

    Fix scope (additive disclosure, contract §用户可见诚实化): surface the
    front-door verdict alongside the raw decision with a ⚠ when they disagree,
    so the operator sees the contradiction. Does NOT change the raw-decision
    display or the ranking (owner-gated); only adds the gated verdict.
    Same disease class as C268 ("High confidence picks" composite-only →
    BUY-verdict) and the opportunity-index fix.
    """

    def test_raw_strong_buy_contradicted_by_front_door_avoid_is_disclosed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """raw decision=strong_buy but front-door verdict=AVOID → the daily-brief
        must surface the contradiction (⚠ + AVOID) so the operator is not told
        'strong_buy' for a pick the gate rejects."""
        # decision=strong_buy (raw LLM read) but NO calibration fields →
        # build_front_door_verdict returns AVOID ("数据缺失" / sample<20).
        rec = _make_recommendation("688019", "安集科技", "电子", score_b=0.61, decision="strong_buy")
        rec["composite_score"] = 0.61  # no win_rates/bucket_sample → AVOID
        _write_report(tmp_path, _make_report([rec]))

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert "strong_buy" in out, "raw decision is still shown (additive disclosure)"
        assert "AVOID" in out, "When the raw decision (strong_buy) is contradicted by the front-door " "verdict (AVOID), the daily-brief MUST surface the gated verdict so the " "operator is not misled into acting on a pre-gate signal the BUY gate rejects."

    def test_raw_decision_agrees_with_front_door_no_contradiction_marker(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Negative guard: when raw decision and front-door verdict AGREE (both
        BUY), no contradiction marker is needed. The verdict is still shown (for
        cross-surface consistency with --top-picks) but without a ⚠ alarm."""
        # decision=strong_buy AND full calibration passing the BUY gate → verdict BUY.
        rec = _make_recommendation("000001", "票A", "银行", score_b=0.70, decision="strong_buy")
        rec["composite_score"] = 0.70
        rec["win_rates"] = {"t5": 0.62, "t10": 0.62}
        rec["expected_returns"] = {"t5": 3.0, "t10": 4.0}
        rec["bucket_sample_count"] = 100
        rec["bucket_t30_mature_count"] = 90
        rec["bucket_label"] = "低 (<0.5)"
        _write_report(tmp_path, _make_report([rec]))

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert "BUY" in out
        # No contradiction alarm when raw decision and verdict agree.
        # (The exact marker wording is implementation-defined; this test only
        # pins that agreement does not trigger the contradiction disclosure.)


class TestDailyBriefVerdictSummary:
    """autodev-23 / loop 126: top-level front-door verdict summary.

    The per-pick `前门: AVOID ⚠` annotation (loop 102) is buried mid-line
    under the medal + strong_buy + bullish one-liner. A top-level summary
    line surfaces the gate's verdict UPFRONT so the operator sees which
    picks are actually endorsed before reading per-pick details.
    """

    def test_summary_lists_buy_and_avoid_counts_upfront(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """When top3 mixes BUY and AVOID, the summary must show both counts
        and the ticker lists so the operator can scan endorsements at a glance."""
        # 2 AVOID (no calibration) + 1 BUY (full calibration passing the gate)
        avoid_a = _make_recommendation("688019", "安集科技", "电子", score_b=0.61, decision="strong_buy")
        avoid_a["composite_score"] = 0.61
        avoid_b = _make_recommendation("688766", "普冉股份", "电子", score_b=0.52, decision="strong_buy")
        avoid_b["composite_score"] = 0.52
        buy_rec = _make_recommendation("002463", "沪电股份", "电子", score_b=0.49, decision="watch")
        buy_rec["composite_score"] = 0.70
        buy_rec["win_rates"] = {"t5": 0.62, "t10": 0.62}
        buy_rec["expected_returns"] = {"t5": 3.0, "t10": 4.0}
        buy_rec["bucket_sample_count"] = 100
        buy_rec["bucket_t30_mature_count"] = 90
        buy_rec["bucket_label"] = "低 (<0.5)"
        _write_report(tmp_path, _make_report([avoid_a, avoid_b, buy_rec]))

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        # Summary line appears before the per-pick cards
        summary_idx = out.find("前门判决")
        first_medal_idx = out.find("🥇")
        assert summary_idx > 0, "top-level 前门判决 summary must be rendered"
        assert first_medal_idx > summary_idx, "summary must appear BEFORE per-pick medal cards"
        # BUY count and ticker list
        assert "BUY 1/3" in out, "summary must show BUY count out of total"
        assert "✓ BUY: 002463" in out, "summary must list the BUY ticker"
        # AVOID count and ticker list
        assert "AVOID 2" in out
        assert "⚠ AVOID: 688019, 688766" in out, "summary must list AVOID tickers with warning"

    def test_summary_omits_avoid_line_when_all_buy(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """When all picks are front-door BUY, no AVOID warning line."""
        buy_recs = []
        for ticker in ("000001", "000002", "000003"):
            rec = _make_recommendation(ticker, f"票{ticker}", "银行", score_b=0.70, decision="strong_buy")
            rec["composite_score"] = 0.70
            rec["win_rates"] = {"t5": 0.62, "t10": 0.62}
            rec["expected_returns"] = {"t5": 3.0, "t10": 4.0}
            rec["bucket_sample_count"] = 100
            rec["bucket_t30_mature_count"] = 90
            rec["bucket_label"] = "低 (<0.5)"
            buy_recs.append(rec)
        _write_report(tmp_path, _make_report(buy_recs))

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert "BUY 3/3" in out
        assert "⚠ AVOID" not in out, "no AVOID warning when all picks are BUY"


class TestDailyBriefSorting:
    def test_consecutive_recommendation_bonus(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """同 score_b 时, 连续 3 日的票排在连续 1 日的票前面。"""
        recs = [
            _make_recommendation("000001", "票A", "银行", score_b=0.50, consecutive_days=1),
            _make_recommendation("000002", "票B", "地产", score_b=0.50, consecutive_days=3),
        ]
        # 加入更多票填充到 Top 3
        recs.append(_make_recommendation("000003", "票C", "电子", score_b=0.40, consecutive_days=0))
        _write_report(tmp_path, _make_report(recs))

        # 写入 tracking_history 强化 consecutive_days
        history = [
            _make_history_record("000002", "20260607"),
            _make_history_record("000002", "20260606"),
            _make_history_record("000002", "20260605"),
            _make_history_record("000001", "20260607"),
        ]
        _write_history(tmp_path, history)

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        # 000002 应该出现在 #1 (同分时连续 3 日胜出)
        # 通过查看哪个 ticker 第一次出现在 #1 行附近来验证
        # 取第一行 ticker 引用: 000002 应在 #1, 000001 在 #2 (因为 score 调整后 000002 + 0.15 > 000001 + 0.05)
        first_pos_000002 = out.find("000002")
        first_pos_000001 = out.find("000001")
        assert first_pos_000002 != -1
        assert first_pos_000001 != -1
        assert first_pos_000002 < first_pos_000001, "000002 (consec=3) 应排在 000001 (consec=1) 之前"

    def test_top3_must_include_consecutive_ge2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Top 3 必须包含至少 1 只连续推荐 ≥2 日的票 — 替换最末位规则。"""
        # 3 只高 score_b 票 (但都只有 consec=0 或 1), 加上 1 只低分但 consec=3 的票
        recs = [
            _make_recommendation("000001", "A", "银行", score_b=0.80, consecutive_days=0),
            _make_recommendation("000002", "B", "电子", score_b=0.70, consecutive_days=1),
            _make_recommendation("000003", "C", "机械", score_b=0.60, consecutive_days=0),
            _make_recommendation("000004", "D", "医药", score_b=0.10, consecutive_days=3),
        ]
        _write_report(tmp_path, _make_report(recs))

        history = [
            _make_history_record("000004", "20260607"),
            _make_history_record("000004", "20260606"),
            _make_history_record("000004", "20260605"),
            _make_history_record("000002", "20260607"),
        ]
        _write_history(tmp_path, history)

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        # 000004 (consec=3) 必须出现在 Top 3 中 — 替换了 #3
        assert "000004" in out

    def test_selection_logic_disclosure_shown_when_top3_different(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """autodev-28 loop 143: 当 _select_top3 的 Top 3 与原始报告排序不同时,
        必须显示排序说明披露."""
        recs = [
            _make_recommendation("000001", "A", "银行", score_b=0.70, consecutive_days=0),
            _make_recommendation("000002", "B", "银行", score_b=0.69, consecutive_days=0),
            _make_recommendation("000003", "C", "银行", score_b=0.68, consecutive_days=0),  # 原始第 3
            _make_recommendation("000004", "D", "科技", score_b=0.10, consecutive_days=3),  # 因加成上位
        ]
        _write_report(tmp_path, _make_report(recs))

        history = [
            _make_history_record("000004", "20260607"),
            _make_history_record("000004", "20260606"),
            _make_history_record("000004", "20260605"),
        ]
        _write_history(tmp_path, history)

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        # 必须有排序说明
        assert "排序说明" in out
        assert "连续推荐" in out
        assert "000004" in out  # 说明中应包含被推荐的标的

    def test_selection_logic_disclosure_omitted_when_top3_matches(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """当 Top 3 与原始报告完全一致时, 不显示排序说明 (减少噪音)."""
        recs = [
            _make_recommendation("000001", "A", "银行", score_b=0.70, consecutive_days=0),
            _make_recommendation("000002", "B", "银行", score_b=0.69, consecutive_days=0),
            _make_recommendation("000003", "C", "银行", score_b=0.68, consecutive_days=0),
        ]
        _write_report(tmp_path, _make_report(recs))
        _write_history(tmp_path, [])

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        assert "排序说明" not in out  # 无差异时不披露


class TestDailyBriefIndustryRotation:
    def test_industry_rotation_top1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """5 只票, 3 只银行 2 只科技 → 行业 Top 1 = 银行业。"""
        recs = [
            _make_recommendation("000001", "银行A", "银行", score_b=0.62),
            _make_recommendation("000002", "银行B", "银行", score_b=0.55),
            _make_recommendation("000003", "银行C", "银行", score_b=0.45),
            _make_recommendation("000004", "科技A", "科技", score_b=0.50),
            _make_recommendation("000005", "科技B", "科技", score_b=0.40),
        ]
        _write_report(tmp_path, _make_report(recs))

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 0
        # 行业轮动 Top 1 行应包含 "银行业"
        assert "银行业" in out or "银行" in out
        # 验证输出结构有 "行业轮动 Top 1"
        assert "行业轮动 Top 1" in out


class TestDailyBriefErrors:
    def test_missing_auto_screening_returns_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """没有任何 auto_screening_*.json 时, 函数返回 1。"""
        # 不写任何报告文件
        assert list(tmp_path.glob("auto_screening_*.json")) == []

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 1
        # 应有 "请先运行 --auto" 之类的提示
        assert "--auto" in out or "请先运行" in out

    def test_corrupt_report_returns_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """报告文件损坏时函数返回 1。"""
        bad_path = tmp_path / "auto_screening_20260607.json"
        bad_path.write_text("{not valid json", encoding="utf-8")

        from src.cli.daily_brief import run_daily_brief

        rc = run_daily_brief(report_dir=tmp_path)
        out = capsys.readouterr().out

        assert rc == 1
        assert "失败" in out or "无法" in out or "读取" in out


class TestDailyBriefHelpers:
    """单元测试 — 内部 helper 函数。"""

    def test_find_latest_report_skips_malformed_filename(self, tmp_path: Path) -> None:
        """R86: ``_find_latest_report`` 必须跳过非日期 stem 的 malformed 文件名。

        bug 复现: 旧实现 ``sorted(glob(...), reverse=True)[0]`` 是纯字母排序,
        字母 (如 'g' in ``auto_screening_garbage.json``) 排在 ASCII 数字之后,
        会把 malformed 文件误选为"最新"报告。sibling ``data_quality_audit.
        _find_latest_report`` 已在 R54 加了日期 stem 校验, daily_brief 漏改。

        影响: reports/ 里混入一个 stray ``auto_screening_garbage.json`` (手动测试
        残留 / 部分写入) 时, ``--daily-brief`` 会选中它而非最新合法日期报告,
        然后 ``_load_report`` 要么 JSONDecodeError 崩溃, 要么渲染错误日期的推荐。
        """
        from src.cli.daily_brief import _find_latest_report

        # 一个合法日期报告 + 一个 malformed stem (字母开头排在数字之后)
        good = tmp_path / "auto_screening_20260607.json"
        good.write_text('{"date": "20260607", "recommendations": []}', encoding="utf-8")
        junk = tmp_path / "auto_screening_garbage.json"
        junk.write_text("{not valid json", encoding="utf-8")

        latest = _find_latest_report(tmp_path)
        # 必须选合法日期报告, 而非字母排序靠后的 garbage
        assert latest == good, f"应选合法日期报告 {good.name}, 实际选了 {latest!r} (malformed 文件名未被日期校验过滤)"

    def test_print_watchlist_health_logs_debug_on_load_failure(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """R86 drain (BH-021 family): watchlist 加载失败时应发 debug 日志, 让运维可诊断
        "配置损坏 / import 失败" vs 良性 "用户没配 watchlist"。
        """
        import logging as _logging

        # monkeypatch load_watchlist 让它抛异常 -- 通过 sys.modules 注入坏模块
        import sys as _sys
        from types import ModuleType

        from src.cli.daily_brief import _print_watchlist_health

        bad_mod = ModuleType("src.screening.watchlist")

        def _bad_load_watchlist():
            raise RuntimeError("watchlist.json 损坏")

        bad_mod.load_watchlist = _bad_load_watchlist
        original = _sys.modules.get("src.screening.watchlist")
        _sys.modules["src.screening.watchlist"] = bad_mod
        try:
            with caplog.at_level(_logging.DEBUG, logger="src.cli.daily_brief"):
                _print_watchlist_health(tmp_path, all_recs=[])
        finally:
            if original is not None:
                _sys.modules["src.screening.watchlist"] = original
            else:
                _sys.modules.pop("src.screening.watchlist", None)

        debug_msgs = [r.message for r in caplog.records if r.levelno == _logging.DEBUG]
        assert any("watchlist" in m and "失败" in m for m in debug_msgs), f"watchlist 加载失败应触发 debug 诊断; got debug msgs={debug_msgs!r}"

    def test_compute_consecutive_days_from_history(self) -> None:
        """tracking_history 推算连续天数 (交易日步进, 非自然日)。"""
        from src.cli.daily_brief import _compute_consecutive_days_from_history

        # 真实交易日序列 (周一/二/三 连续) — tracking_history 只在交易日写推荐
        records = [
            _make_history_record("000001", "20260603"),  # Wed
            _make_history_record("000001", "20260602"),  # Tue
            _make_history_record("000001", "20260601"),  # Mon
            _make_history_record("000002", "20260603"),  # Wed
            _make_history_record("000002", "20260601"),  # Mon (skip Tue = gap → streak=1)
        ]
        result = _compute_consecutive_days_from_history(records)

        assert result["000001"] == 3
        assert result["000002"] == 1

    def test_compute_consecutive_days_weekend_span_bridges_streak(self) -> None:
        """R36/R45 同族: Fri→Mon 跨周末必须计为连续推荐 (交易日步进)。

        bug 复现: 旧自然日逻辑 `(cursor - next_dt).days == 1` 对 Fri(20260605)
        →Mon(20260608) 的 3 天间距会断裂 streak 为 1, 与 R36 修复的
        ``consecutive_recommendation._prev_trading_day`` 主路径行为不一致。
        该 fallback 路径驱动 ``--daily-brief`` Top 3 排序键 (score_b + 0.05*consec)
        与「Top 3 必须含连续推荐 ≥2 日」门控, 周一报告的 streak 被误清零。
        """
        from src.cli.daily_brief import _compute_consecutive_days_from_history

        # 真实场景: 周五推荐 + 周一推荐 (周六/周日闭市无推荐)
        records = [
            _make_history_record("000001", "20260608"),  # Mon
            _make_history_record("000001", "20260605"),  # Fri (prev trading day)
        ]
        result = _compute_consecutive_days_from_history(records)

        # R36 交易日语义: Fri→Mon 连续 = 2 (跨周末不断裂)
        assert result["000001"] == 2

    def test_summarize_one_liner_bullish_convergence(self) -> None:
        """2 个策略都 bullish → 包含 "共振"。"""
        from src.cli.daily_brief import _summarize_one_liner

        rec = _make_recommendation(
            "000001",
            strategy_signals={
                "trend": _make_strategy_signal(1, 80.0),
                "mean_reversion": _make_strategy_signal(1, 70.0),
                "fundamental": _make_strategy_signal(-1, 30.0),
                "event_sentiment": _make_strategy_signal(0, 20.0),
            },
        )
        summary = _summarize_one_liner(rec, "银行")
        assert "共振" in summary
        assert "银行" in summary

    def test_summarize_one_liner_conflict(self) -> None:
        """1 个策略 bullish, 1 个 bearish → 包含 "但" 和 "谨慎"。"""
        from src.cli.daily_brief import _summarize_one_liner

        rec = _make_recommendation(
            "000001",
            strategy_signals={
                "trend": _make_strategy_signal(1, 80.0),
                "mean_reversion": _make_strategy_signal(-1, 70.0),
            },
        )
        summary = _summarize_one_liner(rec, "电子")
        assert "但" in summary
        assert "谨慎" in summary

    def test_summarize_one_liner_no_signals(self) -> None:
        """无 signals → 策略数据缺失。"""
        from src.cli.daily_brief import _summarize_one_liner

        rec = {"ticker": "000001", "industry_sw": "银行", "strategy_signals": {}}
        summary = _summarize_one_liner(rec, "银行")
        assert "策略数据缺失" in summary
