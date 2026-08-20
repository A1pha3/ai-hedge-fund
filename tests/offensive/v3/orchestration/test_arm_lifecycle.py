"""arm_lifecycle driver — Phase 5c (2026-08-20).

锁定: 判定属 resolve_open_execution (锁定判定表), 台账属资本原语, driver 只映射;
UNKNOWN/NO_FILL 零台账写入 (UNKNOWN 保现金); FILLED 以 min(open,limit) 买入价
入账 (分→micros); 执行身份确定性 {arm}:{decision}:{side}。
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
from src.screening.offensive.v3.orchestration.arm_lifecycle import drive_open_fill

UTC = timezone.utc
SESSION = date(2026, 8, 20)
T = datetime(2026, 8, 20, 9, 30, tzinfo=UTC)
DEADLINE = T + timedelta(minutes=30)
ATTR = FillAttribution(
    producer_namespace="btst", research_program_id="prog-1",
    economic_lineage_id="eline-1", stage_id="stage-1",
)


def _bar(open_c: int = 1105, one_price_up: bool = False) -> DailyBar:
    return DailyBar(
        security_id="600000.SH", session=SESSION,
        open_cents=open_c, high_cents=open_c if one_price_up else open_c + 20,
        low_cents=open_c if one_price_up else open_c - 20,
        close_cents=open_c if one_price_up else open_c + 5,
        limit_up_cents=1221, limit_down_cents=999, suspended=False,
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


def _drive(repo, bar, side=ExecutionSide.ENTRY, limit=1200):
    return drive_open_fill(
        repo, arm="champion", decision_id="cyc-1", side=side,
        security_id="600000.SH", position_lineage_id="lin-1", economic_lot_id="lot-1",
        limit_price_cents=limit, quantity=100, bar=bar,
        command_at=T, send_deadline=DEADLINE, attribution=ATTR, as_of=T + timedelta(seconds=1),
    )


def test_filled_entry_writes_ledger_at_better_of_open_and_limit(repo):
    v0 = repo.stream_version()
    res = _drive(repo, _bar(open_c=1105), limit=1200)
    assert res.verdict is OpenExecutionVerdict.FILLED
    assert res.fill_price_cents == 1105  # min(open, limit) 买入
    assert repo.stream_version() > v0


def test_unknown_one_price_limit_keeps_cash_zero_writes(repo):
    v0 = repo.stream_version()
    res = _drive(repo, _bar(open_c=1221, one_price_up=True))
    assert res.verdict is OpenExecutionVerdict.UNKNOWN
    assert repo.stream_version() == v0  # 零台账写入


def test_no_fill_untouched_limit_zero_writes(repo):
    v0 = repo.stream_version()
    res = _drive(repo, _bar(open_c=1200), limit=1100)  # 开盘高于买限, 未触及
    assert res.verdict is OpenExecutionVerdict.NO_FILL
    assert repo.stream_version() == v0


def test_missing_bar_unknown_zero_writes(repo):
    v0 = repo.stream_version()
    res = _drive(repo, None)
    assert res.verdict is OpenExecutionVerdict.UNKNOWN
    assert repo.stream_version() == v0


def test_deterministic_execution_identity_replay_idempotent(repo):
    res1 = _drive(repo, _bar(open_c=1105))
    assert res1.fill_price_cents == 1105
    res2 = _drive(repo, _bar(open_c=1105))  # 同一 (arm, decision, side) 重放
    assert res2.verdict is OpenExecutionVerdict.FILLED
    # fill 幂等键: 同 execution_id+revision 重放不膨胀事件流 (宪法 15)
    assert repo.rebuild_projections()[0] is True


def test_exit_semantics_position_defense_and_one_price_down(repo):
    """三段: 无持仓卖出被资本投影拒 (#9) / 有持仓 max(open,limit) 成交 / 一字 UNKNOWN 零写入."""
    from src.screening.offensive.v3.capital.repository import CapitalConflict
    from src.screening.offensive.v3.execution.lifecycle import DailyBar

    def _sell_bar(open_c, one_price_down=False):
        return DailyBar(
            security_id="600000.SH", session=SESSION,
            open_cents=open_c, high_cents=open_c + 20 if not one_price_down else open_c,
            low_cents=open_c - 20 if not one_price_down else open_c,
            close_cents=open_c - 5 if not one_price_down else open_c,
            limit_up_cents=1221, limit_down_cents=999, suspended=False,
        )

    # ① 无持仓的 FILLED 卖出: 资本投影拒绝 (不得超卖 — 宪法 #9 原语防线)
    with pytest.raises(CapitalConflict):
        _drive(repo, _sell_bar(1105), side=ExecutionSide.EXIT, limit=1000)

    # ② 入场后卖出: max(open, limit) 成交, 台账推进
    _drive(repo, _bar(open_c=1000), limit=1100)
    v0 = repo.stream_version()
    res = _drive(repo, _sell_bar(1105), side=ExecutionSide.EXIT, limit=1000)
    assert res.verdict is OpenExecutionVerdict.FILLED
    assert res.fill_price_cents == 1105  # max(1105, 1000)
    assert repo.stream_version() > v0

    # ③ 一字跌停: 卖出模糊 → UNKNOWN, 零写入 (无需持仓)
    v1 = repo.stream_version()
    locked = _sell_bar(999, one_price_down=True)
    res2 = _drive(repo, locked, side=ExecutionSide.EXIT, limit=900)
    assert res2.verdict is OpenExecutionVerdict.UNKNOWN
    assert repo.stream_version() == v1
