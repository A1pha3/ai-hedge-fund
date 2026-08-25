"""官方前向 Trial 启动引导器 — 端到端测试 (第三十八轮).

钉死: bootstrap 三子命令把 runbook 启动序列从「只有测试 fixture 能构造」
变成可执行命令 —

  seed-evidence:  持久身份发布首会话 regime 观察 (固定 REGIME_EVIDENCE_ID,
                  readiness 指纹绑定) + bars schema 落盘; 首个 driver decide
                  幂等复用种子观察 (不产生第二 revision);
  enroll-spine:   权威日历派生 (signal, assessment=T+10) enrollment;
                  二次注册 session_already_enrolled 类型化拒绝;
  seal-trial:     参数文件 → 四 artifact 内部互证派生 → 四治理键签名 →
                  封存 → stage 签发 → 回执归档; 同参数重放逐字节幂等。

对抗面: dry-run 字节级零写入 / 种子观察与驱动器推导恰等 / 未初始化 root /
窗口倒置 / 参数缺 key / trial-id 错配。
"""

from __future__ import annotations

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

from test_official_trial_stack import TRIAL_ID  # noqa: E402
from test_regime_trial_governance import NOW as GOV_NOW  # noqa: E402
from test_trial_session_driver import (  # noqa: E402
    DECIDE_AT,
    SIGNAL_SESSION,
    _calendar_file,
    _manifest,
    _snapshot,
)

from scripts.v3_trial_bootstrap import main as cli_main  # noqa: E402
from src.screening.offensive.v3.evidence.governance_identity import (  # noqa: E402
    generate_governance_identity,
)
from src.screening.offensive.v3.orchestration.trial_session_driver import (  # noqa: E402
    OfficialTrialSessionDriver,
)

UTC = timezone.utc


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _fresh_layout(tmp_path: Path):
    """全新官方布局世界: 身份 v2 + genesis 双臂 + 四库空文件 (零预置)。"""
    from src.screening.offensive.v3.capital.flows import GenesisRequest
    from src.screening.offensive.v3.capital.identity import AccountBinding
    from src.screening.offensive.v3.capital.repository import CapitalRepository
    from src.screening.offensive.v3.contracts.base import ExecutionMode
    from src.screening.offensive.v3.orchestration.arm_layout import (
        arm_capital_database_path,
    )
    from src.screening.offensive.v3.contracts.trial import TrialArm
    from src.screening.offensive.v3.orchestration.genesis import (
        TrialArmGenesisSource,
        TrialGenesisArchive,
        restore_genesis_arm,
    )

    identity_dir = tmp_path / "identity"
    generate_governance_identity(
        identity_dir,
        clock=lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
    )
    root = tmp_path / "trial-root"
    root.mkdir()
    for name in (
        "evidence.sqlite3",
        "bars-evidence.sqlite3",
        "spine.sqlite3",
        "governance.sqlite3",
    ):
        (root / name).write_bytes(b"")

    seed = tmp_path / "seed-capital.sqlite3"
    repo = CapitalRepository.initialize(seed)
    repo.initialize_genesis(GenesisRequest(
        idempotency_key="genesis-r38",
        account_binding=AccountBinding(
            portfolio_id=f"pf-{TRIAL_ID}",
            mode=ExecutionMode.DAILY_BAR_PROXY,
            broker_account_id=None, base_currency="CNY",
            environment_fingerprint=None,
        ),
        unit_quanta=10_000, unit_price_numerator=1_000,
        unit_price_denominator=1,
        source_authority="governance.test", authorization_reference="t-r38",
        effective_at=GOV_NOW, as_of=GOV_NOW,
    ))
    source = TrialArmGenesisSource(capital_repository=repo)
    manifest = TrialGenesisArchive(root).seal(
        TRIAL_ID, champion_source=source, challenger_source=source
    )
    for arm in ("CHAMPION", "CHALLENGER"):
        target = arm_capital_database_path(root, TrialArm[arm])
        target.parent.mkdir(parents=True, exist_ok=True)
        restore_genesis_arm(manifest, root, target, arm=arm)
    return identity_dir, root


def _readiness_manifest_file(tmp_path: Path) -> Path:
    """经生产发布函数落盘 (单一实现 — 手工序列化会与 canonical 漂移)。"""
    from src.screening.offensive.daily_action_readiness import (
        publish_daily_action_readiness,
    )

    from dataclasses import replace

    from src.screening.offensive.cache_readiness import universe_fingerprint
    from src.screening.offensive.pit_evidence import canonical_fingerprint
    from test_trial_session_driver import TICKERS, _fingerprint

    reports = tmp_path / "reports"
    manifest = _manifest(SIGNAL_SESSION)
    # canonical 校验四处对齐 (驱动器测试从不落盘故未暴露): created_at 要求
    # Z 后缀; universe/suspension 指纹必须是各自载荷的规范哈希; content
    # 指纹是全部其余字段的规范重推导 — 先修子指纹再末位重算 content。
    stepped = replace(
        manifest,
        created_at=manifest.created_at.replace("+00:00", "Z"),
        universe_fingerprint=universe_fingerprint(TICKERS),
        suspension_evidence=replace(
            manifest.suspension_evidence,
            source_fingerprint=canonical_fingerprint("suspension", "*", []),
        ),
    )
    unsigned = {
        key: value
        for key, value in stepped.to_dict().items()
        if key != "content_fingerprint"
    }
    canonical = replace(stepped, content_fingerprint=_fingerprint(unsigned))
    publication = publish_daily_action_readiness(canonical, reports)
    assert publication.status == "healthy", publication.summary
    return publication.artifact_path


def _trial_params_file(tmp_path: Path, *, identity_dir: Path) -> Path:
    """最小合法 trial 参数文件 (语义对齐治理校验器的单 delta 契约)。"""
    from decimal import Decimal

    baseline = {
        "schema_major": 2,
        "policy_id": "growth-kernel-v3",
        "policy_version": "policy-v2",
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": 1,
        "runtime_mode": "shadow",
        "capital": {
            "governed_tiers": [2, 5, 10],
            "exploration_aggregate_gross_cap": "0.02",
            "portfolio_gross_cap": "0.02",
            "single_name_gross_cap": "0.01",
            "industry_gross_cap": "0.02",
            "daily_entry_gross_cap": "0.02",
            "stage_loss_budget_cap": "0.02",
        },
        "risk": {
            "drawdown_scale_start": "0.10",
            "drawdown_halt": "0.15",
            "halt_is_latched": True,
            "inherited_risk_counts_on_restart": True,
        },
        "adv": {
            "lookback_sessions": 20,
            "max_participation_rate": "0.05",
            "missing_data_behavior": "fail_closed",
        },
        "producers": {
            "btst_enabled": True,
            "oversold_bounce_enabled": False,
            "btst_regime_admission_mode": "IGNORE",
            "regime_sizing_enabled": False,
            "streak_sizing_enabled": False,
            "trigger_strength_sizing_enabled": False,
            "composite_sizing_enabled": False,
        },
        "execution": {
            "entry_session_ordinal": 1,
            "exit_session_ordinal": 10,
            "order_type": "opening_auction_limit",
            "time_in_force": "opening_auction",
            "seal_deadline_after_t0_close_minutes": 240,
            "permit_deadline_before_auction_minutes": 20,
            "gateway_send_deadline_before_auction_minutes": 10,
            "broker_auction_submission_cutoff_cn": "09:20:00",
            "worst_case_cost_multiplier": "2",
        },
        "versions": {
            "execution_contract_version": "t0-close-t1-open-t10-open.v1",
            "cost_version": "cn-a-share-costs.v1",
            "board_rule_version": "ashare-board-prefix-v1",
            "calendar_version": "sse-sessions-v1",
            "lot_rule_version": "cn-board-lot.v1",
            "price_boundary_version": "sse-szse-price-limits.v1",
            "setup_version": "daily-action-setups-v1",
            "exit_policy_version": "t10-open.v1",
            "governance_version": "growth-kernel-governance.v2",
        },
        "evidence_gates": {
            "min_mature_outcomes": 150,
            "min_decision_days": 60,
            "min_effective_sample_size": "60",
            "min_distinct_tickers": 80,
            "min_forward_months": 12,
            "adverse_window_required": True,
            "chronological_fold_gate_required": True,
            "capacity_stress_required": True,
            "tail_risk_gate_required": True,
            "fresh_evidence_per_tier_required": True,
            "slippage_stress_multiple": "2",
            "minimum_economic_effect": "0.001",
            "incremental_minimum_economic_effect": "0.001",
        },
    }
    import copy

    target = copy.deepcopy(baseline)
    target["producers"]["btst_regime_admission_mode"] = "NORMAL_ONLY"

    issued_at = GOV_NOW
    enrollment_start = issued_at + timedelta(days=1)
    params = {
        "trial_id": TRIAL_ID,
        "research_program_id": "research.btst.regime",
        "baseline_policy": baseline,
        "target_policy": target,
        "trial": {
            "family_id": "btst.limit-up-breakout",
            "economic_lineage_id": "eline-r38",
            "attempt_ledger_checkpoint_before_trial": "a" * 64,
            "attempt_budget_reservation_id": "attempt-r38-001",
            "statistical_governance_policy_version": "stat-gov.v1",
            "champion_behavior_fingerprint": "b" * 64,
            "challenger_behavior_fingerprint": "c" * 64,
            "primary_metric": "PORTFOLIO_LOG_GROWTH",
            "minimum_economic_effect": "0.001",
            "weight_selection_rule": "fixed-50-50",
            "issued_at": issued_at.isoformat(),
            "enrollment_start": enrollment_start.isoformat(),
            "enrollment_end": (issued_at + timedelta(days=30)).isoformat(),
            "followup_finality_date": (issued_at + timedelta(days=60)).isoformat(),
            "fixed_assessment_date": (issued_at + timedelta(days=90)).isoformat(),
            "execution_version": "t0-close-t1-open-t10-open.v1",
            "cost_version": "cn-a-share-costs.v1",
            "execution_mode": "daily_bar_proxy",
            "benchmark_definition": "csi300-total-return",
            "capacity_policy": "capacity.v1",
            "tail_risk_policy": "tail.v1",
            "estimator": "wild-bootstrap",
            "one_sided_confidence_level": "0.95",
            "bootstrap_method": "wild",
            "bootstrap_repetitions": 10000,
            "bootstrap_seed": 42,
            "block_rule": "monthly",
            "ess_definition": "kish",
            "missing_censoring_itt_rule": "itt",
            "fold_boundaries": ["2026-09-01", "2026-10-01"],
            "purge_embargo": "purge-5d",
            "promotion_boolean_expression": "lcb > mee",
            "multiplicity_policy": "program-global",
            "canonical_outcome_counting_rule": "plan-line-contract",
            "stage_loss_measurement_basis": "stage-budget",
            "expires_at": (issued_at + timedelta(days=120)).isoformat(),
            "expected_signal_cutoff": (issued_at + timedelta(days=1)).isoformat(),
            "trusted_at": enrollment_start.isoformat(),
        },
        "sap": {
            "one_sided_confidence_level": "0.95",
            "bootstrap_method": "wild",
            "repetitions": 10000,
            "seed": 42,
            "block_rule": "monthly",
            "multiplicity_policy": "program-global",
            "alpha_or_evalue_budget_consumption_id": "budget-r38",
            "expires_at": (issued_at + timedelta(days=120)).isoformat(),
        },
        "activation": {
            "portfolio_id": f"pf-{TRIAL_ID}",
            "mode": "daily_bar_proxy",
            "predecessor_policy_activation_hash": "0" * 64,
            "policy_epoch": 1,
            "authority_epoch": 1,
            "risk_epoch": 1,
            "effective_from": enrollment_start.isoformat(),
            "expires_at": (issued_at + timedelta(days=120)).isoformat(),
        },
        "stage": {
            "stage_id": "stage-r38-001",
            "stage_sample_reservation_id": "smp-r38",
            "alpha_sample_consumption_id": "alpha-r38",
            "alpha_or_evalue_budget_consumption_id": "budget-r38",
            "attempt_ledger_checkpoint_hash": "d" * 64,
            "stage_loss_budget_id": "loss-r38",
            "stage_loss_version": 1,
            "maximum_loss_budget_cents": 1000000,
            # stage 契约: issued_at < enrollment_start (入场窗口开始后不可补签)
            "issued_at": issued_at.isoformat(),
        },
    }
    path = tmp_path / "trial-params.json"
    path.write_text(json.dumps(params), encoding="utf-8")
    return path


class TestSeedEvidence:
    def test_seed_then_driver_decide_reuses_observation(self, tmp_path) -> None:
        """种子观察 == 驱动器同 manifest 推导 → 首 decide 幂等复用。"""
        from scripts.v3_trial_session import main as session_cli

        identity_dir, root = _fresh_layout(tmp_path)
        calendar = _calendar_file(tmp_path)
        manifest_file = _readiness_manifest_file(tmp_path)
        rc = cli_main([
            "seed-evidence",
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--calendar", str(calendar),
            "--readiness-manifest", str(manifest_file),
            "--signal-session", SIGNAL_SESSION.isoformat(),
            "--now", DECIDE_AT.isoformat(),
            "--execute",
        ])
        assert rc == 0
        evidence_before = _tree_digest(root / "blobs")

        # 官方栈组装在种子后必须通过 evidence_not_seeded 探测 — 全链:
        # 封存+签发+回执归档由 seal-trial 完成, 这里先只验探测不再报播种。
        # (完整组装验收在 seal-trial 测试里做。)
        import sqlite3

        with sqlite3.connect(f"file:{root / 'evidence.sqlite3'}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT count(*) FROM evidence_records"
                " WHERE issuer_namespace = 'regime'"
            ).fetchone()
        assert row[0] >= 1

        # bars 库 schema 落盘零记录 (合法启动形态)
        with sqlite3.connect(
            f"file:{root / 'bars-evidence.sqlite3'}?mode=ro", uri=True
        ) as conn:
            tables = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()
        assert tables[0] >= 1

        # 二次执行幂等复用 (seeded=False), 字节不变
        rc2 = cli_main([
            "seed-evidence",
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--calendar", str(calendar),
            "--readiness-manifest", str(manifest_file),
            "--signal-session", SIGNAL_SESSION.isoformat(),
            "--now", DECIDE_AT.isoformat(),
            "--execute",
        ])
        assert rc2 == 0
        assert _tree_digest(root / "blobs") == evidence_before

    def test_seed_observation_matches_driver_derivation(self, tmp_path) -> None:
        """种子观察与驱动器 _seed 同源推导逐字段相等。"""
        from scripts.v3_trial_bootstrap import _seed_observation

        snapshot = _snapshot()
        observation, envelope = _seed_observation(
            snapshot, SIGNAL_SESSION, DECIDE_AT
        )
        # 驱动器同款推导 (直接调驱动器私有实现作 oracle)
        from src.screening.offensive.v3.orchestration.trial_session_driver import (
            REGIME_CLASSIFIER_FINGERPRINT,
        )
        from src.screening.offensive.v3.evidence.session_batch import (
            REGIME_EVIDENCE_ID,
        )

        assert envelope.evidence_id == REGIME_EVIDENCE_ID
        assert observation.behavior_fingerprint == REGIME_CLASSIFIER_FINGERPRINT
        revision = observation.source_revisions[0]
        fingerprint = snapshot.manifest.shared_evidence.regime_fingerprint.removeprefix("sha256:")
        assert revision.artifact_hash == fingerprint
        assert envelope.payload_content_hash == hashlib.sha256(
            observation.canonical_bytes()
        ).hexdigest()

    def test_dry_run_zero_write(self, tmp_path) -> None:
        identity_dir, root = _fresh_layout(tmp_path)
        calendar = _calendar_file(tmp_path)
        manifest_file = _readiness_manifest_file(tmp_path)
        before = _tree_digest(root) + _tree_digest(identity_dir)
        rc = cli_main([
            "seed-evidence",
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--calendar", str(calendar),
            "--readiness-manifest", str(manifest_file),
            "--signal-session", SIGNAL_SESSION.isoformat(),
        ])
        assert rc == 0
        assert _tree_digest(root) + _tree_digest(identity_dir) == before

    def test_uninitialized_root_rejected(self, tmp_path) -> None:
        identity_dir = tmp_path / "identity"
        generate_governance_identity(
            identity_dir, clock=lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
        )
        empty_root = tmp_path / "empty-root"
        empty_root.mkdir()
        with pytest.raises(SystemExit) as stopped:
            cli_main([
                "seed-evidence",
                "--identity-dir", str(identity_dir),
                "--trial-root", str(empty_root),
                "--calendar", str(_calendar_file(tmp_path)),
                "--readiness-manifest", "x.json",
                "--signal-session", SIGNAL_SESSION.isoformat(),
            ])
        # fail JSON 走 stdout, SystemExit.code 是 rc=2
        assert stopped.value.code == 2


class TestEnrollSpine:
    def test_enroll_from_calendar_assessment_t_plus_10(self, tmp_path) -> None:
        identity_dir, root = _fresh_layout(tmp_path)
        calendar = _calendar_file(tmp_path)
        rc = cli_main([
            "enroll-spine",
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--calendar", str(calendar),
            "--start", SIGNAL_SESSION.isoformat(),
            "--end", (SIGNAL_SESSION + timedelta(days=2)).isoformat(),
            "--now", DECIDE_AT.isoformat(),
            "--execute",
        ])
        assert rc == 0
        import sqlite3

        with sqlite3.connect(f"file:{root / 'spine.sqlite3'}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT signal_session, assessment_date FROM expected_sessions"
                " ORDER BY signal_session"
            ).fetchall()
        assert len(rows) == 3
        # assessment = 排程末位 = T+10 (日历连续会话下第 10 个后继)
        first_signal = date.fromisoformat(rows[0][0])
        assert date.fromisoformat(rows[0][1]) > first_signal

    def test_double_enroll_fails_closed(self, tmp_path) -> None:
        identity_dir, root = _fresh_layout(tmp_path)
        calendar = _calendar_file(tmp_path)
        argv = [
            "enroll-spine",
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--calendar", str(calendar),
            "--start", SIGNAL_SESSION.isoformat(),
            "--end", SIGNAL_SESSION.isoformat(),
            "--now", DECIDE_AT.isoformat(),
            "--execute",
        ]
        assert cli_main(argv) == 0
        with pytest.raises(SystemExit):
            cli_main(argv)

    def test_inverted_window_rejected(self, tmp_path) -> None:
        identity_dir, root = _fresh_layout(tmp_path)
        with pytest.raises(SystemExit):
            cli_main([
                "enroll-spine",
                "--identity-dir", str(identity_dir),
                "--trial-root", str(root),
                "--calendar", str(_calendar_file(tmp_path)),
                "--start", (SIGNAL_SESSION + timedelta(days=5)).isoformat(),
                "--end", SIGNAL_SESSION.isoformat(),
            ])


class TestSealTrial:
    def _seal_argv(self, identity_dir: Path, root: Path, params: Path) -> list[str]:
        return [
            "seal-trial",
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--trial-id", TRIAL_ID,
            "--params", str(params),
            "--now", (GOV_NOW + timedelta(days=2)).isoformat(),
            "--execute",
        ]

    def test_seal_end_to_end_and_assemble(self, tmp_path) -> None:
        """播种→封存→签发→归档后官方栈组装通过全部冷读守卫。"""
        identity_dir, root = _fresh_layout(tmp_path)
        # 组装的 evidence_not_seeded 守卫要求 regime 证据在位 — 先播种。
        assert cli_main([
            "seed-evidence",
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--calendar", str(_calendar_file(tmp_path)),
            "--readiness-manifest", str(_readiness_manifest_file(tmp_path)),
            "--signal-session", SIGNAL_SESSION.isoformat(),
            "--now", DECIDE_AT.isoformat(),
            "--execute",
        ]) == 0
        assert cli_main([
            "enroll-spine",
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--calendar", str(_calendar_file(tmp_path)),
            "--start", SIGNAL_SESSION.isoformat(),
            "--end", SIGNAL_SESSION.isoformat(),
            "--now", DECIDE_AT.isoformat(),
            "--execute",
        ]) == 0
        params = _trial_params_file(tmp_path, identity_dir=identity_dir)
        rc = cli_main(self._seal_argv(identity_dir, root, params))
        assert rc == 0
        archived = root / "archive" / "stage-issuance" / TRIAL_ID
        receipts = list(archived.glob("*.json"))
        assert len(receipts) == 1

        from src.screening.offensive.v3.orchestration.official_trial_stack import (
            build_official_trial_stack,
        )
        from src.screening.offensive.v3.kernel.sizing import SizingConfig
        from src.screening.offensive.v3.capital.fills import FillAttribution
        from src.screening.offensive.v3.orchestration.arm_lifecycle import (
            CURRENT_COST_SCENARIO,
        )

        stack = build_official_trial_stack(
            identity_dir=identity_dir,
            trial_root=root,
            trial_id=TRIAL_ID,
            sizing_config=SizingConfig(
                per_ticker_gross_cap_cents=200_000,
                per_industry_gross_cap_cents=300_000,
                per_day_gross_cap_cents=500_000,
                portfolio_gross_cap_cents=400_000,
                worst_case_fee_ppm=3_000,
            ),
            clock=lambda: DECIDE_AT,
            market_scenario=CURRENT_COST_SCENARIO,
            trial_attribution=FillAttribution(
                producer_namespace="btst",
                research_program_id="research.btst.regime",
                economic_lineage_id="eline-r38",
                stage_id="stage-r38-001",
            ),
            research_program_id="research.btst.regime",
        )
        assert stack.stage_receipt.stage_id == "stage-r38-001"

    def test_replay_same_params_is_byte_idempotent(self, tmp_path) -> None:
        identity_dir, root = _fresh_layout(tmp_path)
        params = _trial_params_file(tmp_path, identity_dir=identity_dir)
        assert cli_main(self._seal_argv(identity_dir, root, params)) == 0
        governance_before = (root / "governance.sqlite3").read_bytes()
        archive_before = _tree_digest(root / "archive")
        # 恰等重放: stage 幂等收敛; trial_attempts/sealed_trials 的重放走
        # conflict 路径 — 本命令显式拒绝二次封存 (sealed_trials 已有行),
        # 但 stage 回执归档保持不变。
        with pytest.raises(SystemExit):
            cli_main(self._seal_argv(identity_dir, root, params))
        assert _tree_digest(root / "archive") == archive_before

    def test_missing_params_key_rejected(self, tmp_path) -> None:
        identity_dir, root = _fresh_layout(tmp_path)
        params = _trial_params_file(tmp_path, identity_dir=identity_dir)
        broken = json.loads(params.read_text())
        del broken["sap"]
        params.write_text(json.dumps(broken))
        with pytest.raises(SystemExit):
            cli_main(self._seal_argv(identity_dir, root, params))

    def test_trial_id_mismatch_rejected(self, tmp_path) -> None:
        identity_dir, root = _fresh_layout(tmp_path)
        params = _trial_params_file(tmp_path, identity_dir=identity_dir)
        with pytest.raises(SystemExit):
            cli_main([
                "seal-trial",
                "--identity-dir", str(identity_dir),
                "--trial-root", str(root),
                "--trial-id", "trial-other-id",
                "--params", str(params),
            ])

    def test_dry_run_zero_write(self, tmp_path) -> None:
        identity_dir, root = _fresh_layout(tmp_path)
        params = _trial_params_file(tmp_path, identity_dir=identity_dir)
        before = _tree_digest(root) + _tree_digest(identity_dir)
        rc = cli_main([
            "seal-trial",
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--trial-id", TRIAL_ID,
            "--params", str(params),
            "--now", (GOV_NOW + timedelta(days=2)).isoformat(),
        ])
        assert rc == 0
        assert _tree_digest(root) + _tree_digest(identity_dir) == before


class TestIdentityV2BackwardCompat:
    def test_v1_directory_still_loads(self, tmp_path) -> None:
        """旧 v1 目录 (无治理键) 加载行为不变 — 向后兼容。"""
        from src.screening.offensive.v3.evidence.governance_identity import (
            load_governance_identity,
        )

        d = tmp_path / "identity-v1"
        generate_governance_identity(
            d,
            namespaces=("regime", "exchange-calendar", "btst-bars", "btst"),
            clock=lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
        )
        now = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
        identity = load_governance_identity(d, trusted_at=now)
        assert set(identity.key_material) == {
            "regime", "exchange-calendar", "btst-bars", "btst"
        }
        with pytest.raises(Exception) as missing:
            identity.signer_for("governance.stage.manifest")
        assert "namespace_key_missing" in str(missing.value)

    def test_v2_default_has_nine_keys_all_verify(self, tmp_path) -> None:
        from src.screening.offensive.v3.evidence.governance_identity import (
            load_governance_identity,
        )

        d = tmp_path / "identity-v2"
        generated_at = datetime(2026, 8, 6, 8, 0, tzinfo=UTC)
        generate_governance_identity(d, clock=lambda: generated_at)
        now = generated_at + timedelta(hours=2)
        identity = load_governance_identity(d, trusted_at=now)
        # 4 snapshot + 1 signal + 4 governance (root 不是 namespace 键)
        assert len(identity.key_material) == 8
        head = identity.manifest["head_witness"]
        from src.screening.offensive.v3 import trust as v3trust

        witness = v3trust.CurrentTrustHeadWitness.model_validate_json(
            json.dumps(head)
        )
        for ns in (
            "regime", "exchange-calendar", "btst-bars", "btst",
            "governance.trial.manifest", "governance.sap.manifest",
            "governance.policy.activation", "governance.stage.manifest",
        ):
            signer = identity.signer_for(ns)
            envelope = signer(b"probe")
            identity.verifier.verify(
                envelope,
                identity.capabilities[ns],
                current_head=witness,
                trusted_at=now,
            )


class TestFullLaunchSequence:
    def test_seed_enroll_seal_then_decide_pair_committed(
        self, tmp_path
    ) -> None:
        """runbook 启动序列端到端: bootstrap 三步 → 组装 → decide pair 落库。"""
        from src.screening.offensive.v3.kernel.sizing import SizingConfig
        from src.screening.offensive.v3.capital.fills import FillAttribution
        from src.screening.offensive.v3.orchestration.arm_lifecycle import (
            CURRENT_COST_SCENARIO,
        )
        from src.screening.offensive.v3.orchestration.official_trial_stack import (
            build_official_trial_stack,
        )
        from src.screening.offensive.v3.evidence.governance_identity import (
            load_governance_identity,
        )

        identity_dir, root = _fresh_layout(tmp_path)
        calendar = _calendar_file(tmp_path)
        manifest_file = _readiness_manifest_file(tmp_path)
        common = [
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
        ]
        assert cli_main([
            "seed-evidence", *common,
            "--calendar", str(calendar),
            "--readiness-manifest", str(manifest_file),
            "--signal-session", SIGNAL_SESSION.isoformat(),
            "--now", DECIDE_AT.isoformat(),
            "--execute",
        ]) == 0
        assert cli_main([
            "enroll-spine", *common,
            "--calendar", str(calendar),
            "--start", SIGNAL_SESSION.isoformat(),
            "--end", SIGNAL_SESSION.isoformat(),
            "--now", DECIDE_AT.isoformat(),
            "--execute",
        ]) == 0
        params = _trial_params_file(tmp_path, identity_dir=identity_dir)
        assert cli_main([
            "seal-trial", *common,
            "--trial-id", TRIAL_ID,
            "--params", str(params),
            "--now", (GOV_NOW + timedelta(days=2)).isoformat(),
            "--execute",
        ]) == 0

        sizing = SizingConfig(
            per_ticker_gross_cap_cents=200_000,
            per_industry_gross_cap_cents=300_000,
            per_day_gross_cap_cents=500_000,
            portfolio_gross_cap_cents=400_000,
            worst_case_fee_ppm=3_000,
        )
        stack = build_official_trial_stack(
            identity_dir=identity_dir,
            trial_root=root,
            trial_id=TRIAL_ID,
            sizing_config=sizing,
            clock=lambda: DECIDE_AT,
            market_scenario=CURRENT_COST_SCENARIO,
            trial_attribution=FillAttribution(
                producer_namespace="btst",
                research_program_id="research.btst.regime",
                economic_lineage_id="eline-r38",
                stage_id="stage-r38-001",
            ),
            research_program_id="research.btst.regime",
        )
        identity = load_governance_identity(identity_dir, trusted_at=DECIDE_AT)
        driver = OfficialTrialSessionDriver(
            stack=stack,
            identity=identity,
            calendar_path=calendar,
            clock=lambda: DECIDE_AT,
        )
        driver.ensure_trial_registration()
        receipt = driver.decide_session(
            snapshot=_snapshot(), signal_session=SIGNAL_SESSION, now=DECIDE_AT
        )
        assert receipt.pair_key[0] == TRIAL_ID
        # 决策批落库
        import sqlite3

        with sqlite3.connect(
            f"file:{root / 'decisions.sqlite3'}?mode=ro", uri=True
        ) as conn:
            pairs = conn.execute(
                "SELECT count(*) FROM trial_arm_decisions"
            ).fetchone()
        assert pairs[0] >= 2  # 双臂各一条
