#!/usr/bin/env python3
"""官方前向 Trial 启动引导器 (2026-08-25, 第三十八轮; offline primitive).

R36 驱动器落地后, runbook 启动顺序 2-4 步对 owner 仍不可执行: R35/R37
组装器冷读守卫要求 trial root 四库预置 (evidence regime 播种 / bars
schema / spine 注册 / governance 封存 + stage 回执归档), 但预置只有测试
fixture 能构造; 生产身份 v1 缺 exchange-calendar 键与全部治理签发键。
本脚本把缺口收敛为显式子命令 (与 ``v3_trial_session.py`` /
``v3_trial_genesis.py`` 同款纪律: **默认 dry-run 零写入**, ``--execute``
才真写):

  genesis-seed    (第三十九轮) fresh-world 构造器 — 四库空占位 + seed
                  台账 (DAILY_BAR_PROXY 绑定, broker_account_id=None)
                  + genesis 封存 + 双臂 restore 到 arm_layout 约定路径。
                  此前 seed 台账创建只有测试 fixture 的手工 Python 链
                  (test_trial_bootstrap._fresh_layout), runbook 按文
                  不可执行; 本命令使其一步可执行且幂等;
  seed-evidence   首会话 regime 观察播种 + bars 库 schema 落盘
                  — 与驱动器同源推导 (REGIME_EVIDENCE_ID /
                  REGIME_CLASSIFIER_FINGERPRINT / envelope 构造共享),
                  首个 ``decide`` 幂等复用种子观察, 不产生第二 revision;
  enroll-spine    从权威日历派生 enrollment 窗口注册 spine
                  (signal_session ∈ [--start, --end], assessment_date =
                  排程末位 = T+10); 二次注册类型化拒绝 (spine 冻结语义);
  seal-trial      从参数文件派生互证绑定 (SAP↔trial hash↔policy 指纹)
                  的 baseline/target PolicySnapshot + TrialManifest +
                  SAP + PolicyActivation, 用治理键签名 →
                  ``GovernanceRepository.seal_regime_trial`` →
                  ``GovernanceStageIssuer.issue`` → 回执落 trial root 归档。

诚实边界: 全部离线 primitive — 不解锁 runner 权限语义、不连 broker、
不构成资本事实; trial 参数 (策略指纹/损失预算/enrollment 窗口) 的业务
正确性由参数文件作者 (owner) 负责, 本脚本只负责派生一致性与签名链完整。
genesis-seed 的 units/unit price/source authority 是 owner 显式决策的
 genesis 经济事实 (有默认值, 落账后永久), 与任何授权/激活无关。

用法:
  uv run python scripts/v3_trial_bootstrap.py genesis-seed \\
      --trial-root <root> --trial-id <id> [--units 10000] \\
      [--unit-price-cents 1000] [--execute] [--now ISO]
  uv run python scripts/v3_trial_bootstrap.py seed-evidence \\
      --identity-dir data/v3_governance_identity --trial-root <root> \\
      --calendar data/reports/trade_calendar.json \\
      --readiness-manifest data/reports/daily_action_readiness_YYYYMMDD.json \\
      --signal-session YYYY-MM-DD [--execute] [--now ISO]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from src.screening.offensive.v3.contracts.evidence import SUPPORTED_SCHEMA_MAJOR

# 与 v3_trial_genesis 同形 (单一形状规则: 两处 grep 可互相核对的字面 regex)
_TRIAL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")

# 四库占位名 — genesis-seed 的 fresh-world 守卫对象 (R35/R37 组装器冷读
# 探测的同一组文件; genesis-seed 是它们的生产创建者)。
_PREPLACED_DB_NAMES = (
    "evidence.sqlite3",
    "bars-evidence.sqlite3",
    "spine.sqlite3",
    "governance.sqlite3",
)


def _assert_fresh_world(trial_root: Path) -> None:
    """fresh-world 零写守卫 — dry-run 与 execute 共用的单一实现 (R49)。

    每库恰好一次 ``stat(follow_symlinks=False)`` 同时取 mode 与 size：
    symlink (dangling 或指现有文件)、目录或非常规文件 →
    ``trial_root_path_rejected``；非空常规文件 → ``trial_root_not_fresh``；
    缺失 → 合法起点。此前 execute 面是独立的 ``exists()+stat()`` 两调用
    循环——检查点消失竞态下裸抛 FileNotFoundError（D7 同族，R48 D7 扫描
    漏网），且与 dry-run 面是同义而不同源的两套守卫。
    """
    for name in _PREPLACED_DB_NAMES:
        path = trial_root / name
        try:
            info = path.stat(follow_symlinks=False)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode):
            raise SystemExit(_fail("trial_root_path_rejected", name))
        if info.st_size > 0:
            raise SystemExit(
                _fail(
                    "trial_root_not_fresh",
                    "a preplaced database is non-empty; genesis-seed only"
                    " constructs a fresh world (use a new trial root)",
                    name=name,
                )
            )


def _touch_placeholder_dbs(trial_root: Path) -> None:
    """四库空占位独占无跟随创建 (R49)。

    守卫全量通过后逐库 ``O_CREAT|O_EXCL|O_NOFOLLOW`` 创建：守卫→创建
    残余窗口内出现的 symlink 被跟随拒绝、常规文件走 ``FileExistsError``
    → 全量重验空性（非空即拒，已创建的空占位不回滚——append-only 起点
    无需撤销）。0600：资本真相库，收紧此前 ``write_bytes`` 的 umask 默认。
    """
    _assert_fresh_world(trial_root)
    for name in _PREPLACED_DB_NAMES:
        path = trial_root / name
        try:
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            _assert_fresh_world(trial_root)
            continue
        except OSError as exc:
            raise SystemExit(
                _fail("trial_root_placeholder_rejected", f"{name}: {exc}", name=name)
            )
        os.close(fd)


class _PathGuardError(RuntimeError):
    """path_guards 守卫拒绝 → CLI 类型化失败的桥接异常 (code 透传)。"""

    def __init__(self, code: str, detail: str, **details: object) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.details = details


def _publication_settle():
    from src.screening.offensive.v3.orchestration.trial_session_driver import (
        _PUBLICATION_SETTLE,
    )

    return _PUBLICATION_SETTLE


def _fail(code: str, message: str, **details: object) -> int:
    print(
        json.dumps(
            {"ok": False, "code": code, "message": message, "details": details},
            ensure_ascii=False,
        )
    )
    return 2


def _ok(payload: dict) -> int:
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, default=str))
    return 0


def _parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SystemExit(_fail("now_requires_timezone", value))
    return parsed.astimezone(timezone.utc)


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _load_snapshot(
    manifest_path: Path, signal_session: date, *, data_dir: Path
):
    """真实签名三参加载 (signal_date, *, reports_dir, data_dir) + 解包。

    与 ``v3_trial_session._load_snapshot`` 同款形态: reports_dir 取 manifest
    所在目录 (loader 按日期自发现 daily_action_readiness_YYYYMMDD.json 并
    逐票核 PIT 指纹); snapshot 为 None = fail-closed (global_reason 透出)。
    """
    from src.screening.offensive.daily_action_snapshot import (
        load_verified_daily_action_snapshot,
    )

    result = load_verified_daily_action_snapshot(
        signal_session, reports_dir=manifest_path.parent, data_dir=data_dir
    )
    if result.snapshot is None:
        raise SystemExit(
            _fail(
                "snapshot_unavailable",
                "no verified daily-action snapshot for this session",
                reason=result.global_reason,
            )
        )
    return result.snapshot


def _common_checks(*, identity_dir: Path, trial_root: Path) -> dict:
    """Zero-write preflight shared by all subcommands.

    身份 verify + trial root 常规文件守卫 (lstat 家族纪律)。dry-run 与
    execute 都跑 — 拒绝发生在任何写副作用之前。注意 dry-run 绝不构造任何
    repository/store (它们的 __init__ 落 WAL+DDL), 只做磁盘形态检查。
    """
    from src.screening.offensive.v3.evidence.governance_identity import (
        GovernanceIdentityError,
        verify_identity_directory,
    )

    try:
        summary = verify_identity_directory(identity_dir)
    except GovernanceIdentityError as exc:
        raise SystemExit(_fail("identity_check_failed", str(exc)))
    for name in (
        "evidence.sqlite3",
        "bars-evidence.sqlite3",
        "spine.sqlite3",
        "governance.sqlite3",
    ):
        path = trial_root / name
        if not path.is_file():
            raise SystemExit(_fail("trial_root_not_initialized", name))
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise SystemExit(_fail("trial_root_path_rejected", name))
    return {"namespaces": summary.get("namespaces")}


def _seed_observation(snapshot: object, signal_session: date, now: datetime):
    """Seed observation — 驱动器 ``_publish_regime_observation`` 的同源推导。

    与驱动器共享 REGIME_EVIDENCE_ID / REGIME_CLASSIFIER_FINGERPRINT /
    envelope 字段 (单一实现来自被导入的常量与同一 SnapshotEvidence 形状);
    测试钉住「种子观察 == 同 manifest 下驱动器首 decide 会产出的观察」,
    使首个 decide 走幂等复用路径而非第二 revision。
    """
    from src.screening.offensive.v3.contracts.base import (
        EvidenceScope,
        ExecutionMode,
    )
    from src.screening.offensive.v3.contracts.evidence import SnapshotEvidence
    from src.screening.offensive.v3.contracts.regime import (
        RegimeObservation,
        RegimeObservationReason,
        RegimeSourceRevision,
    )
    from src.screening.offensive.v3.contracts.regime import (
        normalize_regime_state,
    )
    from src.screening.offensive.v3.evidence.session_batch import (
        REGIME_EVIDENCE_ID,
    )
    from src.screening.offensive.v3.orchestration.trial_session_driver import (
        _HEX,
        _REGIME_FINGERPRINT_PREFIX,
        REGIME_CLASSIFIER_FINGERPRINT,
    )

    state, reason = normalize_regime_state(
        snapshot.regime,
        reason_if_missing=RegimeObservationReason.MISSING_REQUIRED_INPUT,
    )
    # 与驱动器 _regime_source_artifact_hash 同源: 剥前缀后必须是 sha256
    # hex (拒绝把捏造来源绑进证据时间轴)。常量 import 非字面量复制。
    fingerprint = snapshot.manifest.shared_evidence.regime_fingerprint
    if fingerprint.startswith(_REGIME_FINGERPRINT_PREFIX):
        fingerprint = fingerprint[len(_REGIME_FINGERPRINT_PREFIX):]
    if len(fingerprint) != 64 or not _HEX.issuperset(fingerprint.lower()):
        raise SystemExit(
            _fail(
                "regime_source_fingerprint_invalid",
                "the readiness manifest's regime fingerprint is not a"
                " sha256 hex digest; refusing to bind a fabricated source",
                fingerprint=str(fingerprint),
            )
        )
    observation = RegimeObservation(
        signal_session=signal_session,
        state=state,
        reason=reason,
        raw_state=snapshot.regime,
        source_revisions=(
            RegimeSourceRevision(
                evidence_id=(
                    f"readiness:{snapshot.manifest.domain}:"
                    f"{snapshot.manifest.run_id}"
                ),
                revision=1,
                artifact_hash=fingerprint,
            ),
        ),
        effective_at=now,
        provider_published_at=now,
        observed_at=now,
        classifier_semver="1.0.0",
        behavior_fingerprint=REGIME_CLASSIFIER_FINGERPRINT,
        input_schema_hash=REGIME_CLASSIFIER_FINGERPRINT,
    )
    envelope = SnapshotEvidence(
        evidence_id=REGIME_EVIDENCE_ID,
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer="regime",
        family_id=None,
        strategy_semver="1.0.0",
        behavior_fingerprint=REGIME_CLASSIFIER_FINGERPRINT,
        policy_epoch=1,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=now,
        provider_published_at=now,
        observed_at=now,
        available_at=now,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="regime.classifier",
        payload_content_hash=hashlib.sha256(
            observation.canonical_bytes()
        ).hexdigest(),
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="snapshot",
    )
    return observation, envelope


def _cmd_genesis_seed(args: argparse.Namespace) -> int:
    """genesis-seed — runbook 启动序列第 0/1 步的生产入口 (第三十九轮)。

    把此前只有测试 fixture 能构造的世界构造 (test_trial_bootstrap
    ``_fresh_layout`` 的手工 Python 链) 收敛为一条命令: 四库空占位 +
    seed 台账 (DAILY_BAR_PROXY 绑定) + genesis 封存 + 双臂 restore。
    全部消费既有单一实现 (CapitalRepository/TrialGenesisArchive/
    arm_layout/restore_genesis_arm), 本命令零新资本语义。

    纪律: dry-run 默认字节级零写入 (连 trial root 目录都不创建); 拒绝
    发生在任何写副作用之前 (canonical 绝对路径/fresh-world/形状校验);
    同参数重放幂等 (seed 幂等键 + archive 恰等幂等 + restore 覆写同字节)。
    """
    now = _parse_now(args.now)
    trial_root = Path(args.trial_root)
    trial_id = args.trial_id

    if _TRIAL_ID_RE.fullmatch(trial_id) is None:
        raise SystemExit(
            _fail(
                "trial_id_invalid",
                "trial id must match ^[a-z0-9][a-z0-9-]{2,63}$",
                trial_id=trial_id,
            )
        )
    if not trial_root.is_absolute():
        raise SystemExit(
            _fail(
                "trial_root_not_absolute",
                "the capital truth layer requires a canonical absolute"
                " trial root (path guards reject relative paths)",
                trial_root=str(trial_root),
            )
        )
    if args.units <= 0:
        raise SystemExit(_fail("units_invalid", str(args.units)))
    if args.unit_price_cents <= 0:
        raise SystemExit(_fail("unit_price_invalid", str(args.unit_price_cents)))

    # fresh-world 守卫 (零写): 四库占位存在且非空 = 世界已越权初始化。
    # 缺失/空 0 字节是合法起点 (execute 期补 touch)。dry-run 与 execute
    # 共用同一单一实现 — R49 前是同义而不同源的两套循环。
    _assert_fresh_world(trial_root)

    if not args.execute:
        return _ok(
            {
                "mode": "dry-run",
                "plan": [
                    "ensure trial root directory (guarded components)",
                    "touch the four empty db placeholders",
                    "initialize seed capital ledger"
                    " (DAILY_BAR_PROXY binding, broker_account_id=None)",
                    f"record genesis units ({args.units} units @"
                    f" {args.unit_price_cents} cents) — idempotency key"
                    f" bootstrap:{trial_id}",
                    "seal paired genesis archive (content-addressed)",
                    "restore both arms to <trial_root>/arms/<arm>/capital.sqlite3",
                ],
                "trial_id": trial_id,
                "trial_root": str(trial_root),
                "units": args.units,
                "unit_price_cents": args.unit_price_cents,
                "source_authority": args.source_authority,
                "authorization_reference": (
                    args.authorization_reference
                    if args.authorization_reference is not None
                    else f"bootstrap:{trial_id}"
                ),
            }
        )

    # ---- execute ----
    from src.screening.offensive.v3.capital.flows import GenesisRequest
    from src.screening.offensive.v3.capital.identity import AccountBinding
    from src.screening.offensive.v3.capital.repository import (
        CapitalConflict,
        CapitalRepository,
    )
    from src.screening.offensive.v3.contracts.base import ExecutionMode
    from src.screening.offensive.v3.contracts.trial import TrialArm
    from src.screening.offensive.v3.orchestration.arm_layout import (
        arm_capital_database_path,
    )
    from src.screening.offensive.v3.orchestration.genesis import (
        TrialArmGenesisSource,
        TrialGenesisArchive,
        TrialGenesisError,
        restore_genesis_arm,
    )
    from src.screening.offensive.v3.orchestration.path_guards import (
        ensure_directory_components,
    )

    def _guard_fail(exc: _PathGuardError, *, surface: str) -> SystemExit:
        return SystemExit(
            _fail(surface, str(exc), guard_code=exc.code)
        )

    try:
        ensure_directory_components(
            trial_root,
            fail=_PathGuardError,
            missing_code="trial_root_component_missing",
            rejected_code="trial_root_component_rejected",
        )
    except _PathGuardError as exc:
        raise _guard_fail(exc, surface="trial_root_rejected")

    # 四库空占位。execute 期重验空性 (dry-run 与 --execute 之间可能隔了
    # 任意长的墙钟; 陈旧 dry-run 的放行不构成 execute 的事实) — 任一非空
    # 即拒绝, 与零写阶段同码。独占无跟随创建关闭守卫→创建残余窗口 (R49)。
    _touch_placeholder_dbs(trial_root)

    seed_dir = trial_root / "genesis-seed"
    try:
        ensure_directory_components(
            seed_dir,
            fail=_PathGuardError,
            missing_code="seed_dir_component_missing",
            rejected_code="seed_dir_component_rejected",
        )
    except _PathGuardError as exc:
        raise _guard_fail(exc, surface="seed_dir_rejected")
    seed_path = seed_dir / "seed-capital.sqlite3"

    try:
        repo = CapitalRepository.initialize(seed_path)
        repo.initialize_genesis(
            GenesisRequest(
                idempotency_key=f"bootstrap:{trial_id}",
                account_binding=AccountBinding(
                    portfolio_id=f"pf-{trial_id}",
                    mode=ExecutionMode.DAILY_BAR_PROXY,
                    broker_account_id=None,
                    base_currency="CNY",
                    environment_fingerprint=None,
                ),
                unit_quanta=args.units,
                unit_price_numerator=args.unit_price_cents,
                unit_price_denominator=1,
                source_authority=args.source_authority,
                authorization_reference=(
                    args.authorization_reference
                    if args.authorization_reference is not None
                    else f"bootstrap:{trial_id}"
                ),
                effective_at=now,
                as_of=now,
            )
        )
        source = TrialArmGenesisSource(capital_repository=repo)
        manifest = TrialGenesisArchive(trial_root).seal(
            trial_id, champion_source=source, challenger_source=source
        )
        arms = {}
        for arm in ("CHAMPION", "CHALLENGER"):
            target = arm_capital_database_path(trial_root, TrialArm[arm])
            restore_genesis_arm(manifest, trial_root, target, arm=arm)
            arms[arm.lower()] = str(target)
    except (CapitalConflict, TrialGenesisError) as exc:
        raise SystemExit(
            _fail(
                getattr(exc, "code", "genesis_seed_failed"),
                str(exc),
            )
        )

    return _ok(
        {
            "mode": "execute",
            "trial_id": manifest.trial_id,
            "genesis_manifest_hash": hashlib.sha256(
                (trial_root / trial_id / "genesis-manifest.json").read_bytes()
            ).hexdigest(),
            "seed_ledger": str(seed_path),
            "arms": arms,
            "units": args.units,
            "unit_price_cents": args.unit_price_cents,
        }
    )


def _cmd_seed_evidence(args: argparse.Namespace) -> int:
    now = _parse_now(args.now)
    identity_dir = Path(args.identity_dir)
    trial_root = Path(args.trial_root)
    checks = _common_checks(identity_dir=identity_dir, trial_root=trial_root)

    from src.screening.offensive.v3.evidence.trading_schedule import (
        TradingScheduleError,
        load_authoritative_dates,
    )

    try:
        calendar_dates = load_authoritative_dates(Path(args.calendar))
    except (TradingScheduleError, OSError) as exc:
        raise SystemExit(_fail("calendar_unreadable", str(exc)))
    signal_session = _parse_date(args.signal_session)
    if signal_session not in calendar_dates:
        raise SystemExit(
            _fail(
                "signal_session_not_in_calendar",
                "the signal session is absent from the authoritative calendar",
                signal_session=signal_session.isoformat(),
            )
        )
    if not args.execute:
        return _ok(
            {
                "mode": "dry-run",
                "plan": [
                    "publish seed regime observation (fixed"
                    " REGIME_EVIDENCE_ID, readiness-fingerprint bound)",
                    "initialize bars store schema (zero records)",
                ],
                **(checks or {}),
            }
        )

    snapshot = _load_snapshot(
        Path(args.readiness_manifest), signal_session, data_dir=Path(args.data_dir)
    )

    from src.screening.offensive.v3 import trust as v3_trust
    from src.screening.offensive.v3.evidence.governance_identity import (
        load_governance_identity,
    )
    from src.screening.offensive.v3.evidence.regime import (
        RegimeObservationPublisher,
        RegimeObservationReader,
    )
    from src.screening.offensive.v3.evidence.repository import EvidenceStoreError
    from src.screening.offensive.v3.evidence.session_batch import REGIME_NAMESPACE

    # 不经 build_official_trial_stack (那会触发治理封存前置探测, 而封存
    # 可能尚未发生); 直接 identity.repository_for 构造发布仓库。dry-run
    # 已在上游完成磁盘形态检查, execute 期 repository 构造落 WAL+DDL 是
    # 本命令的目的本身。
    identity = load_governance_identity(identity_dir, trusted_at=now)
    head = v3_trust.CurrentTrustHeadWitness.model_validate_json(
        json.dumps(identity.manifest["head_witness"])
    )
    blobs = trial_root / "blobs"

    class _SnapshotSignerPort:
        def __init__(self, signer) -> None:
            self._signer = signer

        def sign_snapshot(self, snapshot: object, payload: bytes):
            return self._signer(payload)

    regime_repo = identity.repository_for(
        namespace=REGIME_NAMESPACE,
        database_path=str(trial_root / "evidence.sqlite3"),
        blobs_dir=blobs,
        clock=lambda: now,
        trust_head=head,
    )
    bars_repo = identity.repository_for(
        namespace="btst-bars",
        database_path=str(trial_root / "bars-evidence.sqlite3"),
        blobs_dir=blobs,
        clock=lambda: now,
        trust_head=head,
    )

    observation, envelope = _seed_observation(snapshot, signal_session, now)
    publisher = RegimeObservationPublisher(regime_repo)
    reader = RegimeObservationReader(regime_repo)

    class _SignerPort:
        def __init__(self, signer) -> None:
            self._inner = signer

        def sign_snapshot(self, snap: object, payload: bytes):
            return self._inner(payload)

    probe_cutoff = now + _publication_settle()
    existing = None
    try:
        active = reader.active(envelope.evidence_id, probe_cutoff)
        existing = active
    except EvidenceStoreError as exc:
        # P2-1 纪律 (驱动器同款 _store_code 分流): 只吞「cutoff 前无提交」
        # 缺席; 其余仓库错误 propagate — 宽吞会假装没看到坏记录。
        if str(exc).partition(":")[0] != "evidence_not_committed_before_cutoff":
            raise

    seeded: bool
    if existing is None:
        publisher.publish(
            observation, envelope, _SignerPort(identity.signer_for(REGIME_NAMESPACE))
        )
        seeded = True
    else:
        if (
            existing.observation != observation
            or existing.record.evidence.payload_content_hash
            != envelope.payload_content_hash
        ):
            raise SystemExit(
                _fail(
                    "seed_conflict",
                    "an active regime observation already exists with"
                    " different content; the fixed evidence id carries one"
                    " truth per session lineage",
                )
            )
        seeded = False
    regime_repo._engine.dispose()

    # bars 库 schema 落盘 (零记录是合法启动形态; 构造即 DDL), dispose 冷读。
    bars_repo._engine.dispose()

    return _ok(
        {
            "mode": "execute",
            "seeded": seeded,
            "reused_existing": not seeded,
            "signal_session": signal_session.isoformat(),
        }
    )


def _cmd_enroll_spine(args: argparse.Namespace) -> int:
    now = _parse_now(args.now)
    identity_dir = Path(args.identity_dir)
    trial_root = Path(args.trial_root)
    checks = _common_checks(identity_dir=identity_dir, trial_root=trial_root)
    start = _parse_date(args.start)
    end = _parse_date(args.end)
    if end < start:
        raise SystemExit(_fail("window_inverted", "end precedes start"))

    from src.screening.offensive.v3.evidence.trading_schedule import (
        FOLLOWING_SESSION_COUNT,
        TradingScheduleError,
        derive_trading_schedule,
        load_authoritative_dates,
    )

    try:
        calendar_dates = load_authoritative_dates(Path(args.calendar))
    except (TradingScheduleError, OSError) as exc:
        raise SystemExit(_fail("calendar_unreadable", str(exc)))

    enrollments = []
    gaps = []
    for session in sorted(d for d in calendar_dates if start <= d <= end):
        try:
            schedule = derive_trading_schedule(
                signal_session=session,
                calendar_dates=calendar_dates,
                available_at=now,
            )
        except TradingScheduleError as exc:
            gaps.append({"session": session.isoformat(), "reason": str(exc)})
            continue
        enrollments.append((session, schedule.following_sessions[-1]))
    if not enrollments and not args.execute:
        raise SystemExit(
            _fail("enrollment_window_empty", "no enrollable sessions in window")
        )
    if not args.execute:
        return _ok(
            {
                "mode": "dry-run",
                "plan": ["enroll expected sessions (assessment = T+10)"],
                "sessions": [s.isoformat() for s, _ in enrollments],
                "insufficient_forward_sessions": gaps,
                **(checks or {}),
            }
        )
    if not enrollments:
        raise SystemExit(
            _fail("enrollment_window_empty", "no enrollable sessions in window")
        )

    from src.screening.offensive.v3.evidence.session_spine import (
        SessionEnrollment,
        SessionSpine,
        SessionSpineError,
    )

    spine = SessionSpine(
        database_path=str(trial_root / "spine.sqlite3"), clock=lambda: now
    )
    try:
        count = spine.enroll_expected_sessions(
            tuple(
                SessionEnrollment(args.research_program, session, assessment)
                for session, assessment in enrollments
            )
        )
    except SessionSpineError as exc:
        raise SystemExit(
            _fail(
                "spine_enroll_failed",
                str(exc),
                spine_code=exc.code,
            )
        )
    finally:
        # 冷读纪律 (R35): 引擎 dispose 使 -wal 确定性 checkpoint 进主文件,
        # 官方栈组装器的冷读探测才能看到已落盘的 enrollment。
        spine._engine.dispose()
    return _ok(
        {
            "mode": "execute",
            "enrolled": count,
            "first_session": enrollments[0][0].isoformat(),
            "last_assessment": enrollments[-1][1].isoformat(),
            "following_session_count": FOLLOWING_SESSION_COUNT,
        }
    )


def _cmd_seal_trial(args: argparse.Namespace) -> int:
    now = _parse_now(args.now)
    identity_dir = Path(args.identity_dir)
    trial_root = Path(args.trial_root)
    checks = _common_checks(identity_dir=identity_dir, trial_root=trial_root)
    params_path = Path(args.params)
    if not params_path.is_file():
        raise SystemExit(_fail("params_missing", str(params_path)))
    try:
        raw_params = json.loads(params_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(_fail("params_unparsable", str(exc)))
    required_keys = (
        "trial_id",
        "research_program_id",
        "baseline_policy",
        "target_policy",
        "trial",
        "sap",
        "activation",
        "stage",
    )
    missing = [key for key in required_keys if key not in raw_params]
    if missing:
        raise SystemExit(_fail("params_incomplete", "missing keys", missing=missing))
    if raw_params["trial_id"] != args.trial_id:
        raise SystemExit(
            _fail(
                "params_trial_mismatch",
                "--trial-id and params.trial_id disagree",
            )
        )
    stage_id = raw_params["stage"].get("stage_id")
    if not stage_id:
        raise SystemExit(_fail("params_stage_id_missing", "stage.stage_id"))
    if not args.execute:
        return _ok(
            {
                "mode": "dry-run",
                "plan": [
                    "derive mutually-bound artifacts (SAP binds trial hash,"
                    " manifests bind policy fingerprints)",
                    "sign with governance issuer keys (4 namespaces)",
                    "seal_regime_trial → GovernanceStageIssuer.issue →"
                    " archive receipt to trial root",
                ],
                "stage_id": stage_id,
                **(checks or {}),
            }
        )

    from decimal import Decimal

    from src.screening.offensive.v3.contracts.base import ExecutionMode
    from src.screening.offensive.v3.contracts.governance import PrimaryMetric
    from src.screening.offensive.v3.evidence.governance_identity import (
        _issuer_id_for,
        load_governance_identity,
    )
    from src.screening.offensive.v3.governance.regime_trial import (
        target_policy_registration_hash,
    )
    from src.screening.offensive.v3.governance.repository import (
        GovernanceRepository,
        GovernanceStoreError,
        RegimeTrialSealRequest,
    )
    from src.screening.offensive.v3.governance.stage_issuance import (
        GovernanceStageIssuer,
        StageIssuanceError,
        StageIssuanceRequest,
    )
    from src.screening.offensive.v3.contracts.governance import (
        PolicyActivation,
        StatisticalAnalysisPlan,
        TrialManifest,
    )
    from src.screening.offensive.v3.policy.models import PolicySnapshot

    # 严格模型经 JSON 面 reconstruction (model_dump(mode="json") 的产物
    # 直接 model_validate 会被 strict 类型拒绝 — model_validate_json 是
    # CanonicalModel 的正规往返面, 指纹逐位一致)。
    baseline = PolicySnapshot.model_validate_json(
        json.dumps(raw_params["baseline_policy"])
    )
    target = PolicySnapshot.model_validate_json(
        json.dumps(raw_params["target_policy"])
    )

    def _dt(section: dict, key: str) -> datetime:
        value = datetime.fromisoformat(section[key])
        if value.tzinfo is None:
            raise SystemExit(
                _fail("params_time_requires_timezone", f"{section}.{key}")
            )
        return value.astimezone(timezone.utc)

    p_trial = raw_params["trial"]
    p_sap = raw_params["sap"]
    p_act = raw_params["activation"]
    p_stage = raw_params["stage"]

    issued_at = _dt(p_trial, "issued_at")
    if issued_at > now:
        raise SystemExit(
            _fail(
                "future_issuance_instant",
                "trial issued_at cannot be ahead of the injected clock",
                issued_at=issued_at.isoformat(),
            )
        )
    # 信任头绑定从磁盘身份派生 (单一事实源): 参数文件不供给 trust_bundle
    # hash/epoch — 伪造的信任头在封存验签时才会被拒, 这里提前 fail-closed
    # 并保证 manifest/activation 与身份目录逐值一致。
    from src.screening.offensive.v3 import trust as v3_trust

    _identity_for_head = load_governance_identity(identity_dir, trusted_at=now)
    trust_bundle_hash = _identity_for_head.manifest["head_witness"][
        "active_trust_bundle_hash"
    ]
    registry_epoch = int(
        _identity_for_head.manifest["head_witness"]["registry_epoch"]
    )

    activation = PolicyActivation(
        portfolio_id=p_act["portfolio_id"],
        broker_account_id=p_act.get("broker_account_id"),
        broker_account_fingerprint=p_act.get("broker_account_fingerprint"),
        mode=ExecutionMode(p_act["mode"]),
        policy_snapshot_hash=baseline.policy_fingerprint,
        predecessor_policy_activation_hash=p_act["predecessor_policy_activation_hash"],
        trust_bundle_hash=trust_bundle_hash,
        registry_epoch=registry_epoch,
        policy_epoch=int(p_act["policy_epoch"]),
        authority_epoch=int(p_act["authority_epoch"]),
        risk_epoch=int(p_act["risk_epoch"]),
        effective_from=_dt(p_act, "effective_from"),
        expires_at=_dt(p_act, "expires_at"),
        issuer_id=_issuer_id_for("governance.policy.activation"),
        issuer_capability="governance.policy.activation.v1",
        schema_major=2,
    )

    trial = TrialManifest(
        family_id=p_trial["family_id"],
        economic_lineage_id=p_trial["economic_lineage_id"],
        research_program_id=raw_params["research_program_id"],
        trial_id=raw_params["trial_id"],
        baseline_portfolio_policy_fingerprint=baseline.policy_fingerprint,
        target_portfolio_policy_fingerprint=target.policy_fingerprint,
        trust_bundle_hash=trust_bundle_hash,
        registry_epoch=registry_epoch,
        # activation 哈希从派生对象计算 (互证绑定): trial manifest 绑定的
        # 就是本次封存的 activation 字节, 不接受外部声称值。
        baseline_policy_activation_hash=activation.artifact_hash(),
        target_policy_snapshot_registration_hash=target_policy_registration_hash(target),
        attempt_ledger_checkpoint_before_trial=(
            p_trial["attempt_ledger_checkpoint_before_trial"]
        ),
        attempt_budget_reservation_id=p_trial["attempt_budget_reservation_id"],
        statistical_governance_policy_version=(
            p_trial["statistical_governance_policy_version"]
        ),
        champion_behavior_fingerprint=p_trial["champion_behavior_fingerprint"],
        challenger_behavior_fingerprint=p_trial["challenger_behavior_fingerprint"],
        primary_metric=PrimaryMetric(p_trial["primary_metric"]),
        minimum_economic_effect=Decimal(str(p_trial["minimum_economic_effect"])),
        weight_selection_rule=p_trial["weight_selection_rule"],
        trial_manifest_sealed_at=issued_at,
        enrollment_start=_dt(p_trial, "enrollment_start"),
        enrollment_end=_dt(p_trial, "enrollment_end"),
        followup_finality_date=_dt(p_trial, "followup_finality_date"),
        fixed_assessment_date=_dt(p_trial, "fixed_assessment_date"),
        execution_version=p_trial["execution_version"],
        cost_version=p_trial["cost_version"],
        execution_mode=ExecutionMode(p_trial["execution_mode"]),
        benchmark_definition=p_trial["benchmark_definition"],
        capacity_policy=p_trial["capacity_policy"],
        tail_risk_policy=p_trial["tail_risk_policy"],
        estimator=p_trial["estimator"],
        one_sided_confidence_level=Decimal(str(p_trial["one_sided_confidence_level"])),
        bootstrap_method=p_trial["bootstrap_method"],
        bootstrap_repetitions=int(p_trial["bootstrap_repetitions"]),
        bootstrap_seed=int(p_trial["bootstrap_seed"]),
        block_rule=p_trial["block_rule"],
        ess_definition=p_trial["ess_definition"],
        missing_censoring_itt_rule=p_trial["missing_censoring_itt_rule"],
        fold_boundaries=tuple(p_trial["fold_boundaries"]),
        purge_embargo=p_trial["purge_embargo"],
        promotion_boolean_expression=p_trial["promotion_boolean_expression"],
        multiplicity_policy=p_trial["multiplicity_policy"],
        broker_experiment_design=p_trial.get("broker_experiment_design"),
        canonical_outcome_counting_rule=p_trial["canonical_outcome_counting_rule"],
        stage_loss_measurement_basis=p_trial["stage_loss_measurement_basis"],
        issuer_id=_issuer_id_for("governance.trial.manifest"),
        issuer_capability="governance.trial.manifest.v1",
        issued_at=issued_at,
        expires_at=_dt(p_trial, "expires_at"),
        schema_major=2,
    )

    sap = StatisticalAnalysisPlan(
        sap_id=p_sap.get("sap_id", raw_params["trial_id"]),
        trial_manifest_hash=trial.artifact_hash(),
        research_program_id=trial.research_program_id,
        economic_lineage_id=trial.economic_lineage_id,
        primary_metric=trial.primary_metric,
        baseline_portfolio_policy_fingerprint=(trial.baseline_portfolio_policy_fingerprint),
        target_portfolio_policy_fingerprint=(trial.target_portfolio_policy_fingerprint),
        execution_mode=trial.execution_mode,
        one_sided_confidence_level=Decimal(str(p_sap["one_sided_confidence_level"])),
        bootstrap_method=p_sap["bootstrap_method"],
        repetitions=int(p_sap["repetitions"]),
        seed=int(p_sap["seed"]),
        block_rule=p_sap["block_rule"],
        multiplicity_policy=p_sap["multiplicity_policy"],
        alpha_or_evalue_budget_consumption_id=(
            p_sap["alpha_or_evalue_budget_consumption_id"]
        ),
        issued_at=issued_at,
        sealed_at=issued_at,
        enrollment_start=trial.enrollment_start,
        expires_at=_dt(p_sap, "expires_at"),
        issuer_id=_issuer_id_for("governance.sap.manifest"),
        issuer_capability="governance.sap.v1",
        schema_major=2,
    )

    # 复用信任头加载 (单一实现): manifest 同一磁盘字节, 不重复加载。
    identity = _identity_for_head

    head = v3_trust.CurrentTrustHeadWitness.model_validate_json(
        json.dumps(identity.manifest["head_witness"])
    )

    governance = GovernanceRepository(
        database_path=str(trial_root / "governance.sqlite3"), clock=lambda: now
    )
    verifier = identity.verifier

    def sign_with(namespace: str):
        signer = identity.signer_for(namespace)
        capability = identity.capabilities[namespace]

        def sign(payload: bytes):
            return signer(payload)

        return sign, capability

    trial_sign, trial_cap = sign_with("governance.trial.manifest")
    sap_sign, sap_cap = sign_with("governance.sap.manifest")
    act_sign, act_cap = sign_with("governance.policy.activation")

    request = RegimeTrialSealRequest(
        stage_id=stage_id,
        signed_trial_envelope=trial_sign(trial.canonical_bytes()),
        trial_manifest=trial,
        trial_capability=trial_cap,
        signed_sap_envelope=sap_sign(sap.canonical_bytes()),
        sap_manifest=sap,
        sap_capability=sap_cap,
        signed_baseline_activation_envelope=act_sign(activation.canonical_bytes()),
        baseline_policy_activation=activation,
        baseline_activation_capability=act_cap,
        baseline_policy=baseline,
        target_policy=target,
        expected_signal_cutoff=_dt(p_trial, "expected_signal_cutoff"),
    )
    try:
        seal_receipt = governance.seal_regime_trial(
            request, verifier=verifier, current_head=head,
            trusted_at=_dt(p_trial, "trusted_at"),
        )
    except GovernanceStoreError as exc:
        raise SystemExit(
            _fail(
                "seal_failed",
                str(exc),
                store_code=exc.code,
                **exc.details,
            )
        )

    stage_sign, stage_cap = sign_with("governance.stage.manifest")
    issuer = GovernanceStageIssuer(
        repository=governance,
        signer=stage_sign,
        stage_capability=stage_cap,
        verifier=verifier,
        trust_head=lambda: head,
        clock=lambda: now,
    )
    stage_request = StageIssuanceRequest(
        trial_id=raw_params["trial_id"],
        stage_id=stage_id,
        stage_sample_reservation_id=p_stage["stage_sample_reservation_id"],
        alpha_sample_consumption_id=p_stage["alpha_sample_consumption_id"],
        alpha_or_evalue_budget_consumption_id=(
            p_stage["alpha_or_evalue_budget_consumption_id"]
        ),
        attempt_ledger_checkpoint_hash=p_stage["attempt_ledger_checkpoint_hash"],
        stage_loss_budget_id=p_stage["stage_loss_budget_id"],
        stage_loss_version=int(p_stage["stage_loss_version"]),
        maximum_loss_budget_cents=int(p_stage["maximum_loss_budget_cents"]),
        issuer_id=_issuer_id_for("governance.stage.manifest"),
        issued_at=_dt(p_stage, "issued_at"),
    )
    try:
        receipt = issuer.issue(stage_request)
    except (StageIssuanceError, GovernanceStoreError) as exc:
        raise SystemExit(
            _fail(
                "stage_issue_failed",
                str(exc),
                store_code=getattr(exc, "code", ""),
            )
        )

    from src.screening.offensive.v3.orchestration.stage_archive import (
        StageArchiveError,
        write_stage_issuance_receipt,
    )

    try:
        archive_path = write_stage_issuance_receipt(trial_root, receipt)
    except StageArchiveError as exc:
        raise SystemExit(
            _fail("archive_failed", str(exc), archive_code=exc.code)
        )
    finally:
        # 冷读纪律 (R35/R37): 封存/签发进程终止前确定性 checkpoint,
        # 组装器冷读探测才看到主文件事实而非未 checkpoint 的 -wal。
        governance._engine.dispose()
    return _ok(
        {
            "mode": "execute",
            "trial_sealed_at": seal_receipt.sealed_at.isoformat(),
            "trial_manifest_hash": seal_receipt.trial_manifest_hash,
            "stage_id": stage_id,
            "receipt_archived_to": str(archive_path),
        }
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--identity-dir", required=True)
        p.add_argument("--trial-root", required=True)
        p.add_argument("--research-program", default="research.btst.regime")
        p.add_argument("--now", default=None, help="UTC ISO instant (default: now)")
        p.add_argument("--execute", action="store_true", help="real writes (default: dry-run)")

    genesis = sub.add_parser(
        "genesis-seed",
        help="fresh-world constructor: 4 db placeholders + seed capital ledger"
        " + paired genesis seal + both arms (no identity needed — capital plane)",
    )
    genesis.add_argument("--trial-root", required=True)
    genesis.add_argument("--trial-id", required=True)
    genesis.add_argument(
        "--units", type=int, default=10_000, help="genesis unit quanta (default 10000)"
    )
    genesis.add_argument(
        "--unit-price-cents",
        type=int,
        default=1_000,
        help="genesis unit price in integer cents (default 1000 = ¥10.00)",
    )
    genesis.add_argument(
        "--source-authority",
        default="governance.bootstrap",
        help="genesis attribution recorded permanently in the capital ledger",
    )
    genesis.add_argument(
        "--authorization-reference",
        default=None,
        help="authorization reference (default: bootstrap:{trial_id})",
    )
    genesis.add_argument("--now", default=None, help="UTC ISO instant (default: now)")
    genesis.add_argument("--execute", action="store_true", help="real writes (default: dry-run)")
    genesis.set_defaults(func=_cmd_genesis_seed)

    seed = sub.add_parser("seed-evidence", help="seed first-session regime evidence + bars schema")
    common(seed)
    seed.add_argument("--calendar", required=True)
    seed.add_argument("--readiness-manifest", required=True)
    seed.add_argument("--data-dir", default="data")
    seed.add_argument("--signal-session", required=True)
    seed.set_defaults(func=_cmd_seed_evidence)

    enroll = sub.add_parser("enroll-spine", help="register expected sessions (assessment = T+10)")
    common(enroll)
    enroll.add_argument("--calendar", required=True)
    enroll.add_argument("--start", required=True, help="window start YYYY-MM-DD (inclusive)")
    enroll.add_argument("--end", required=True, help="window end YYYY-MM-DD (inclusive)")
    enroll.set_defaults(func=_cmd_enroll_spine)

    seal = sub.add_parser("seal-trial", help="seal paired trial bundle + issue stage receipt")
    common(seal)
    seal.add_argument("--trial-id", required=True)
    seal.add_argument("--params", required=True, help="trial parameters JSON file")
    seal.set_defaults(func=_cmd_seal_trial)
    return parser


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
