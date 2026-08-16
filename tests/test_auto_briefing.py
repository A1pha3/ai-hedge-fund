"""--auto 决策简报卡 (briefing card) 契约测试.

三轮对抗审查 (2026-08-16) 收敛的展示契约:
- H1 事实计算一次, CLI 卡片 / push 摘要消费同一 payload;
- H2 异常块区分「已自动发生」与「可选处置」, 不暗示展示层权限;
- H3 n<30 的基线桶不显示数值, 空槽由跨周期警示填补 (crisis 日不失明);
- H4 [AUTO] 推荐前向是弱证据, 只作触发器, 不占稳态席位;
- H5 触发器阈值预注册 (模块常量), 渲染层不得改判;
- H6 心跳是断言式 (无（6/6 检查通过）), 区分「无异常」与「检测器哑了」;
- H7 失败构成未命名占比超阈必须点名;
- H9 每个比率带 n 或 ⏳; 降级路径输出固定标记; 无未计算的因果断言.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.reporting.auto_briefing import (
    AUTO_FORWARD_LB_FLOOR,
    BASELINE_MIN_N,
    BTST_BASELINE_BUCKETS,
    BRIEFING_SCHEMA_VERSION,
    build_auto_briefing,
    failure_composition_from_outcomes,
    render_briefing_card,
    render_briefing_push_lines,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _market(
    state: str = "mixed",
    gate: str = "normal",
    scale: float = 1.0,
    **over,
) -> SimpleNamespace:
    base = dict(
        state_type=state,
        position_scale=scale,
        adx=28.3,
        atr_price_ratio=0.019,
        breadth_ratio=0.42,
        daily_return=0.004,
        limit_up_count=96,
        limit_down_count=30,
        limit_up_down_ratio=3.2,
        northbound_flow_days=-2,
        regime_flip_risk=0.18,
        regime_gate_level=gate,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _write_panel(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "setup_output_panel.jsonl"
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _panel_rows(n_elig: int, n_filt: int, elig_ret: float, filt_ret: float) -> list[dict]:
    rows = [
        {"plan_eligible": True, "return_t5": elig_ret, "realized": True}
        for _ in range(n_elig)
    ] + [
        {"plan_eligible": False, "return_t5": filt_ret, "realized": True}
        for _ in range(n_filt)
    ]
    return rows


def _write_regime(tmp_path: Path, history: dict[str, str]) -> Path:
    path = tmp_path / "regime_history.json"
    path.write_text(json.dumps(history), encoding="utf-8")
    return path


def _write_ledger(tmp_path: Path, dd: float, nav: float = 1_310_000.0, as_of: str = "20260813") -> Path:
    path = tmp_path / "ledger.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
CREATE TABLE IF NOT EXISTS daily_valuations (
  ledger_id TEXT, trade_date TEXT, cash REAL, market_value REAL,
  nav REAL, peak REAL, drawdown REAL, stale_tickers_json TEXT
);
"""
    )
    peak = nav / (1.0 + dd) if dd < 0 else nav
    conn.execute("DELETE FROM daily_valuations")
    conn.execute(
        "INSERT INTO daily_valuations VALUES (?,?,?,?,?,?,?,?)",
        ("daily-action-v2", as_of, nav, nav, nav, peak, dd, "[]"),
    )
    conn.commit()
    conn.close()
    return path


def _write_tracking(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "tracking_history.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _readiness(
    universe: int = 1585,
    scannable: int = 1523,
    failed: int = 62,
    degraded: int = 0,
) -> dict:
    return {
        "status": "healthy",
        "universe_count": universe,
        "scannable_count": scannable,
        "plan_eligible_count": scannable,
        "degraded_count": degraded,
        "failed_count": failed,
    }


_UNSET = object()  # 区分「未传 market」与「显式传 market=None (降级用例)」


def _build(
    tmp_path: Path,
    *,
    market: object = _UNSET,
    panel_rows: list[dict] | None = None,
    regime: dict[str, str] | None = None,
    ledger_dd: float | None = -0.06,
    tracking: list[dict] | None = None,
    readiness: dict | None = None,
    composition: dict | None = None,
    payload_extra: dict | None = None,
) -> dict:
    if panel_rows is None:
        panel_rows = _panel_rows(20, 20, 1.0, 0.5)
    if regime is None:
        regime = {"20260813": "normal"}
    if tracking is None:
        # 世代内样本健康 (胜率 ~60%), 不触发崩塌检测.
        tracking = [
            {"recommended_date": "20260730", "next_5day_return": 3.0 if i % 10 < 6 else -2.0}
            for i in range(130)
        ]
    if readiness is None:
        readiness = _readiness()
    panel_path = _write_panel(tmp_path, panel_rows)
    regime_path = _write_regime(tmp_path, regime)
    tracking_path = _write_tracking(tmp_path, tracking)
    if ledger_dd is None:
        ledger_path = tmp_path / "absent_ledger.sqlite3"
    else:
        ledger_path = _write_ledger(tmp_path, ledger_dd)

    report_payload = {
        "layer_a_count": 300,
        "top_n": 10,
        "recommendations": [{} for _ in range(10)],
        "daily_action_readiness": readiness,
        "daily_action_cache_refresh": (
            {"failure_composition": composition} if composition is not None else {}
        ),
    }
    if payload_extra:
        report_payload.update(payload_extra)

    return build_auto_briefing(
        trade_date="20260814",
        market_state=_market() if market is _UNSET else market,
        report_payload=report_payload,
        panel_path=panel_path,
        regime_history_path=regime_path,
        tracking_history_path=tracking_path,
        ledger_path=ledger_path,
    )


# ---------------------------------------------------------------------------
# 安静日 golden
# ---------------------------------------------------------------------------


def test_quiet_day_card_shape(tmp_path: Path) -> None:
    payload = _build(tmp_path)
    card = render_briefing_card(payload)

    assert "2026-08-14（周五）" in card
    assert "混合市（mixed）" in card
    assert "仓位系数 1.00" in card
    assert "regime_gate=normal" in card
    # 判据: 结论附可证伪输入
    assert "上涨占比 0.42" in card
    assert "排序" in card  # v3: 记分牌常驻 header (fixture tracking 无分数 → 样本不足态)
    assert "观察清单" in card
    assert "涨/跌停 96/30" in card
    assert "ADX 28.3" in card
    assert "北向连续 2 日流出" in card
    assert "翻转风险" in card
    # BTST 前向 + 基线
    assert "前向 panel 信号" in card and "已到期" in card
    assert "基线 normal 期望+4.2%·胜率59%·n=103" in card
    # 口径披露 (trap: recorded vs corrected)
    assert "T0收盘/零成本" in card
    assert "牛市样本" in card
    assert "源 2026-07-18" in card
    # 台账 + as-of 戳 (H8)
    assert "净值 1,310,000" in card
    assert "回撤 -6.0%" in card
    assert "距 -15% 半仓线" in card
    assert "截至 2026-08-13" in card
    # 数据行: 失败率 + 构成
    assert "失败 62/全域 1585" in card
    # 心跳 (H6)
    assert "▲异常: 无（6/6 检查通过）" in card
    # 图例恒在 — 前向符号不自明, 卡片必须自我解释 (清晰度审查 2026-08-16)
    assert "说明" in card and "⏳样本未足" in card and "全过滤" in card
    # 池/推荐
    assert "Layer A 候选池 300 只" in card
    assert "Top 10 推荐" in card


def test_steady_state_line_cap(tmp_path: Path) -> None:
    """安静日卡片 ≤ 10 行内容 (含标题/不含边框), 异常详情行不计入稳态.

    2026-08-16 v3: 9→10 — 「排序」记分牌行是刻意新增的稳态席位 (表格的
    常驻先验), 不是回归。
    """
    card = render_briefing_card(_build(tmp_path))
    lines = card.splitlines()
    content = [ln for ln in lines if ln.strip("=─- ") != ""]
    assert len(content) <= 10, f"card too tall: {len(content)} content lines"


def test_scorecard_segment_states(tmp_path: Path) -> None:
    """排序记分牌三种渲染态: 可用(带数字+verdict)、样本不足、payload 缺失。"""
    # 可用态: 12 个推荐日 × 10 只, 分数与收益单调同向 → IC=+1 → 有正向证据
    mono = [6.0, 5.0, 4.0, 3.0, 2.0, 1.0, -1.0, -2.0, -3.0, -4.0]
    tracking: list[dict] = []
    for d in range(12):
        for i in range(10):
            tracking.append(
                {
                    "recommended_date": f"202607{d + 1:02d}",
                    "recommendation_score": 0.40 - 0.01 * i,
                    "next_5day_return": mono[i],
                }
            )
    payload = _build(tmp_path, tracking=tracking)
    card = render_briefing_card(payload)
    assert "排序" in card and "有正向证据" in card
    assert "胜率60%" in card and "IC+1.00" in card
    assert payload["ranking_scorecard"]["available"] is True
    assert payload["ranking_scorecard"]["verdict"] == "positive"
    # ic_t_str 是预格式化字符串 (±inf 不进 JSON 数值)
    assert payload["ranking_scorecard"]["ic_t_str"] == "∞"
    push = render_briefing_push_lines(payload)
    assert any("排序记分牌" in ln and "胜率" in ln for ln in push)

    # 样本不足态 (默认 fixture: tracking 无 recommendation_score)
    insufficient = render_briefing_card(_build(tmp_path))
    assert "样本不足" in insufficient
    push_insufficient = render_briefing_push_lines(_build(tmp_path))
    assert any("样本不足" in ln for ln in push_insufficient)

    # payload 缺失 ranking_scorecard → 渲染降级, 不崩溃 (旧 payload 兼容)
    legacy = _build(tmp_path, tracking=tracking)
    legacy.pop("ranking_scorecard")
    assert "观察清单" in render_briefing_card(legacy)


def test_heartbeat_counts_total_checks(tmp_path: Path) -> None:
    card = render_briefing_card(_build(tmp_path))
    assert "6/6" in card


# ---------------------------------------------------------------------------
# H3: 基线桶展示规则
# ---------------------------------------------------------------------------


def test_crisis_baseline_suppressed_with_cross_cycle_warning(tmp_path: Path) -> None:
    """crisis 桶 n=21<30: 不给数值, 空槽由跨周期警示填补 — 最需要它的日子不失明."""
    payload = _build(tmp_path, market=_market(state="crisis", gate="crisis", scale=0.5))
    card = render_briefing_card(payload)
    assert "样本不足" in card
    assert "跨周期警示" in card
    assert "2022/2024" in card
    # 点估计不得出现
    assert "+10.4%" not in card
    assert "66.7" not in card and "67%" not in card


def test_risk_off_baseline_suppressed(tmp_path: Path) -> None:
    payload = _build(tmp_path, market=_market(gate="risk_off", scale=0.5))
    card = render_briefing_card(payload)
    assert "样本不足" in card
    assert "n=9" in card
    assert "+2.0%" not in card


def test_baseline_buckets_meet_min_n_discipline() -> None:
    """基线常量与 n 阈值自洽: 恰好只有 normal 桶可显示数值."""
    showable = [k for k, v in BTST_BASELINE_BUCKETS.items() if v["n"] >= BASELINE_MIN_N]
    assert showable == ["normal"]


# ---------------------------------------------------------------------------
# H2/H5: 触发器
# ---------------------------------------------------------------------------


def test_regime_flip_exception_distinguishes_automatic_vs_optional(tmp_path: Path) -> None:
    payload = _build(
        tmp_path,
        market=_market(gate="risk_off", scale=0.5),
        regime={"20260813": "normal"},
    )
    card = render_briefing_card(payload)
    assert "▲异常: 1 项" in card
    assert "regime 翻转 normal→risk_off" in card
    # 已自动发生的部分必须点明 (不是建议, 是事实)
    assert "已" in card and "0.50" in card
    codes = [e["code"] for e in payload["exceptions"]]
    assert codes == ["regime_flip"]


def test_no_regime_flip_when_history_matches(tmp_path: Path) -> None:
    payload = _build(tmp_path, regime={"20260813": "normal", "20260812": "normal"})
    assert [e["code"] for e in payload["exceptions"]] == []


def test_no_regime_flip_without_history(tmp_path: Path) -> None:
    """无历史可比时不触发 — 未知不是翻转."""
    payload = _build(tmp_path, regime={})
    assert [e["code"] for e in payload["exceptions"]] == []


def test_panel_adverse_triggers_only_when_testable(tmp_path: Path) -> None:
    adverse = _build(tmp_path, panel_rows=_panel_rows(20, 20, -2.0, 2.0))
    codes = [e["code"] for e in adverse["exceptions"]]
    assert "panel_adverse" in codes
    card = render_briefing_card(adverse)
    assert "反向" in card and "p<0.001" in card  # p≈0 必须写成不等式, 不写 p=0.000

    small = _build(tmp_path, panel_rows=_panel_rows(3, 3, -2.0, 2.0))
    assert "panel_adverse" not in [e["code"] for e in small["exceptions"]]
    assert "⏳" in render_briefing_card(small)


def test_panel_positive_not_adverse(tmp_path: Path) -> None:
    payload = _build(tmp_path, panel_rows=_panel_rows(20, 20, 3.0, 0.2))
    assert "panel_adverse" not in [e["code"] for e in payload["exceptions"]]


def test_breaker_proximity_engaged_and_quiet(tmp_path: Path) -> None:
    near = _build(tmp_path, ledger_dd=-0.12)
    assert "breaker" in [e["code"] for e in near["exceptions"]]
    assert "距 -15% 半仓线" in render_briefing_card(near)

    engaged = _build(tmp_path, ledger_dd=-0.16)
    card = render_briefing_card(engaged)
    assert "已越 -15% 半仓线" in card

    stopped = _build(tmp_path, ledger_dd=-0.21)
    assert "-20%" in render_briefing_card(stopped)

    quiet = _build(tmp_path, ledger_dd=-0.06)
    assert "breaker" not in [e["code"] for e in quiet["exceptions"]]


def test_auto_forward_collapse_trigger_threshold(tmp_path: Path) -> None:
    # 崩塌: n=80, 胜率 25% → 下界远低于 45% 阈值
    bad = [{"recommended_date": "20260801", "next_5day_return": 3.0 if i % 4 == 0 else -2.0} for i in range(80)]
    payload = _build(tmp_path, tracking=bad)
    assert "auto_forward_collapse" in [e["code"] for e in payload["exceptions"]]
    card = render_briefing_card(payload)
    assert "劣于随机" in card
    assert f"n=80" in card

    # 健康: 57.5%/n=80 → 下界 48.4% > 45%, 不触发 (真实数据形态)
    ok = [{"recommended_date": "20260801", "next_5day_return": 3.0 if i % 100 < 57 else -2.0} for i in range(200)]
    payload_ok = _build(tmp_path, tracking=ok)
    assert "auto_forward_collapse" not in [e["code"] for e in payload_ok["exceptions"]]


def test_auto_forward_never_in_steady_state(tmp_path: Path) -> None:
    """H4: [AUTO] 前向是弱证据 — 不触发时不出现在卡片稳态区."""
    card = render_briefing_card(_build(tmp_path))
    assert "[AUTO]" not in card


def test_da_failure_rate_trigger_and_composition_rule(tmp_path: Path) -> None:
    hot = _build(
        tmp_path,
        readiness=_readiness(universe=1000, scannable=800, failed=200),
        composition={"停牌": 100, "其他": 100},
    )
    codes = [e["code"] for e in hot["exceptions"]]
    assert "da_failure_anomaly" in codes
    card = render_briefing_card(hot)
    assert "20%" in card  # 200/1000

    # H7: 未命名占比 50% 且单一主因 → 必须点名
    assert "其他" in card


def test_da_composition_requires_naming_top_unknown(tmp_path: Path) -> None:
    """未命名占比 >50% 时, 构成行必须点名首位原因, 不允许裸「其他」."""
    payload = _build(
        tmp_path,
        composition={"停牌": 10, "价格刷新失败": 40, "资金流刷新失败": 12},
    )
    card = render_briefing_card(payload)
    breakdown_line = next(ln for ln in card.splitlines() if "构成" in ln)
    assert "价格刷新失败" in breakdown_line


def test_failure_rate_under_threshold_is_quiet(tmp_path: Path) -> None:
    payload = _build(tmp_path)  # 62/1585 = 3.9%
    assert "da_failure_anomaly" not in [e["code"] for e in payload["exceptions"]]


# ---------------------------------------------------------------------------
# ⑥ DA 运行级阻断 (2026-08-16 真实降级运行暴露的缺口)
# ---------------------------------------------------------------------------


def test_da_run_level_block_fires_sixth_check(tmp_path: Path) -> None:
    """fatal 原因在场 → 必须进异常账本; 「明日无法生成新计划」是当天最大的
    可行动事实, 不允许只活在上方的 domain summary 里而心跳全绿."""
    payload = _build(
        tmp_path,
        readiness={
            "status": "blocked",
            "block_reasons": ("readiness_attempt_only",),
        },
    )
    codes = [e["code"] for e in payload["exceptions"]]
    assert "da_blocked" in codes
    card = render_briefing_card(payload)
    assert "DA 就绪阻断" in card
    assert "无法生成新计划" in card
    assert "readiness_attempt_only" in card  # 原始码必须可见 (排查入口)
    # 阻断 payload 带不了计数 → ④ 未评估, 心跳必须如实区分 (H6)
    assert "5/6 检查" in card and "数据不可用: DA 计数" in card


def test_da_disclosure_only_reason_does_not_fire(tmp_path: Path) -> None:
    """披露-only 原因 (regime 加仓证据不可验) 不是阻断 — 分类与 domain summary 一致."""
    payload = _build(
        tmp_path,
        readiness={
            "status": "healthy",
            "universe_count": 1585,
            "failed_count": 62,
            "block_reasons": ("regime_authorization_evidence_unavailable",),
        },
    )
    assert "da_blocked" not in [e["code"] for e in payload["exceptions"]]


def test_da_unknown_status_is_not_anomaly(tmp_path: Path) -> None:
    """状态缺失/未知不触发 (未知≠异常); 计数缺失已由「计数不可用」披露."""
    payload = _build(tmp_path, readiness={})
    assert "da_blocked" not in [e["code"] for e in payload["exceptions"]]


# ---------------------------------------------------------------------------
# 降级契约
# ---------------------------------------------------------------------------


def test_degradation_ledger_missing(tmp_path: Path) -> None:
    payload = _build(tmp_path, ledger_dd=None)
    card = render_briefing_card(payload)
    assert "台账 不可用" in card
    assert "净值" not in card


def test_degradation_panel_empty(tmp_path: Path) -> None:
    payload = _build(tmp_path, panel_rows=[])
    card = render_briefing_card(payload)
    assert "未累积" in card
    assert "panel_adverse" not in [e["code"] for e in payload["exceptions"]]


def test_degradation_panel_file_missing(tmp_path: Path) -> None:
    payload = _build(tmp_path)
    # 重新构建: panel 路径指向不存在文件
    payload2 = build_auto_briefing(
        trade_date="20260814",
        market_state=_market(),
        report_payload={"layer_a_count": 300, "top_n": 10},
        panel_path=tmp_path / "nope.jsonl",
        regime_history_path=tmp_path / "nope.json",
        tracking_history_path=tmp_path / "nope.json",
        ledger_path=tmp_path / "nope.sqlite3",
    )
    card = render_briefing_card(payload2)
    assert "未累积" in card
    assert "台账 不可用" in card
    # 全源缺失 → 0/6 执行, 但心跳仍在场且点名未评估项 — 不是静默, 也不是谎报全绿
    assert "0/6 检查通过" in card
    assert "6 项数据不可用" in card


def test_degradation_readiness_counts_missing(tmp_path: Path) -> None:
    payload = _build(tmp_path, readiness={"status": "healthy"})
    card = render_briefing_card(payload)
    assert "计数不可用" in card


def test_degradation_market_state_none(tmp_path: Path) -> None:
    payload = _build(tmp_path, market=None)
    card = render_briefing_card(payload)
    assert "数据不可用" in card
    assert payload["market"]["available"] is False


def test_build_never_raises_on_total_absence(tmp_path: Path) -> None:
    # 显式 nope 路径: 不显式传参会落到生产默认台账路径 (DEFAULT_LEDGER_PATH),
    # 测试结果依赖机器状态 — 违反测试隔离规则 (AGENTS.md), 诚实记账把它暴露了.
    payload = build_auto_briefing(
        trade_date="20260814",
        market_state=None,
        report_payload={},
        panel_path=tmp_path / "nope.jsonl",
        regime_history_path=tmp_path / "nope.json",
        tracking_history_path=tmp_path / "nope.json",
        ledger_path=tmp_path / "nope.sqlite3",
    )
    assert payload["schema_version"] == BRIEFING_SCHEMA_VERSION
    card = render_briefing_card(payload)
    assert "▲异常: 无（0/6 检查通过，6 项数据不可用" in card  # 检测器仍心跳, 缺数据不谎报全绿


# ---------------------------------------------------------------------------
# H1: 跨通道一致
# ---------------------------------------------------------------------------


def test_push_lines_share_card_facts(tmp_path: Path) -> None:
    payload = _build(tmp_path)
    card = render_briefing_card(payload)
    push = "\n".join(render_briefing_push_lines(payload))

    assert "仓位系数 `1.00`" in push
    assert "gate `normal`" in push
    assert "n=103" in push and "基线 normal" in push
    assert "截至 2026-08-13" in push
    # push 无 ANSI 转义
    assert "\x1b" not in push
    # 心跳结论一致
    assert ("无（6/6" in push) == ("▲异常: 无" in card)


def test_push_lines_carry_exceptions(tmp_path: Path) -> None:
    payload = _build(
        tmp_path,
        market=_market(gate="risk_off", scale=0.5),
        regime={"20260813": "normal"},
    )
    push = "\n".join(render_briefing_push_lines(payload))
    assert "regime 翻转" in push


# ---------------------------------------------------------------------------
# provenance / 常量纪律
# ---------------------------------------------------------------------------


def test_baseline_constants_match_correction_artifact() -> None:
    """基线常量与修正产物逐字段一致 (trap#4: 硬编码统计必须可追溯到源)."""
    artifact = Path("outputs/journal_corrected_stats_20260718.json")
    if not artifact.exists():
        pytest.skip("correction artifact not present")
    data = json.loads(artifact.read_text(encoding="utf-8"))
    for bucket, key in (("normal", "btst/normal"), ("crisis", "btst/crisis"), ("risk_off", "btst/risk_off")):
        src = data["by_group"][key]
        assert BTST_BASELINE_BUCKETS[bucket]["n"] == src["n"]
        assert BTST_BASELINE_BUCKETS[bucket]["mean_pct"] == src["corrected_mean"]
        assert BTST_BASELINE_BUCKETS[bucket]["win_rate"] == pytest.approx(src["corrected_wr"] / 100.0)


def test_lb_floor_is_preregistered() -> None:
    assert AUTO_FORWARD_LB_FLOOR == 0.45


# ---------------------------------------------------------------------------
# 失败构成聚合 (刷新 outcome 口径)
# ---------------------------------------------------------------------------


def test_failure_composition_from_outcomes() -> None:
    def outcome(ticker: str, price: str, flow: str) -> SimpleNamespace:
        return SimpleNamespace(ticker=ticker, price_status=SimpleNamespace(value=price), fund_flow_status=SimpleNamespace(value=flow))

    outcomes = {
        "1": outcome("1", "suspended", "suspended"),
        "2": outcome("2", "failed", "current"),
        "3": outcome("3", "current", "failed"),
        "4": outcome("4", "current", "current"),
        "5": outcome("5", "missing_unexplained", "current"),
    }
    comp = failure_composition_from_outcomes(outcomes)
    assert comp == {"停牌": 1, "价格刷新失败": 1, "资金流刷新失败": 1, "缺失未解释": 1}


def test_failure_composition_empty_inputs() -> None:
    assert failure_composition_from_outcomes({}) == {}
    assert failure_composition_from_outcomes(None) == {}


# ---------------------------------------------------------------------------
# CLI 集成: _print_auto_screening_table 的卡片模式 / legacy 回退
# ---------------------------------------------------------------------------


def test_cli_table_card_mode_replaces_legacy_header(tmp_path, capsys) -> None:
    from src.main import _print_auto_screening_table
    from src.screening.models import FusedScore, StrategySignal

    item = FusedScore(
        ticker="000001",
        name="测试股",
        industry_sw="电子",
        score_b=0.357,
        strategy_signals={
            "trend": StrategySignal(direction=1, confidence=50.0, completeness=1.0, sub_factors={}),
        },
        weights_used={"trend": 0.4},
        decision="watch",
    )
    card = render_briefing_card(_build(tmp_path))
    _print_auto_screening_table(
        "20260814",
        [item],
        _market(),
        300,
        10,
        tmp_path / "report.json",
        consecutive_recommendations=[],
        briefing_text=card,
    )
    out = capsys.readouterr().out
    # 卡片标记在场, legacy header 的重复池行只出现一次 (卡片自带)
    assert "▲异常: 无（6/6 检查通过）" in out
    assert out.count("Layer A 候选池 300 只") == 1
    assert "基线 normal 期望+4.2%·胜率59%·n=103" in out


def test_cli_table_legacy_fallback_without_briefing(capsys) -> None:
    from src.main import _print_auto_screening_table

    _print_auto_screening_table(
        "20260814",
        [],
        _market(),
        300,
        10,
        Path("data/reports/x.json"),
        consecutive_recommendations=[],
    )
    out = capsys.readouterr().out
    assert "[Auto Screening] 一键全流程" in out
    assert "▲异常" not in out
