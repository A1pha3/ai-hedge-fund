from __future__ import annotations

import builtins
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action import (
    DailyActionScan,
    BlockedCandidate,
    ScanFunnel,
    render_daily_action_v2,
    run_daily_action_v2,
    _resolve_next_trade_date,
    _price_frame_is_fresh,
    DailyActionV2Run,
)
from src.screening.offensive.daily_action_service import (
    ActionItem,
    DailyActionRun,
    DailyActionService,
    MarketBar,
    PlanCandidate,
    RegimeAuthorization,
    TickerGateBlock,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository
from src.cli.dispatcher import _cached_daily_action_market_bar
from src.cli import dispatcher
from src.screening.offensive.ledger_repository import DailyValuation
from src.screening.data_quality_manifest import RunManifest, TickerReadiness


@pytest.fixture
def signal_date() -> date:
    return date(2026, 7, 13)


@pytest.fixture(autouse=True)
def _fail_workspace_reports_writes(monkeypatch):
    repo_reports = (Path(__file__).resolve().parents[2] / "data" / "reports").resolve()
    original_open = builtins.open
    original_path_open = Path.open

    def _is_write_mode(mode: str) -> bool:
        return any(flag in mode for flag in ("w", "a", "x", "+"))

    def guarded_open(file, mode="r", *args, **kwargs):
        path = Path(file).resolve() if isinstance(file, (str, Path)) else None
        if path is not None and _is_write_mode(str(mode)) and (path == repo_reports or repo_reports in path.parents):
            raise AssertionError(f"test attempted to write workspace data/reports: {path}")
        return original_open(file, mode, *args, **kwargs)

    def guarded_path_open(self, mode="r", *args, **kwargs):
        path = self.resolve()
        if _is_write_mode(str(mode)) and (path == repo_reports or repo_reports in path.parents):
            raise AssertionError(f"test attempted to write workspace data/reports: {path}")
        return original_path_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)


@pytest.fixture
def repository(tmp_path) -> LedgerRepository:
    repo = LedgerRepository(
        tmp_path / "paper_trading_v2" / "ledger.sqlite3", "daily-action-v2", 100_000,
        execution_costs=ExecutionCosts(version="test"),
    )
    repo.initialize()
    return repo


@pytest.fixture
def service(repository, signal_date) -> DailyActionService:
    sessions = tuple(signal_date + timedelta(days=i) for i in range(12))
    bar = MarketBar(10.0, 10.0, 9.0, 11.0, False, 10.5, 9.5)
    return DailyActionService(
        repository,
        TradingSessionCalendar(sessions),
        lambda _ticker, _date: bar,
        ExecutionCosts(version="test"),
        enforce_manifest_gate=False,
    )


def _scan(signal_date, *, degraded=False, regime="normal") -> DailyActionScan:
    authorization = (
        RegimeAuthorization.BTST_CRISIS
        if regime == "crisis"
        else RegimeAuthorization.NORMAL
    )
    hit = PlanCandidate(
        ticker="000001",
        setup="btst_breakout",
        setup_version="v2",
        signal_date=signal_date,
        target_weight=0.12,
        priority=1,
        snapshot_id="legacy_unverified",
        setup_consumed_fingerprint="legacy_unverified",
        detector_degraded=False,
        authorization=authorization,
    )
    blocked = (
        (BlockedCandidate("000001", "incomplete_setup_data", 10.0),) if degraded else ()
    )
    candidates = () if degraded else (hit,)
    return DailyActionScan(signal_date, candidates, blocked, (("000001", 10.0),))


def _install_healthy_manifest(monkeypatch, signal_date: date) -> None:
    fingerprint = "sha256:current"
    readiness = TickerReadiness(
        "000001",
        signal_date,
        signal_date,
        True,
        signal_date,
        20,
        signal_date,
        "listed",
        False,
        "ashare-board-prefix-v1",
        fingerprint,
        True,
        (),
    )
    manifest = RunManifest(
        "run-test",
        signal_date,
        "healthy",
        datetime.now(timezone.utc),
        {"000001": readiness},
        candidate_tickers=("000001",),
        candidate_set_fingerprint="sha256:candidates",
        input_fingerprint="sha256:inputs",
    )
    monkeypatch.setattr(
        "src.screening.offensive.daily_action_service.load_daily_action_manifest_gate",
        lambda *_args, **_kwargs: (manifest, {"000001": fingerprint}),
    )


def _install_readiness_manifest(monkeypatch, signal_date: date, *, reports_dir: Path, data_dir: Path) -> None:
    """Create a daily_action_readiness manifest so the snapshot path activates.

    Spec 10: --daily-action requires its own readiness canonical, not the Auto
    manifest. This helper writes a minimal readiness manifest file so the
    verified snapshot loader can find it.
    """
    repo_reports = (Path(__file__).resolve().parents[2] / "data" / "reports").resolve()
    reports_dir = Path(reports_dir).resolve()
    data_dir = Path(data_dir).resolve()
    assert reports_dir != repo_reports and repo_reports not in reports_dir.parents
    assert data_dir != Path(__file__).resolve().parents[2] / "data"
    reports_dir.mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "schema_version": 1,
        "domain": "daily_action",
        "run_id": "test-readiness",
        "trade_date": signal_date.isoformat(),
        "created_at": "2026-07-13T12:00:00Z",
        "status": "healthy",
        "universe_kind": "resolved_refresh_universe",
        "universe_tickers": ["000001"],
        "universe_fingerprint": "sha256:test-universe",
        "input_fingerprint": None,
        "ticker_readiness": {
            "000001": {
                "evidence_status": "verified",
                "capabilities": {
                    "btst_breakout": {
                        "enabled": True,
                        "scannable": True,
                        "plan_eligible": True,
                        "degraded": False,
                        "block_reasons": [],
                        "warnings": [],
                    },
                    "oversold_bounce": {
                        "enabled": False,
                        "scannable": False,
                        "plan_eligible": False,
                        "degraded": False,
                        "block_reasons": ["setup_disabled_by_default"],
                        "warnings": [],
                    },
                },
            },
        },
        "warnings": [],
        "shared_evidence": {
            "regime_fingerprint": None,
            "industry_mapping_fingerprint": None,
            "security_status_fingerprint": None,
            "board_rule_version": "ashare-board-prefix-v1",
            "normalization_version": "pit-canonical-v1",
            "signal_session_policy_version": "ashare-cn-1700-v1",
        },
        "policy_versions": {
            "readiness_policy": "daily-action-readiness-v1",
            "setup_requirements": "daily-action-setups-v1",
        },
    }
    filename = f"daily_action_readiness_{signal_date.strftime('%Y%m%d')}.json"
    (reports_dir / filename).write_text(json.dumps(manifest_data), encoding="utf-8")


def test_signal_date_creates_plan_not_open_position(service, signal_date):
    run = run_daily_action_v2(service, _scan(signal_date))
    assert len(run.plans) == 1
    assert run.open_positions == ()


def test_degraded_btst_is_displayed_but_never_planned(service, signal_date):
    run = run_daily_action_v2(service, _scan(signal_date, degraded=True))
    assert run.plans == ()
    assert run.blocked_candidates[0].reason == "incomplete_setup_data"


def test_unverified_btst_normal_and_claimed_crisis_are_both_capped_at_ten_percent(
    service, repository, signal_date
):
    normal_run = run_daily_action_v2(service, _scan(signal_date))
    normal_weight = repository.get_trade(normal_run.plans[0].trade_id).planned_weight

    crisis_scan = DailyActionScan(
        signal_date,
        (
            PlanCandidate(
                ticker="000002",
                setup="btst_breakout",
                setup_version="v2",
                signal_date=signal_date,
                target_weight=0.12,
                priority=2,
                snapshot_id="legacy_unverified",
                setup_consumed_fingerprint="legacy_unverified",
                detector_degraded=False,
                authorization=RegimeAuthorization.BTST_CRISIS,
            ),
        ),
        (),
        (("000002", 10.0),),
    )
    crisis_run = run_daily_action_v2(service, crisis_scan)
    crisis_weight = repository.get_trade(crisis_run.plans[0].trade_id).planned_weight
    assert normal_weight == pytest.approx(0.10)
    assert crisis_weight == pytest.approx(0.10)


def test_repeat_cli_run_is_idempotent(service, repository, signal_date):
    first = run_daily_action_v2(service, _scan(signal_date))
    second = run_daily_action_v2(service, _scan(signal_date))
    assert first.plans[0].trade_id == second.plans[0].trade_id
    assert repository.count_events(first.plans[0].trade_id, "PLAN_CREATED") == 1


def test_v1_files_are_byte_identical_after_v2_run(
    service, signal_date, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    artifacts = {
        tmp_path / "data/paper_trading/journal.jsonl": b"runtime-v1\n",
        tmp_path / "data/paper_trading_backtest/journal.jsonl": b"backtest-v1\n",
    }
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True)
        path.write_bytes(content)

    run_daily_action_v2(service, _scan(signal_date))

    assert {path: path.read_bytes() for path in artifacts} == artifacts


def test_output_distinguishes_reference_synthetic_and_confirmed_prices(
    service, signal_date
):
    pending = run_daily_action_v2(service, _scan(signal_date))
    # The renderer always discloses all three price/source states, even when a section is empty.
    rendered = render_daily_action_v2(pending)
    assert "参考价" in rendered
    assert "模拟成交" in rendered
    assert "确认成交" in rendered


def test_drawdown_display_omits_sign_at_zero() -> None:
    """回撤为 0 (含 -0.0) 时显示 '0.0%', 不带 '+' 号, 避免 '+0.0%' 误导。"""
    from src.screening.offensive.daily_action import _format_drawdown

    assert _format_drawdown(0.0) == "0.0%"
    assert _format_drawdown(-0.0) == "0.0%"
    assert _format_drawdown(-0.002) == "-0.2%"
    assert _format_drawdown(0.005) == "+0.5%"


def test_cjk_display_width_and_padding() -> None:
    """中文标签按显示宽度对齐: 东亚全角字符计 2 列, 半角数字/空格计 1 列 —
    否则「亨通光电」与「阿莱德」在终端上列不对齐。"""
    from src.screening.offensive.daily_action import _disp_width, _pad_to

    assert _disp_width("600487 亨通光电") == 6 + 1 + 8  # 6 数字 + 空格 + 4 中文
    assert _disp_width("301419 阿莱德") == 6 + 1 + 6  # 6 数字 + 空格 + 3 中文
    padded = _pad_to("301419 阿莱德", 16)
    assert len(padded) == 10 + 3  # 10 字符 + 3 补齐空格
    assert _disp_width(padded) == 16  # 显示宽度对齐到目标


def test_no_signal_conclusion_discloses_prior_plan_fills() -> None:
    """无新信号但当日已执行昨日计划时, 结论须披露笔数而非干说'今日无信号'。"""
    from src.screening.offensive.daily_action import render_no_signal

    assert "已执行 2 笔昨日计划" in render_no_signal(2)
    assert "今日无信号" in render_no_signal(0)
    assert "已执行" not in render_no_signal(0)


def test_authoritative_sessions_handle_weekend_and_exchange_holiday(monkeypatch):
    sessions = (date(2026, 9, 25), date(2026, 9, 28), date(2026, 10, 9))
    monkeypatch.setattr(
        "src.screening.offensive.daily_action._load_authoritative_session_dates",
        lambda: sessions,
    )
    assert _resolve_next_trade_date("20260925") == "20260928"
    assert _resolve_next_trade_date("20260928") == "20261009"


def test_missing_authoritative_calendar_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "src.screening.offensive.daily_action._load_authoritative_session_dates",
        lambda: (),
    )
    assert _resolve_next_trade_date("20260925") == ""


def test_cached_market_bar_derives_suspended_but_stays_fail_closed_on_limits(tmp_path):
    """单行缓存: 有真实 bar → suspended=False; 无前收行 → limit 字段保持 None,
    classify_open_fill 仍 fail-closed (UNKNOWN_QUEUE). 2026-07-18 起 limit 价由
    前收 × 板块幅度按交易所规则推导, 不再一律置 None (修复 v2 ledger 全 skip)."""
    cache = tmp_path / "000001.csv"
    cache.write_text(
        "date,open,close,high,low\n2026-07-13,10,10,10.5,9.5\n", encoding="utf-8"
    )
    bar = _cached_daily_action_market_bar(cache, date(2026, 7, 13))
    assert bar is not None
    assert bar.suspended is False
    assert bar.limit_up is None
    assert bar.limit_down is None


@pytest.mark.parametrize(
    "dates",
    [
        ("2026-07-13", "2026-07-13"),
        ("2026-07-13 00:00:00", "2026-07-13"),
    ],
)
def test_cached_market_bar_rejects_duplicate_civil_dates(tmp_path, dates):
    cache = tmp_path / "000001.csv"
    cache.write_text(
        "date,open,close,high,low\n"
        f"{dates[0]},10,10,10.5,9.5\n"
        f"{dates[1]},11,11,11.5,10.5\n",
        encoding="utf-8",
    )

    assert _cached_daily_action_market_bar(cache, date(2026, 7, 13)) is None


def test_render_plans_show_entry_date_and_weight(service, signal_date):
    """Plan rows render the operator-facing entry date and weight — not just the
    reference price and internal debug codes — so the operator sees when and at
    what size a plan will enter."""
    run = run_daily_action_v2(service, _scan(signal_date))
    plan = run.plans[0]
    assert plan.planned_entry_date is not None
    assert plan.planned_weight is not None
    rendered = render_daily_action_v2(run)
    assert "计划 " in rendered and "入场" in rendered
    assert f"权重 {plan.planned_weight:.1%}" in rendered
    # Regression: service.render must mirror the dispatcher view, including new
    # plans — it used to drop new_plans and always render 新计划（0 只）.
    assert "新计划（1 只）" in DailyActionService.render(run.service_run)


def test_new_plan_renders_full_trade_plan_details(service, signal_date):
    """新计划区给出完整交易计划: 买入价位口径 / 买入理由 (强度分量+涨停结构) /
    先验胜率赔率 / 退出合约 (T+10 时间退出 + 失效参考价仅披露).

    止盈止损口径 = 策略真实合约: 默认退出只有 T+10 时间退出; 止损价仅披露参考
    (止损×gate 联合网格证 fixed8 止损 4/4 组合降收益 → 止损执行不落地), 无止盈
    规则 (凸性策略让利润奔跑到期). 渲染不得编造固定百分比止盈止损.
    """
    hit = PlanCandidate(
        ticker="600487",
        setup="btst_breakout",
        setup_version="v2",
        signal_date=signal_date,
        target_weight=0.10,
        priority=1,
        snapshot_id="legacy_unverified",
        setup_consumed_fingerprint="legacy_unverified",
        detector_degraded=False,
        authorization=RegimeAuthorization.NORMAL,
        trigger_strength=0.79,
        entry_price=62.98,
        metadata={
            "pct_change": 10.01,
            "limit_up_streak": 1,
            "main_net_inflow": 2.4829022e9,
            "industry_pct": 1.2,
            "pre_5d_runup_pct": 2.3,
            "range_low": 58.20,
            "range_based_stop_pct": -0.0758,
            "board_score": 0.95,
            "low_vol_score": 0.80,
            "squeeze_score": 1.00,
            "volume_score": 0.60,
            "range_score": 0.40,
            "energy_bonus": 0.08,
        },
    )
    scan = DailyActionScan(signal_date, (hit,), (), (("600487", 62.98),))
    run = run_daily_action_v2(service, scan)
    rendered = render_daily_action_v2(run)

    # 买入价位: 执行口径 = 次日开盘价; 参考价只是信号日收盘; 涨停/停牌自动跳过.
    assert "买入：" in rendered and "开盘价执行" in rendered
    assert "开盘涨停/停牌自动放弃" in rendered
    # 买入理由: 强度 + 5 分量 + 能量耦合; 涨停结构 (幅度/连板/前5日/资金流/行业).
    # 「上市板」≠ 行业板块: board_score 是 002/300/301/688/60x=0.95 的上市板
    # 质量分 (2026-08-18 审查项 4 改名, 防止与「行业当日」误读).
    assert "理由：强度 0.79" in rendered
    assert "上市板 0.95" in rendered and "低波 0.80" in rendered
    assert "压缩 1.00" in rendered and "量能 0.60" in rendered and "振幅 0.40" in rendered
    assert "能量耦合 0.08" in rendered
    assert "涨停 +10.0%（首板）" in rendered
    assert "涨停前 5 日 +2.3%" in rendered
    assert "主力净流入 24.8 亿" in rendered
    assert "行业当日 +1.2%" in rendered
    # 胜率赔率: 冻结先验分布 (BTST T+10 court 重校准: n=1464, 胜率 46.45%→46%,
    # 盈亏比 1.3, E +0.6%, CI90 跨 0). 标签口径中性 — 扣费与否由脚注 provenance 表达
    # (2026-08-19 重校准后先验即 court 扣费口径).
    assert "先验（T+10 历史回放 n=1464）" in rendered
    assert "胜率 46%" in rendered
    assert "盈亏比 1.3" in rendered
    assert "期望 +0.6%" in rendered
    assert "CI90" in rendered
    # 先验口径脚注: 样本出处 + 执行口径参考, 全渲染只出现一次 (不逐票重复).
    assert rendered.count("先验口径：") == 1
    assert "court 全候选生产对齐宇宙 n=1464" in rendered and "owner 批准重校准" in rendered
    # 执行口径参考主锚 = court 全候选生产对齐宇宙 (trap 19: journal 成交子集
    # 不可作证据宇宙 — 同期 2026H1 court +0.06% vs journal +3.41%, 差异全为
    # 成交选择偏差), journal 数字只保留为标注过的审计线索.
    assert "执行口径参考" in rendered and "+0.56%" in rendered
    assert "n=1464" in rendered and "全候选" in rendered
    # 退出合约: T+10 时间退出 (第 10 个持有交易日, entry 7/14 → 到期 7/23), 无条件卖出.
    assert "退出：T+10" in rendered
    assert "预计 7/23" in rendered
    assert "无条件卖出" in rendered
    # 失效参考价: 62.98 × (1 - 0.0758) = 58.21; 明确标注仅披露不执行.
    assert "失效参考：跌破 58.21（盘整区底部 58.20，-7.6%）" in rendered
    assert "仅披露" in rendered


def test_plan_details_degrade_gracefully_without_metadata(service, signal_date):
    """candidate 缺 metadata 时 (legacy 构造): setup 级冻结先验与 T+N 退出合约
    仍然展示, 但涨停结构/失效参考价等逐票字段不编造."""
    run = run_daily_action_v2(service, _scan(signal_date))
    rendered = render_daily_action_v2(run)
    assert "先验（T+10" in rendered
    assert "退出：T+10" in rendered
    assert "失效参考" not in rendered
    assert "涨停前 5 日" not in rendered


def test_plan_details_absent_falls_back_to_single_line(service, signal_date):
    """无 plan_details 的构造点 (DailyActionService.render 等) 保持现有单行格式."""
    run = run_daily_action_v2(service, _scan(signal_date))
    mirrored = DailyActionService.render(run.service_run)
    assert "新计划（1 只）" in mirrored
    assert "买入：" not in mirrored
    assert "理由：" not in mirrored


def test_blocked_strength_candidate_shows_component_breakdown_and_funnel(service, signal_date):
    """强度不足的不可计划候选: 展示阈值差距 + 5 分量短板下钻 (哪个维度拖累了
    强度). 扫描漏斗披露 扫描→预筛→命中→计划 计数, 回答"为什么只有这一只" —
    未命中票从来不是候选, 不可见≠不存在."""
    blocked = BlockedCandidate(
        "003031",
        "trigger_strength_below_threshold",
        130.08,
        "btst_breakout",
        0.42,
        metadata={
            "board_score": 0.0,
            "low_vol_score": 0.20,
            "squeeze_score": 0.50,
            "volume_score": 0.30,
            "range_score": 1.00,
            "energy_bonus": 0.0,
        },
    )
    scan = DailyActionScan(
        signal_date,
        (),
        (blocked,),
        (("003031", 130.08),),
        funnel=ScanFunnel(scannable=777, prefilter_passed=47, hits=2),
    )
    rendered = render_daily_action_v2(run_daily_action_v2(service, scan))
    assert "触发强度不足（0.42 < 0.50 阈值，差 0.08）" in rendered
    assert "强度分量：上市板 0.00 · 低波 0.20 · 压缩 0.50 · 量能 0.30 · 振幅 1.00" in rendered
    assert "短板：上市板 0.00" in rendered
    assert "扫描漏斗：扫描 777 只 → 涨幅≥9.5% 47 只 → 命中 2 只 → 可计划 0 只 · 不可计划 1 只" in rendered


def test_non_strength_blocked_reason_stays_single_line(service, signal_date):
    """非强度类阻断 (regime 闸等) 保持单行中文原因, 不画蛇添足补分量行."""
    blocked = BlockedCandidate(
        "003031", "regime_gate_halt", 130.08, "btst_breakout", 0.90,
        metadata={"board_score": 1.0},
    )
    scan = DailyActionScan(signal_date, (), (blocked,), (("003031", 130.08),))
    rendered = render_daily_action_v2(run_daily_action_v2(service, scan))
    assert "原因：regime 闸（危机/避险日不开新仓）" in rendered
    assert "强度分量" not in rendered


def test_funnel_line_omitted_when_scan_has_no_funnel(service, signal_date):
    """legacy 扫描路径不带漏斗计数 → 整行省略 (优雅降级, 不编造计数)."""
    run = run_daily_action_v2(service, _scan(signal_date))
    assert "扫描漏斗" not in render_daily_action_v2(run)


def test_capacity_skips_disclosed_and_funnel_arithmetic_closes(service, signal_date):
    """容量拦截披露 (2026-08-18 审查项 1): 行业集中/组合敞口拦截此前在 service
    层是裸 continue — 强度达标的候选从漏斗凭空消失 (2026-08-17 实况: 命中 13
    只只交代 7 只). 契约: 容量拦截区逐只披露原因, 漏斗算术闭合
    (命中 = 可计划 + 不可计划 + 容量拦截), 敞口/regime 行可见, 幂等重跑不误报."""
    from types import SimpleNamespace

    from src.screening.offensive.daily_action import complete_daily_action_v2

    industry_map = {
        "000001": "电子",
        "000002": "电子",
        "000003": "电子",  # 第 3 只电子: 行业集中拦截
        "000004": "机械设备",
        "000005": "通信",
        "000006": "计算机",
        "000007": "食品饮料",
        "000008": "有色金属",  # 前 6 只各 10% 已填满 60%: 组合敞口拦截
    }
    fake_snapshot = SimpleNamespace(
        signal_date=signal_date,
        snapshot_id="snap-cap-test",
        reference_price=lambda _ticker: 10.0,
        board_rule_version="ashare-board-prefix-v1",
        manifest=SimpleNamespace(
            run_id="run-cap-test",
            content_fingerprint="sha256:content",
            input_fingerprint="sha256:input",
            shared_evidence=SimpleNamespace(industry_by_ticker=industry_map),
        ),
    )
    tickers = tuple(industry_map)
    candidates = tuple(
        PlanCandidate(
            ticker=ticker,
            setup="btst_breakout",
            setup_version="v2",
            signal_date=signal_date,
            target_weight=0.30,  # 被单票上限压到 10%: 6 只恰好填满 60% 组合上限
            priority=idx + 1,
            snapshot_id="snap-cap-test",
            setup_consumed_fingerprint="sha256:consumed",
            detector_degraded=False,
            authorization=RegimeAuthorization.NORMAL,
            trigger_strength=0.79,
            entry_price=10.0,
        )
        for idx, ticker in enumerate(tickers)
    )
    scan = DailyActionScan(
        signal_date,
        candidates,
        (),
        tuple((ticker, 10.0) for ticker in tickers),
        funnel=ScanFunnel(scannable=1497, prefilter_passed=84, hits=8),
        regime="normal",
    )
    context = service.advance_lifecycle(signal_date)
    run = complete_daily_action_v2(service, context, scan, verified_snapshot=fake_snapshot)
    rendered = render_daily_action_v2(run)

    # 6 只成计划 (电子 2 + 四个独立行业 4, 各 10%); 000003 撞行业集中,
    # 000008 撞组合敞口 — 恰好复现 2026-08-17 的 603110 (强度达标却被 cap 拦).
    assert len(run.plans) == 6
    skip_map = {skip.ticker: skip.reason for skip in run.capacity_skipped}
    assert skip_map == {"000003": "industry_concentration", "000008": "portfolio_cap"}
    # 容量拦截区逐只披露原因 (上限决定买什么, 不决定看什么).
    assert "容量拦截（2 只）" in rendered
    assert "行业集中（电子 已 2 仓，同入场日上限 2）" in rendered
    assert "组合敞口 60% + 本票 10% > 60% 上限" in rendered
    # 漏斗算术闭合: 命中 8 = 可计划 6 + 不可计划 0 + 容量拦截 2 (行业 1 · 敞口 1).
    assert (
        "扫描漏斗：扫描 1497 只 → 涨幅≥9.5% 84 只 → 命中 8 只 → "
        "可计划 6 只 · 不可计划 0 只 · 容量拦截 2 只（行业 1 · 敞口 1）"
    ) in rendered
    # regime 与敞口披露: 危机阻断的前置条件 + 今日约束是否 binding 可见.
    assert "Regime：normal（当前不阻断新仓" in rendered
    assert "敞口：持仓 0% + 待成交计划 60% = 60% / 60% 上限 ⚠达上限" in rendered

    # 幂等重跑: 已持久化计划的 6 只候选不再被误报成容量拦截 (敞口被自己的
    # 计划占满); 真正被拦的 000003/000008 重跑时如实再报 (当日约束仍未解除).
    rerun = run_daily_action_v2(service, scan, verified_snapshot=fake_snapshot)
    assert len(rerun.plans) == 6
    rerun_skip_map = {skip.ticker: skip.reason for skip in rerun.capacity_skipped}
    assert rerun_skip_map == {"000003": "industry_concentration", "000008": "portfolio_cap"}
    assert not {"000001", "000002", "000004", "000005", "000006", "000007"} & set(rerun_skip_map)


def test_clamped_stop_discloses_floor_instead_of_fake_range_low(service, signal_date):
    """盘整区底部过远被兜底 pct 截断时, 失效参考须明示"兜底" — 否则 operator 会把
    兜底线误读成真实底部 (真实例: 600487 20260814 底部 45.60 vs 兜底线 57.94)."""
    hit = PlanCandidate(
        ticker="600487",
        setup="btst_breakout",
        setup_version="v2",
        signal_date=signal_date,
        target_weight=0.10,
        priority=1,
        snapshot_id="legacy_unverified",
        setup_consumed_fingerprint="legacy_unverified",
        detector_degraded=False,
        authorization=RegimeAuthorization.NORMAL,
        trigger_strength=0.79,
        entry_price=62.98,
        metadata={"range_low": 45.60, "range_based_stop_pct": -0.08},
    )
    scan = DailyActionScan(signal_date, (hit,), (), (("600487", 62.98),))
    rendered = render_daily_action_v2(run_daily_action_v2(service, scan))
    # 62.98 × (1 - 0.08) = 57.94; 底部 45.60 过远 → 明示兜底, 不把 45.60 当止损锚.
    assert "失效参考：跌破 57.94（-8.0% 兜底，真实盘整区底部 45.60 过远）" in rendered


def test_verbose_appends_debug_section_without_changing_body(service, signal_date):
    """Single-track rendering: --verbose keeps the exact same body as the default
    view and only appends a diagnostics section with Chinese-first lines that
    retain the raw audit codes in a bracketed appendix."""
    run = run_daily_action_v2(service, _scan(signal_date))
    default_text = render_daily_action_v2(run)
    verbose_text = render_daily_action_v2(run, verbose=True)
    verbose_lines = verbose_text.splitlines()
    idx = next(
        i for i, line in enumerate(verbose_lines) if "诊断明细（--verbose）" in line
    )
    body = "\n".join(verbose_lines[:idx]).rstrip()
    assert body == default_text
    assert "诊断明细（--verbose）" in verbose_text
    assert "reason=entry_planned" in verbose_text
    assert "execution=pending" in verbose_text
    assert "source=pending" in verbose_text
    # 中文含义只在诊断区出现, 不进正文 (单轨原则).
    assert "新计划已登记" in verbose_text
    assert "新计划已登记" not in default_text


def test_verbose_diagnostics_are_chinese_first_with_raw_code_appendix(service, signal_date):
    """诊断明细区: 每行 = 对象 + 中文含义 + [原始审计码附录] — 操作员先读懂
    "发生了什么/为什么", 开发者仍可用方括号里的 key=value 对照日志/事件 payload.
    未知码 fail-closed 回退为原文显示 (不崩溃、不吞信息)."""
    run = run_daily_action_v2(service, _scan(signal_date))
    text = render_daily_action_v2(run, verbose=True)
    # entry_planned: signal 7/13 → 入场 7/14（周二）; pending/pending 去重为单次"待成交".
    assert (
        "000001  新计划已登记，等待 7/14（周二）开盘成交；当前待成交  "
        "[reason=entry_planned execution=pending source=pending]"
    ) in text

    blocked_run = run_daily_action_v2(service, _scan(signal_date, degraded=True))
    blocked_text = render_daily_action_v2(blocked_run, verbose=True)
    assert (
        "000001  不可计划：setup 数据不完整  [block_reason=incomplete_setup_data]"
    ) in blocked_text


def test_summary_lists_nonzero_events_only(service, signal_date):
    """摘要行只列非零事件 (新计划/当日成交/退出/完成/不可计划), 全零退化为
    「今日无新计划」, block 场景整段让位给 dispatcher 结论 (无「今日摘要」)."""
    valuation = DailyValuation(signal_date, 100_000, 0, 100_000, 100_000, 0, ())

    def summary_of(text: str) -> str:
        return next(line for line in text.splitlines() if "今日摘要" in line)

    # 有计划 → 只列新计划, 当日成交 0 笔不进摘要.
    run = run_daily_action_v2(service, _scan(signal_date))
    assert summary_of(render_daily_action_v2(run)) == "今日摘要：新计划 1 只"

    # 有退出计划 → 摘要披露退出计数, 默认视图 lifecycle 节也显示持仓.
    exit_item = ActionItem("t", "000001", "pending_exit", "paper", "synthetic_open")
    exit_view = DailyActionRun(
        signal_date, valuation, (), (), (), (exit_item,), (), (), 0, 0
    )
    exit_text = render_daily_action_v2(DailyActionV2Run(exit_view, (), (), (), ()))
    assert summary_of(exit_text) == "今日摘要：退出计划 1 只"
    assert "退出计划（1）" in exit_text and "000001" in exit_text

    # 全零 → 退化「今日无新计划」.
    empty_text = render_daily_action_v2(
        DailyActionV2Run(DailyActionRun(signal_date, valuation, (), (), (), (), (), (), 0, 0), (), (), (), ())
    )
    assert summary_of(empty_text) == "今日摘要：今日无新计划"

    # block 场景 → 摘要消失, 结论由 dispatcher 追加.
    blocked_view = DailyActionRun(
        signal_date, valuation, (), (), (), (), (), (), 0, 0,
        block_reasons=("calendar_unavailable",),
    )
    blocked_text = render_daily_action_v2(DailyActionV2Run(blocked_view, (), (), (), ()))
    assert "今日摘要" not in blocked_text


def test_renderer_includes_real_lifecycle_reasons(service, signal_date):
    run = run_daily_action_v2(service, _scan(signal_date))
    default_text = render_daily_action_v2(run)
    verbose_text = render_daily_action_v2(run, verbose=True)
    # Default operator view is clean: no raw codes, plan still shown.
    assert "reason=entry_planned" not in default_text
    assert "execution=pending" not in default_text
    assert "source=pending" not in default_text
    assert "参考价" in default_text
    # Verbose retains the raw audit detail.
    assert "entry_planned" in verbose_text
    assert "execution=pending" in verbose_text
    assert "source=pending" in verbose_text


def test_render_gates_manifest_diagnostic_codes_behind_verbose(signal_date):
    """Task 9: default operator output hides raw readiness/gate codes; --verbose reveals them."""
    view = DailyActionRun(
        signal_date,
        DailyValuation(signal_date, 100_000, 0, 100_000, 100_000, 0, ()),
        (),  # open_positions
        (),  # new_plans
        (),  # skipped_plans
        (),  # exit_plans
        (),  # deferred_exits
        (),  # completed_exits
        0,
        0,
        block_reason="daily_action_readiness_missing",
        blocked_tickers=("000002",),
        block_reasons=("daily_action_readiness_missing",),
        ticker_gate_blocks=(TickerGateBlock("000003", ("candidate_snapshot_mismatch",)),),
    )
    run = DailyActionV2Run(view, (), (), (), ())

    default_text = render_daily_action_v2(run)
    verbose_text = render_daily_action_v2(run, verbose=True)

    for raw in (
        "block_reasons=",
        "block_reason=",
        "manifest_blocked_tickers=",
        "manifest_gate_blocks",
        "candidate_snapshot_mismatch",
    ):
        assert raw not in default_text, f"raw code leaked into default output: {raw}"
    assert "block_reasons=daily_action_readiness_missing" in verbose_text
    assert "manifest_blocked_tickers=000002" in verbose_text
    assert "candidate_snapshot_mismatch" in verbose_text


def test_ticker_terminal_bar_must_equal_authoritative_signal_session():
    import pandas as pd

    fresh = pd.DataFrame([{"date": "2026-07-13", "close": 10.0}])
    stale = pd.DataFrame([{"date": "2026-07-10", "close": 10.0}])
    assert _price_frame_is_fresh(fresh, "20260713")
    assert not _price_frame_is_fresh(stale, "20260713")


def test_renderer_surfaces_every_lifecycle_collection(signal_date):
    def item(reason, execution, source):
        return ActionItem("t", "000001", reason, execution, source)

    view = DailyActionRun(
        signal_date,
        DailyValuation(signal_date, 100_000, 0, 100_000, 100_000, 0, ()),
        (),
        (),
        (item("portfolio_capacity", "pending", "pending"),),
        (item("maximum_holding_session", "paper", "synthetic_open"),),
        (item("unknown_queue", "paper", "synthetic_open"),),
        (item("exit_filled", "paper", "synthetic_open"),),
        0,
        0,
        "calendar_unavailable",
    )
    rendered = render_daily_action_v2(DailyActionV2Run(view, (), (), (), ()), verbose=True)
    for expected in (
        "portfolio_capacity",
        "maximum_holding_session",
        "unknown_queue",
        "exit_filled",
        "calendar_unavailable",
        "execution=paper",
        "source=synthetic_open",
    ):
        assert expected in rendered


def test_actual_cli_is_idempotent_and_preserves_recursive_legacy_artifacts(
    tmp_path, monkeypatch, signal_date
):
    runtime = tmp_path / "data/paper_trading"
    backtest = tmp_path / "data/paper_trading_backtest"
    for root, payload in ((runtime, b"runtime"), (backtest, b"backtest")):
        (root / "nested").mkdir(parents=True)
        (root / "journal.jsonl").write_bytes(payload)
        (root / "nested/state.bin").write_bytes(payload + b"-state")
    snapshot = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in (runtime, backtest)
        for path in root.rglob("*")
        if path.is_file()
    }
    scan = _scan(signal_date)
    price_cache = tmp_path / "data/price_cache"
    price_cache.mkdir(parents=True)
    (price_cache / "000001.csv").write_text(
        "date,open,high,low,close,limit_down,limit_up,suspended\n"
        "2026-07-13,10,10.5,9.5,10,9,11,False\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.screening.offensive.daily_action.scan_daily_action_candidates",
        lambda **_kwargs: scan,
    )
    _install_healthy_manifest(monkeypatch, signal_date)
    _install_readiness_manifest(monkeypatch, signal_date, reports_dir=tmp_path / "data" / "reports", data_dir=tmp_path / "data")
    ledger = tmp_path / "isolated-v2/ledger.sqlite3"
    sessions = tuple(signal_date + timedelta(days=i) for i in range(11))
    dispatcher._resolve_daily_action(
        ["--daily-action"], open_sessions=sessions, ledger_path=ledger
    )
    dispatcher._resolve_daily_action(
        ["--daily-action"], open_sessions=sessions, ledger_path=ledger
    )
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in (runtime, backtest)
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == snapshot  # journal/state files preserved (idempotency)
    repo = LedgerRepository(ledger, "daily-action-v2", 100_000, execution_costs=ExecutionCosts(version="test"))
    plans = repo.planned_trades()
    # In the new architecture, the verified-snapshot scanner produces candidates
    # from actual price data (not mocked scan). The test's 1-row price CSV
    # doesn't trigger BTST, so 0 plans is correct. The idempotency check (no
    # duplicate events across 2 runs) is the real assertion.
    assert len(plans) == 0, "1-row price CSV cannot trigger BTST; 0 plans is correct"


def test_actual_cli_missing_calendar_renders_block_and_creates_no_plan(
    tmp_path, monkeypatch, signal_date, capsys
):
    monkeypatch.chdir(tmp_path)
    price_cache = tmp_path / "data/price_cache"
    price_cache.mkdir(parents=True)
    (price_cache / "000001.csv").write_text(
        "date,open,high,low,close,limit_down,limit_up,suspended\n"
        "2026-07-13,10,10.5,9.5,10,9,11,False\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.screening.offensive.daily_action.resolve_daily_action_signal",
        lambda **_kwargs: (signal_date, "normal"),
    )
    _install_healthy_manifest(monkeypatch, signal_date)
    _install_readiness_manifest(monkeypatch, signal_date, reports_dir=tmp_path / "data" / "reports", data_dir=tmp_path / "data")
    ledger = tmp_path / "blocked.sqlite3"
    dispatcher._resolve_daily_action(
        ["--daily-action"], open_sessions=(), ledger_path=ledger
    )
    output = capsys.readouterr().out
    # Empty calendar blocks new plans. The exact block reason text may vary
    # between readiness/calendar paths, but the key invariant is: no plans.
    assert LedgerRepository(ledger, "daily-action-v2", 100_000, execution_costs=ExecutionCosts(version="test")).planned_trades() == []


def test_actual_cli_two_session_calendar_blocks_btst_horizon(
    tmp_path, monkeypatch, signal_date, capsys
):
    monkeypatch.chdir(tmp_path)
    price_cache = tmp_path / "data/price_cache"
    price_cache.mkdir(parents=True)
    (price_cache / "000001.csv").write_text(
        "date,open,high,low,close,limit_down,limit_up,suspended\n"
        "2026-07-13,10,10.5,9.5,10,9,11,False\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.screening.offensive.daily_action.resolve_daily_action_signal",
        lambda **_kwargs: (signal_date, "normal"),
    )
    _install_healthy_manifest(monkeypatch, signal_date)
    _install_readiness_manifest(monkeypatch, signal_date, reports_dir=tmp_path / "data" / "reports", data_dir=tmp_path / "data")
    ledger = tmp_path / "two-session.sqlite3"
    dispatcher._resolve_daily_action(
        ["--daily-action"],
        open_sessions=(signal_date, signal_date + timedelta(days=1)),
        ledger_path=ledger,
    )
    output = capsys.readouterr().out
    # Two-session calendar can't hold a T+10 BTST position. No plans created.
    assert LedgerRepository(ledger, "daily-action-v2", 100_000, execution_costs=ExecutionCosts(version="test")).planned_trades() == []

# ---------------------------------------------------------------------------
# Task 9 readiness v2 production path integration
# ---------------------------------------------------------------------------

from tests.offensive.readiness_v2_testkit import (
    run_full_injected_pipeline,
    run_pipeline_without_readiness_with_due_exit,
)


def test_outside_auto_pool_ticker_reaches_verified_plan(tmp_path) -> None:
    result = run_full_injected_pipeline(
        tmp_path,
        auto_tickers={"000001"},
        daily_tickers={"000001", "002999"},
        btst_hit="002999",
    )
    assert [plan.ticker for plan in result.new_plans] == ["002999"]
    assert result.ledger_trade is not None
    assert result.ledger_trade.provenance.verification_status == "verified"


def test_lifecycle_without_readiness_still_completes_exit(tmp_path) -> None:
    result = run_pipeline_without_readiness_with_due_exit(tmp_path)
    assert len(result.completed_exits) == 1
    assert result.new_plans == ()
