"""信号会话 decide 全链预演 (隔离副本, R108 Op1).

在官方前向 Trial 的信号会话 decide 窗 (23:00 北京) 之前的可干预窗内
(readiness manifest ~18:30 就绪), 对生产 trial root 的**隔离副本**预演
整条 decide 链, 把 R103 形态的「烧会话」缺陷 (准点 decide 被自己的信封
时间戳冒充迟到, 08-31/09-01 两会话七候选实烧) 从 23:05 后移到人眼可
拦截的位置: 预演报告 verbatim 披露 pair 结果——「7 候选 →
DEADLINE_MISSED」这类语义异常在真实运行前就可见。

安全边界 (与 review_v2_forward_evidence.py / v3_trial_status.py 同属
scripts/ 纯诊断安全类别):

- 生产 trial root 与 identity 目录**字节级零写**: 前后树 digest 自证
  (rc=4 最响亮的失败), 副本之外的唯一写入是 scratch 目录本身;
- 预演经官方 CLI ``v3_trial_session.py decide --execute`` 子进程完成
  (夜间链同款参数面, 无平行实现), 排练时钟注入 ``--at`` (默认
  signal_date 15:05 UTC ≈ 夜间链实际时刻);
- 副本落 ``--scratch-root`` (默认 data/tmp/v3_trial_preflight/),
  成功默认清理, 失败保留供诊断 (路径在报告中披露);
- fail-closed 守卫 (先于复制): 生产 root 含 symlink / 非空 ``-wal``
  (活跃写者或 crash 残留——撕裂副本风险, R35 checkpoint 纪律) /
  排练时钟在候选入库窗外 / manifest 缺失一律类型化拒绝。

本工具不构成权限、不改变任何决策语义: 副本里的 pair 与生产 root 无关,
真实结果仍以 23:05 夜间链为准 (同参数重放由 store 幂等纪律收敛)。

重放语义边界 (R108 宿主实演三次取证成文, 非缺陷):

- 主用途是 **decide 前的同晚预演**——副本里尚无该会话 pair, 预演干净
  收敛, 报告即当晚 decide 的分类预言;
- **对已决策会话的事后重放不逐字节幂等** (typed 冲突如实透传, 分类仍
  可对比): decide 之后夜间链 advance 会向臂台账追加该会话收盘 mark
  (经济时点早于 decide, 写入时点晚于 decide), 而 capital 快照读的是
  台账**当前头**——``capital_risk_snapshot(as_of)`` 的 as_of 只是快照
  印记, 不过滤历史 (R108 取证: repository.read_capital_risk_snapshot
  全函数 as_of 仅落 as_of/valid_until 两字段)——故重放的
  arm_capital_checkpoint_hash 必然偏离已存 pair →
  ``arm_decision_conflict``。decide 窗口内的 crash-retry (无交错写入)
  幂等性不受影响——fixture 实证同窗异钟、无资本前进的重放恰等收敛
  (``created_at`` 不在 store 恰等比较域, 时钟无关纪律);
- 排练时钟早于证据库已记录的 trusted 高水位 (对已运行会话用早于原
  decide 时刻的 --at) → store ``trusted_clock_rollback``, 当前经
  CLI 裸异常逃逸, 工具以 ``cli_output_unparseable`` + stderr 尾如实
  透传 (CLI typed-error 契约的缺口, 属 decide CLI 面, 非本工具 scope)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SESSION_CLI: Final[Path] = Path(__file__).resolve().with_name("v3_trial_session.py")

#: 排练时钟默认值: signal_date 15:05 UTC (夜间链 23:05 北京实际时刻附近,
#: 落在候选入库窗 [signal 15:00 UTC, +24h] 内)。确定性默认使多次预演
#: 逐字节可比; --at 可显式覆盖 (必须在窗内)。
_DEFAULT_AT_UTC_TIME: Final = "15:05:00"


class PreflightError(RuntimeError):
    """Typed fail-closed rejection (mirrors the repo's CLI error contract)."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _fail(code: str, message: str, rc: int = 2, **details: object) -> int:
    print(
        json.dumps(
            {"ok": False, "code": code, "message": message, **details},
            ensure_ascii=False,
        )
    )
    return rc


def _ok(payload: dict) -> int:
    print(json.dumps({"ok": True, **payload}, ensure_ascii=False, default=str))
    return 0


def _tree_digest(root: Path) -> str:
    """Deterministic content digest of every file under ``root``.

    与 tests/offensive/v3/orchestration 的 ``_tree_digest`` 同构: 相对路径
    + 字节逐文件累积。目录元数据 (mtime 等) 不参与——只有内容变化才改变
    digest; 新文件/改字节/删文件都会改变。
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _assert_no_symlinks(root: Path) -> None:
    """root 内任何 symlink (文件或目录) 都拒绝——不跟随也不保留。

    生产 trial root 由官方栈构造纪律保证无 symlink (R31 家族守卫);
    预置 symlink 属异常形态, 跟随 = 读穿任意文件, 保留 = 副本语义漂移。
    os.walk(followlinks=False) 不下降符号目录, dirnames/filenames 中
    的链接成员逐个核验。
    """
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in (*dirnames, *filenames):
            if os.path.islink(os.path.join(dirpath, name)):
                raise PreflightError(
                    "symlink_in_root",
                    "production trial root carries a symlink; refusing to"
                    " rehearse through it",
                    root=str(root),
                    offending=os.path.relpath(
                        os.path.join(dirpath, name), root
                    ),
                )


def _assert_wal_quiescent(root: Path) -> dict[str, int]:
    """非空 ``-wal`` sidecar 拒绝 (活跃写者 / crash 残留 → 撕裂副本)。

    返回全部 sidecar 字节披露 (含零字节——诚实报告形态, R107 纪律)。
    """
    wal_bytes: dict[str, int] = {}
    for path in sorted(root.rglob("*-wal")):
        if path.is_file():
            wal_bytes[path.relative_to(root).as_posix()] = path.stat().st_size
    active = {name: size for name, size in wal_bytes.items() if size > 0}
    if active:
        raise PreflightError(
            "wal_sidecar_active",
            "production trial root has non-empty -wal sidecars (a live"
            " writer or crash residue would make the copy torn); retry"
            " after the writer checkpoints or investigate the residue",
            root=str(root),
            active_wal=active,
            all_wal_bytes=wal_bytes,
        )
    return wal_bytes


def _parse_at(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _assert_at_in_window(at: datetime, signal_session: date) -> None:
    """排练时钟必须在候选入库窗内, 否则预演结果无意义 (R48 D8 同族)."""
    from src.screening.offensive.v3.producers.auto import (
        candidate_ingestion_window,
    )

    window_open, window_close = candidate_ingestion_window(signal_session)
    if not (window_open <= at <= window_close):
        raise PreflightError(
            "rehearsal_clock_out_of_window",
            "the rehearsal clock must sit inside the candidate ingestion"
            " window [signal_date 15:00 UTC, +24h]; outside it the rehearsal"
            " would rehearse a deadline violation instead of tonight's run",
            at=at.isoformat(),
            window_open=window_open.isoformat(),
            window_close=window_close.isoformat(),
        )


def _run_rehearsal(
    *,
    copy_root: Path,
    identity_dir: Path,
    trial_id: str,
    research_program: str,
    calendar: Path,
    readiness_manifest: Path,
    signal_session: date,
    data_dir: Path,
    at: datetime,
) -> tuple[int, dict, str]:
    """官方 CLI 子进程预演 (夜间链同款参数面, trial-root 指向副本)."""
    argv = [
        sys.executable,
        str(SESSION_CLI),
        "decide",
        "--identity-dir", str(identity_dir),
        "--trial-root", str(copy_root),
        "--trial-id", trial_id,
        "--research-program", research_program,
        "--calendar", str(calendar),
        "--now", at.isoformat(),
        "--execute",
        "--readiness-manifest", str(readiness_manifest),
        "--signal-session", signal_session.isoformat(),
        "--data-dir", str(data_dir),
    ]
    completed = subprocess.run(
        argv,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=900,
    )
    cli_payload: dict = {}
    try:
        cli_payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        cli_payload = {"ok": False, "code": "cli_output_unparseable"}
    stderr_tail = completed.stderr[-2000:]
    return completed.returncode, cli_payload, stderr_tail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="信号会话 decide 全链预演 (隔离副本, 生产 root 字节级零写)"
    )
    parser.add_argument("--trial-root", required=True, type=Path)
    parser.add_argument("--identity-dir", required=True, type=Path)
    parser.add_argument("--trial-id", required=True)
    parser.add_argument("--research-program", default="research.btst.regime")
    parser.add_argument("--calendar", required=True, type=Path)
    parser.add_argument("--readiness-manifest", required=True, type=Path)
    parser.add_argument("--signal-session", required=True, type=date.fromisoformat)
    parser.add_argument(
        "--at",
        default=None,
        help="排练时钟 (UTC ISO; 默认 signal_date 15:05Z ≈ 夜间链时刻)",
    )
    parser.add_argument("--data-dir", default="data", type=Path)
    parser.add_argument(
        "--scratch-root",
        default=REPO_ROOT / "data/tmp/v3_trial_preflight",
        type=Path,
        help="隔离副本根目录 (默认 data/tmp/v3_trial_preflight/)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="成功路径也保留副本 (默认仅失败保留)",
    )
    args = parser.parse_args(argv)

    signal_session = args.signal_session
    at = (
        _parse_at(args.at)
        if args.at is not None
        else datetime.combine(
            signal_session,
            datetime.strptime(_DEFAULT_AT_UTC_TIME, "%H:%M:%S").time(),
            tzinfo=timezone.utc,
        )
    )
    # 守卫次序: 请求合法性 (时钟窗) → 生产 root 安全 (symlink/wal, 先于
    # 任何扫描-复制副作用) → 输入存在 (manifest)。
    try:
        if not args.trial_root.is_dir():
            raise PreflightError(
                "trial_root_missing", "production trial root is not a directory"
            )
        _assert_at_in_window(at, signal_session)
        _assert_no_symlinks(args.trial_root)
        wal_bytes = _assert_wal_quiescent(args.trial_root)
        if not args.readiness_manifest.is_file():
            raise PreflightError(
                "readiness_manifest_missing",
                "the readiness manifest does not exist (the v2 pipeline has"
                " not published it — rehearsing is meaningless without it)",
                manifest=str(args.readiness_manifest),
            )
    except PreflightError as exc:
        # 守卫失败先于任何复制: 生产面结构性零写 (统一披露该字段)。
        return _fail(
            exc.code,
            str(exc).split(": ", 1)[1],
            production_root_untouched=True,
            **exc.details,
        )

    identity_before = _tree_digest(args.identity_dir)
    root_before = _tree_digest(args.trial_root)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    copy_root = (
        args.scratch_root
        / f"{args.trial_id}_{signal_session:%Y%m%d}"
        / f"run-{stamp}"
    )
    copy_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(args.trial_root, copy_root)

    cli_rc, cli_payload, stderr_tail = _run_rehearsal(
        copy_root=copy_root,
        identity_dir=args.identity_dir,
        trial_id=args.trial_id,
        research_program=args.research_program,
        calendar=args.calendar,
        readiness_manifest=args.readiness_manifest,
        signal_session=signal_session,
        data_dir=args.data_dir,
        at=at,
    )

    root_after = _tree_digest(args.trial_root)
    identity_after = _tree_digest(args.identity_dir)
    untouched = (root_after == root_before) and (identity_after == identity_before)

    rehearsal_ok = cli_rc == 0 and cli_payload.get("ok") is True
    keep_copy = args.keep or not rehearsal_ok
    if not keep_copy:
        shutil.rmtree(copy_root, ignore_errors=True)
        shutil.rmtree(copy_root.parent, ignore_errors=True)

    if not untouched:
        # 最响亮的失败: 预演工具自身越界写了生产面——立即暴露, 绝不静默。
        # rc=4 与 typed 拒绝族 (rc=2) 分离, 退出码层即分诊。
        return _fail(
            "production_root_mutated",
            "the rehearsal changed production bytes (this is a preflight"
            " bug — do not trust this tool until investigated)",
            rc=4,
            production_root_untouched=False,
            copy_root=str(copy_root),
            cli_rc=cli_rc,
        )

    common = {
        "mode": "preflight",
        "signal_session": signal_session.isoformat(),
        "rehearsal_at": at.isoformat(),
        "copy_root": str(copy_root) if keep_copy else None,
        "cli_rc": cli_rc,
        "production_root_untouched": True,
        "wal_bytes": wal_bytes,
        "stderr_tail": stderr_tail or None,
    }
    if rehearsal_ok:
        # pair 结果 verbatim 披露 (不重推导 — R107 读取侧纪律)
        return _ok(
            {
                **common,
                "pair_key": cli_payload.get("pair_key"),
                "champion_status": cli_payload.get("champion_status"),
                "challenger_status": cli_payload.get("challenger_status"),
            }
        )
    return _fail(
        cli_payload.get("code") or "rehearsal_failed",
        "the rehearsal itself was rejected (typed code passthrough; the"
        " copy is retained for diagnosis)",
        **{
            **common,
            "cli_payload": cli_payload,
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
