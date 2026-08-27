"""官方前向 Trial 日度会话驱动器 — 端到端测试 (R36).

真实官方布局世界 (身份目录 + genesis 双臂 restore + 治理封存 + stage 签发
回执 + spine enrollment + 证据库真实播种) → OfficialTrialSessionDriver 三入口:

  decide:  发布链 (regime/排程/候选) → pair 落库 → 恰等重放收敛
           (同 clock 与推进 clock 双面 — cutoff 水位重导出是关键断言);
  advance: bar-set 证据发布 → 市场窗口推进 → 守恒;
  finalize-missed: 错过会话 NO_RUN 补记幂等。

对抗面: 同会话 regime 状态分歧 / snapshot 会话错配 / 窗口外 through_session /
CLI dry-run 字节级零写入。
"""

from __future__ import annotations

import gc
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _dir in (
    Path(__file__).resolve().parents[1] / "governance",
    Path(__file__).resolve().parents[1] / "kernel",
    Path(__file__).resolve().parents[1] / "evidence",
):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from test_regime_trial_governance import NOW as GOV_NOW  # noqa: E402
from test_shadow_kernel import _config  # noqa: E402
from test_official_trial_stack import (  # noqa: E402
    TRIAL_ID,
    _issue_receipt,
    _official_archive_world,
)

from src.screening.offensive.daily_action_readiness import (  # noqa: E402
    BOARD_RULE_VERSION,
    DAILY_ACTION_READINESS_SCHEMA_VERSION,
    NORMALIZATION_VERSION,
    READINESS_POLICY_VERSION,
    SETUP_REQUIREMENTS_VERSION,
    DailyActionReadinessManifest,
    DailyActionTickerReadiness,
    SharedReadinessEvidence,
    SuspensionReadinessEvidence,
    _fingerprint,
)
from src.screening.offensive.daily_action_snapshot import (  # noqa: E402
    FrozenFlowRow,
    FrozenPriceRow,
    VerifiedDailyActionSnapshot,
)
from src.screening.offensive.readiness_reference import ReferenceProvenance  # noqa: E402
from src.screening.offensive.v3.evidence.governance_identity import (  # noqa: E402
    load_governance_identity,
)
from src.screening.offensive.v3.orchestration.official_trial_stack import (  # noqa: E402
    build_official_trial_stack,
)
from src.screening.offensive.v3.orchestration.stage_archive import (  # noqa: E402
    write_stage_issuance_receipt,
)
from src.screening.offensive.v3.orchestration.trial_session_driver import (  # noqa: E402
    OfficialTrialSessionDriver,
    TrialSessionDriverError,
)
from src.screening.offensive.setups.base import DetectionResult  # noqa: E402
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION  # noqa: E402

UTC = timezone.utc
SIGNAL_SESSION = date(2026, 8, 6)
DECIDE_AT = datetime(2026, 8, 6, 15, 30, tzinfo=UTC)
LATER_AT = datetime(2026, 8, 6, 16, 30, tzinfo=UTC)
TICKERS = ("300001", "300002")


# ---------------------------------------------------------------------------
# Snapshot fixture (crib test_btst_producer_api, signal session 08-06)
# ---------------------------------------------------------------------------

def _hit_result(ticker: str) -> DetectionResult:
    return DetectionResult(
        hit=True,
        ticker=ticker,
        trade_date=SIGNAL_SESSION.strftime("%Y%m%d"),
        trigger_strength=0.90,
        invalidation_condition="price below trigger close",
        metadata={"range_based_stop_pct": -0.08},
        degraded=False,
        degradation_reason="",
    )


def _prices(*, flat: bool = False) -> tuple[FrozenPriceRow, ...]:
    rows: list[FrozenPriceRow] = []
    for index in range(22):
        session = SIGNAL_SESSION - timedelta(days=21 - index)
        close = 10.0
        pct = 0.0
        if index == 16 and not flat:
            close = 10.5
        if index == 21 and not flat:
            close = 11.0
            pct = 10.0
        rows.append(
            FrozenPriceRow(
                trade_date=session,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=1000000,
                pct_change=pct,
            )
        )
    return tuple(rows)


def _flows() -> tuple[FrozenFlowRow, ...]:
    return tuple(
        FrozenFlowRow(
            trade_date=SIGNAL_SESSION - timedelta(days=offset),
            close=11.0,
            pct_change=0.0,
            main_net_inflow=1000000,
        )
        for offset in range(3)
    )


def _shared_evidence(session: date = SIGNAL_SESSION) -> SharedReadinessEvidence:
    regime_row = {"trade_date": session.isoformat(), "regime": "normal"}
    industry_by_ticker = {ticker: "software" for ticker in TICKERS}
    industry_day_pct = {ticker: 3.2 for ticker in TICKERS}
    security_status_by_ticker = {ticker: "listed" for ticker in TICKERS}
    security_reference = ReferenceProvenance.create(
        observed_on=session,
        effective_from=session,
        effective_through=session,
        source="tushare.stock_basic",
        version="test-stock-basic-v1",
        content_fingerprint=_fingerprint({"security": TICKERS}),
    )
    sw_reference = ReferenceProvenance.create(
        observed_on=session,
        effective_from=session,
        effective_through=session,
        source="tushare.index_classify+index_member",
        version="test-sw-v1",
        content_fingerprint=_fingerprint({"sw": TICKERS}),
    )
    return SharedReadinessEvidence(
        as_of_date=session,
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint(
            {"as_of_date": session.isoformat(), "regime_row": regime_row}
        ),
        industry_fingerprint=_fingerprint(
            {
                "as_of_date": session.isoformat(),
                "industry_by_ticker": industry_by_ticker,
                "industry_day_pct": industry_day_pct,
            }
        ),
        security_fingerprint=_fingerprint(
            {
                "as_of_date": session.isoformat(),
                "security_status_by_ticker": security_status_by_ticker,
            }
        ),
        security_reference=security_reference,
        sw_reference=sw_reference,
        frozen_source_fingerprint=_fingerprint({"frozen": TICKERS}),
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _manifest(session: date = SIGNAL_SESSION) -> DailyActionReadinessManifest:
    return DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain="daily_action",
        run_id=f"r36-driver-{session.isoformat()}",
        trade_date=session,
        created_at=f"{session.isoformat()}T12:00:00+00:00",
        status="healthy",
        universe_kind="resolved_refresh_universe",
        universe_tickers=TICKERS,
        universe_fingerprint="sha256:" + "f" * 64,
        input_fingerprint="sha256:" + "d" * 64,
        suspension_evidence=SuspensionReadinessEvidence(
            "available_empty", (), "sha256:" + "1" * 64
        ),
        ticker_readiness=MappingProxyType(
            {
                ticker: DailyActionTickerReadiness(
                    evidence_status="verified",
                    capabilities=MappingProxyType(
                        {
                            "btst_breakout": _plain_capability(),
                            "oversold_bounce": _disabled_capability(),
                        }
                    ),
                )
                for ticker in TICKERS
            }
        ),
        warnings=(),
        shared_evidence=_shared_evidence(session),
        policy_versions=MappingProxyType(
            {
                "readiness_policy": READINESS_POLICY_VERSION,
                "normalization": NORMALIZATION_VERSION,
                "board_rule": BOARD_RULE_VERSION,
                "setup_requirements": SETUP_REQUIREMENTS_VERSION,
                "signal_session_cutoff": SIGNAL_SESSION_POLICY_VERSION,
            }
        ),
        content_fingerprint="sha256:" + "c" * 64,
    )


def _plain_capability():
    from src.screening.offensive.setup_data_contracts import SetupCapability

    return SetupCapability(
        enabled=True,
        scannable=True,
        plan_eligible=True,
        degraded=False,
        block_reasons=(),
        warnings=(),
        consumed_fingerprint="sha256:" + "a" * 64,
    )


def _disabled_capability():
    from src.screening.offensive.setup_data_contracts import SetupCapability

    return SetupCapability(
        enabled=False,
        scannable=False,
        plan_eligible=False,
        degraded=False,
        block_reasons=("setup_disabled_by_default",),
        warnings=(),
        consumed_fingerprint=None,
    )


def _published_manifest(reports_dir: Path, session: date = SIGNAL_SESSION):
    """经生产发布函数落盘一份合法 readiness manifest (R38 首用, R41 提为共享)。"""
    from dataclasses import replace as _replace

    from src.screening.offensive.cache_readiness import universe_fingerprint
    from src.screening.offensive.daily_action_readiness import (
        publish_daily_action_readiness,
    )
    from src.screening.offensive.pit_evidence import canonical_fingerprint

    manifest = _manifest(session)
    stepped = _replace(
        manifest,
        created_at=manifest.created_at.replace("+00:00", "Z"),
        universe_fingerprint=universe_fingerprint(TICKERS),
        suspension_evidence=_replace(
            manifest.suspension_evidence,
            source_fingerprint=canonical_fingerprint("suspension", "*", []),
        ),
    )
    unsigned = {
        key: value
        for key, value in stepped.to_dict().items()
        if key != "content_fingerprint"
    }
    return publish_daily_action_readiness(
        _replace(stepped, content_fingerprint=_fingerprint(unsigned)),
        reports_dir,
    )


def _snapshot(
    *,
    regime: str = "normal",
    signal_date: date = SIGNAL_SESSION,
    flat: bool = False,
    snapshot_id: str | None = None,
):
    return VerifiedDailyActionSnapshot(
        signal_date=signal_date,
        snapshot_id=snapshot_id or ("sha256:" + "b" * 64),
        manifest=_manifest(signal_date),
        universe_tickers=TICKERS,
        prices_by_ticker=MappingProxyType(
            {ticker: _prices(flat=flat) for ticker in TICKERS}
        ),
        fund_flow_by_ticker=MappingProxyType(
            {ticker: _flows() for ticker in TICKERS}
        ),
        industry_day_pct_by_ticker=MappingProxyType(
            {ticker: 3.2 for ticker in TICKERS}
        ),
        regime=regime,
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        setup_requirements_version=SETUP_REQUIREMENTS_VERSION,
        ticker_blocks=MappingProxyType({}),
        consumed_fingerprint_by_ticker=MappingProxyType(
            {
                ticker: MappingProxyType(
                    {"btst_breakout": "sha256:" + "a" * 64}
                )
                for ticker in TICKERS
            }
        ),
    )


# ---------------------------------------------------------------------------
# Driver world (official layout + calendar + driver)
# ---------------------------------------------------------------------------

def _calendar_file(tmp_path: Path) -> Path:
    sessions = [SIGNAL_SESSION + timedelta(days=offset) for offset in range(0, 16)]
    path = tmp_path / "trade-calendar.json"
    path.write_text(
        json.dumps([session.strftime("%Y%m%d") for session in sessions]),
        encoding="utf-8",
    )
    return path


class _DriverWorld:
    def __init__(self, tmp_path: Path) -> None:
        from src.screening.offensive.v3.orchestration.arm_lifecycle import (
            CURRENT_COST_SCENARIO,
        )

        archive = _official_archive_world(tmp_path)
        receipt = _issue_receipt(
            archive.issuer, stage_id="stage-regime-001", issued_at=GOV_NOW
        )
        write_stage_issuance_receipt(archive.root, receipt)
        # R41 接管定位的 R38 flake 根因: 回执签发经 issuer 的 repository
        # 重开 governance 写连接 (_official_archive_world 的 R35 dispose 在
        # 签发之前), 池化连接存续到 GC —— 闭合时机非确定, CLI 冷读探测
        # (governance_not_checkpointed) 先于收集运行即失败。构造期确定性
        # 闭合第三写者 (与下方测试内私有引擎处置同一手法)。
        archive.issuer._repository._engine.dispose()
        self.root = archive.root
        self.identity_dir = archive.identity_dir
        self.calendar_path = _calendar_file(tmp_path)
        self._clock_value = DECIDE_AT
        # 影子诊断口径的放大 caps: 让两个候选真的形成入场计划 (官方栈构造
        # 参数是 caller 责任; caps 是诊断面不是授权)。
        from src.screening.offensive.v3.kernel.sizing import SizingConfig

        sizing = SizingConfig(
            per_ticker_gross_cap_cents=20_000_000,
            per_industry_gross_cap_cents=30_000_000,
            per_day_gross_cap_cents=50_000_000,
            portfolio_gross_cap_cents=40_000_000,
            worst_case_fee_ppm=3_000,
        )
        self.stack = build_official_trial_stack(
            identity_dir=archive.identity_dir,
            trial_root=archive.root,
            trial_id=TRIAL_ID,
            sizing_config=sizing,
            clock=lambda: self._clock_value,
            market_scenario=CURRENT_COST_SCENARIO,
            trial_attribution=archive.trial_attribution,
            research_program_id="research.btst.regime",
        )
        identity = load_governance_identity(
            archive.identity_dir, trusted_at=self._clock_value
        )
        self.driver = OfficialTrialSessionDriver(
            stack=self.stack,
            identity=identity,
            calendar_path=self.calendar_path,
            clock=lambda: self._clock_value,
        )

    @property
    def now(self) -> datetime:
        return self._clock_value

    @now.setter
    def now(self, value: datetime) -> None:
        self._clock_value = value


@pytest.fixture()
def world(tmp_path: Path) -> _DriverWorld:
    return _DriverWorld(tmp_path)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# decide: end-to-end + idempotent replay (same clock and advanced clock)
# ---------------------------------------------------------------------------

class TestDecideSession:
    def test_pair_committed_end_to_end(self, world: _DriverWorld) -> None:
        world.driver.ensure_trial_registration()
        receipt = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        assert receipt.pair_key == (
            TRIAL_ID,
            SIGNAL_SESSION.isoformat(),
            "daily-action-20260806",
        )
        champion, challenger = world.stack.decision_store.pair(receipt.pair_key)
        assert {champion.arm, challenger.arm} == {"CHAMPION", "CHALLENGER"}
        # 两个 SELECTED 候选入批 → 会话分类 RUN (normal regime 两臂都放行)。
        assert receipt.champion_status == receipt.challenger_status

    def test_replay_same_clock_is_exact(self, world: _DriverWorld) -> None:
        world.driver.ensure_trial_registration()
        first = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        second = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        assert second.pair_key == first.pair_key
        assert second.champion_status == first.champion_status

    def test_replay_advanced_clock_reuses_watermark(self, world: _DriverWorld) -> None:
        """推进 clock 重放: 成员复用 → cutoff 水位重导出不变 → pair 恰等。"""
        world.driver.ensure_trial_registration()
        first = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        world.now = LATER_AT
        second = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=LATER_AT
        )
        assert second.pair_key == first.pair_key
        assert second.champion_status == first.champion_status
        rows_before = world.stack.decision_store.pair(first.pair_key)
        world.now = LATER_AT + timedelta(hours=1)
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=world.now
        )
        rows_after = world.stack.decision_store.pair(first.pair_key)
        assert rows_after == rows_before


# ---------------------------------------------------------------------------
# advance + finalize-missed
# ---------------------------------------------------------------------------

class TestAdvanceAndFinalize:
    def test_advance_conservation(self, world: _DriverWorld) -> None:
        from src.screening.offensive.v3.execution.lifecycle import DailyBar

        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        bars: dict[date, dict[str, DailyBar]] = {}
        for session in (SIGNAL_SESSION, SIGNAL_SESSION + timedelta(days=1)):
            bars[session] = {
                f"{ticker}.SZ": DailyBar(
                    security_id=f"{ticker}.SZ",
                    session=session,
                    open_cents=1100,
                    high_cents=1200,
                    low_cents=1050,
                    close_cents=1150,
                    limit_up_cents=1320,
                    limit_down_cents=880,
                )
                for ticker in TICKERS
            }
        receipt = world.driver.advance_sessions(
            signal_session=SIGNAL_SESSION,
            through_session=SIGNAL_SESSION + timedelta(days=1),
            bars_by_session=bars,
            now=LATER_AT,
        )
        assert receipt.through_session == SIGNAL_SESSION + timedelta(days=1)
        assert all(receipt.conservation_ok_by_arm.values())

    def test_advance_replay_is_idempotent(self, world: _DriverWorld) -> None:
        from src.screening.offensive.v3.execution.lifecycle import DailyBar

        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        bars = {
            session: {
                f"{ticker}.SZ": DailyBar(
                    security_id=f"{ticker}.SZ",
                    session=session,
                    open_cents=1100,
                    high_cents=1200,
                    low_cents=1050,
                    close_cents=1150,
                    limit_up_cents=1320,
                    limit_down_cents=880,
                )
                for ticker in TICKERS
            }
            for session in (SIGNAL_SESSION, SIGNAL_SESSION + timedelta(days=1))
        }
        first = world.driver.advance_sessions(
            signal_session=SIGNAL_SESSION,
            through_session=SIGNAL_SESSION + timedelta(days=1),
            bars_by_session=bars,
            now=LATER_AT,
        )
        second = world.driver.advance_sessions(
            signal_session=SIGNAL_SESSION,
            through_session=SIGNAL_SESSION + timedelta(days=1),
            bars_by_session=bars,
            now=LATER_AT + timedelta(minutes=30),
        )
        assert second.through_session == first.through_session
        assert second.settlements_by_arm == first.settlements_by_arm

    def test_advance_after_no_signal_session(self, world: _DriverWorld) -> None:
        """R25 缺陷回归: no-trade 会话 (零候选 NO_SIGNAL) 后 advance 不崩溃。

        修复前: pair 行含 NoTradeDecision, ``advance_market_session`` 无条件
        访问 ``target_entry_session`` → AttributeError, 官方 Trial 无法跨
        会话推进。
        """
        from src.screening.offensive.v3.execution.lifecycle import DailyBar

        world.driver.ensure_trial_registration()
        # 08-06: 有候选的会话 (决定入场)
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        # 08-07: 零候选会话 — 平价格历史不触发射程 → NO_SIGNAL pair 落库
        flat = _snapshot(signal_date=date(2026, 8, 7), flat=True)
        world.now = datetime(2026, 8, 7, 15, 30, tzinfo=UTC)
        receipt_0807 = world.driver.decide_session(
            snapshot=flat, signal_session=date(2026, 8, 7), now=world.now
        )
        assert receipt_0807.pair_key[1] == "2026-08-07"
        bars = {
            session: {
                f"{ticker}.SZ": DailyBar(
                    security_id=f"{ticker}.SZ",
                    session=session,
                    open_cents=1100,
                    high_cents=1200,
                    low_cents=1050,
                    close_cents=1150,
                    limit_up_cents=1320,
                    limit_down_cents=880,
                )
                for ticker in TICKERS
            }
            for session in (SIGNAL_SESSION, date(2026, 8, 7), date(2026, 8, 8))
        }
        # 生命周期窗口需 ≥2 会话 (出场会话语义): no-trade 会话 08-07 + 次日。
        advance = world.driver.advance_sessions(
            signal_session=date(2026, 8, 7),
            through_session=date(2026, 8, 8),
            bars_by_session=bars,
            now=datetime(2026, 8, 8, 16, 0, tzinfo=UTC),
        )
        assert advance.through_session == date(2026, 8, 8)
        assert all(advance.conservation_ok_by_arm.values())

    def test_advance_window_outside_schedule_rejected(
        self, world: _DriverWorld
    ) -> None:
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.advance_sessions(
                signal_session=SIGNAL_SESSION,
                through_session=SIGNAL_SESSION + timedelta(days=99),
                bars_by_session={},
                now=LATER_AT,
            )
        assert rejected.value.code == "advance_window_not_in_schedule"

    def test_advance_bar_content_conflict_rejected(self, world: _DriverWorld) -> None:
        from src.screening.offensive.v3.execution.lifecycle import DailyBar

        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )

        def bars_for(session: date, open_cents: int) -> dict[str, DailyBar]:
            return {
                f"{ticker}.SZ": DailyBar(
                    security_id=f"{ticker}.SZ",
                    session=session,
                    open_cents=open_cents,
                    high_cents=open_cents + 100,
                    low_cents=open_cents - 50,
                    close_cents=open_cents + 50,
                    limit_up_cents=1320,
                    limit_down_cents=880,
                )
                for ticker in TICKERS
            }

        window = (SIGNAL_SESSION, SIGNAL_SESSION + timedelta(days=1))
        world.driver.advance_sessions(
            signal_session=SIGNAL_SESSION,
            through_session=window[-1],
            bars_by_session={s: bars_for(s, 1100) for s in window},
            now=LATER_AT,
        )
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.advance_sessions(
                signal_session=SIGNAL_SESSION,
                through_session=window[-1],
                bars_by_session={s: bars_for(s, 1110) for s in window},
                now=LATER_AT + timedelta(minutes=5),
            )
        assert rejected.value.code == "bar_set_content_conflict"

    def test_finalize_missed_idempotent(self, world: _DriverWorld) -> None:
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        finalized = world.driver.finalize_missed(
            trusted_at=datetime(2026, 8, 20, 15, 0, tzinfo=UTC)
        )
        assert finalized == (date(2026, 8, 13),)
        again = world.driver.finalize_missed(
            trusted_at=datetime(2026, 8, 20, 15, 0, tzinfo=UTC)
        )
        assert again == ()


# ---------------------------------------------------------------------------
# Adversarial: state conflicts / mismatches / CLI dry-run zero-write
# ---------------------------------------------------------------------------

class TestAdversarial:
    def test_regime_state_conflict_rejected(self, world: _DriverWorld) -> None:
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.decide_session(
                snapshot=_snapshot(regime="crisis"),
                signal_session=SIGNAL_SESSION,
                now=LATER_AT,
            )
        assert rejected.value.code == "regime_state_conflict"

    def test_snapshot_session_mismatch_rejected(self, world: _DriverWorld) -> None:
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.decide_session(
                snapshot=_snapshot(signal_date=date(2026, 8, 5)),
                signal_session=SIGNAL_SESSION,
                now=DECIDE_AT,
            )
        assert rejected.value.code == "snapshot_session_mismatch"

    def test_signal_session_not_in_calendar_rejected(
        self, world: _DriverWorld
    ) -> None:
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.decide_session(
                snapshot=_snapshot(signal_date=date(2026, 8, 30)),
                signal_session=date(2026, 8, 30),
                now=datetime(2026, 8, 30, 15, 30, tzinfo=UTC),
            )
        assert rejected.value.code == "signal_session_not_in_calendar"

    def test_cli_dry_run_is_zero_write(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        """R36→R41: dry-run 仍字节级零写入, 但现在带 manifest pre-flight。

        R36 契约 (manifest 缺失仍报绿) 正是 R41 关闭的操作员假信心面;
        缺失/会话错位两形态的拒绝由 TestDecideManifestPreflight 钉死。
        R48 D6 契约更新: 窗口 pre-flight 上线后 dry-run 必须显式注入窗口内
        --now (旧版无 --now 即真实墙钟, 对陈旧会话假绿 — 正是 D6 关闭的
        面注入 --now 后本测试守护『合法窗内 dry-run 仍字节级零写入』)。
        """
        from scripts.v3_trial_session import main as cli_main

        reports = tmp_path / "reports"
        reports.mkdir()
        publication = _published_manifest(reports, SIGNAL_SESSION)
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        rc = cli_main(
            [
                "decide",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--readiness-manifest", str(publication.artifact_path),
                "--data-dir", str(tmp_path),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--now", DECIDE_AT.isoformat(),
            ]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["mode"] == "dry-run"
        assert payload["readiness_session"] == SIGNAL_SESSION.isoformat()
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before

    def test_decide_loads_snapshot_with_real_loader_signature(
        self, world: _DriverWorld, tmp_path_factory, capsys
    ) -> None:
        """R38 修复钉死: decide 的快照加载用真实三参签名并解包 Result。

        R36 缺陷: 单参调用 load_verified_daily_action_snapshot(manifest_path)
        — 真实签名 (signal_date, *, reports_dir, data_dir), 一执行即
        TypeError; 且返回值是 VerifiedSnapshotResult 包装, 需解包 .snapshot。
        本测试经生产发布函数落盘真实 manifest 后走 CLI --execute 全链。
        """
        from scripts.v3_trial_session import main as cli_main

        reports = tmp_path_factory.mktemp("reports-r38")
        publication = _published_manifest(reports, SIGNAL_SESSION)
        assert publication.status == "healthy"

        world.driver.ensure_trial_registration()
        # R35 冷读纪律: CLI 是新进程, 组装器冷读探测要求事实文件已
        # checkpoint — 同进程 stack (spine + assembler 持有的 governance)
        # 与 registration 构造的引擎先确定性 dispose。governance 引擎不
        # 在 stack 公开面, 经同路径重建一个等价引擎 dispose (SQLite WAL
        # checkpoint 是文件级效果, 与引擎实例无关)。
        world.stack.spine._engine.dispose()
        world.stack.runner._assembler._governance._engine.dispose()
        # dispose 只归还池内闲置连接; 被引用循环 Session 持有的
        # governance 连接要等 GC 才释放, 活连接会让 -wal 留存到 CLI
        # 冷读探测之后 (governance_not_checkpointed 假阳性, R41 slot
        # 验证 2/2 确定性复现)。强制回收使最后连接关闭、WAL 落盘清除。
        gc.collect()
        rc = cli_main(
            [
                "decide",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--readiness-manifest", str(publication.artifact_path),
                "--data-dir", str(tmp_path_factory.mktemp("data-r38")),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--now", DECIDE_AT.isoformat(),
                "--execute",
            ]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["champion_status"] == str(payload["challenger_status"])


# ---------------------------------------------------------------------------
# R40: advance 数据面前置完备性 — driver 整窗口预检 + CLI 双面 pre-flight
# ---------------------------------------------------------------------------

_COURT_HEADER = (
    "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount\n"
)


def _court_bar_dir(tmp_path: Path, sessions) -> Path:
    """Court raw daily_YYYYMMDD.csv 快照目录 (bars_from_court_csv 消费格式)."""
    bar_dir = tmp_path / "court-daily"
    bar_dir.mkdir(parents=True, exist_ok=True)
    for session in sessions:
        rows = [_COURT_HEADER]
        for ticker in TICKERS:
            rows.append(
                f"{ticker}.SZ,{session:%Y%m%d},"
                "11.0,12.0,10.5,11.5,10.9,5.5,1000,11000\n"
            )
        (bar_dir / f"daily_{session:%Y%m%d}.csv").write_text(
            "".join(rows), encoding="utf-8"
        )
    return bar_dir


def _bars_for(session: date):
    from src.screening.offensive.v3.execution.lifecycle import DailyBar

    return {
        f"{ticker}.SZ": DailyBar(
            security_id=f"{ticker}.SZ",
            session=session,
            open_cents=1100,
            high_cents=1200,
            low_cents=1050,
            close_cents=1150,
            limit_up_cents=1320,
            limit_down_cents=880,
        )
        for ticker in TICKERS
    }


class TestAdvanceDatafacePreflight:
    def test_driver_missing_session_publishes_nothing(
        self, world: _DriverWorld
    ) -> None:
        """整窗口预检: 任一会话缺失 → 零 bar 发布 (修复前窗口前段已发布)。"""
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        through = SIGNAL_SESSION + timedelta(days=1)
        before = _tree_digest(world.root)
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.advance_sessions(
                signal_session=SIGNAL_SESSION,
                through_session=through,
                bars_by_session={SIGNAL_SESSION: _bars_for(SIGNAL_SESSION)},
                now=LATER_AT,
            )
        assert rejected.value.code == "bar_set_missing"
        assert rejected.value.details.get("missing_sessions") == [
            through.isoformat()
        ]
        assert _tree_digest(world.root) == before

    def test_cli_advance_dry_run_reports_missing_sessions(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        from scripts.v3_trial_session import main as cli_main

        bar_dir = _court_bar_dir(tmp_path, [SIGNAL_SESSION])
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        rc = cli_main(
            [
                "advance",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--through-session", (SIGNAL_SESSION + timedelta(days=1)).isoformat(),
                "--bar-source", str(bar_dir),
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert payload["ok"] is False
        assert payload["code"] == "bar_sessions_missing"
        assert payload["details"]["missing_sessions"] == [
            (SIGNAL_SESSION + timedelta(days=1)).isoformat()
        ]
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before

    def test_cli_advance_dry_run_complete_window_ok(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        from scripts.v3_trial_session import main as cli_main

        window = (SIGNAL_SESSION, SIGNAL_SESSION + timedelta(days=1))
        bar_dir = _court_bar_dir(tmp_path, window)
        rc = cli_main(
            [
                "advance",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--through-session", window[-1].isoformat(),
                "--bar-source", str(bar_dir),
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["mode"] == "dry-run"
        assert payload["window_sessions"] == 2

    def test_cli_advance_execute_preflight_is_zero_write(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        """execute 缺失会话 → 栈构造之前拒绝: trial root 字节级零突变。

        修复前: _build_stack 先行 (对 trial root 落 WAL+DDL 写副作用),
        之后 driver 才以 bar_set_missing 晚失败。
        """
        from scripts.v3_trial_session import main as cli_main

        bar_dir = _court_bar_dir(tmp_path, [SIGNAL_SESSION])
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        rc = cli_main(
            [
                "advance",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--through-session", (SIGNAL_SESSION + timedelta(days=1)).isoformat(),
                "--bar-source", str(bar_dir),
                "--now", LATER_AT.isoformat(),
                "--execute",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert payload["code"] == "bar_sessions_missing"
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before

    def test_cli_advance_dry_run_rejects_through_outside_schedule(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        """窗口外 through_session 在 dry-run 即拒 (修复前只在 execute 期)。"""
        from scripts.v3_trial_session import main as cli_main

        bar_dir = _court_bar_dir(
            tmp_path, [SIGNAL_SESSION, SIGNAL_SESSION + timedelta(days=99)]
        )
        with pytest.raises(SystemExit) as stopped:
            cli_main(
                [
                    "advance",
                    "--identity-dir", str(world.identity_dir),
                    "--trial-root", str(world.root),
                    "--trial-id", TRIAL_ID,
                    "--calendar", str(world.calendar_path),
                    "--signal-session", SIGNAL_SESSION.isoformat(),
                    "--through-session",
                    (SIGNAL_SESSION + timedelta(days=99)).isoformat(),
                    "--bar-source", str(bar_dir),
                ]
            )
        assert stopped.value.code == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["code"] == "advance_window_not_in_schedule"

    def test_cli_advance_execute_parses_only_window_files(
        self, world: _DriverWorld, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        """execute 只解析窗口内 daily_*.csv (修复前全目录解析 394 文件级浪费)。"""
        import scripts.v3_seed_market_bars as seeder
        from scripts.v3_trial_session import main as cli_main

        window = (SIGNAL_SESSION, SIGNAL_SESSION + timedelta(days=1))
        bar_dir = _court_bar_dir(
            tmp_path,
            [
                SIGNAL_SESSION - timedelta(days=7),  # 窗口外的多余快照
                *window,
            ],
        )
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        # R35 冷读纪律: CLI 构造新栈前确定性 checkpoint 既有引擎。
        world.stack.spine._engine.dispose()
        world.stack.runner._assembler._governance._engine.dispose()
        gc.collect()  # 同 R38 测试位: 释放引用循环 Session 持有的活连接, WAL 才随最后连接关闭而清除

        calls: list[date] = []
        original = seeder.bars_from_court_csv

        def counting(path, session):
            calls.append(session)
            return original(path, session)

        monkeypatch.setattr(seeder, "bars_from_court_csv", counting)
        rc = cli_main(
            [
                "advance",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--through-session", window[-1].isoformat(),
                "--bar-source", str(bar_dir),
                "--now", LATER_AT.isoformat(),
                "--execute",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["ok"] is True
        assert calls == list(window)


# ---------------------------------------------------------------------------
# R41: 会话真相序纪律 — regime 头前向唯序 + 候选集同会话唯一真相
# ---------------------------------------------------------------------------

EARLIER_SESSION = date(2026, 8, 5)


def _wide_calendar_file(tmp_path: Path, earliest: date) -> Path:
    """含 earliest 起共 20 个会话的日历 (夹具默认日历从 SIGNAL_SESSION 起)."""
    wide = tmp_path / "wide-trade-calendar.json"
    wide.write_text(
        json.dumps(
            [
                (earliest + timedelta(days=offset)).strftime("%Y%m%d")
                for offset in range(0, 20)
            ]
        ),
        encoding="utf-8",
    )
    return wide


class TestSessionTruthOrderDiscipline:
    """R41: 前向 Trial 的 regime active 头只能随驱动前进。

    修复前 (RED 探针实锤): 先驱动 08-06 再补驱动 08-05 静默成功——
    修正链追加倒序 revision 并把 active 头倒回早会话, 此后本应逐字节
    幂等的 08-06 重放以 batch_seal_conflict 破裂 (与真实损坏不可区分)。
    """

    def test_retro_drive_rejected_zero_write(
        self, world: _DriverWorld, tmp_path: Path
    ) -> None:
        world.driver._calendar_path = _wide_calendar_file(tmp_path, EARLIER_SESSION)
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        before = _tree_digest(world.root)
        # R48 D6: retro 尝试注入 EARLIER_SESSION 入库窗内的时刻 — 窗外形态
        # 现由 decide_window_violated 先拦 (CLI dry-run 同源), 本测试钉的
        # 会话真相序面 (regime_session_regression) 在窗内注入钟下保持可达。
        world.now = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)  # 仍在 08-05 入库窗内 (窗至 08-06 15:00) 且晚于身份 notBefore
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.decide_session(
                snapshot=_snapshot(signal_date=EARLIER_SESSION),
                signal_session=EARLIER_SESSION,
                now=world.now,
            )
        assert rejected.value.code == "regime_session_regression"
        assert rejected.value.details["active_session"] == SIGNAL_SESSION.isoformat()
        assert rejected.value.details["requested_session"] == EARLIER_SESSION.isoformat()
        assert _tree_digest(world.root) == before

    def test_rejected_retro_preserves_later_replay_idempotency(
        self, world: _DriverWorld, tmp_path: Path
    ) -> None:
        """被拒的 retro 尝试之后, 晚会话重放仍收敛到同 pair (危害回归)."""
        world.driver._calendar_path = _wide_calendar_file(tmp_path, EARLIER_SESSION)
        world.driver.ensure_trial_registration()
        first = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        # R48 D6: 同 test_retro_drive_rejected_zero_write — retro 尝试注入
        # EARLIER_SESSION 入库窗内时刻, 使会话真相序面保持可达。
        world.now = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)  # 仍在 08-05 入库窗内 (窗至 08-06 15:00) 且晚于身份 notBefore
        with pytest.raises(TrialSessionDriverError):
            world.driver.decide_session(
                snapshot=_snapshot(signal_date=EARLIER_SESSION),
                signal_session=EARLIER_SESSION,
                now=world.now,
            )
        world.now = DECIDE_AT + timedelta(hours=3)
        replay = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=world.now
        )
        assert replay.pair_key == first.pair_key
        assert replay.champion_status == first.champion_status

    def test_forward_next_session_still_publishes(
        self, world: _DriverWorld
    ) -> None:
        """前向驱动 (active 头属早会话) 不受守卫影响。"""
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        next_session = SIGNAL_SESSION + timedelta(days=1)
        world.now = datetime(2026, 8, 7, 15, 30, tzinfo=UTC)
        receipt = world.driver.decide_session(
            snapshot=_snapshot(signal_date=next_session, flat=True),
            signal_session=next_session,
            now=world.now,
        )
        assert receipt.pair_key[1] == next_session.isoformat()


def _miss_result(ticker: str, trade_date: str) -> DetectionResult:
    return DetectionResult(
        hit=False,
        ticker=ticker,
        trade_date=trade_date,
        trigger_strength=0.0,
        invalidation_condition="",
        metadata={},
        degraded=False,
        degradation_reason="",
    )


@pytest.fixture()
def live_candidates(
    world: _DriverWorld, monkeypatch: pytest.MonkeyPatch
) -> _DriverWorld:
    """R41: 让扫描真实产出 SELECTED 候选 (crib test_btst_producer_api.world)。

    夹具价格 (300xxx 创业板, 信号日 pct=10.0) 不过 ~19.5% 涨停门槛, 真实
    detect 恒 miss——分歧场景需要会话真的提交 SELECTED 候选。detect 固定
    为命中但保持价格感知: flat 世界 (全部 close=10.0) 仍 miss, 使
    shrunk-to-empty (重生成后零候选) 场景可达。
    """
    from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup

    def _detect(self, ticker: str, trade_date: str, context: dict) -> DetectionResult:
        prices = context.get("prices")
        if prices is None or len(prices) == 0:
            return _miss_result(ticker, trade_date)
        if float(prices.iloc[-1]["close"]) <= 10.0:
            return _miss_result(ticker, trade_date)
        return _hit_result(ticker)

    monkeypatch.setattr(BtstBreakoutSetup, "detect", _detect)
    return world


class TestCandidateSetDivergence:
    """R41: 同会话已提交 SELECTED 候选集是唯一真相。

    修复前: crash (候选发布后 pair 前崩) + readiness manifest 重生成 +
    重驱动会静默发布第二套同会话 SELECTED, 晚失败于批完备性且永久污染
    证据时间轴。分歧 (生产形态 = snapshot_id 内容派生变化 → id 集变化)
    必须在零新发布处类型化拒绝; 恰等重放不受影响。
    """

    def test_disjoint_snapshot_ids_rejected_zero_write(
        self, live_candidates: _DriverWorld
    ) -> None:
        world = live_candidates
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        before = _tree_digest(world.root)
        world.now = DECIDE_AT + timedelta(hours=2)
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.decide_session(
                snapshot=_snapshot(snapshot_id="sha256:" + "c" * 64),
                signal_session=SIGNAL_SESSION,
                now=world.now,
            )
        assert rejected.value.code == "candidate_set_divergence"
        committed = rejected.value.details["committed_not_derived"]
        assert len(committed) == 2  # 两个 A 集合 id 均不在 B 集合内
        assert _tree_digest(world.root) == before

    def test_shrunk_to_empty_rejected(
        self, live_candidates: _DriverWorld
    ) -> None:
        """重生成后零候选 (全部候选消失) 同样是分歧, 不是合法重放。"""
        world = live_candidates
        world.driver.ensure_trial_registration()
        world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        world.now = DECIDE_AT + timedelta(hours=2)
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.decide_session(
                snapshot=_snapshot(flat=True),
                signal_session=SIGNAL_SESSION,
                now=world.now,
            )
        assert rejected.value.code == "candidate_set_divergence"

    def test_exact_replay_still_converges(
        self, live_candidates: _DriverWorld
    ) -> None:
        """恰等重放 (同 snapshot) 不受分歧守卫影响 (复用路径)."""
        world = live_candidates
        world.driver.ensure_trial_registration()
        first = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        world.now = DECIDE_AT + timedelta(hours=4)
        replay = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=world.now
        )
        assert replay.pair_key == first.pair_key


class TestCourtBarCsvMalformed:
    """R41: bar 源畸形文件的句法层类型化拒绝 (runbook qfq 红线执行面)."""

    def _write_csv(self, tmp_path: Path, name: str, content: str) -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_missing_pre_close_column_rejected(self, tmp_path: Path) -> None:
        """price_cache 式 qfq 快照 (缺 pre_close) 在列校验即拒。"""
        from scripts.v3_seed_market_bars import (
            CourtBarCsvError,
            bars_from_court_csv,
        )

        path = self._write_csv(
            tmp_path,
            "daily_20260806.csv",
            "ts_code,trade_date,open,high,low,close\n300001.SZ,20260806,11,12,10.5,11.5\n",
        )
        with pytest.raises(CourtBarCsvError) as rejected:
            bars_from_court_csv(path, SIGNAL_SESSION)
        assert rejected.value.code == "bar_csv_columns_missing"
        assert "pre_close" in rejected.value.details["missing_columns"]

    def test_empty_file_rejected(self, tmp_path: Path) -> None:
        from scripts.v3_seed_market_bars import (
            CourtBarCsvError,
            bars_from_court_csv,
        )

        path = self._write_csv(
            tmp_path,
            "daily_20260806.csv",
            "ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount\n",
        )
        with pytest.raises(CourtBarCsvError) as rejected:
            bars_from_court_csv(path, SIGNAL_SESSION)
        assert rejected.value.code == "bar_csv_empty"

    def test_duplicate_ticker_rejected(self, tmp_path: Path) -> None:
        from scripts.v3_seed_market_bars import (
            CourtBarCsvError,
            bars_from_court_csv,
        )

        path = self._write_csv(
            tmp_path,
            "daily_20260806.csv",
            _COURT_HEADER
            + "300001.SZ,20260806,11.0,12.0,10.5,11.5,10.9,5.5,1000,11000\n"
            + "300001.SZ,20260806,11.1,12.1,10.6,11.6,10.9,5.5,1000,11000\n",
        )
        with pytest.raises(CourtBarCsvError) as rejected:
            bars_from_court_csv(path, SIGNAL_SESSION)
        assert rejected.value.code == "bar_csv_duplicate_ticker"
        assert rejected.value.details["ts_code"] == "300001.SZ"

    def test_non_numeric_row_rejected(self, tmp_path: Path) -> None:
        from scripts.v3_seed_market_bars import (
            CourtBarCsvError,
            bars_from_court_csv,
        )

        path = self._write_csv(
            tmp_path,
            "daily_20260806.csv",
            _COURT_HEADER
            + "300001.SZ,20260806,'11.0,12.0,10.5,11.5,10.9,5.5,1000,11000\n",
        )
        with pytest.raises(CourtBarCsvError) as rejected:
            bars_from_court_csv(path, SIGNAL_SESSION)
        assert rejected.value.code == "bar_csv_row_invalid"

    def test_cli_execute_malformed_csv_typed_zero_write(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        """CLI execute 遇畸形快照 → 类型化 JSON (非裸 traceback), 且在
        栈构造之前拒绝 (trial root 字节级零突变)."""
        from scripts.v3_trial_session import main as cli_main

        bar_dir = tmp_path / "court-malformed"
        bar_dir.mkdir(parents=True, exist_ok=True)
        good = _court_bar_dir(tmp_path, [SIGNAL_SESSION])
        (good / f"daily_{SIGNAL_SESSION:%Y%m%d}.csv").rename(
            bar_dir / f"daily_{SIGNAL_SESSION:%Y%m%d}.csv"
        )
        (bar_dir / f"daily_{SIGNAL_SESSION + timedelta(days=1):%Y%m%d}.csv").write_text(
            "ts_code,trade_date,open,high,low,close\n300001.SZ,20260807,1,2,3,4\n",
            encoding="utf-8",
        )
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        rc = cli_main(
            [
                "advance",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--through-session", (SIGNAL_SESSION + timedelta(days=1)).isoformat(),
                "--bar-source", str(bar_dir),
                "--now", LATER_AT.isoformat(),
                "--execute",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert payload["ok"] is False
        assert payload["code"] == "bar_csv_invalid"
        assert payload["details"]["code"] == "bar_csv_columns_missing"
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before


class TestDecideManifestPreflight:
    """R41: decide dry-run 的 readiness manifest pre-flight (docstring 对齐)."""

    def test_dry_run_missing_manifest_rejected(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        """manifest 缺失在 dry-run 即拒 (修复前 dry-run 对缺失 manifest 报绿)."""
        from scripts.v3_trial_session import main as cli_main

        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        rc = cli_main(
            [
                "decide",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--readiness-manifest", str(tmp_path / "missing.json"),
                "--data-dir", str(tmp_path),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--now", DECIDE_AT.isoformat(),
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert payload["ok"] is False
        assert payload["code"] == "snapshot_load_failed"
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before

    def test_dry_run_manifest_session_mismatch_rejected(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        """manifest 属另一交易日 → dry-run 即拒 (类型化, 零写入).

        loader 按文件名解析 (daily_action_readiness_{signal_date}.json) 且
        内部校验 trade_date; 错位的真实可达形态是「文件名 08-06 / 内容
        08-07」→ global_reason=readiness_date_mismatch。_load_snapshot 的
        manifest_session_mismatch 分支是该面之下的防御纵深 (真实 loader
        先拒绝, 不可达)。
        """
        from scripts.v3_trial_session import main as cli_main

        other_day = SIGNAL_SESSION + timedelta(days=1)
        publication = _published_manifest(tmp_path, other_day)
        mislabeled = tmp_path / (
            f"daily_action_readiness_{SIGNAL_SESSION:%Y%m%d}.json"
        )
        publication.artifact_path.rename(mislabeled)
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        rc = cli_main(
            [
                "decide",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--readiness-manifest", str(mislabeled),
                "--data-dir", str(tmp_path),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--now", DECIDE_AT.isoformat(),
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert rc == 2
        assert payload["ok"] is False
        assert payload["code"] == "snapshot_load_failed"
        assert payload["details"]["global_reason"] == "readiness_date_mismatch"
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before


# -- R47: CLI _fail code 恒碰撞收口 -------------------------------------------


def test_driver_error_reports_typed_code_without_collision(capsys):
    """R47 真实数据演练实锤 (D1): ``_fail("driver_failed", …, code=exc.code,
    **exc.details)`` 的位置/关键字 ``code`` 恒碰撞 — 任何 driver 类型化错误
    都被 TypeError 掩盖 (rc=1、stdout 无 typed JSON), R38/R41 同族第四处。

    修复后 helper 以 ``exc.code`` 为权威码构造输出, rc=2。
    """
    import json

    from scripts.v3_trial_session import _fail_driver
    from src.screening.offensive.v3.orchestration.trial_session_driver import (
        TrialSessionDriverError,
    )

    rc = _fail_driver(
        TrialSessionDriverError(
            "regime_session_regression",
            "regime head regression",
            active_session="2026-08-26",
            requested_session="2026-08-12",
        )
    )
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["code"] == "regime_session_regression"
    assert out["details"] == {
        "active_session": "2026-08-26",
        "requested_session": "2026-08-12",
    }


def test_driver_error_details_cannot_shadow_code():
    """结构性保证: TrialSessionDriverError 构造器即拒绝 details 携带
    code 键 (位置/关键字同名碰撞) — details 永远不可能遮蔽权威码,
    _fail_driver 的同名键防御只是对鸭子/子类形态的纵深。"""
    import pytest

    from src.screening.offensive.v3.orchestration.trial_session_driver import (
        TrialSessionDriverError,
    )

    with pytest.raises(TypeError, match="multiple values for argument 'code'"):
        TrialSessionDriverError("outer_code", "m", code="inner")


# ---------------------------------------------------------------------------
# R48 D6: decide 会话真相守卫 — 窗口外拒绝 + 已提交重放逃生门 + CLI pre-flight
# ---------------------------------------------------------------------------

LATE_AT = datetime(2026, 8, 8, 15, 30, tzinfo=UTC)
"""08-06 会话入库窗 [08-05 15:00, 08-06 15:00] (信封时间链) 之外的时刻。

注: 驱动器世界的 _calendar_file 覆盖 08-06..08-21, 08-08 在日历内 —
本节窗口测试与日历成员正交。
"""


class TestDecideWindowGuard:
    def test_decide_outside_window_rejected_before_any_publication(
        self, world: _DriverWorld
    ) -> None:
        """窗口外 + 无已提交候选: 零发布类型化拒绝 (regime/排程/候选全不动)。"""
        world.driver.ensure_trial_registration()
        snapshots_before = set(
            world.stack.regime_repository.evidence_ids_by_kind("snapshot")
        )
        signals_before = set(
            world.stack.btst_repository.evidence_ids_by_kind("signal")
        )
        with pytest.raises(TrialSessionDriverError) as rejected:
            world.driver.decide_session(
                snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=LATE_AT
            )
        assert rejected.value.code == "decide_window_violated"
        assert rejected.value.details["signal_session"] == SIGNAL_SESSION.isoformat()
        assert set(
            world.stack.regime_repository.evidence_ids_by_kind("snapshot")
        ) == snapshots_before
        assert set(world.stack.btst_repository.evidence_ids_by_kind("signal")) == (
            signals_before
        )

    def test_decide_outside_window_committed_replay_converges(
        self, world: _DriverWorld, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """逃生门: 窗口内已提交会话的窗口外重驱动恰等收敛 (复验形态)。

        驱动器世界的合成快照默认零候选 (NO_SIGNAL) — 逃生门前提是『已有
        已提交 SELECTED 候选』, 故按 test_btst_producer_api 先例 patch
        setup.detect 使首驱动真实产生并提交候选。
        """
        from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup

        def hit(self, ticker, trade_date, context):
            return DetectionResult(
                hit=True,
                ticker=ticker,
                trade_date=SIGNAL_SESSION.strftime("%Y%m%d"),
                trigger_strength=0.90,
                invalidation_condition="price below trigger close",
                metadata={"range_based_stop_pct": -0.08},
                degraded=False,
                degradation_reason="",
            )

        monkeypatch.setattr(BtstBreakoutSetup, "detect", hit)
        world.driver.ensure_trial_registration()
        first = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        committed = world.stack.btst_repository.evidence_ids_by_kind("signal")
        assert committed, "escape-hatch premise: the in-window decide must commit SELECTED candidates"
        world.now = LATE_AT
        second = world.driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=LATE_AT
        )
        assert second.pair_key == first.pair_key
        assert second.champion_status == first.champion_status


class TestDecideCliPreflight:
    def test_cli_dry_run_rejects_stale_session_zero_write(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        """D6: 陈旧会话的 dry-run 不再假绿 — 构造栈之前类型化拒绝。

        R41 manifest 假绿的精确同族: dry-run 报绿的语义是『execute 的前置
        全部成立』; 窗口外会话 execute 必然失败, dry-run 必须先说。
        """
        from scripts.v3_trial_session import main as cli_main

        reports = tmp_path / "reports"
        reports.mkdir()
        publication = _published_manifest(reports, SIGNAL_SESSION)
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        rc = cli_main(
            [
                "decide",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--readiness-manifest", str(publication.artifact_path),
                "--data-dir", str(tmp_path),
                "--signal-session", SIGNAL_SESSION.isoformat(),
                "--now", LATE_AT.isoformat(),
            ]
        )
        assert rc == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is False
        assert payload["code"] == "decide_window_violated"
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before

    def test_cli_dry_run_rejects_session_not_in_calendar(
        self, world: _DriverWorld, tmp_path: Path, capsys
    ) -> None:
        """D6: 日历成员 pre-flight 与 advance 的 R40 语义对齐 (dry-run 即拒)。"""
        from scripts.v3_trial_session import main as cli_main

        reports = tmp_path / "reports"
        reports.mkdir()
        publication = _published_manifest(reports, date(2026, 8, 30))
        rc = cli_main(
            [
                "decide",
                "--identity-dir", str(world.identity_dir),
                "--trial-root", str(world.root),
                "--trial-id", TRIAL_ID,
                "--calendar", str(world.calendar_path),
                "--readiness-manifest", str(publication.artifact_path),
                "--data-dir", str(tmp_path),
                "--signal-session", "2026-08-30",
                "--now", "2026-08-30T15:30:00+00:00",
            ]
        )
        assert rc == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["code"] == "signal_session_not_in_calendar"
