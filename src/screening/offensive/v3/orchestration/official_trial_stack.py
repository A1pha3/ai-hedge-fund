"""官方 Trial 运行栈组装器 — 真实治理身份接线 (2026-08-23, R27).

把散落的原语 (治理身份目录 / arm_layout 资本约定 / SessionSpine / 决策库
/ 三入口 runner) 组装成**从磁盘一次构造**的官方运行栈 — runbook 启动顺序
第 2-3 步的落地。此前官方链全部在测试夹具 (ephemeral rig) 上验证; 本层
之后, ephemeral 只在测试/播种, 官方栈的每个签名面都来自持久身份目录。

布局约定 (trial root 单库形态 + arm_layout 唯一权威):

    <trial_root>/
      evidence.sqlite3          # regime/schedule/btst 三命名空间共库
      bars-evidence.sqlite3     # bar-set 证据 (btst-bars 命名空间)
      spine.sqlite3             # SessionSpine (append-only)
      decisions.sqlite3         # TrialArmDecisionStore
      governance.sqlite3        # 治理库 (由封存流程预置, 本层只读路径暴露)
      arms/<champion|challenger>/capital.sqlite3   # arm_layout 约定

诚实边界: 治理库的 trial/seal 由封存流程 (genesis/签发) 预置, 本层不
重签; stage 签发密钥不在当前身份目录 namespace 清单内 (v1 只覆盖证据
发布面) — 身份目录 v2 轮换时补, 此前 stage 回执经归档冷读消费。本层
不解锁任何权限、不连接 broker; 它只是把"官方栈构造"从散件变成一个
可审计的函数。
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Final

from src.screening.offensive.v3.evidence.governance_identity import (
    load_governance_identity,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.evidence.session_batch import REGIME_NAMESPACE
from src.screening.offensive.v3.evidence.session_spine import SessionSpine
from src.screening.offensive.v3.governance.stage_issuance import (
    StageIssuanceReceipt,
)
from src.screening.offensive.v3.kernel.sizing import SizingConfig
from src.screening.offensive.v3.orchestration.paired_trial import (
    ForwardPairedTrialRunner,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionStore,
)


class OfficialStackError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _require_regular_database(path: Path, *, missing_code: str) -> None:
    """官方栈磁盘面守卫 (R29): 库文件必须是真实常规文件。

    ``is_file()`` 跟随 symlink — 预置 ``evidence.sqlite3 -> 外部伪库``
    会让官方栈在敌手库上构造 (regime/排程/候选/批授权 merkle 根全部
    绑定污染源; PoC 实锤)。lstat 拒 symlink 与目录/FIFO 等非常规替换
    物, 与 blob_store/arm_capital (第四/五轮) 的同族纪律一致。
    """
    import stat

    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise OfficialStackError(
            missing_code,
            "the trial root lacks this database (seeding/genesis flows"
            " must run first)",
            path=str(path),
        ) from None
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise OfficialStackError(
            "official_stack_path_rejected",
            "an official-stack database must be a regular non-symlink file",
            path=str(path),
        )


def _require_optional_regular_database(path: Path) -> None:
    """存在的运行态库必须是常规文件; 缺失保持构造器既有语义 (自建)。"""
    try:
        path.lstat()
    except FileNotFoundError:
        return
    _require_regular_database(path, missing_code="trial_root_not_initialized")


_SPINE_ENROLLMENT_PROBE_SQL: Final = (
    "SELECT 1 FROM expected_sessions"
    " WHERE research_program_id = :program LIMIT 1"
)
_GOVERNANCE_SEALED_PROBE_SQL: Final = (
    "SELECT 1 FROM sealed_trials WHERE trial_id = :trial LIMIT 1"
)
_EVIDENCE_REGIME_PROBE_SQL: Final = (
    "SELECT 1 FROM evidence_records"
    " WHERE issuer_namespace = :ns LIMIT 1"
)
_BARS_SCHEMA_PROBE_SQL: Final = (
    "SELECT 1 FROM sqlite_master"
    " WHERE type = 'table' AND name = 'evidence_records' LIMIT 1"
)
_ANY_SQLITE_PROBE_SQL: Final = "SELECT count(*) FROM sqlite_master"


def _require_valid_sqlite_when_present(
    path: Path,
    *,
    rejection_code: str,
    message: str,
    **details: object,
) -> None:
    """运行时自建库「存在即须为合法 sqlite」探测 (R37 Act 期对抗发现)。

    decisions.sqlite3 是运行时产物: 缺失 → 构造器首决策自建 (R32 成文
    语义), 0 字节/空 schema → 构造器自愈式落 schema (``CREATE TABLE IF
    NOT EXISTS`` 是该 store 的设计行为, 与 spine/governance 的「预注册
    事实不得被读侧组装写入」相反)。唯一拒绝形态 = 非 sqlite 垃圾字节
    — 修复前 ``TrialArmDecisionStore.__init__`` 的 WAL/DDL 在垃圾文件
    上以非类型化 ``sqlalchemy.exc.DatabaseError`` 泄漏 (与 evidence/bars
    的 R37 缺陷同族; ``SELECT count(*)`` 在任何合法 sqlite 上恒返回
    一行, 故 row 永不为 None — 只有垃圾触发 sqlite3.Error)。
    """
    if not path.exists():
        return
    uri = f"file:{urllib.parse.quote(str(path))}?immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute(_ANY_SQLITE_PROBE_SQL).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise OfficialStackError(rejection_code, message, **details) from exc


def _build_decision_store(root: Path) -> TrialArmDecisionStore:
    decisions_db = root / "decisions.sqlite3"
    _require_valid_sqlite_when_present(
        decisions_db,
        rejection_code="decision_store_corrupt",
        message=(
            "an existing decisions.sqlite3 is not a valid SQLite"
            " database (missing files self-build on first decision and"
            " empty files self-heal schema by design — only non-sqlite"
            " garbage is rejected, previously leaking an untyped"
            " database error from the assembly read path)"
        ),
        fact_file=decisions_db.name,
    )
    return TrialArmDecisionStore(database_path=str(decisions_db))


def _require_seeded_database(
    path: Path,
    *,
    probe_sql: str,
    params: dict[str, object],
    rejection_code: str,
    message: str,
    **details: object,
) -> None:
    """运行时 append 面证据库的冷读零写痕探测 (R37, R35 同族)。

    与 ``_require_pre_registered_fact`` (spine/governance) 的语义分流
    成文: 那两者是 **write-once 冻结事实文件** — sidecar 存在即拒
    (R35); 本 helper 面向 **evidence.sqlite3 / bars-evidence.sqlite3
    运行时 append 面** — 活 publisher 的未 checkpoint WAL 是合法形态
    (publish→assemble 同进程流), 不做 blanket sidecar 拒绝。

    R35 登记的同族缺陷在此收口: ``EvidenceRepository.__init__`` 连接时
    无条件 ``journal_mode=WAL`` + DDL + ``INSERT OR IGNORE`` — 组装器
    读路径对 0 字节/空 schema 库会静默落写副作用后以「合法空证据世界」
    通过 (fixture 曾以 ``touch()`` 依赖该副作用, 实证可达), 垃圾字节
    以非类型化 sqlalchemy 异常泄漏, 垃圾主文件 + 残留 sidecar 复活面
    与 R35 spine/governance PoC 同族。

    ``immutable=1`` 只读探测在构造任何 repository 之前执行: 探测本身
    零写痕 (不落 DDL/sidecar), 垃圾/空 schema/未播种统一类型化为
    ``rejection_code``; R35 的复活形态 (主文件被替换) 由探测视图本身
    关闭 — 垃圾主文件无论 sidecar 与否在探测即失败, 复活数据到不了
    消费面。代价与 R35 相同: 探测只看冷主文件 (忽略未 checkpoint
    WAL) — 对 append 面这是刻意选择, 事实 (regime 记录/schema) 由
    播种/发布流程在组装前持久化, 活 writer 的增量留给正常读路径。
    """
    uri = f"file:{urllib.parse.quote(str(path))}?immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            row = connection.execute(probe_sql, params).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise OfficialStackError(rejection_code, message, **details) from exc
    if row is None:
        raise OfficialStackError(rejection_code, message, **details)


def _require_pre_registered_fact(
    path: Path,
    *,
    checkpoint_code: str,
    probe_sql: str,
    params: dict[str, object],
    rejection_code: str,
    message: str,
    **details: object,
) -> None:
    """预注册治理事实的冷读零写痕探测 (R35, R34 0 字节特检的全形态泛化)。

    在构造 ``SessionSpine`` / ``GovernanceRepository`` 之前验证「注册/
    封存流程确实跑过」: 两者的 ``__init__`` 都在连接时执行
    ``journal_mode=WAL`` + ``CREATE TABLE IF NOT EXISTS``, 对任何未注册
    形态 (0 字节/空 schema/垃圾字节/异归属) 的拒绝路径都会先把 DDL 与
    WAL sidecar 写进预注册治理事实文件 (发现 5: R34 只封了 0 字节)。

    两段防线:
    1. **冷文件检查** — ``-wal`` sidecar 存在即以 ``checkpoint_code``
       拒绝: 未 checkpoint 的 WAL 意味着注册/封存 writer 仍打开或曾
       中断; 更危险的是 sidecar 复活 (对抗复现实锤): 主文件被替换成
       任意字节后, SQLite 可经残留 ``-wal``/``-shm`` 读出旧写入 —
       90 字节垃圾主文件 + 构造期 ``regime_trial_bundle`` 返回合法
       封存 bundle, 组装静默成功。读侧组装只信任已 checkpoint 的
       冷文件, 使「文件字节」与「消费到的事实」不脱钩。
    2. **immutable 探测** — ``immutable=1`` 只读连接让 SQLite 完全
       跳过锁与 sidecar 创建, 探测本身零写痕; 垃圾/空 schema 统一
       类型化为 ``rejection_code`` (修复前以非类型化 sqlalchemy 异常
       泄漏或经 sidecar 复活静默通过)。代价是忽略未 checkpoint 的
       ``-wal`` — 注册中断残留本就该 fail-closed 重跑注册, 而非由
       读侧组装恢复 (恢复=写), 冷文件检查已显式拒绝该形态。
    """
    if (path.parent / f"{path.name}-wal").exists():
        raise OfficialStackError(
            checkpoint_code,
            "a pre-registered governance fact file must be fully"
            " checkpointed (no -wal sidecar) before read-side assembly —"
            " an un-checkpointed WAL means the sealing/registration"
            " writer is still open or was interrupted, and stale"
            " sidecars can resurrect replaced main-file bytes",
            fact_file=path.name,
            **details,
        )
    uri = f"file:{urllib.parse.quote(str(path))}?immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
        try:
            row = connection.execute(probe_sql, params).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise OfficialStackError(rejection_code, message, **details) from exc
    if row is None:
        raise OfficialStackError(rejection_code, message, **details)


@dataclass(frozen=True)
class OfficialTrialStack:
    """One fully-wired official trial runtime over the persistent identity."""

    identity_dir: Path
    trial_root: Path
    trial_id: str
    stage_receipt: StageIssuanceReceipt
    regime_repository: EvidenceRepository
    schedule_repository: EvidenceRepository
    btst_repository: EvidenceRepository
    bars_repository: EvidenceRepository
    spine: SessionSpine
    decision_store: TrialArmDecisionStore
    runner: ForwardPairedTrialRunner

    def governance_database(self) -> Path:
        return self.trial_root / "governance.sqlite3"


def build_official_trial_stack(
    *,
    identity_dir: Path,
    trial_root: Path,
    trial_id: str,
    sizing_config: SizingConfig,
    clock: Callable[[], datetime],
    market_scenario: object,
    trial_attribution: object,
    research_program_id: str,
    stage_id: str | None = None,
) -> OfficialTrialStack:
    """从身份目录 + trial root 一次构造官方栈 (全部真实身份签名面)。

    前置: 身份目录已经 ``generate`` 且 ``check`` 通过; trial root 下
    genesis/治理封存已由各自流程预置 (缺库 fail-closed 由 arm_layout
    读面强制)。资本/治理的写入流程 (seal/restore/签发) 不在本层 —
    本层是运行栈的读侧组装。

    stage 选择 (R28): 消费哪个 stage 是治理事实。显式 ``stage_id``
    精确选择; 缺省时全量严格冷读按 receipt 的权威签发时刻
    ``issued_at`` 取最新 — 文件名字典序不是治理事实 (stage_id 无
    命名约束), 任何一个回执损坏都 fail-closed, 同 ``issued_at``
    双签是治理异常 (歧义拒绝)。
    """
    from src.screening.offensive.v3 import trust as v3trust
    from src.screening.offensive.v3.orchestration.arm_layout import (
        open_arm_capital_repository,
    )

    # trial_root resolve 前全组件 walk (R31): ``resolve()`` 静默跟随
    # symlink 组件 — 预置 ``trial-root -> /attacker/root`` 使 R29 的五库
    # lstat 守卫/归档 walk/arms 校验全部作用在敌手 root 的真实路径上,
    # 守卫永远看不到重定向 (stage_archive._validate_root 对 trial root
    # 的同族纪律被组装器自己的 resolve 抵消)。walk 之后前缀已无 symlink,
    # resolve 仅做词法规范化; 相对路径含 ``..`` 在此显式拒绝 — 与
    # v3_regime_trial runbook 的 canonical 路径要求一致。
    candidate_root = Path(trial_root)
    if not candidate_root.is_absolute():
        candidate_root = Path.cwd() / candidate_root
    from src.screening.offensive.v3.orchestration.path_guards import (
        require_safe_segment,
        walk_components,
    )

    walk_components(
        candidate_root,
        fail=OfficialStackError,
        missing_code="trial_root_not_initialized",
        rejected_code="official_stack_path_rejected",
    )
    root = candidate_root.resolve()
    # identity_dir 同族 walk (R34): 身份目录是全部签名面的信任链根 —
    # R31 对 trial_root 拒绝的 symlink 重定向对它原样有效 (敌手可用
    # 离线 generate 原语自建合法形态的身份目录; load 面的 identity.json
    # is_file() 跟随 symlink, 中间组件零防护)。
    candidate_identity = Path(identity_dir)
    if not candidate_identity.is_absolute():
        candidate_identity = Path.cwd() / candidate_identity
    walk_components(
        candidate_identity,
        fail=OfficialStackError,
        missing_code="identity_not_initialized",
        rejected_code="official_stack_path_rejected",
    )
    identity_dir = candidate_identity
    # trial_id 入口单段校验 (R29): 该 id 直接拼进归档路径与 portfolio_id,
    # 穿越/绝对注入在拼路径前即拒 (深处 assembler 的 stage_trial_mismatch
    # 是兜底而非纵深; R28 已修 stage_id 段, 本轮补 trial_id 段)。
    require_safe_segment(trial_id, field="trial_id", fail=OfficialStackError)
    now = clock()
    identity = load_governance_identity(identity_dir, trusted_at=now)
    head = v3trust.CurrentTrustHeadWitness.model_validate_json(
        json.dumps(identity.manifest["head_witness"])
    )

    evidence_db = root / "evidence.sqlite3"
    bars_db = root / "bars-evidence.sqlite3"
    _require_regular_database(
        evidence_db, missing_code="trial_root_not_initialized"
    )
    _require_regular_database(
        bars_db, missing_code="trial_root_not_initialized"
    )
    # 运行时 append 面冷读探测 (R37, R35 登记的同族遗留): 在构造任何
    # EvidenceRepository 之前验证「播种/发布流程确实跑过」 —
    # EvidenceRepository.__init__ 连接即 WAL+DDL+INSERT, 0 字节/空
    # schema 形态会被静默写副作用后以合法空证据世界通过。evidence 库
    # 的事实 = regime 命名空间 ≥1 条 committed 记录 (批规则 v1 固定
    # 成员、runbook ④ 启动前置、首 decide 硬前提); bars 库的事实 =
    # schema 已落盘 (记录可空 — 首发 market session 前 0 bars 合法)。
    # sidecar 不拒 (活 writer 合法, 与 spine/governance 冻结事实文件
    # 分流), 复活形态由 immutable 主文件探测本身关闭 (见 helper)。
    _require_seeded_database(
        evidence_db,
        probe_sql=_EVIDENCE_REGIME_PROBE_SQL,
        params={"ns": REGIME_NAMESPACE},
        rejection_code="evidence_not_seeded",
        message=(
            "the trial evidence store carries no committed regime"
            " evidence (runbook step 4 requires the evidence pipeline"
            " to run before assembly; a schema-only or empty store"
            " means the trial never completed launch)"
        ),
        fact_file=evidence_db.name,
    )
    _require_seeded_database(
        bars_db,
        probe_sql=_BARS_SCHEMA_PROBE_SQL,
        params={},
        rejection_code="bars_store_not_seeded",
        message=(
            "the bars evidence store was never initialized by the"
            " seeding/publishing pipeline (no schema on disk; records"
            " may legitimately be empty before the first market"
            " session, but the store itself must exist)"
        ),
        fact_file=bars_db.name,
    )
    blobs = root / "blobs"

    def repo(namespace: str, database: Path) -> EvidenceRepository:
        return identity.repository_for(
            namespace=namespace,
            database_path=str(database),
            blobs_dir=blobs,
            clock=clock,
            trust_head=head,
        )

    # 运行态库磁盘面: spine 与 governance 都是封存/注册流程的预置产物
    # (宪法 #13 expected-session spine + 治理封存; runbook ④/封存是启动
    # 前置) — 缺失即拒, 绝不静默自建 (空 spine 使 finalize 的 NO_RUN
    # 补记静默失效; 空 governance 把「封存流程没跑」推迟到首次 decide
    # 的 stage_unknown)。decisions 是运行时产物: 存在时常规文件, 缺失
    # 保持构造器既有语义 (首决策自建)。
    _require_regular_database(root / "spine.sqlite3", missing_code="trial_root_not_initialized")
    _require_optional_regular_database(root / "decisions.sqlite3")
    _require_regular_database(
        root / "governance.sqlite3", missing_code="trial_root_not_initialized"
    )
    spine_path = root / "spine.sqlite3"
    # 冷读零写痕探测 (R35): 全部未注册/垃圾/sidecar 形态在
    # SessionSpine.__init__ 落 WAL+DDL 写副作用**之前**类型化拒绝 —
    # 读侧组装对预注册治理事实文件的任何拒绝路径零写痕 (字节与
    # sidecar), R34 的 0 字节特检被本机制包含。
    _require_pre_registered_fact(
        spine_path,
        checkpoint_code="spine_not_checkpointed",
        probe_sql=_SPINE_ENROLLMENT_PROBE_SQL,
        params={"program": research_program_id},
        rejection_code="spine_not_registered",
        message=(
            "the session spine carries no enrollment for this research"
            " program (runbook session registration must run first; an"
            " empty or foreign-program spine silently voids the finalize"
            " NO_RUN bookkeeping, and a rejected read-side assembly must"
            " leave zero write traces on the pre-registered fact file)"
        ),
        research_program_id=research_program_id,
    )
    spine = SessionSpine(database_path=str(spine_path), clock=clock)
    # spine 事实非空性与归属 (R32): 文件存在 ≠ 注册流程跑过 — 0 字节
    # 文件经 SessionSpine.__init__ 静默建 DDL 成为零 enrollment 空 spine,
    # 异 research_program 的合法 spine 按 program 过滤后同样为空。
    # worker/runner 侧无此校验 (无主校验), 组装面是唯一收口点。
    if not spine.enrolled_sessions(research_program_id):
        raise OfficialStackError(
            "spine_not_registered",
            "the session spine carries no enrollment for this research"
            " program (runbook session registration must run first; an"
            " empty or foreign-program spine silently voids the"
            " finalize NO_RUN bookkeeping)",
            research_program_id=research_program_id,
        )
    store = _build_decision_store(root)
    # 资本约定路径在构造期即校验 (缺库 fail-closed 提前到组装面)
    from src.screening.offensive.v3.contracts.trial import TrialArm

    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        open_arm_capital_repository(root, arm)

    from src.screening.offensive.v3.orchestration.privileged_worker import (
        ForwardSessionAssembler,
    )
    from src.screening.offensive.v3.governance.repository import (
        GovernanceRepository,
        GovernanceStoreError,
    )

    # 冷读零写痕探测 (R35): governance 同族 — GovernanceRepository 的
    # __init__ 连接时落 WAL+DDL, 空 schema/垃圾主文件先被写再被 R34
    # 的 quiet 读拒绝; sidecar 复活形态则完全静默通过 (见探测 docstring)。
    _require_pre_registered_fact(
        root / "governance.sqlite3",
        checkpoint_code="governance_not_checkpointed",
        probe_sql=_GOVERNANCE_SEALED_PROBE_SQL,
        params={"trial": trial_id},
        rejection_code="governance_not_sealed",
        message=(
            "the governance database carries no sealed paired trial"
            " bundle for this trial (sealing flow must run first; an"
            " empty or foreign-trial store must not defer this fact to"
            " the first decide's stage_unknown, and a rejected read-side"
            " assembly must leave zero write traces on the pre-registered"
            " fact file)"
        ),
        trial_id=trial_id,
    )

    governance = GovernanceRepository(
        database_path=str(root / "governance.sqlite3"), clock=clock
    )
    # 治理事实非空 + program 三角互证 (R34): 构造期 quiet 读
    # regime_trial_bundle (stage 签发的单一事实源) — 探测只验
    # 「行存在」, 封存字节的严格重解析/哈希互证仍在此处; 同时断言
    # 封存 manifest 的 research_program_id 与组装入参一致
    # (spine↔入参↔封存权威三角闭合, 错位时 NO_RUN 补记会按错误
    # program 记账)。
    try:
        sealed_bundle = governance.regime_trial_bundle(trial_id)
    except GovernanceStoreError as exc:
        raise OfficialStackError(
            "governance_not_sealed",
            "the governance database carries no sealed paired trial"
            " bundle for this trial (sealing flow must run first; an"
            " empty or foreign-trial store must not defer this fact to"
            " the first decide's stage_unknown)",
            trial_id=trial_id,
        ) from exc
    if sealed_bundle.trial_manifest.research_program_id != research_program_id:
        raise OfficialStackError(
            "program_binding_mismatch",
            "the sealed trial manifest binds a different research program"
            " than the stack was assembled with — the spine NO_RUN"
            " bookkeeping would record against the wrong program",
            sealed_program=(
                sealed_bundle.trial_manifest.research_program_id
            ),
            requested_program=research_program_id,
        )
    receipt = _latest_stage_receipt(root, trial_id, stage_id)
    assembler = ForwardSessionAssembler(
        sealer=_build_sealer(root, identity, clock),
        governance=governance,
        trial_id=trial_id,
        stage_receipt=receipt,
        regime_repository=repo("regime", evidence_db),
        schedule_repository=repo("sse-sessions", evidence_db),
        btst_repository=repo("btst", evidence_db),
    )
    runner = ForwardPairedTrialRunner(
        assembler=assembler,
        capital_trial_root=root,
        portfolio_id=_portfolio_id_for(trial_id),
        sizing_config=sizing_config,
        decision_store=store,
        bar_repository=repo("btst-bars", bars_db),
        market_scenario=market_scenario,
        trial_attribution=trial_attribution,
        session_spine=spine,
        research_program_id=research_program_id,
    )
    return OfficialTrialStack(
        identity_dir=identity_dir,
        trial_root=root,
        trial_id=trial_id,
        stage_receipt=receipt,
        regime_repository=repo("regime", evidence_db),
        schedule_repository=repo("sse-sessions", evidence_db),
        btst_repository=repo("btst", evidence_db),
        bars_repository=repo("btst-bars", bars_db),
        spine=spine,
        decision_store=store,
        runner=runner,
    )


def _portfolio_id_for(trial_id: str) -> str:
    return f"pf-{trial_id}"


def _latest_stage_receipt(root: Path, trial_id: str, stage_id: str | None) -> object:
    """Stage 签发回执选择 (R28 修复): 治理事实决定, 不由文件名决定。

    - 显式 ``stage_id``: 单段形状校验 (穿越/绝对注入到不了 lstat) 后
      精确路径冷读 (确定性最强的审计路径), 回执内容 stage_id 必须与
      请求一致 (R33-①: 文件名与内容背离 = 静默接线错误治理事实);
    - 缺省: 归档中全部回执严格冷读 — 任何一个损坏即 fail-closed
      (预置文件不能靠字典序静默出局操纵选择面) — 回执 trial_id 必须
      与归档归属 trial 一致 (R33-②: write 面按内容定路径, 外 trial
      回执只能是预置污染 — 静默出局/参与选择都违反 R28 先例, 与
      assemble 深处 stage_trial_mismatch 兜底分工为纵深), 同
      ``stage_id`` 出现多个 ``issued_at`` 是归档异常 (R33-③: 镜像
      seal_stage 写面同 id 异内容的 ``stage_seal_conflict`` 纪律 —
      签发行为身份含时刻, 双时刻同 id 只能来自另一条签发链), 按
      receipt 权威签发时刻 ``issued_at`` 取最新;
    - 同 ``issued_at`` 不同 stage_id: 治理异常, ``stage_selection_ambiguous``。

    identity v1 无 stage 签发 key, 回执由签发流程归档、本层不重签。
    """
    from src.screening.offensive.v3.orchestration.stage_archive import (
        StageArchiveError,
        read_stage_issuance_receipt,
    )

    archive = root / "archive" / "stage-issuance" / trial_id
    if stage_id is not None:
        # 单段形状校验先于拼路径 (对抗审查 R28: stage_id 直拼会让
        # ``../`` 穿越归档读外部文件 — 与 stage_receipt_path 同款纪律)。
        from src.screening.offensive.v3.orchestration.path_guards import (
            require_safe_segment,
        )

        safe_stage_id = require_safe_segment(
            stage_id, field="stage_id", fail=OfficialStackError
        )
        target = archive / f"{safe_stage_id}.json"
        try:
            receipt = read_stage_issuance_receipt(target)
        except StageArchiveError as exc:
            if exc.code == "archive_artifact_missing":
                raise OfficialStackError(
                    "stage_receipt_missing",
                    "the requested archived stage issuance receipt does not"
                    " exist (issuance flow must run first; identity v1 has"
                    " no stage signing key — receipts are consumed from"
                    " the archive)",
                    stage_id=stage_id,
                ) from exc
            raise OfficialStackError(
                "stage_receipt_corrupt",
                "the requested archived stage issuance receipt failed"
                " strict cold-read",
                stage_id=stage_id,
            ) from exc
        if receipt.trial_id != trial_id:
            raise OfficialStackError(
                "stage_receipt_foreign_trial",
                "the archived receipt belongs to a different trial;"
                " the archive directory is scoped to one trial by the"
                " write face — a foreign-trial receipt is preset"
                " contamination",
                requested_trial_id=trial_id,
                receipt_trial_id=receipt.trial_id,
                stage_id=stage_id,
            )
        if receipt.stage_id != safe_stage_id:
            raise OfficialStackError(
                "stage_receipt_id_mismatch",
                "the archived receipt content carries a different"
                " stage_id than the requested artifact name — the"
                " filename has never been bound to content, so this"
                " divergence silently wires the wrong governance facts",
                requested_stage_id=stage_id,
                receipt_stage_id=receipt.stage_id,
            )
        return receipt
    receipts = sorted(archive.glob("*.json")) if archive.is_dir() else []
    if not receipts:
        raise OfficialStackError(
            "stage_receipt_missing",
            "no archived stage issuance receipt for this trial"
            " (issuance flow must run first; identity v1 has no stage"
            " signing key — receipts are consumed from the archive)",
            archive=str(archive),
        )
    parsed: list[StageIssuanceReceipt] = []
    for path in receipts:
        try:
            receipt = read_stage_issuance_receipt(path)
        except StageArchiveError as exc:
            raise OfficialStackError(
                "stage_receipt_corrupt",
                "an archived stage receipt failed strict cold-read;"
                " a corrupt artifact must not silently drop out of the"
                " selection set",
                path=str(path),
            ) from exc
        if receipt.trial_id != trial_id:
            raise OfficialStackError(
                "stage_receipt_foreign_trial",
                "an archived receipt belongs to a different trial;"
                " the archive directory is scoped to one trial by the"
                " write face — a foreign-trial receipt is preset"
                " contamination and must not silently drop out of or"
                " join the selection set",
                requested_trial_id=trial_id,
                receipt_trial_id=receipt.trial_id,
                stage_id=receipt.stage_id,
                path=str(path),
            )
        parsed.append(receipt)
    _reject_duplicate_stage_ids(parsed)
    latest_at = max(receipt.issued_at for receipt in parsed)
    candidates = sorted(
        receipt.stage_id for receipt in parsed if receipt.issued_at == latest_at
    )
    if len(candidates) > 1:
        raise OfficialStackError(
            "stage_selection_ambiguous",
            "multiple distinct stages share the same issuance instant;"
            " issuance identity includes the instant — an explicit"
            " stage_id is required to consume this archive",
            issued_at=latest_at.isoformat(),
            stage_ids=candidates,
        )
    for receipt in parsed:
        # 纵深: 附 issued_at 条件 — 即便上游校验被未来改动弱化, 也不
        # 会按文件名序静默选中较旧签发 (R33-③ 的原始缺陷形态)。
        if receipt.stage_id == candidates[0] and receipt.issued_at == latest_at:
            return receipt
    raise OfficialStackError(  # pragma: no cover — candidates 来自 parsed
        "stage_receipt_corrupt",
        "selected stage receipt vanished between parse and select",
    )


def _reject_duplicate_stage_ids(parsed: list[StageIssuanceReceipt]) -> None:
    """同 stage_id 多个 issued_at = 归档异常 (R33-③)。

    签发行为身份 = trial + stage + 时刻 (P2-c); seal_stage 写面对同
    id 异内容落 ``stage_seal_conflict``。归档里同 id 双时刻只能来自
    另一条签发链的手工放置 — 按文件名序任选其一会静默选中可能更旧
    的治理事实, 与写面纪律一致地 fail-closed。
    """
    instants: dict[str, set[datetime]] = {}
    for receipt in parsed:
        instants.setdefault(receipt.stage_id, set()).add(receipt.issued_at)
    duplicated = sorted(sid for sid, at in instants.items() if len(at) > 1)
    if duplicated:
        raise OfficialStackError(
            "stage_receipt_duplicate_id",
            "the archive carries multiple issuance instants for the same"
            " stage_id; issuance identity includes the instant, so this"
            " can only be a receipt from a second signing chain —"
            " selecting either one by filename order would silently bind"
            " unverified governance facts",
            stage_ids=duplicated,
        )


def _build_sealer(root: Path, identity, clock) -> object:
    """SessionBatchSealer over 真实身份的三个命名空间仓库句柄。"""
    from src.screening.offensive.v3.evidence.session_batch import (
        BTST_NAMESPACE,
        REGIME_NAMESPACE,
        SCHEDULE_NAMESPACE,
        SessionBatchSealer,
    )
    import json as _json

    from src.screening.offensive.v3 import trust as v3trust

    head = v3trust.CurrentTrustHeadWitness.model_validate_json(
        _json.dumps(identity.manifest["head_witness"])
    )
    evidence_db = root / "evidence.sqlite3"
    blobs = root / "blobs"

    def repo(namespace: str) -> EvidenceRepository:
        return identity.repository_for(
            namespace=namespace,
            database_path=str(evidence_db),
            blobs_dir=blobs,
            clock=clock,
            trust_head=head,
        )

    return SessionBatchSealer(
        database_path=str(evidence_db),
        repositories={
            REGIME_NAMESPACE: repo(REGIME_NAMESPACE),
            SCHEDULE_NAMESPACE: repo(SCHEDULE_NAMESPACE),
            BTST_NAMESPACE: repo(BTST_NAMESPACE),
        },
        clock=clock,
    )


__all__ = [
    "OfficialStackError",
    "OfficialTrialStack",
    "build_official_trial_stack",
]
