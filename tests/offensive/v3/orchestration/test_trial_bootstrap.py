"""官方 Trial 启动引导器 — 端到端测试 (R38; 一会话声明、接管会话完成)。

钉死 runbook 启动顺序 2-4 步的生产工具面:
  seed-evidence / enroll-spine / seal-trial 三子命令 — dry-run 字节级零写入、
  execute 落地事实、幂等/冲突类型化; 全链 = 身份 v2 → genesis 双臂 →
  bootstrap 三步 → 官方栈组装 → OfficialTrialSessionDriver.decide_session。

readiness 世界复用 readiness_v2_testkit 的注入管道 (真实 manifest + PIT
指纹核验的 cache 世界, 信号日 2026-07-13)。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _dir in (
    Path(__file__).resolve().parents[1] / "governance",
    Path(__file__).resolve().parents[1] / "kernel",
    Path(__file__).resolve().parents[1] / "evidence",
):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from test_regime_trial_governance import _trial_policy  # noqa: E402

from scripts.v3_trial_bootstrap import main as bootstrap_main  # noqa: E402
from tests.offensive.readiness_v2_testkit import (  # noqa: E402
    SIGNAL_DATE,
    run_injected_auto_refresh_for_20260713,
)

UTC = timezone.utc
TRIAL_ID = "trial-btst-r38-001"
PROGRAM = "research.btst.regime"
#: 身份生成时刻 — 早于全部签发/信封时刻 (root key not-yet-valid 陷阱)。
GEN_AT = datetime(2026, 6, 25, 8, 0, tzinfo=UTC)
#: 首信号会话 = testkit 信号日; 决策时刻 T0 15:30。
DECIDE_AT = datetime(SIGNAL_DATE.year, SIGNAL_DATE.month, SIGNAL_DATE.day, 15, 30, tzinfo=UTC)


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _calendar_file(tmp_path: Path) -> Path:
    sessions = [SIGNAL_DATE + timedelta(days=offset) for offset in range(16)]
    path = tmp_path / "trade-calendar.json"
    path.write_text(
        json.dumps([s.strftime("%Y%m%d") for s in sessions]), encoding="utf-8"
    )
    return path


def _trial_root_world(tmp_path: Path) -> Path:
    """官方布局 trial root: 四空库占位 + genesis 封存 + 双臂 restore。

    genesis 是资本事实 (bootstrap 范围之外, 与 runbook 分工一致); 四空库
    touch 是 runbook 前置 (见 runbook 「owner 前置」段)。
    """
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

    root = tmp_path / "trial-root"
    root.mkdir(parents=True)
    for name in (
        "evidence.sqlite3",
        "bars-evidence.sqlite3",
        "spine.sqlite3",
        "governance.sqlite3",
    ):
        (root / name).touch()
    seed = tmp_path / "seed-capital.sqlite3"
    repo = CapitalRepository.initialize(seed)
    repo.initialize_genesis(
        GenesisRequest(
            idempotency_key="genesis-r38",
            account_binding=AccountBinding(
                portfolio_id=f"pf-{TRIAL_ID}",
                mode=ExecutionMode.DAILY_BAR_PROXY,
                broker_account_id=None,
                base_currency="CNY",
                environment_fingerprint=None,
            ),
            unit_quanta=10_000,
            unit_price_numerator=1_000,
            unit_price_denominator=1,
            source_authority="governance.test",
            authorization_reference="t-r38",
            effective_at=GEN_AT,
            as_of=GEN_AT,
        )
    )
    source = TrialArmGenesisSource(capital_repository=repo)
    manifest = TrialGenesisArchive(root).seal(
        TRIAL_ID, champion_source=source, challenger_source=source
    )
    for arm in ("CHAMPION", "CHALLENGER"):
        target = arm_capital_database_path(root, TrialArm[arm])
        target.parent.mkdir(parents=True, exist_ok=True)
        restore_genesis_arm(manifest, root, target, arm=arm)
    return root


def _params_file(tmp_path: Path) -> Path:
    """seal-trial 参数文件 — 与治理契约 fixture 同源派生的可序列化形态。"""
    baseline = _trial_policy(__import__(
        "src.screening.offensive.v3.contracts.regime", fromlist=["RegimeAdmissionMode"]
    ).RegimeAdmissionMode.IGNORE)
    target = _trial_policy(__import__(
        "src.screening.offensive.v3.contracts.regime", fromlist=["RegimeAdmissionMode"]
    ).RegimeAdmissionMode.NORMAL_ONLY)
    enrollment_start = datetime(2026, 7, 1, tzinfo=UTC)
    issued_at = datetime(2026, 6, 26, 8, 0, tzinfo=UTC)
    trust_hash = "a" * 64
    params = {
        "trial_id": TRIAL_ID,
        "research_program_id": PROGRAM,
        "baseline_policy": baseline.model_dump(mode="json"),
        "target_policy": target.model_dump(mode="json"),
        "trial": {
            "family_id": "btst.limit-up-breakout",
            "economic_lineage_id": "eline-r38",
            "trust_bundle_hash": trust_hash,
            "registry_epoch": 1,
            "attempt_ledger_checkpoint_before_trial": trust_hash,
            "attempt_budget_reservation_id": "attempt-r38",
            "statistical_governance_policy_version": "stat-gov.v1",
            "champion_behavior_fingerprint": "b" * 64,
            "challenger_behavior_fingerprint": "c" * 64,
            "primary_metric": "PORTFOLIO_LOG_GROWTH",
            "minimum_economic_effect": "0.001",
            "weight_selection_rule": "fixed-50-50",
            "issued_at": issued_at.isoformat(),
            "enrollment_start": enrollment_start.isoformat(),
            "enrollment_end": datetime(2026, 8, 31, tzinfo=UTC).isoformat(),
            "followup_finality_date": datetime(2026, 9, 30, tzinfo=UTC).isoformat(),
            "fixed_assessment_date": datetime(2026, 10, 30, tzinfo=UTC).isoformat(),
            "expires_at": datetime(2026, 11, 30, tzinfo=UTC).isoformat(),
            "execution_version": "t0-close-t1-open-t10-open.v1",
            "cost_version": "cn-a-share-costs.v1",
            "execution_mode": "daily_bar_proxy",
            "benchmark_definition": "csi300-total-return",
            "capacity_policy": "capacity.v1",
            "tail_risk_policy": "tail.v1",
            "estimator": "wild-bootstrap",
            "one_sided_confidence_level": "0.95",
            "bootstrap_method": "wild",
            "bootstrap_repetitions": 2000,
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
            "expected_signal_cutoff": datetime(
                SIGNAL_DATE.year, SIGNAL_DATE.month, SIGNAL_DATE.day, 12, 0, tzinfo=UTC
            ).isoformat(),
            # 封存信任时刻须落在 enrollment 窗口内 [07-01, 08-31)。
            "trusted_at": datetime(2026, 7, 1, 8, 0, tzinfo=UTC).isoformat(),
        },
        "sap": {
            "one_sided_confidence_level": "0.95",
            "bootstrap_method": "wild",
            "repetitions": 2000,
            "seed": 42,
            "block_rule": "monthly",
            "multiplicity_policy": "program-global",
            "alpha_or_evalue_budget_consumption_id": "budget-r38",
            "expires_at": datetime(2026, 11, 30, tzinfo=UTC).isoformat(),
        },
        "activation": {
            "portfolio_id": f"pf-{TRIAL_ID}",
            "mode": "daily_bar_proxy",
            "predecessor_policy_activation_hash": "0" * 64,
            "policy_epoch": 1,
            "authority_epoch": 1,
            "risk_epoch": 1,
            "effective_from": issued_at.isoformat(),
            "expires_at": datetime(2026, 11, 30, tzinfo=UTC).isoformat(),
        },
        "stage": {
            "stage_id": "stage-r38-001",
            "stage_sample_reservation_id": "smp-r38",
            "alpha_sample_consumption_id": "alpha-r38",
            "alpha_or_evalue_budget_consumption_id": "budget-r38",
            "attempt_ledger_checkpoint_hash": "d" * 64,
            "stage_loss_budget_id": "loss-r38",
            "stage_loss_version": 1,
            "maximum_loss_budget_cents": 1_000_000,
            "issued_at": datetime(2026, 6, 26, 9, 0, tzinfo=UTC).isoformat(),
        },
    }
    path = tmp_path / "trial-params.json"
    path.write_text(json.dumps(params, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def readiness_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("readiness")
    run_injected_auto_refresh_for_20260713(root)
    return root


@pytest.fixture()
def world(tmp_path: Path, readiness_root: Path):
    from src.screening.offensive.v3.evidence.governance_identity import (
        generate_governance_identity,
    )

    identity_dir = tmp_path / "identity-v2"
    generate_governance_identity(identity_dir, clock=lambda: GEN_AT)
    root = _trial_root_world(tmp_path)
    calendar = _calendar_file(tmp_path)
    params = _params_file(tmp_path)
    return {
        "identity_dir": identity_dir,
        "root": root,
        "calendar": calendar,
        "params": params,
        "readiness_root": readiness_root,
    }


def _manifest_path(world) -> Path:
    return (
        world["readiness_root"]
        / "data"
        / "reports"
        / f"daily_action_readiness_{SIGNAL_DATE.strftime('%Y%m%d')}.json"
    )


def _run(argv: list[str], capsys) -> dict:
    try:
        rc = bootstrap_main(argv)
    except SystemExit as exc:  # _fail 以 SystemExit(2) 退出
        rc = int(exc.code)
    payload = json.loads(capsys.readouterr().out)
    assert rc == (0 if payload["ok"] else 2), payload
    return payload


def _common(argv_prefix: list[str], world) -> list[str]:
    return [
        *argv_prefix,
        "--identity-dir", str(world["identity_dir"]),
        "--trial-root", str(world["root"]),
        "--now", "2026-06-26T10:00:00+00:00",
    ]


# ---------------------------------------------------------------------------
# dry-run: 字节级零写入
# ---------------------------------------------------------------------------

class TestDryRunZeroWrite:
    @pytest.mark.parametrize(
        "argv_prefix",
        [
            ["seed-evidence", "--calendar", "", "--readiness-manifest", "", "--signal-session", ""],
            ["enroll-spine", "--calendar", "", "--start", "", "--end", ""],
            ["seal-trial", "--trial-id", "", "--params", ""],
        ],
        ids=["seed", "enroll", "seal"],
    )
    def test_dry_run_is_zero_write(self, world, capsys, argv_prefix):
        # 参数在 world 内解析后填充 (parametrize 只定形状)。
        if argv_prefix[0] == "seed-evidence":
            argv_prefix[2] = str(world["calendar"])
            argv_prefix[4] = str(_manifest_path(world))
            argv_prefix[6] = SIGNAL_DATE.isoformat()
        elif argv_prefix[0] == "enroll-spine":
            argv_prefix[2] = str(world["calendar"])
            argv_prefix[4] = SIGNAL_DATE.isoformat()
            argv_prefix[6] = (SIGNAL_DATE + timedelta(days=1)).isoformat()
        else:
            argv_prefix[2] = TRIAL_ID
            argv_prefix[4] = str(world["params"])
        before = _tree_digest(world["root"]) + _tree_digest(world["identity_dir"])
        payload = _run([*argv_prefix, *(a for a in ())], capsys) if False else _run(
            _common(argv_prefix, world), capsys
        )
        assert payload["ok"] is True
        assert payload["mode"] == "dry-run"
        after = _tree_digest(world["root"]) + _tree_digest(world["identity_dir"])
        assert after == before


# ---------------------------------------------------------------------------
# seed-evidence: execute 落地 + 与驱动器首 decide 的幂等复用
# ---------------------------------------------------------------------------

class TestSeedEvidence:
    def test_execute_seeds_and_first_decide_reuses(self, world, capsys):
        payload = _run(
            _common(
                [
                    "seed-evidence",
                    "--calendar", str(world["calendar"]),
                    "--readiness-manifest", str(_manifest_path(world)),
                    "--data-dir", str(world["readiness_root"] / "data"),
                    "--signal-session", SIGNAL_DATE.isoformat(),
                ],
                world,
            )
            + ["--execute"],
            capsys,
        )
        assert payload["ok"] is True and payload["mode"] == "execute"
        assert payload["seeded"] is True

        # 组装器 evidence_not_seeded 探测事实: regime 命名空间有 committed 记录。
        from src.screening.offensive.v3.evidence.governance_identity import (
            load_governance_identity,
        )
        from src.screening.offensive.v3.evidence.regime import RegimeObservationReader
        from src.screening.offensive.v3.evidence.session_batch import (
            REGIME_EVIDENCE_ID,
            REGIME_NAMESPACE,
        )
        from src.screening.offensive.v3 import trust as v3_trust

        identity = load_governance_identity(world["identity_dir"], trusted_at=DECIDE_AT)
        head = v3_trust.CurrentTrustHeadWitness.model_validate_json(
            json.dumps(identity.manifest["head_witness"])
        )
        repo = identity.repository_for(
            namespace=REGIME_NAMESPACE,
            database_path=str(world["root"] / "evidence.sqlite3"),
            blobs_dir=world["root"] / "blobs",
            clock=lambda: DECIDE_AT,
            trust_head=head,
        )
        active = RegimeObservationReader(repo).active(REGIME_EVIDENCE_ID, DECIDE_AT)
        assert active.observation.signal_session == SIGNAL_DATE
        repo._engine.dispose()

        # (首 decide 幂等复用种子观察的断言在 TestFullChain — 需要完整世界。)


# ---------------------------------------------------------------------------
# enroll-spine: 注册 + 冻结语义
# ---------------------------------------------------------------------------

class TestEnrollSpine:
    def test_execute_then_refrozen(self, world, capsys):
        payload = _run(
            _common(
                [
                    "enroll-spine",
                    "--calendar", str(world["calendar"]),
                    "--start", SIGNAL_DATE.isoformat(),
                    "--end", (SIGNAL_DATE + timedelta(days=2)).isoformat(),
                ],
                world,
            )
            + ["--execute"],
            capsys,
        )
        assert payload["ok"] is True and payload["enrolled"] == 3

        again = _run(
            _common(
                [
                    "enroll-spine",
                    "--calendar", str(world["calendar"]),
                    "--start", SIGNAL_DATE.isoformat(),
                    "--end", SIGNAL_DATE.isoformat(),
                ],
                world,
            )
            + ["--execute"],
            capsys,
        )
        assert again["ok"] is False
        assert again["code"] == "spine_enroll_failed"


# ---------------------------------------------------------------------------
# seal-trial: 端到端 + 同参数重放幂等
# ---------------------------------------------------------------------------

class TestSealTrial:
    def test_execute_and_replay_idempotent(self, world, capsys):
        argv = _common(
            ["seal-trial", "--trial-id", TRIAL_ID, "--params", str(world["params"])],
            world,
        ) + ["--execute"]
        first = _run(argv, capsys)
        assert first["ok"] is True and first["mode"] == "execute"
        assert first["stage_id"] == "stage-r38-001"

        # 同参数重放 = 类型化冲突 (attempt 预留 UNIQUE — 宪法 multiplicity
        # 纪律: attempt 不可免费重用)。冻结验收条款的「重放幂等收敛」在
        # seal 面不成立: stage 签发/证据发布是 insert-or-verify-exact, 而
        # attempt 预留是消耗性 — 已入册为设计观察, 不是本 op 缺陷。
        second = _run(argv, capsys)
        assert second["ok"] is False
        assert second["code"] == "seal_failed"
        assert "attempt" in second.get("details", {}).get("detail", "")


# ---------------------------------------------------------------------------
# 全链: bootstrap 三步 → 官方栈 → 驱动器 decide
# ---------------------------------------------------------------------------

class TestFullChain:
    def test_bootstrap_to_decide_end_to_end(self, tmp_path: Path, readiness_root: Path, capsys):
        from src.screening.offensive.v3.evidence.governance_identity import (
            generate_governance_identity,
        )

        identity_dir = tmp_path / "identity-v2"
        generate_governance_identity(identity_dir, clock=lambda: GEN_AT)
        root = _trial_root_world(tmp_path)
        calendar = _calendar_file(tmp_path)
        params = _params_file(tmp_path)
        world = {
            "identity_dir": identity_dir,
            "root": root,
            "calendar": calendar,
            "params": params,
            "readiness_root": readiness_root,
        }
        common = [
            "--identity-dir", str(identity_dir),
            "--trial-root", str(root),
            "--now", "2026-06-26T10:00:00+00:00",
        ]
        # ① seed-evidence
        seeded = _run(
            [
                "seed-evidence",
                "--calendar", str(calendar),
                "--readiness-manifest", str(_manifest_path(world)),
                "--data-dir", str(readiness_root / "data"),
                "--signal-session", SIGNAL_DATE.isoformat(),
                *common,
                "--execute",
            ],
            capsys,
        )
        assert seeded["ok"] is True
        # ② enroll-spine (首会话)
        enrolled = _run(
            [
                "enroll-spine",
                "--calendar", str(calendar),
                "--start", SIGNAL_DATE.isoformat(),
                "--end", SIGNAL_DATE.isoformat(),
                *common,
                "--execute",
            ],
            capsys,
        )
        assert enrolled["ok"] is True
        # ③ seal-trial
        sealed = _run(
            ["seal-trial", "--trial-id", TRIAL_ID, "--params", str(params), *common, "--execute"],
            capsys,
        )
        assert sealed["ok"] is True

        # ④ 官方栈 + 驱动器 decide (R36 驱动器消费 bootstrap 产物)。
        from src.screening.offensive.v3.capital.fills import FillAttribution
        from src.screening.offensive.v3.evidence.governance_identity import (
            load_governance_identity,
        )
        from src.screening.offensive.v3.kernel.sizing import SizingConfig
        from src.screening.offensive.v3.orchestration.arm_lifecycle import (
            CURRENT_COST_SCENARIO,
        )
        from src.screening.offensive.v3.orchestration.official_trial_stack import (
            build_official_trial_stack,
        )
        from src.screening.offensive.v3.orchestration.trial_session_driver import (
            OfficialTrialSessionDriver,
        )
        from src.screening.offensive.daily_action_snapshot import (
            load_verified_daily_action_snapshot,
        )

        stack = build_official_trial_stack(
            identity_dir=identity_dir,
            trial_root=root,
            trial_id=TRIAL_ID,
            sizing_config=SizingConfig(
                per_ticker_gross_cap_cents=20_000_000,
                per_industry_gross_cap_cents=30_000_000,
                per_day_gross_cap_cents=50_000_000,
                portfolio_gross_cap_cents=40_000_000,
                worst_case_fee_ppm=3_000,
            ),
            clock=lambda: DECIDE_AT,
            market_scenario=CURRENT_COST_SCENARIO,
            trial_attribution=FillAttribution(
                producer_namespace="btst",
                research_program_id=PROGRAM,
                economic_lineage_id="eline-r38",
                stage_id="stage-r38-001",
            ),
            research_program_id=PROGRAM,
        )
        identity = load_governance_identity(identity_dir, trusted_at=DECIDE_AT)
        driver = OfficialTrialSessionDriver(
            stack=stack,
            identity=identity,
            calendar_path=calendar,
            clock=lambda: DECIDE_AT,
        )
        driver.ensure_trial_registration()
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE,
            reports_dir=readiness_root / "data" / "reports",
            data_dir=readiness_root / "data",
        )
        assert result.snapshot is not None
        receipt = driver.decide_session(
            snapshot=result.snapshot, signal_session=SIGNAL_DATE, now=DECIDE_AT
        )
        assert receipt.pair_key == (TRIAL_ID, SIGNAL_DATE.isoformat(), f"daily-action-{SIGNAL_DATE.strftime('%Y%m%d')}")
        champion, challenger = stack.decision_store.pair(receipt.pair_key)
        assert {champion.arm, challenger.arm} == {"CHAMPION", "CHALLENGER"}

        # 首会话 regime 证据恰一 revision — 驱动器幂等复用了 bootstrap 种子
        # 观察 (criterion: 不产生第二 revision)。
        import sqlite3

        conn = sqlite3.connect(root / "evidence.sqlite3")
        try:
            revisions = conn.execute(
                "SELECT COUNT(*) FROM evidence_records"
                " WHERE issuer_namespace = 'regime'"
                " AND evidence_id = 'regime:csi300:1.0'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert revisions == 1
