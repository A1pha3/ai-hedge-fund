"""v3 官方 Trial 夜间运维链组合契约 (R54 Op2 建立, R55 补全 runbook 五步序列)。

runbook 权威日度序列 (docs/runbooks/v3-trial-launch.md 「日度驱动」) 的自动化:
  fetch (bar 源刷新) → seed (首会话 regime 证据, 与 decide 同门) →
  decide (今日会话, 窗口 23:00 北京后) → advance (pair 执行窗口推进) →
  finalize-missed (NO_RUN 补记)。

R55 补全的两处断层:
- seed 缺失 → decide execute 在官方栈构造处以 evidence_not_seeded/
  bars_store_not_seeded 冷读拒绝 (R37 守卫; 生产 evidence/bars 库是
  genesis-seed 空占位) — 首个前向证据日会静默丢失。
- advance 缺失 → decide 产出 pair 后 T+1 结算/marks/守恒推进无驱动,
  Trial 静默停滞。

组合不变式 (hermetic stub 注入, 零网络、零生产 trial root 触碰):
- 每阶段独立记录 JSONL (v3_nightly_history.jsonl: date/stage/rc/detail);
  单阶段失败不中止后续阶段; 整体 rc = 失败阶段数。
- 解释器 preflight 失败 → 恰一条失败记录 + exit 97 + 零阶段调用
  (镜像 daily_daemon R54 Op1 语义)。
- seed/decide 共用双门: 本地时刻 < 23:00 或今日 readiness manifest 缺失
  → skipped 记录, 绝不调用 CLI (typed 拒绝语义由 CLI 权威, 夜间链只如实转记)。
  R57 收紧: decide 门的「无 manifest」三分性 — 交易日 (今日 ∈ 权威日历)
  响亮失败 trading_day_no_manifest (烧会话不可再静默); 周末/假日维持静默;
  日历过期/不可读响亮 calendar_stale/calendar_unresolved (fail-closed)。
- advance 每夜恰一次 deepest-advanceable-window 推进 (R223 Op1): 信号会话 =
  S* (deepest pair <= min_entry; 无任何入场时 = 最新 pair), through =
  min(A_S*, bar 源最新会话)。约束链 (生产实录): R216 覆盖门要求窗口起点
  <= 全 trial 一切已决策入场会话 (入场结算无 catch-up), CLI 冻结切片限定
  每窗 reach = 信号+10 → 可 advance 窗口恰为 S <= min_entry (冻结于最早
  入场); per-pair 逐窗在首个入场后结构性被拒 (20260914 实录: 3× rc=2
  advance_entry_window_skipped 逐夜累积 = 纯浪费)。枚举面 fail-closed
  (pair 不在 spine / decision_json 列缺失 / json 畸形 / RUN 无 entry →
  阶段失败, 绝不静默跳过); RUN pair P > S* 的出场义务超出可达视野 =
  runner 层缺口, 以 rc=0 pending_exit_horizon_breach 响亮披露 (独立
  operation 修复前的结构性事实, 非已核销类假阳性)。
- selftest 面 (--selftest-once) 零锁、零 pid、零生产状态。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NIGHTLY = REPO_ROOT / "scripts" / "v3_trial_nightly.sh"
TIMEOUT_S = 30

STAGES = ("fetch", "seed", "decide", "advance", "finalize")
TRIAL_ROOT_REL = "data/v3_trial_root"


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    (tmp_path / "logs" / "cron").mkdir(parents=True)
    (tmp_path / "data" / "reports").mkdir(parents=True)
    return tmp_path


def _write_stub(path: Path, body: str) -> str:
    path.write_text(body)
    path.chmod(0o755)
    return str(path)


def _control_stub_py(fake_repo: Path) -> str:
    """stub 解释器: 消费 V3N_* 控制变量 (nightly 透传 env)。

    - V3N_PREFLIGHT_FAIL=1 → "-c" 探活形态也失败 (7)
    - 其余 "-c" 调用 (advance pair 枚举器): 直接成功, 不留痕
    - 其余调用: 记录 argv (单行) 进 stub_invocations.jsonl
    - V3N_FAIL_STAGE 命中 argv 中的 stage 令牌 → 打印 V3N_FAIL_STDOUT 后退 V3N_FAIL_RC
    """
    log = fake_repo / "stub_invocations.jsonl"
    return _write_stub(
        fake_repo / "stub_py",
        f'#!/bin/bash\n'
        f'if [ "${{1:-}}" = "-c" ]; then [ "${{V3N_PREFLIGHT_FAIL:-0}}" = "1" ] && exit 7; exit 0; fi\n'
        f'printf \'%s\\n\' "$*" >> "{log}"\n'
        # 只按 脚本 basename + 子命令 分词匹配 (禁全 argv 子串: tmp 路径含测试名)
        f'subject=" ${{1##*/}} ${{2:-}} "\n'
        f'case "$subject" in\n'
        f'  *" ${{V3N_FAIL_STAGE:-__none__}} "*) ;;\n'
        f'  *"btst_court_fetch.py"*) exit 0 ;;\n'
        f'  *" seed-evidence "*) exit 0 ;;\n'
        f'  *" decide "*) [ -n "${{V3N_FAIL_STDOUT:-}}" ] && printf \'%s\\n\' "$V3N_FAIL_STDOUT"; exit 0 ;;\n'
        f'  *" advance "*) [ -n "${{V3N_FAIL_STDOUT:-}}" ] && printf \'%s\\n\' "$V3N_FAIL_STDOUT"; exit 0 ;;\n'
        f'  *" finalize-missed "*) exit 0 ;;\n'
        f'  *) exit 0 ;;\n'
        f'esac\n'
        f'[ -n "${{V3N_FAIL_STDOUT:-}}" ] && printf \'%s\\n\' "$V3N_FAIL_STDOUT"\n'
        f'exit "${{V3N_FAIL_RC:-0}}"\n',
    )


def _run_nightly(fake_repo: Path, *args: str, now_hhmm: str = "2305",
                 manifest: bool = True, timeout: int = TIMEOUT_S,
                 extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("V3N_")]:
        env.pop(key)
    env.update(
        {
            "V3N_REPO": str(fake_repo),
            "V3N_PY": _control_stub_py(fake_repo),
            # pair 枚举器走真实解释器 (纯 stdlib 冷读; 控制 stub 对 -c 只回探活)
            "V3N_ENUM_PY": sys.executable,
            "V3N_TRIAL_CLI": str(fake_repo / "trial_cli_dummy"),
            "V3N_BOOTSTRAP_CLI": str(fake_repo / "bootstrap_cli_dummy"),
            "V3N_REPORTS_DIR": str(fake_repo / "data" / "reports"),
            "V3N_HISTORY": str(fake_repo / "logs" / "cron" / "v3_nightly_history.jsonl"),
            "V3N_NOW_HHMM": now_hhmm,
            "V3N_TODAY": "20260101",
        }
    )
    if manifest:
        (fake_repo / "data" / "reports" / "daily_action_readiness_20260101.json").write_text("{}")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(NIGHTLY), *args],
        cwd=str(fake_repo), env=env, capture_output=True, text=True, timeout=timeout,
    )


def _history(fake_repo: Path) -> list[dict]:
    path = fake_repo / "logs" / "cron" / "v3_nightly_history.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _invocations(fake_repo: Path) -> list[str]:
    path = fake_repo / "stub_invocations.jsonl"
    if not path.exists():
        return []
    return path.read_text().splitlines()


_NO_ENTRY_DECISION_JSON = json.dumps(
    {
        "decision_cycle_id": "c",
        "detail": "no candidates",
        "kernel_input_hash": "sha256:x",
        "portfolio_id": "p",
        "reason": "NO_SIGNAL",
        "signal_session": "unused",
    }
)


def _run_decision_json(entry_session: str | None, session: str = "unused") -> str:
    """RUN 决策 = 生产 27 键形态的 minimal 投影 (target_entry_session 在场);
    no-trade 决策 = 生产 6 键形态 (键缺席)。"""
    if entry_session is None:
        return _NO_ENTRY_DECISION_JSON
    return json.dumps(
        {
            "artifact_kind": "ShadowDecision",
            "decision_cycle_id": "c",
            "kernel_input_hash": "sha256:x",
            "portfolio_id": "p",
            "signal_session": session,
            "target_entry_session": entry_session,
        }
    )


def _seed_pair_stores(fake_repo: Path, *, pairs: list[str],
                      spine_rows: list[tuple[str, str]],
                      entries: dict[str, str | None] | None = None,
                      decision_json: dict[str, str] | None = None) -> None:
    """在 fake trial root 里构造 decisions/spine 冷读形态 (hermetic)。

    entries: pair 会话 → target_entry_session (RUN 决策); 缺省键 = no-trade。
    decision_json: pair 会话 → 原始 JSON 覆盖 (畸形注入测试用)。
    """
    entries = entries or {}
    decision_json = decision_json or {}
    root = fake_repo / TRIAL_ROOT_REL
    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / "decisions.sqlite3")
    conn.execute(
        "CREATE TABLE trial_arm_decisions ("
        "trial_id TEXT NOT NULL, signal_session TEXT NOT NULL,"
        " decision_cycle_id TEXT NOT NULL, arm TEXT NOT NULL,"
        " decision_json TEXT NOT NULL)"
    )
    for session in pairs:
        payload = decision_json.get(
            session, _run_decision_json(entries.get(session), session)
        )
        conn.execute(
            "INSERT INTO trial_arm_decisions VALUES ('t', ?, 'c', 'champion', ?)",
            (session, payload),
        )
    conn.commit()
    conn.close()
    conn = sqlite3.connect(root / "spine.sqlite3")
    conn.execute(
        "CREATE TABLE expected_sessions ("
        "research_program_id TEXT NOT NULL, signal_session TEXT NOT NULL,"
        " assessment_date TEXT NOT NULL)"
    )
    conn.executemany("INSERT INTO expected_sessions VALUES (?, ?, ?)", spine_rows)
    conn.commit()
    conn.close()


def _write_bars(fake_repo: Path, yyyymmdds: list[str]) -> str:
    bar_dir = fake_repo / "bars"
    bar_dir.mkdir(exist_ok=True)
    for day in yyyymmdds:
        (bar_dir / f"daily_{day}.csv").write_text("ts_code,pre_close\n")
    return str(bar_dir)


def test_preflight_broken_interpreter_records_and_skips_all_stages(fake_repo: Path) -> None:
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_PREFLIGHT_FAIL": "1"})
    assert proc.returncode == 97
    records = _history(fake_repo)
    assert len(records) == 1
    assert records[0]["detail"] == "interpreter_unavailable"
    assert _invocations(fake_repo) == []


def test_all_stages_recorded_in_order_when_gate_open_and_manifest_present(fake_repo: Path) -> None:
    proc = _run_nightly(fake_repo, "--selftest-once")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    invocations = _invocations(fake_repo)
    # fetch / seed / decide / finalize 各一次; advance 无 pair 可推进 (零决策库)
    assert len(invocations) == 4
    assert "btst_court_fetch.py" in invocations[0]
    assert " seed-evidence " in f" {invocations[1]} "
    assert " decide " in f" {invocations[2]} "
    assert f"--trial-root {fake_repo}/{TRIAL_ROOT_REL} " in f" {invocations[2]} "
    assert " finalize-missed " in f" {invocations[3]} "
    records = _history(fake_repo)
    assert [r["stage"] for r in records] == list(STAGES)
    assert all(r["rc"] == 0 for r in records)
    advance = records[3]
    assert advance["detail"] == "skipped_no_pairs"


def test_seed_invocation_carries_session_manifest_and_execute(fake_repo: Path) -> None:
    _run_nightly(fake_repo, "--selftest-once")
    seed_line = next(l for l in _invocations(fake_repo) if " seed-evidence " in f" {l} ")
    assert "--execute" in seed_line
    assert "--signal-session" in seed_line
    assert "2026-01-01" in seed_line
    assert "--readiness-manifest" in seed_line
    assert "--calendar" in seed_line
    assert "--now" in seed_line
    # seed-evidence 子命令不接受 --trial-id (生产 argv 预检实锤: argparse 即败)
    assert "--trial-id" not in seed_line
    # trial-root 必须 canonical 绝对路径 (R56 首夜实锤: 相对路径在 BlobStore
    # 构造处 blob_root_not_canonical traceback, seed 失败 → decide 链式搁浅)
    assert f"--trial-root {fake_repo}/{TRIAL_ROOT_REL} " in f" {seed_line} "


def test_seed_skipped_once_trial_underway(fake_repo: Path) -> None:
    # regime 观察是单 id 修正链且首夜后由 decide 逐会话追加 (runbook):
    # decisions 库在位 = trial 已开工, 再播必 seed_conflict — 结构性 skip。
    _seed_pair_stores(
        fake_repo,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15")],
    )
    proc = _run_nightly(fake_repo, "--selftest-once")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    records = _history(fake_repo)
    seed = next(r for r in records if r["stage"] == "seed")
    assert seed["rc"] == 0
    assert seed["detail"] == "skipped_trials_underway"
    assert not [l for l in _invocations(fake_repo) if " seed-evidence " in f" {l} "]
    # decide 照常 (regime 链归 decide 所有)
    assert " decide " in f" {_invocations(fake_repo)[1]} "


def test_gate_closed_skips_seed_and_decide_but_runs_other_stages(fake_repo: Path) -> None:
    proc = _run_nightly(fake_repo, "--selftest-once", now_hhmm="1200")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    records = _history(fake_repo)
    seed = next(r for r in records if r["stage"] == "seed")
    decide = next(r for r in records if r["stage"] == "decide")
    assert seed["detail"] == "skipped_gate_closed"
    assert decide["detail"] == "skipped_gate_closed"
    assert [r["stage"] for r in records] == list(STAGES)
    assert len(_invocations(fake_repo)) == 2  # fetch + finalize, 无 seed/decide


def test_gate_compare_is_octal_safe_for_early_morning_hours(fake_repo: Path) -> None:
    # 00-09 时段 HHMM 前导零: 门比较必须十进制 (无 stderr 八进制报错、语义恒为跳过)
    proc = _run_nightly(fake_repo, "--selftest-once", now_hhmm="0805")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "integer expression" not in proc.stderr
    records = _history(fake_repo)
    for stage in ("seed", "decide"):
        skipped = next(r for r in records if r["stage"] == stage)
        assert skipped["detail"] == "skipped_gate_closed"


def test_manifest_missing_skips_seed_and_decide_but_runs_other_stages(fake_repo: Path) -> None:
    # R57 契约收紧: 静默 skip 仅限「非交易日」(今日 ∉ 日历且 ≤ max); 日历缺失已改为
    # 响亮 calendar_unresolved, 故本回归锚显式供给周末日历 (今日 20260101 介于两会话间)。
    _write_calendar(fake_repo, ["20251231", "20260105"])
    proc = _run_nightly(fake_repo, "--selftest-once", manifest=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    records = _history(fake_repo)
    for stage in ("seed", "decide"):
        skipped = next(r for r in records if r["stage"] == stage)
        assert skipped["detail"] == "skipped_no_manifest"
    assert len(_invocations(fake_repo)) == 2


# ---- R57: decide 门交易日烧会话收口 (『无 manifest』三分类) ----
# 管道以 manifest 存在为交易日代理 → 交易日管道失败与休市日跳过在历史里逐字节
# 不可区分, R41 前向唯序下错过夜即烧官方会话。权威日历 (与管道同源) 三分类:
# 交易日 → 响亮; 周末/假日 → 静默; 日历过期/不可读 → 响亮 (分类不可信即缺口)。


def _write_calendar(fake_repo: Path, sessions: list[str]) -> str:
    path = fake_repo / "data" / "reports" / "trade_calendar.json"
    path.write_text(json.dumps(sessions), encoding="utf-8")
    return str(path)


def test_trading_day_without_manifest_fails_loud(fake_repo: Path) -> None:
    _write_calendar(fake_repo, ["20251231", "20260101", "20260105"])
    proc = _run_nightly(fake_repo, "--selftest-once", manifest=False)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    records = _history(fake_repo)
    decide = next(r for r in records if r["stage"] == "decide")
    assert decide["rc"] == 4
    assert decide["detail"] == "trading_day_no_manifest"
    # seed 同门静默 skip 保持 — 首夜种子缺席由 decide 响亮信号承载, 不双计
    seed = next(r for r in records if r["stage"] == "seed")
    assert seed["rc"] == 0
    assert seed["detail"] == "skipped_no_manifest"
    # manifest 是 decide CLI 硬输入: 缺失时绝不调用
    assert not [l for l in _invocations(fake_repo) if " decide " in f" {l} "]


def test_non_trading_day_without_manifest_stays_silent(fake_repo: Path) -> None:
    # 周末/假日 (今日 ∉ 日历但 ≤ max): 设计性静默 skip, 链 rc=0 (逐字节回归)
    _write_calendar(fake_repo, ["20251231", "20260105"])
    proc = _run_nightly(fake_repo, "--selftest-once", manifest=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    decide = next(r for r in _history(fake_repo) if r["stage"] == "decide")
    assert decide["rc"] == 0
    assert decide["detail"] == "skipped_no_manifest"


def test_stale_calendar_without_manifest_fails_loud(fake_repo: Path) -> None:
    # 今日 > 日历 max (过期): 无法确认今日是否交易日 → 响亮失败 (fail-closed)
    _write_calendar(fake_repo, ["20251231"])
    proc = _run_nightly(fake_repo, "--selftest-once", manifest=False)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    decide = next(r for r in _history(fake_repo) if r["stage"] == "decide")
    assert decide["rc"] == 4
    assert decide["detail"] == "calendar_stale"


def test_missing_calendar_without_manifest_fails_loud(fake_repo: Path) -> None:
    # 日历文件缺失: 分类不可信 → 响亮失败 (日历缺失本身即运维缺口 —
    # 管道/decide/advance 全部消费同一日历)
    proc = _run_nightly(fake_repo, "--selftest-once", manifest=False)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    decide = next(r for r in _history(fake_repo) if r["stage"] == "decide")
    assert decide["rc"] == 4
    assert decide["detail"] == "calendar_unresolved"


def test_stage_failure_recorded_without_aborting_later_stages(fake_repo: Path) -> None:
    # fetch 失败 (rc 3): seed/decide/advance/finalize 照常; 整体 rc = 失败阶段数 = 1
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_FAIL_STAGE": "btst_court_fetch.py", "V3N_FAIL_RC": "3"})
    assert proc.returncode == 1
    records = _history(fake_repo)
    assert [r["stage"] for r in records] == list(STAGES)
    assert records[0]["rc"] == 3
    assert all(r["rc"] == 0 for r in records[1:])
    assert len(_invocations(fake_repo)) == 4  # fetch(败) + seed + decide + finalize


def test_seed_typed_refusal_recorded_with_code(fake_repo: Path) -> None:
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_FAIL_STAGE": "seed-evidence", "V3N_FAIL_RC": "2",
                                   "V3N_FAIL_STDOUT": '{"ok": false, "code": "seed_conflict", "message": "m", "details": {}}'})
    assert proc.returncode == 1
    records = _history(fake_repo)
    seed = next(r for r in records if r["stage"] == "seed")
    assert seed["rc"] == 2
    assert seed["detail"] == "seed_conflict"
    # 单阶段失败不中止后续
    assert next(r for r in records if r["stage"] == "decide")["rc"] == 0
    assert next(r for r in records if r["stage"] == "finalize")["rc"] == 0


def test_advance_invokes_pair_session_with_through_clamped_to_latest_bar(fake_repo: Path) -> None:
    _seed_pair_stores(
        fake_repo,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15")],
    )
    bar_source = _write_bars(fake_repo, ["20260101", "20260102"])
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_BAR_SOURCE": bar_source})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    advance_line = next(l for l in _invocations(fake_repo) if " advance " in f" {l} ")
    assert "--execute" in advance_line
    assert "--signal-session" in advance_line and "2026-01-01" in advance_line
    # bar 只到 01-02, 未达 T+10 (01-15): through 收敛到最新 bar 会话
    assert "--through-session" in advance_line and "2026-01-02" in advance_line
    assert "--bar-source" in advance_line
    records = _history(fake_repo)
    advance = next(r for r in records if r["stage"] == "advance")
    assert advance["rc"] == 0
    assert advance["detail"] == "ok:2026-01-01->2026-01-02"


def test_advance_through_clamped_to_assessment_when_bars_beyond_window(fake_repo: Path) -> None:
    _seed_pair_stores(
        fake_repo,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15")],
    )
    bar_source = _write_bars(fake_repo, ["20260120"])
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_BAR_SOURCE": bar_source})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    advance_line = next(l for l in _invocations(fake_repo) if " advance " in f" {l} ")
    # bar 已越过 T+10: through 冻结在评估会话, 绝不越窗 (advance_window_not_in_schedule 防线)
    assert "2026-01-15" in advance_line
    assert "2026-01-20" not in advance_line


def test_advance_skipped_when_no_bars_beyond_signal_session(fake_repo: Path) -> None:
    _seed_pair_stores(
        fake_repo,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15")],
    )
    bar_source = _write_bars(fake_repo, ["20260101"])
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_BAR_SOURCE": bar_source})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    records = _history(fake_repo)
    advance = next(r for r in records if r["stage"] == "advance")
    assert advance["rc"] == 0
    assert advance["detail"] == "skipped_no_new_bars:2026-01-01"
    assert not [l for l in _invocations(fake_repo) if " advance " in f" {l} "]


def test_advance_typed_refusal_recorded_with_code_and_session(fake_repo: Path) -> None:
    _seed_pair_stores(
        fake_repo,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15")],
    )
    bar_source = _write_bars(fake_repo, ["20260101", "20260102"])
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_FAIL_STAGE": "advance", "V3N_FAIL_RC": "2",
                                   "V3N_BAR_SOURCE": bar_source,
                                   "V3N_FAIL_STDOUT": '{"ok": false, "code": "bar_sessions_missing", "message": "m", "details": {}}'})
    assert proc.returncode == 1
    records = _history(fake_repo)
    advance = next(r for r in records if r["stage"] == "advance")
    assert advance["rc"] == 2
    assert advance["detail"] == "bar_sessions_missing:2026-01-01"
    assert next(r for r in records if r["stage"] == "finalize")["rc"] == 0


def test_advance_enumeration_failure_is_fail_closed(fake_repo: Path) -> None:
    # pair 会话不在 spine (决策库与 spine 分歧) → 阶段失败, 绝不静默跳过
    _seed_pair_stores(
        fake_repo,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-02-02", "2026-02-16")],
    )
    bar_source = _write_bars(fake_repo, ["20260102"])
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_BAR_SOURCE": bar_source})
    assert proc.returncode == 1
    records = _history(fake_repo)
    advance = next(r for r in records if r["stage"] == "advance")
    assert advance["rc"] != 0
    assert advance["detail"] == "pair_enumeration_failed"
    assert not [l for l in _invocations(fake_repo) if " advance " in f" {l} "]
    assert next(r for r in records if r["stage"] == "finalize")["rc"] == 0


# ---- R223 Op1: deepest-advanceable-window advance (v1 单窗全跨度假设被生产
# dry-run 证伪: 窗口被冻结排程切片限定 = 信号+10 会话) ----
# 20260914 实录同构: pair 01-01..01-14, 入场簇 01-08 (pair 01-07)/01-09
# (pair 01-08) → min_entry=01-08, S* = 01-08, 窗口 [01-08..min(01-22, bar)]。
# per-pair 逐窗对 S>min_entry 结构性被 R216 覆盖门拒绝 = 逐夜确定性 rc=2。


def test_advance_deepest_advanceable_window_with_entry_cluster(fake_repo: Path) -> None:
    pairs = ["2026-01-01", "2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07",
             "2026-01-08", "2026-01-09", "2026-01-12", "2026-01-13", "2026-01-14"]
    assessments = {
        "2026-01-01": "2026-01-15", "2026-01-02": "2026-01-16",
        "2026-01-05": "2026-01-19", "2026-01-06": "2026-01-20",
        "2026-01-07": "2026-01-21", "2026-01-08": "2026-01-22",
        "2026-01-09": "2026-01-23", "2026-01-12": "2026-01-26",
        "2026-01-13": "2026-01-27", "2026-01-14": "2026-01-28",
    }
    _seed_pair_stores(
        fake_repo,
        pairs=pairs,
        spine_rows=[("research.btst.regime", s, a) for s, a in assessments.items()],
        entries={"2026-01-07": "2026-01-08", "2026-01-08": "2026-01-09"},
    )
    bar_source = _write_bars(fake_repo, [f"202601{d:02d}" for d in range(1, 16)])
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_BAR_SOURCE": bar_source})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    advance_lines = [l for l in _invocations(fake_repo) if " advance " in f" {l} "]
    # per-pair 形态 (修复前) 会对全部 10 个 pair 各发一次调用 — 单窗契约恰好一次
    assert len(advance_lines) == 1, advance_lines
    line = f" {advance_lines[0]} "
    # S* = deepest pair <= min_entry(01-08) = 01-08 (非最早 pair 01-01, 非最新 01-14)
    assert "--signal-session 2026-01-08" in line
    # through = min(A_S*=01-22, 最新 bar 01-15) = 01-15
    assert "--through-session 2026-01-15" in line
    records = _history(fake_repo)
    advance = next(r for r in records if r["stage"] == "advance")
    assert advance["rc"] == 0
    assert advance["detail"] == "ok:2026-01-08->2026-01-15"
    # 全部 pair 的出场在 S*+10 视野内 (BREACH 空) → 无披露行
    assert not [r for r in records if "pending_exit_horizon_breach" in r["detail"]]


def test_advance_breach_disclosure_recorded_when_run_pair_beyond_horizon(fake_repo: Path) -> None:
    # RUN pair (01-14) 超出 S* 可达视野 (01-08+10=01-22 < A_01-14=01-28) →
    # runner 层缺口的结构性披露: rc=0 响亮行, 不计入失败 (非已核销类假阳性)
    pairs = ["2026-01-07", "2026-01-08", "2026-01-14"]
    assessments = {
        "2026-01-07": "2026-01-21", "2026-01-08": "2026-01-22",
        "2026-01-14": "2026-01-28",
    }
    _seed_pair_stores(
        fake_repo,
        pairs=pairs,
        spine_rows=[("research.btst.regime", s, a) for s, a in assessments.items()],
        entries={"2026-01-07": "2026-01-08", "2026-01-08": "2026-01-09",
                 "2026-01-14": "2026-01-15"},
    )
    bar_source = _write_bars(fake_repo, ["20260115"])
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_BAR_SOURCE": bar_source})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    records = _history(fake_repo)
    advance_ok = next(r for r in records if r["stage"] == "advance"
                      and r["detail"].startswith("ok:"))
    assert advance_ok["detail"] == "ok:2026-01-08->2026-01-15"
    breach = next(r for r in records if "pending_exit_horizon_breach" in r["detail"])
    assert breach["rc"] == 0
    assert "2026-01-14" in breach["detail"]
    # 披露行不计入整体失败数
    assert proc.returncode == 0


def _read_nightly_enum_body() -> str:
    import re

    script = NIGHTLY.read_text(encoding="utf-8")
    match = re.search(r'PAIR_ENUM_PY=\$\(cat <<\'PYEOF\'\n(.*?)\nPYEOF\n\)', script, re.DOTALL)
    assert match, "PAIR_ENUM_PY heredoc not found in nightly script"
    return match.group(1)


def _run_enum(fake_repo: Path, enum_body: str, *, pairs: list[str],
              spine_rows: list[tuple[str, str]],
              entries: dict[str, str | None] | None = None,
              decision_json: dict[str, str] | None = None,
              with_column: bool = True) -> subprocess.CompletedProcess:
    import shutil

    root = fake_repo / TRIAL_ROOT_REL
    if root.exists():
        shutil.rmtree(root)
    if with_column:
        _seed_pair_stores(fake_repo, pairs=pairs, spine_rows=spine_rows,
                          entries=entries, decision_json=decision_json)
    else:
        root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(root / "decisions.sqlite3")
        conn.execute(
            "CREATE TABLE trial_arm_decisions ("
            "trial_id TEXT NOT NULL, signal_session TEXT NOT NULL,"
            " decision_cycle_id TEXT NOT NULL, arm TEXT NOT NULL)"
        )
        for session in pairs:
            conn.execute(
                "INSERT INTO trial_arm_decisions VALUES ('t', ?, 'c', 'champion')",
                (session,),
            )
        conn.commit()
        conn.close()
        conn = sqlite3.connect(root / "spine.sqlite3")
        conn.execute(
            "CREATE TABLE expected_sessions ("
            "research_program_id TEXT NOT NULL, signal_session TEXT NOT NULL,"
            " assessment_date TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO expected_sessions VALUES (?, ?, ?)", spine_rows
        )
        conn.commit()
        conn.close()
    return subprocess.run(
        [sys.executable, "-c", enum_body,
         str(root / "decisions.sqlite3"), str(root / "spine.sqlite3"),
         "research.btst.regime"],
        capture_output=True, text=True, timeout=TIMEOUT_S,
    )


def test_real_pair_enumerator_deepest_window_and_breach(fake_repo: Path) -> None:
    enum_body = _read_nightly_enum_body()

    # 入场簇形态: ADVANCE 行 = (S*=01-08, A=01-22); BREACH 空
    proc = _run_enum(
        fake_repo, enum_body,
        pairs=["2026-01-01", "2026-01-07", "2026-01-08", "2026-01-12"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15"),
                    ("research.btst.regime", "2026-01-07", "2026-01-21"),
                    ("research.btst.regime", "2026-01-08", "2026-01-22"),
                    ("research.btst.regime", "2026-01-12", "2026-01-26")],
        entries={"2026-01-07": "2026-01-08", "2026-01-08": "2026-01-09"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["ADVANCE 2026-01-08 2026-01-22"]

    # RUN pair 超视野: BREACH 行列出全部 P > S* 的 RUN pair
    proc = _run_enum(
        fake_repo, enum_body,
        pairs=["2026-01-07", "2026-01-08", "2026-01-12", "2026-01-14"],
        spine_rows=[("research.btst.regime", "2026-01-07", "2026-01-21"),
                    ("research.btst.regime", "2026-01-08", "2026-01-22"),
                    ("research.btst.regime", "2026-01-12", "2026-01-26"),
                    ("research.btst.regime", "2026-01-14", "2026-01-28")],
        entries={"2026-01-07": "2026-01-08", "2026-01-08": "2026-01-09",
                 "2026-01-12": "2026-01-13", "2026-01-14": "2026-01-15"},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [
        "ADVANCE 2026-01-08 2026-01-22",
        "BREACH 2026-01-12,2026-01-14",
    ]

    # 无任何入场: S* = 最新 pair (与无入场 trial 的现行行为兼容), 无 BREACH
    proc = _run_enum(
        fake_repo, enum_body,
        pairs=["2026-01-01", "2026-01-02"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15"),
                    ("research.btst.regime", "2026-01-02", "2026-01-16")],
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == ["ADVANCE 2026-01-02 2026-01-16"]

    # 零 pair: 空 stdout rc=0 → 上层 skipped_no_pairs
    proc = _run_enum(fake_repo, enum_body, pairs=[], spine_rows=[])
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""

    # 发散: pair 不在 spine → rc=3, 无 stdout
    proc = _run_enum(
        fake_repo, enum_body,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-02-02", "2026-02-16")],
    )
    assert proc.returncode == 3
    assert proc.stdout.strip() == ""
    assert "absent from spine" in proc.stderr


def test_real_pair_enumerator_fail_closed_on_decision_json_shapes(fake_repo: Path) -> None:
    enum_body = _read_nightly_enum_body()

    # decision_json 列缺失 (schema 漂移) → rc=3
    proc = _run_enum(
        fake_repo, enum_body,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15")],
        with_column=False,
    )
    assert proc.returncode == 3
    assert proc.stdout.strip() == ""

    # decision_json 畸形 (不可解析) → rc=3
    proc = _run_enum(
        fake_repo, enum_body,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15")],
        decision_json={"2026-01-01": "{not-json"},
    )
    assert proc.returncode == 3
    assert proc.stdout.strip() == ""

    # RUN 决策缺 target_entry_session (json 键漂移) → rc=3, 不冒充无入场
    proc = _run_enum(
        fake_repo, enum_body,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15")],
        decision_json={"2026-01-01": json.dumps(
            {"artifact_kind": "ShadowDecision", "decision_cycle_id": "c"})},
    )
    assert proc.returncode == 3
    assert proc.stdout.strip() == ""

    # target_entry_session 形状漂移 (恰 10 位但无连字符) → rc=3 (R223 Op2 P12 钉:
    # ISO 形状校验弱化 (仅查长度) 会让 "2026010800" 放行, min_entry 字典序
    # 比较中毒 — 用例必须恰被连字符检查拒绝而非长度检查, 否则是假牙)
    proc = _run_enum(
        fake_repo, enum_body,
        pairs=["2026-01-01"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15")],
        entries={"2026-01-01": "2026010800"},
    )
    assert proc.returncode == 3
    assert proc.stdout.strip() == ""
    assert "target_entry_session malformed" in proc.stderr


def test_advance_multi_advance_row_drift_is_fail_closed(fake_repo: Path) -> None:
    # R223 Op2 P15 钉: 枚举器输出多行 ADVANCE = 漂移形态 — 选取面 (head/tail)
    # 必须不可达, 恰一行契约违例 → pair_enumeration_failed (绝不静默选一行)
    _seed_pair_stores(
        fake_repo,
        pairs=["2026-01-01", "2026-01-08"],
        spine_rows=[("research.btst.regime", "2026-01-01", "2026-01-15"),
                    ("research.btst.regime", "2026-01-08", "2026-01-22")],
    )
    bar_source = _write_bars(fake_repo, ["20260115"])
    stub_enum = _write_stub(
        fake_repo / "stub_enum_py",
        '#!/bin/bash\nprintf "ADVANCE 2026-01-01 2026-01-15\\nADVANCE 2026-01-08 2026-01-22\\n"\nexit 0\n',
    )
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_BAR_SOURCE": bar_source,
                                   "V3N_ENUM_PY": stub_enum})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    records = _history(fake_repo)
    advance = next(r for r in records if r["stage"] == "advance"
                   and r["detail"] != "skipped_no_bars")
    assert advance["rc"] == 3
    assert advance["detail"] == "pair_enumeration_failed"
    assert not [l for l in _invocations(fake_repo) if " advance " in f" {l} "]


def test_selftest_touches_no_lock_or_pid(fake_repo: Path) -> None:
    _run_nightly(fake_repo, "--selftest-once")
    assert not (fake_repo / "logs" / ".daily_daemon.pid").exists()
    assert not (fake_repo / "logs" / ".daily_daemon.lock.d").exists()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
