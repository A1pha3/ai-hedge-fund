"""--daily-action v2 渲染面测试 (R80 Op2) — 漏斗 per-condition 分桶行.

prefilter→hits 之间此前是黑箱: 0828 零命中日 (85 prefilter→0 命中) 的检测面
取证只能手工复现检测路径 (66 C2 / 16 C3 / 3 C1). 本文件钉死: detect_miss_stages
非空时渲染未命中分桶行 (只列非零桶), None 的旧构造点不出现分桶行 (向后兼容).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action import (
    DailyActionV2Run,
    ScanFunnel,
    render_daily_action_v2,
)
from src.screening.offensive.daily_action_service import (
    DailyActionService,
    MarketBar,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository


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
    as_of = sessions[3]
    prices = {
        (symbol, session): _bar(10.0)
        for symbol in ("300009", "600000")
        for session in sessions
    }
    costs = ExecutionCosts(version="test", commission=5.0, other_fee=10.0)
    repository = LedgerRepository(
        tmp_path / "ledger.sqlite3", "v2-render", 1_000_000, execution_costs=costs
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


def test_funnel_miss_stage_buckets_render_when_present(case):
    """非零桶按名称排序成行 — 0828 形态 (66 C2 / 16 C3 / 3 C1) 自解释."""
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        funnel=ScanFunnel(
            scannable=85,
            prefilter_passed=85,
            hits=0,
            universe=1840,
            detect_miss_stages={
                "c2_flow_below_mean": 66,
                "c3_industry_weak": 16,
                "c1_limit_up_pct": 3,
            },
        ),
    )
    text = render_daily_action_v2(view)
    assert "未命中分桶：c1_limit_up_pct 3 · c2_flow_below_mean 66 · c3_industry_weak 16" in text


def test_funnel_miss_stage_absent_on_legacy_construction(case):
    """detect_miss_stages=None (旧构造点) 不出现分桶行 — 向后兼容."""
    service, _repository, as_of, _sessions = case
    context = service.advance_lifecycle(as_of)
    run = service.complete_run(context, candidates=())
    view = DailyActionV2Run(
        run, (), run.open_positions, (), (),
        funnel=ScanFunnel(scannable=10, prefilter_passed=3, hits=1),
    )
    assert "未命中分桶" not in render_daily_action_v2(view)
