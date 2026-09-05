"""渲染对账 join (2026-08-23 对抗审查收敛 Item 2) — 台账↔操作员视图单一真相.

事件回放 (2026-08-20 晚): 18:09 运行创建 300009 计划; 22:47 重跑未检出它,
操作员视图对该计划只字未提 — 摘要"无新计划"与敞口行"待成交 6%"同屏矛盾,
操作员的记忆被摘要塑造, 真相留在台账里. 本文件钉死: 计划的存在必须被陈述.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action import (
    DailyActionScan,
    DailyActionV2Run,
    complete_daily_action_v2,
    render_daily_action_v2,
)
from src.screening.offensive.daily_action_service import (
    DailyActionService,
    MarketBar,
    PlanCandidate,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts


@pytest.fixture(autouse=True)
def _isolate_alignment_summary(tmp_path, monkeypatch):
    """R120b: 宿主真实 realized_vs_court_alignment.json 在场时, 宇宙对齐行会渲染进
    本文件全部渲染输出 (『宇宙 not in text』等全文断言误中) — 默认隔离保持 hermetic;
    显式对齐行测试 (test_daily_action_v2_render 内) 自行 monkeypatch 覆盖此默认值。"""
    from src.screening.offensive import daily_action as _da

    monkeypatch.setattr(_da, "_ALIGNMENT_SUMMARY_PATH", tmp_path / "no-alignment.json")
from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.trade_lifecycle import TradeState


def _sessions() -> tuple[date, ...]:
    start = date(2026, 8, 17)
    return tuple(start + timedelta(days=offset) for offset in range(30))


def _bar(close: float) -> MarketBar:
    return MarketBar(
        open=close,
        close=close,
        limit_down=close * 0.9,
        limit_up=close * 1.1,
        suspended=False,
        high=close + 0.2,
        low=close - 0.2,
    )


@pytest.fixture
def case(tmp_path):
    sessions = _sessions()
    as_of = sessions[3]  # 周四
    ticker = "300009"
    prices = {(symbol, session): _bar(10.0) for symbol in ("300009", "600000") for session in sessions}
    costs = ExecutionCosts(version="test", commission=5.0, other_fee=10.0)
    repository = LedgerRepository(
        tmp_path / "ledger.sqlite3", "render-recon", 1_000_000, execution_costs=costs
    )
    repository.initialize()
    service = DailyActionService(
        repository,
        TradingSessionCalendar(sessions),
        lambda symbol, session: prices.get((symbol, session)),
        costs,
        enforce_manifest_gate=False,
    )
    return service, repository, as_of, sessions


def _candidate(ticker: str, signal: date) -> PlanCandidate:
    return PlanCandidate(
        ticker=ticker,
        setup="btst_breakout",
        setup_version="v2",
        signal_date=signal,
        target_weight=0.06,
        priority=1,
        snapshot_id="sha256:test-snapshot",
        setup_consumed_fingerprint="sha256:test-consumed",
        trigger_strength=0.60,
        entry_price=9.55,
        metadata={"pct_change": 19.98},
    )


def test_undetected_pending_plan_surfaces_in_view(case):
    """22:47 场景主回归: 台账计划存在、扫描未检出 → 视图必须陈述它."""
    service, repository, as_of, sessions = case
    plan = repository.create_plan(
        "300009", "btst_breakout", "v2", as_of, sessions[4], 0.0595, 1
    )
    assert plan.state is TradeState.PLANNED

    context = service.advance_lifecycle(as_of)
    v2_run = complete_daily_action_v2(service, context, DailyActionScan(as_of, (), (), ()))

    # join 第四态: 未检出但台账存在
    assert len(v2_run.undetected_pending_plans) == 1
    ref = v2_run.undetected_pending_plans[0]
    assert ref.ticker == "300009"
    assert ref.planned_entry_date == sessions[4]
    assert ref.created_at is not None and "2026" in ref.created_at

    # 渲染: 摘要 + 专属区, 计划的消失不再可能
    text = render_daily_action_v2(v2_run)
    assert "既有待成交 1 只（早前运行创建）" in text
    assert "既有待成交计划（1 只，本次未再检出）" in text
    assert "300009" in text
    assert "创建于" in text


def test_redetected_existing_plan_is_annotated_not_duplicated(case):
    """重新检出的既有计划: 新计划区显示但标注出身, 不与第四态重复计数."""
    service, repository, as_of, sessions = case
    repository.create_plan("300009", "btst_breakout", "v2", as_of, sessions[4], 0.0595, 1)

    context = service.advance_lifecycle(as_of)
    v2_run = complete_daily_action_v2(
        service, context, DailyActionScan(as_of, (_candidate("300009", as_of),), (), ())
    )

    # 重新检出 → 计划区 (既有标注), 不进第四态
    assert not v2_run.undetected_pending_plans
    assert any(item.ticker == "300009" for item in v2_run.plans)
    text = render_daily_action_v2(v2_run)
    assert "〔既有计划·本次重新检出〕" in text
    assert "既有待成交计划（" not in text


def test_fresh_plan_this_run_has_no_prior_annotation(case):
    """本次新建的计划不标注 (created_now 区分 — 标注只属于早前运行)."""
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    v2_run = complete_daily_action_v2(
        service, context, DailyActionScan(as_of, (_candidate("600000", as_of),), (), ())
    )

    text = render_daily_action_v2(v2_run)
    assert "〔既有计划·本次重新检出〕" not in text
    assert "新计划（1 只）" in text


def test_event_occurred_at_reader(case):
    """repository.event_occurred_at: PLAN_CREATED 时刻可读, 未知事件 None."""
    service, repository, as_of, sessions = case
    plan = repository.create_plan(
        "300009", "btst_breakout", "v2", as_of, sessions[4], 0.0595, 1
    )
    occurred = repository.event_occurred_at(plan.trade_id, "PLAN_CREATED")
    assert occurred is not None and occurred.startswith("20")
    assert repository.event_occurred_at(plan.trade_id, "NO_SUCH_EVENT") is None


def test_legacy_v2_run_omits_section_when_field_empty(case):
    """旧构造点 (DailyActionV2Run 直构, 不传新字段) 渲染不变 — 向后兼容."""
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())
    text = render_daily_action_v2(view)
    assert "既有待成交计划（" not in text


def test_funnel_closed_format_renders_universe_decomposition(case):
    """漏斗闭合 (Item 3): 宇宙→扫描的差额必须可见且算术可复核."""
    from src.screening.offensive.daily_action import ScanFunnel

    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run,
        (),
        run.open_positions,
        (),
        (),
        funnel=ScanFunnel(
            scannable=1645,
            prefilter_passed=47,
            hits=4,
            universe=1733,
            verify_blocked=80,
            excluded_permanent=8,
            data_rejected=0,
        ),
        regime="normal",
    )
    text = render_daily_action_v2(view)
    assert "宇宙 1733 只" in text
    assert "验证拒绝 80" in text and "永久排除 8" in text and "数据拒绝 0" in text
    assert "扫描 1645 只" in text


def test_funnel_legacy_format_when_universe_absent(case):
    """旧构造点 (universe=None) 漏斗退化为旧格式 — 向后兼容."""
    from src.screening.offensive.daily_action import ScanFunnel

    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        funnel=ScanFunnel(scannable=10, prefilter_passed=3, hits=1),
    )
    text = render_daily_action_v2(view)
    assert "扫描漏斗：扫描 10 只 → 涨幅≥9.5% 3 只 → 命中 1 只" in text
    assert "宇宙" not in text


def test_extra_excluded_tickers_rendered_when_active(case, monkeypatch):
    """Item 5: EXTRA_EXCLUDED_TICKERS 生效时必须陈述 — 配置不是隐形政策."""
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(run, (), run.open_positions, (), ())

    monkeypatch.setenv("EXTRA_EXCLUDED_TICKERS", "600999,000888")
    text = render_daily_action_v2(view)
    assert "EXTRA_EXCLUDED_TICKERS 生效 2 只" in text
    assert "600999" in text and "000888" in text

    monkeypatch.delenv("EXTRA_EXCLUDED_TICKERS", raising=False)
    text = render_daily_action_v2(view)
    assert "EXTRA_EXCLUDED_TICKERS" not in text


# ---------------------------------------------------------------------------
# R122 Op1: 宇宙对齐行实现归因子句 (realization gap attribution)
# ---------------------------------------------------------------------------

def _alignment_summary_with_gap(**overrides):
    import json

    payload = {
        "date": "20260905",
        "total_buys": 33,
        "class_counts": {
            "outside_window": 0,
            "day_excluded_regime_gap": 0,
            "day_missing_panel_data": 0,
            "day_missing_from_court": 6,
            "ticker_not_in_court_day": 3,
            "matched": 24,
        },
        "realized_only": {
            "n": 24, "win_rate_pct": 20.83, "avg_win_pct": 6.0,
            "avg_loss_pct": -11.0, "payoff": 0.55, "expectancy_pct": -7.34,
        },
        "stores": {
            "legacy_journal": {"buys": 18, "open_buys": 3,
                               "realized_only": {"n": 15, "win_rate_pct": 20.0,
                                                 "expectancy_pct": -6.04}},
            "ledger_v2": {"buys": 15, "open_buys": 6,
                          "realized_only": {"n": 9, "win_rate_pct": 22.22,
                                            "expectancy_pct": -9.52}},
        },
        "latest_split_signal_date": "20260813",
        "latest_matched_signal_date": "20260821",
        "court_window": {"start": "20250701", "end": "20260904"},
        "realization_gap": {
            "n": 15,
            "court_conditional_expectancy_pct": -8.34,
            "realized_expectancy_pct": -7.85,
            "realization_gap_pp": 0.48,
            "direction_agree_n": 15,
            "direction_disagree_n": 0,
            "horizons": {"8": 5, "10": 10},
        },
    }
    payload.update(overrides)
    return payload


def _write_alignment(base, payload):
    import json

    base.mkdir(parents=True, exist_ok=True)
    p = base / "realized_vs_court_alignment.json"
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_alignment_line_realization_gap_clause(tmp_path, monkeypatch):
    """归因块在场 → 子句出行, selection/实现差两项齐备."""
    from src.screening.offensive import daily_action as da

    monkeypatch.setattr(
        da, "_ALIGNMENT_SUMMARY_PATH",
        _write_alignment(tmp_path, _alignment_summary_with_gap()),
    )
    line = da._render_universe_alignment_line()
    assert line is not None
    assert "实现归因（matched 已平仓 15）" in line
    assert "court 同票假想期望 -8.34%" in line
    assert "逐笔实现差 +0.48pp" in line


def test_alignment_line_realization_gap_absent_old_shape(tmp_path, monkeypatch):
    """旧 summary (无 realization_gap 键) → 子句省略; 新形态 = 旧行 + 纯子句追加
    (旧 summary 逐字节回退旧行, 行其余部分零变化)."""
    from src.screening.offensive import daily_action as da

    payload = _alignment_summary_with_gap()
    del payload["realization_gap"]
    monkeypatch.setattr(
        da, "_ALIGNMENT_SUMMARY_PATH", _write_alignment(tmp_path, payload)
    )
    line_old = da._render_universe_alignment_line()
    assert "实现归因" not in line_old

    monkeypatch.setattr(
        da, "_ALIGNMENT_SUMMARY_PATH",
        _write_alignment(tmp_path / "new", _alignment_summary_with_gap()),
    )
    line_new = da._render_universe_alignment_line()
    clause = (
        " · 实现归因（matched 已平仓 15）: court 同票假想期望 -8.34%"
        " · 逐笔实现差 +0.48pp（含锚点差）"
    )
    assert clause in line_new
    assert line_new.replace(clause, "") == line_old


def test_alignment_line_realization_gap_malformed_omitted(tmp_path, monkeypatch):
    """块畸形 (非 dict / n 非 int / 数值非有限) → 整子句省略不崩 (R119 P1 家族)."""
    from src.screening.offensive import daily_action as da

    for bad in (
        "banana",
        {"n": "15", "court_conditional_expectancy_pct": -8.34,
         "realization_gap_pp": 0.48},
        {"n": 15, "court_conditional_expectancy_pct": "banana",
         "realization_gap_pp": 0.48},
        {"n": 15, "court_conditional_expectancy_pct": float("nan"),
         "realization_gap_pp": 0.48},
        {"n": True, "court_conditional_expectancy_pct": -8.34,
         "realization_gap_pp": 0.48},
        {"n": 0, "court_conditional_expectancy_pct": -8.34,
         "realization_gap_pp": 0.48},
    ):
        payload = _alignment_summary_with_gap(realization_gap=bad)
        monkeypatch.setattr(
            da, "_ALIGNMENT_SUMMARY_PATH", _write_alignment(tmp_path, payload)
        )
        line = da._render_universe_alignment_line()
        assert line is not None, f"line must survive malformed block: {bad!r}"
        assert "实现归因" not in line, f"clause must be omitted: {bad!r}"


def test_alignment_line_realization_gap_count_contradiction_omitted(
    tmp_path, monkeypatch
):
    """R122b 对抗收口: 块 n > matched = 工件损坏 (reconcile 全局去重保证结构性
    n ≤ matched) — 整子句省略不渲染矛盾读数 (R119 P3 家族: 渲染矛盾比不渲染更有害)."""
    from src.screening.offensive import daily_action as da

    payload = _alignment_summary_with_gap()
    payload["realization_gap"] = {
        **payload["realization_gap"],
        "n": 999,  # matched=24
    }
    monkeypatch.setattr(
        da, "_ALIGNMENT_SUMMARY_PATH", _write_alignment(tmp_path, payload)
    )
    line = da._render_universe_alignment_line()
    assert line is not None
    assert "实现归因" not in line
    assert "matched 已平仓 999" not in line
