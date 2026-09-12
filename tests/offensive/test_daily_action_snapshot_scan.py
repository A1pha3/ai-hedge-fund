from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from unittest.mock import Mock

import pytest

from src.screening.offensive.daily_action import DailyActionScan, scan_from_verified_snapshot
from src.screening.offensive.daily_action_readiness import (
    BOARD_RULE_VERSION,
    DAILY_ACTION_READINESS_SCHEMA_VERSION,
    NORMALIZATION_VERSION,
    READINESS_POLICY_VERSION,
    DailyActionReadinessManifest,
    DailyActionTickerReadiness,
    SharedReadinessEvidence,
    SuspensionReadinessEvidence,
    _fingerprint,
)
from src.screening.offensive.daily_action_snapshot import FrozenFlowRow, FrozenPriceRow, VerifiedDailyActionSnapshot
from src.screening.offensive.readiness_reference import ReferenceProvenance
from src.screening.offensive.setups.base import DetectionResult
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setup_data_contracts import SETUP_REQUIREMENTS_VERSION, SetupCapability
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION

SIGNAL_DATE = date(2026, 7, 13)
CONSUMED_FP = "sha256:" + "a" * 64
SNAPSHOT_ID = "sha256:" + "b" * 64
CONTENT_FP = "sha256:" + "c" * 64
INPUT_FP = "sha256:" + "d" * 64
UNIVERSE_FP = "sha256:" + "e" * 64
SUSPENSION_FP = "sha256:" + "f" * 64


def _shared_evidence(ticker: str = "300001") -> SharedReadinessEvidence:
    regime_row = {"trade_date": SIGNAL_DATE.isoformat(), "regime": "normal"}
    industry_by_ticker = {ticker: "software"}
    industry_day_pct = {ticker: 3.2}
    security_status_by_ticker = {ticker: "listed"}
    security_reference = ReferenceProvenance.create(
        observed_on=SIGNAL_DATE,
        effective_from=SIGNAL_DATE,
        effective_through=SIGNAL_DATE,
        source="tushare.stock_basic",
        version="test-stock-basic-v1",
        content_fingerprint=_fingerprint({"security": ticker}),
    )
    sw_reference = ReferenceProvenance.create(
        observed_on=SIGNAL_DATE,
        effective_from=SIGNAL_DATE,
        effective_through=SIGNAL_DATE,
        source="tushare.index_classify+index_member",
        version="test-sw-v1",
        content_fingerprint=_fingerprint({"sw": ticker}),
    )
    return SharedReadinessEvidence(
        as_of_date=SIGNAL_DATE,
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "regime_row": regime_row}),
        industry_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "industry_by_ticker": industry_by_ticker, "industry_day_pct": industry_day_pct}),
        security_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "security_status_by_ticker": security_status_by_ticker}),
        security_reference=security_reference,
        sw_reference=sw_reference,
        frozen_source_fingerprint=_fingerprint({"frozen": ticker}),
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _capability(*, plan_eligible: bool = True, degraded: bool = False, warnings: tuple[str, ...] = ()) -> SetupCapability:
    return SetupCapability(
        enabled=True,
        scannable=True,
        plan_eligible=plan_eligible,
        degraded=degraded,
        block_reasons=() if plan_eligible else ("fund_flow_history_short",),
        warnings=warnings,
        consumed_fingerprint=CONSUMED_FP,
    )


def _disabled_capability() -> SetupCapability:
    return SetupCapability(
        enabled=False,
        scannable=False,
        plan_eligible=False,
        degraded=False,
        block_reasons=("setup_disabled_by_default",),
        warnings=(),
        consumed_fingerprint=None,
    )


def _manifest(ticker: str = "300001", *, capability: SetupCapability | None = None) -> DailyActionReadinessManifest:
    return DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain="daily_action",
        run_id="task7test",
        trade_date=SIGNAL_DATE,
        created_at="2026-07-13T12:00:00+00:00",
        status="healthy",
        universe_kind="resolved_refresh_universe",
        universe_tickers=(ticker,),
        universe_fingerprint=UNIVERSE_FP,
        input_fingerprint=INPUT_FP,
        suspension_evidence=SuspensionReadinessEvidence("available_empty", (), SUSPENSION_FP),
        ticker_readiness=MappingProxyType(
            {
                ticker: DailyActionTickerReadiness(
                    evidence_status="verified",
                    capabilities=MappingProxyType(
                        {
                            "btst_breakout": capability or _capability(),
                            "oversold_bounce": _disabled_capability(),
                        }
                    ),
                )
            }
        ),
        warnings=(),
        shared_evidence=_shared_evidence(ticker),
        policy_versions=MappingProxyType(
            {
                "readiness_policy": READINESS_POLICY_VERSION,
                "normalization": NORMALIZATION_VERSION,
                "board_rule": BOARD_RULE_VERSION,
                "setup_requirements": SETUP_REQUIREMENTS_VERSION,
                "signal_session_cutoff": SIGNAL_SESSION_POLICY_VERSION,
            }
        ),
        content_fingerprint=CONTENT_FP,
    )


def _prices() -> tuple[FrozenPriceRow, ...]:
    rows: list[FrozenPriceRow] = []
    for index in range(22):
        session = SIGNAL_DATE - timedelta(days=21 - index)
        close = Decimal("10")
        pct = Decimal("0")
        if index == 16:
            close = Decimal("10.5")
        if index == 21:
            close = Decimal("11")
            pct = Decimal("10")
        rows.append(
            FrozenPriceRow(
                trade_date=session,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("1000000"),
                pct_change=pct,
            )
        )
    return tuple(rows)


def _flows() -> tuple[FrozenFlowRow, ...]:
    return tuple(
        FrozenFlowRow(
            trade_date=SIGNAL_DATE - timedelta(days=offset),
            close=Decimal("11"),
            pct_change=Decimal("0"),
            main_net_inflow=Decimal("1000000"),
        )
        for offset in range(3)
    )


def _snapshot(ticker: str = "300001", *, capability: SetupCapability | None = None, ticker_blocks: dict[str, tuple[str, ...]] | None = None, regime: str = "normal") -> VerifiedDailyActionSnapshot:
    manifest = _manifest(ticker, capability=capability)
    return VerifiedDailyActionSnapshot(
        signal_date=SIGNAL_DATE,
        snapshot_id=SNAPSHOT_ID,
        manifest=manifest,
        universe_tickers=(ticker,),
        prices_by_ticker=MappingProxyType({ticker: _prices()}),
        fund_flow_by_ticker=MappingProxyType({ticker: _flows()}),
        industry_day_pct_by_ticker=MappingProxyType({ticker: 3.2}),
        regime=regime,
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        setup_requirements_version=SETUP_REQUIREMENTS_VERSION,
        ticker_blocks=MappingProxyType(ticker_blocks or {}),
        consumed_fingerprint_by_ticker=MappingProxyType({ticker: MappingProxyType({"btst_breakout": CONSUMED_FP})}),
    )


def hit_result(*, degraded: bool = False) -> DetectionResult:
    return DetectionResult(
        hit=True,
        ticker="300001",
        trade_date=SIGNAL_DATE.strftime("%Y%m%d"),
        trigger_strength=0.90,
        invalidation_condition="price below trigger close",
        metadata={"range_based_stop_pct": -0.08},
        degraded=degraded,
        degradation_reason="detector skipped a required condition" if degraded else "",
    )


def test_empty_snapshot_returns_empty_scan() -> None:
    snapshot = _snapshot(ticker_blocks={"300001": ("fingerprint_mismatch",)})

    scan = scan_from_verified_snapshot(snapshot)

    assert isinstance(scan, DailyActionScan)
    assert scan.signal_date == SIGNAL_DATE
    assert scan.candidates == ()
    assert scan.blocked_candidates == ()


def test_manifest_degraded_capability_is_display_only_before_detector(monkeypatch) -> None:
    detector = Mock(return_value=hit_result())
    monkeypatch.setattr(BtstBreakoutSetup, "detect", detector)
    capability = _capability(plan_eligible=False, degraded=True, warnings=("fund_flow_history_short",))

    scan = scan_from_verified_snapshot(_snapshot(capability=capability))

    assert scan.candidates == ()
    assert len(scan.blocked_candidates) == 1
    assert scan.blocked_candidates[0].ticker == "300001"
    assert scan.blocked_candidates[0].reason == "candidate_not_plan_eligible"
    detector.assert_not_called()


def test_detector_degraded_hit_is_display_only(monkeypatch) -> None:
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result(degraded=True))

    scan = scan_from_verified_snapshot(_snapshot())

    assert scan.candidates == ()
    assert len(scan.blocked_candidates) == 1
    assert scan.blocked_candidates[0].reason == "detector_degraded"


def test_regime_gate_blocks_new_entries_on_crisis_and_risk_off(monkeypatch) -> None:
    """regime gate 守卫 (2026-08-14 R-5.F 接线): 信号日 crisis/risk_off 不开新仓.

    证据: 诚实 court (2026H1) crisis/risk_off 胜率 8-9% 灾难, gated BTST-only
    NAV 1.430 vs ungated 1.133; 跨期 2025H2 gated 51.4%/+3.97% vs ungated
    50.0%/+3.71% (牛市零成本). 被闸票进 blocked (带 trigger_strength),
    面板继续积累危机日对照组.
    """
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())

    for regime in ("crisis", "risk_off"):
        scan = scan_from_verified_snapshot(_snapshot(regime=regime))
        assert scan.candidates == (), f"{regime}: 不应产生候选"
        assert len(scan.blocked_candidates) == 1
        assert scan.blocked_candidates[0].reason == "regime_gate_halt"
        assert scan.blocked_candidates[0].trigger_strength == 0.90


def test_regime_gate_passes_normal_regime(monkeypatch) -> None:
    """normal regime 不受 gate 影响 — 候选正常产出."""
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())

    scan = scan_from_verified_snapshot(_snapshot(regime="normal"))

    assert len(scan.candidates) == 1
    assert scan.blocked_candidates == ()


def test_candidate_carries_structured_snapshot_provenance(monkeypatch) -> None:
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())

    scan = scan_from_verified_snapshot(_snapshot())

    assert len(scan.candidates) == 1
    candidate = scan.candidates[0]
    assert candidate.signal_date == SIGNAL_DATE
    assert candidate.snapshot_id == SNAPSHOT_ID
    assert candidate.setup_consumed_fingerprint == CONSUMED_FP
    assert candidate.detector_degraded is False
    assert candidate.target_weight == pytest.approx(0.09)
    assert scan.reference_prices == (("300001", 11.0),)


def test_scanner_never_reopens_cache_files(monkeypatch) -> None:
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())
    monkeypatch.setattr("pandas.read_csv", Mock(side_effect=AssertionError("scanner reopened cache file")))

    scan = scan_from_verified_snapshot(_snapshot())

    assert len(scan.candidates) == 1


def test_scanner_is_deterministic_after_runtime_setup_env_changes(monkeypatch) -> None:
    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: hit_result(),
    )
    snapshot = _snapshot()

    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "btst_breakout")
    disabled_scan = scan_from_verified_snapshot(snapshot)
    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "none")
    enabled_scan = scan_from_verified_snapshot(snapshot)

    assert disabled_scan == enabled_scan
    assert len(disabled_scan.candidates) == 1


# ---------------------------------------------------------------------------
# R191 Op1: 漏斗就绪门拦截通道命名 — 宇宙→扫描之间的静默通道必须有名字.
# scannable_tickers 在验证拒绝之外还有两道过滤 (manifest 成员资格/无 scannable
# 能力), 此前这批票无痕消失, 闭合格式算术不闭合 (2026-09-12 实录: 1991→1912
# 差 79 = st_stock 70 / suspended 8 / price_missing_unexplained 1).
# ---------------------------------------------------------------------------


def _blocked_capability(*reasons: str) -> SetupCapability:
    return SetupCapability(
        enabled=True,
        scannable=False,
        plan_eligible=False,
        degraded=False,
        block_reasons=reasons,
        warnings=(),
        consumed_fingerprint=CONSUMED_FP,
    )


def _multi_manifest(
    universe: tuple[str, ...],
    readiness: dict[str, tuple[tuple[str, SetupCapability], ...]],
) -> DailyActionReadinessManifest:
    """多票 manifest: readiness 缺席的 universe 票 = not_in_readiness 通道."""
    ticker_readiness = {}
    for ticker, caps in readiness.items():
        ticker_readiness[ticker] = DailyActionTickerReadiness(
            evidence_status="verified"
            if any(cap.scannable for _, cap in caps)
            else "blocked",
            capabilities=MappingProxyType(dict(caps)),
        )
    return DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain="daily_action",
        run_id="task7test",
        trade_date=SIGNAL_DATE,
        created_at="2026-07-13T12:00:00+00:00",
        status="healthy",
        universe_kind="resolved_refresh_universe",
        universe_tickers=universe,
        universe_fingerprint=UNIVERSE_FP,
        input_fingerprint=INPUT_FP,
        suspension_evidence=SuspensionReadinessEvidence("available_empty", (), SUSPENSION_FP),
        ticker_readiness=MappingProxyType(ticker_readiness),
        warnings=(),
        shared_evidence=_shared_evidence(universe[0]),
        policy_versions=MappingProxyType(
            {
                "readiness_policy": READINESS_POLICY_VERSION,
                "normalization": NORMALIZATION_VERSION,
                "board_rule": BOARD_RULE_VERSION,
                "setup_requirements": SETUP_REQUIREMENTS_VERSION,
                "signal_session_cutoff": SIGNAL_SESSION_POLICY_VERSION,
            }
        ),
        content_fingerprint=CONTENT_FP,
    )


def _multi_snapshot(
    universe: tuple[str, ...],
    readiness: dict[str, tuple[tuple[str, SetupCapability], ...]],
    ticker_blocks: dict[str, tuple[str, ...]] | None = None,
) -> VerifiedDailyActionSnapshot:
    manifest = _multi_manifest(universe, readiness)
    scannable = [
        ticker
        for ticker in universe
        if ticker in readiness
        and any(cap.scannable for _, cap in readiness[ticker])
    ]
    return VerifiedDailyActionSnapshot(
        signal_date=SIGNAL_DATE,
        snapshot_id=SNAPSHOT_ID,
        manifest=manifest,
        universe_tickers=universe,
        prices_by_ticker=MappingProxyType({t: _prices() for t in universe}),
        fund_flow_by_ticker=MappingProxyType({t: _flows() for t in universe}),
        industry_day_pct_by_ticker=MappingProxyType({t: 3.2 for t in universe}),
        regime="normal",
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        setup_requirements_version=SETUP_REQUIREMENTS_VERSION,
        ticker_blocks=MappingProxyType(ticker_blocks or {}),
        consumed_fingerprint_by_ticker=MappingProxyType(
            {t: MappingProxyType({"btst_breakout": CONSUMED_FP}) for t in scannable}
        ),
    )


def test_funnel_counts_readiness_gate_exclusions_with_reasons(monkeypatch) -> None:
    """就绪门拦截票 (st_stock/suspended) 计数且按原因分桶 — 20260911 形态."""
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())
    universe = ("300001", "300002", "300003")
    readiness = {
        "300001": (
            ("btst_breakout", _capability()),
            ("oversold_bounce", _disabled_capability()),
        ),
        "300002": (
            ("btst_breakout", _blocked_capability("st_stock")),
            ("oversold_bounce", _disabled_capability()),
        ),
        "300003": (
            ("btst_breakout", _blocked_capability("suspended")),
            ("oversold_bounce", _disabled_capability()),
        ),
    }

    scan = scan_from_verified_snapshot(_multi_snapshot(universe, readiness))
    funnel = scan.funnel
    assert funnel is not None
    assert funnel.universe == 3
    assert funnel.verify_blocked == 0
    assert funnel.readiness_excluded == 2
    assert funnel.readiness_miss_stages == {"st_stock": 1, "suspended": 1}
    assert funnel.scannable == 1
    # 漏斗算术闭合: 宇宙 = 验证 + 永久 + 数据 + 就绪 + 计划不合格 + 扫描
    assert (
        funnel.universe
        == funnel.verify_blocked
        + funnel.excluded_permanent
        + funnel.data_rejected
        + funnel.readiness_excluded
        + funnel.not_plan_eligible
        + funnel.scannable
    )


def test_funnel_readiness_exclusion_not_in_readiness_channel(monkeypatch) -> None:
    """universe 在场但 manifest 无 readiness 的票 → not_in_readiness 桶."""
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())
    universe = ("300001", "300004")
    readiness = {
        "300001": (
            ("btst_breakout", _capability()),
            ("oversold_bounce", _disabled_capability()),
        ),
    }

    scan = scan_from_verified_snapshot(_multi_snapshot(universe, readiness))
    funnel = scan.funnel
    assert funnel.readiness_excluded == 1
    assert funnel.readiness_miss_stages == {"not_in_readiness": 1}


def test_funnel_readiness_exclusion_no_enabled_setup_channel(monkeypatch) -> None:
    """在场但全部 setup 被 policy 禁用的票 → no_enabled_setup 桶 (非数据原因)."""
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())
    universe = ("300001", "300005")
    readiness = {
        "300001": (
            ("btst_breakout", _capability()),
            ("oversold_bounce", _disabled_capability()),
        ),
        "300005": (
            ("btst_breakout", _disabled_capability()),
            ("oversold_bounce", _disabled_capability()),
        ),
    }

    scan = scan_from_verified_snapshot(_multi_snapshot(universe, readiness))
    funnel = scan.funnel
    assert funnel.readiness_excluded == 1
    assert funnel.readiness_miss_stages == {"no_enabled_setup": 1}


def test_funnel_readiness_exclusion_multi_reason_joined_sorted(monkeypatch) -> None:
    """同票多原因按排序 + 号连接成桶 — 每票恰计一次, 分桶和 = 拦截总数."""
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())
    universe = ("300001", "300006")
    readiness = {
        "300001": (
            ("btst_breakout", _capability()),
            ("oversold_bounce", _disabled_capability()),
        ),
        "300006": (
            ("btst_breakout", _blocked_capability("suspended", "st_stock")),
            ("oversold_bounce", _disabled_capability()),
        ),
    }

    scan = scan_from_verified_snapshot(_multi_snapshot(universe, readiness))
    funnel = scan.funnel
    assert funnel.readiness_excluded == 1
    assert funnel.readiness_miss_stages == {"st_stock+suspended": 1}
    assert sum(funnel.readiness_miss_stages.values()) == funnel.readiness_excluded


def test_funnel_counts_plan_eligible_blocks(monkeypatch) -> None:
    """plan_eligible 拦截通道计数 — 此前只进 blocked 列表, 漏斗头算术断链."""
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())

    scan = scan_from_verified_snapshot(
        _snapshot(capability=_capability(plan_eligible=False))
    )
    funnel = scan.funnel
    assert funnel is not None
    assert funnel.not_plan_eligible == 1
    assert funnel.scannable == 0
    assert funnel.readiness_excluded == 0
    assert (
        funnel.universe
        == funnel.verify_blocked
        + funnel.excluded_permanent
        + funnel.data_rejected
        + funnel.readiness_excluded
        + funnel.not_plan_eligible
        + funnel.scannable
    )


def test_funnel_single_ticker_identity_closes(monkeypatch) -> None:
    """单票健康世界: 恒等式逐项为零断言 — 防未来通道再度静默."""
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())

    scan = scan_from_verified_snapshot(_snapshot())
    funnel = scan.funnel
    assert funnel.universe == 1
    assert funnel.verify_blocked == 0
    assert funnel.excluded_permanent == 0
    assert funnel.data_rejected == 0
    assert funnel.readiness_excluded == 0
    assert funnel.not_plan_eligible == 0
    assert funnel.scannable == 1


def test_funnel_blocked_ticker_not_double_counted(monkeypatch) -> None:
    """R191 Op2 P02 盲区钉: 验证拒绝票不得再计入就绪拦截 — 每票恰一个去处."""
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())
    universe = ("300001", "300002")
    readiness = {
        "300001": (
            ("btst_breakout", _capability()),
            ("oversold_bounce", _disabled_capability()),
        ),
        "300002": (
            ("btst_breakout", _capability()),
            ("oversold_bounce", _disabled_capability()),
        ),
    }

    scan = scan_from_verified_snapshot(
        _multi_snapshot(universe, readiness, ticker_blocks={"300002": ("fingerprint_mismatch",)})
    )
    funnel = scan.funnel
    assert funnel.verify_blocked == 1
    assert funnel.readiness_excluded == 0
    assert funnel.readiness_miss_stages == {}
    assert funnel.scannable == 1
    assert (
        funnel.universe
        == funnel.verify_blocked
        + funnel.excluded_permanent
        + funnel.data_rejected
        + funnel.readiness_excluded
        + funnel.not_plan_eligible
        + funnel.scannable
    )


def test_funnel_same_reason_accumulates_across_tickers(monkeypatch) -> None:
    """R191 Op2 P08 盲区钉: 同原因多票累积计数 — 覆盖写 1 即回归."""
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())
    universe = ("300001", "300002", "300003", "300007")
    readiness = {
        "300001": (
            ("btst_breakout", _capability()),
            ("oversold_bounce", _disabled_capability()),
        ),
        "300002": (
            ("btst_breakout", _blocked_capability("st_stock")),
            ("oversold_bounce", _disabled_capability()),
        ),
        "300003": (
            ("btst_breakout", _blocked_capability("st_stock")),
            ("oversold_bounce", _disabled_capability()),
        ),
        "300007": (
            ("btst_breakout", _blocked_capability("suspended")),
            ("oversold_bounce", _disabled_capability()),
        ),
    }

    scan = scan_from_verified_snapshot(_multi_snapshot(universe, readiness))
    funnel = scan.funnel
    assert funnel.readiness_excluded == 3
    assert funnel.readiness_miss_stages == {"st_stock": 2, "suspended": 1}
    assert sum(funnel.readiness_miss_stages.values()) == funnel.readiness_excluded
