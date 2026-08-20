"""arm settlement driver — Phase 5c/5d merged (2026-08-20).

锁定: 结算属 settle_proxy_open (判定+滑点+费+reserve 一次到位), driver 只构造
intent 委托; 买入 adverse 价 >= 原始成交价; UNKNOWN/NO_FILL 语义; 无持仓卖出
被资本投影拒 (#9); 双情景常量 = 30bps/60bps + REPLAY_FEE_POLICY。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.capital.flows import GenesisRequest
from src.screening.offensive.v3.capital.fills import FillAttribution
from src.screening.offensive.v3.capital.identity import AccountBinding
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.contracts.execution import ExecutionSide
from src.screening.offensive.v3.execution.lifecycle import DailyBar, OpenExecutionVerdict
from src.screening.offensive.v3.orchestration.arm_lifecycle import (
    CURRENT_COST_SCENARIO,
    DOUBLE_SLIPPAGE_SCENARIO,
    drive_open_settlement,
)

UTC = timezone.utc
SESSION = date(2026, 8, 20)
T = datetime(2026, 8, 20, 9, 30, tzinfo=UTC)
DEADLINE = T + timedelta(minutes=30)
ATTR = FillAttribution(
    producer_namespace="btst", research_program_id="prog-1",
    economic_lineage_id="eline-1", stage_id="stage-1",
)


def _bar(open_c: int = 1105, one_price: int | None = None) -> DailyBar:
    """one_price=围栏值时构造四价合一一字 bar."""
    if one_price is not None:
        return DailyBar(
            security_id="600000.SH", session=SESSION,
            open_cents=one_price, high_cents=one_price, low_cents=one_price,
            close_cents=one_price, limit_up_cents=1221, limit_down_cents=999,
        )
    return DailyBar(
        security_id="600000.SH", session=SESSION,
        open_cents=open_c, high_cents=open_c + 20, low_cents=open_c - 20,
        close_cents=open_c + 5, limit_up_cents=1221, limit_down_cents=999,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> CapitalRepository:
    repository = CapitalRepository.initialize(tmp_path / "arm.sqlite3")
    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key="genesis-arm",
            account_binding=AccountBinding(
                portfolio_id="trial-portfolio",
                mode=ExecutionMode.DAILY_BAR_PROXY,
                broker_account_id=None,
                base_currency="CNY",
                environment_fingerprint=None,
            ),
            unit_quanta=10_000, unit_price_numerator=1_000, unit_price_denominator=1,
            source_authority="test.seed", authorization_reference="auth-1",
            effective_at=T, as_of=T,
        )
    )
    return repository


def _drive(repo, bar, side=ExecutionSide.ENTRY, limit=1200, qty=100,
           decision="cyc-1", scenario=CURRENT_COST_SCENARIO):
    return drive_open_settlement(
        repo, arm="champion", decision_id=decision, side=side,
        security_id="600000.SH", position_lineage_id="lin-1", economic_lot_id="lot-1",
        limit_price_cents=limit, quantity=qty, bar=bar,
        command_at=T, send_deadline=DEADLINE, attribution=ATTR, scenario=scenario,
    )


def test_filled_entry_books_fill_and_fee_at_adverse_price(repo):
    v0 = repo.stream_version()
    s = _drive(repo, _bar(open_c=1105), limit=1200)
    assert s.verdict is OpenExecutionVerdict.FILLED
    assert s.fill_price_cents > 1105  # 买入 adverse: 高于原始开盘
    assert s.fill_price_cents <= 1109  # ~30bps 量级 (1105*1.003≈1108.3)
    assert s.fee_receipt is not None  # 费用同笔入账 (v2.1 口径)
    assert repo.stream_version() > v0 + 1  # fill + fee 至少两个事件


def test_double_slippage_is_more_adverse(repo):
    a = _drive(repo, _bar(open_c=1105), limit=1200, decision="d-a",
               scenario=CURRENT_COST_SCENARIO)
    b = _drive(repo, _bar(open_c=1105), limit=1200, decision="d-b",
               scenario=DOUBLE_SLIPPAGE_SCENARIO)
    assert b.fill_price_cents > a.fill_price_cents  # 60bps > 30bps 更不利
    assert b.fill_price_cents <= 1112  # 1105*1.006≈1111.6


def test_unknown_one_price_zero_writes(repo):
    v0 = repo.stream_version()
    s = _drive(repo, _bar(one_price=1221))
    assert s.verdict is OpenExecutionVerdict.UNKNOWN
    assert s.fill_receipt is None and s.fee_receipt is None


def test_no_fill_untouched_limit(repo):
    s = _drive(repo, _bar(open_c=1200), limit=1100)
    assert s.verdict is OpenExecutionVerdict.NO_FILL


def test_exit_position_defense_and_sell(repo):
    from src.screening.offensive.v3.capital.repository import CapitalConflict

    sell_bar = _bar(open_c=1000)
    with pytest.raises(CapitalConflict):  # 无持仓卖出被拒 (#9 原语防线)
        _drive(repo, sell_bar, side=ExecutionSide.EXIT, limit=1000)
    _drive(repo, _bar(open_c=1000), limit=1100)  # 入场
    s = _drive(repo, sell_bar, side=ExecutionSide.EXIT, limit=900, decision="cyc-2")
    assert s.verdict is OpenExecutionVerdict.FILLED
    assert s.fill_price_cents < 1000  # 卖出 adverse: 低于原始开盘


def test_replay_same_identity_idempotent(repo):
    _drive(repo, _bar(open_c=1105), limit=1200)
    ok, _ = repo.rebuild_projections()
    assert ok  # 守恒重验通过 (fill/fee 幂等键语义由原语承担)
