#!/bin/bash
# v3 官方 Trial 夜间运维链 (2026-08-28, R54 Op2 建立; R55 补全 runbook 五步序列)
#
# runbook 权威日度序列 (docs/runbooks/v3-trial-launch.md 「日度驱动」) 的自动化,
# 由 daily_daemon.sh 的 23:05 触发点串行调用 (也可手动单跑):
#
# 五阶段 (顺序执行, 单阶段失败不中止后续, 整体 rc = 失败阶段数):
#   1. fetch    — bar 源幂等续传 (scripts/btst_court_fetch.py, runbook 2b 前置)
#   2. seed     — 首夜 bootstrap: regime 证据播种 (v3_trial_bootstrap.py
#                 seed-evidence), 与 decide 共用双门; 缺席则 decide execute 在
#                 官方栈构造处以 evidence_not_seeded/bars_store_not_seeded
#                 冷读拒绝 (R37 守卫)。regime 观察是单 id 修正链且首夜后由
#                 decide 逐会话追加 (runbook), 故 trial 开工 (decisions 库在位)
#                 后本阶段 skip; 首夜 crash 重试若异时刻重放会 seed_conflict
#                 (typed, 只记失败不停链) — decide 复用首播观察照常收敛。
#   3. decide   — 今日信号会话决策 (v3_trial_session.py decide --execute)
#                 门: 本地时刻 >= 23:00 (decide 窗 15:00 UTC 开) 且今日
#                 readiness manifest 在位; 缺一为 skipped 记录而非失败 —
#                 decide 窗口只开 24h, 错过即由 finalize-missed 走 NO_RUN,
#                 绝不回头补 decide (R41 前向唯序纪律)。
#   4. advance  — pair 执行窗口推进 (v3_trial_session.py advance --execute)
#                 只推进 decisions 库已有 pair 的会话; through =
#                 min(spine T+10 评估会话, bar 源最新会话); 枚举面 fail-closed。
#                 冷读只见已 checkpoint 主文件: crash 残留 WAL 的 pair 本夜
#                 不可见 → skipped_no_pairs, 次夜追平 (失败方向=欠推进)。
#   5. finalize — 错过会话 NO_RUN 补记 (v3_trial_session.py finalize-missed --execute)
#
# 每阶段一条 JSONL 记录进 logs/cron/v3_nightly_history.jsonl
# (date/stage/rc/detail); seed/decide/advance/finalize 的 rc=2 typed 拒绝如实
# 转记 code。解释器 preflight 失败 → 恰一条失败记录 + exit 97 + 零阶段调用
# (镜像 daily_daemon R54 Op1 语义)。
#
# selftest 注入面 (--selftest-once + V3N_* 环境变量) 供 hermetic 测试:
# 零锁、零 pid、零生产 trial root 触碰。生产默认 (V3N_* 未设) 即官方栈参数。

set -u

REPO="${V3N_REPO:-/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork}"
PY="${V3N_PY:-$REPO/.venv/bin/python}"
# pair 枚举器解释器独立注入面: 生产 = $PY (preflight 已保证可用; 枚举纯 stdlib);
# hermetic 测试指向真实 python3 (控制 stub 对 -c 形态只回探活结果, 不真执行)
ENUM_PY="${V3N_ENUM_PY:-$PY}"
TRIAL_CLI="${V3N_TRIAL_CLI:-scripts/v3_trial_session.py}"
BOOTSTRAP_CLI="${V3N_BOOTSTRAP_CLI:-scripts/v3_trial_bootstrap.py}"
FETCH="${V3N_FETCH:-scripts/btst_court_fetch.py}"
# 数据路径默认全部锚定 $REPO 绝对化 (R56 首夜实锤: 相对 trial-root 在
# BlobStore 构造处被 canonical-absolute 守卫拒绝 blob_root_not_canonical —
# R31 路径纪律要求调用方供 canonical 绝对路径, 脚本不得依赖 cd 后的相对语义)
IDENTITY_DIR="${V3N_IDENTITY_DIR:-$REPO/data/v3_governance_identity}"
TRIAL_ROOT="${V3N_TRIAL_ROOT:-$REPO/data/v3_trial_root}"
TRIAL_ID="${V3N_TRIAL_ID:-trial-btst-regime-r1}"
RESEARCH_PROGRAM="${V3N_RESEARCH_PROGRAM:-research.btst.regime}"
CALENDAR="${V3N_CALENDAR:-$REPO/data/reports/trade_calendar.json}"
BAR_SOURCE="${V3N_BAR_SOURCE:-$REPO/data/research/btst_court/raw/daily}"
DATA_DIR="${V3N_DATA_DIR:-$REPO/data}"
REPORTS_DIR="${V3N_REPORTS_DIR:-$REPO/data/reports}"
HISTORY="${V3N_HISTORY:-$REPO/logs/cron/v3_nightly_history.jsonl}"
DECIDE_GATE="${V3N_DECIDE_GATE:-2300}"
NOW_HHMM="${V3N_NOW_HHMM:-$(date +%H%M)}"
TODAY_COMPACT="${V3N_TODAY:-$(date +%Y%m%d)}"
TODAY_DASH="${TODAY_COMPACT:0:4}-${TODAY_COMPACT:4:2}-${TODAY_COMPACT:6:2}"

# advance pair 枚举器 (immutable 冷读, 零写入; R35/R37 冷读纪律):
# decisions 库缺失/无表 = 尚无 pair (合法形态, 空输出);
# 决策库与 spine 分歧 (pair 会话缺 T+10 注册 / spine 缺失) = 真实损坏面,
# 非零退出 → 阶段失败, 绝不静默跳过 (P2-1: 宽吞会假装没看到坏记录)。
PAIR_ENUM_PY=$(cat <<'PYEOF'
import sqlite3
import sys
from pathlib import Path

decisions_db, spine_db, program = sys.argv[1], sys.argv[2], sys.argv[3]
if not Path(decisions_db).is_file():
    print("")
    raise SystemExit(0)
conn = sqlite3.connect(f"file:{decisions_db}?mode=ro&immutable=1", uri=True)
try:
    pairs = [row[0] for row in conn.execute(
        "SELECT DISTINCT signal_session FROM trial_arm_decisions"
        " ORDER BY signal_session"
    )]
except sqlite3.OperationalError as exc:
    if "no such table" in str(exc):
        print("")
        raise SystemExit(0)
    print(exc, file=sys.stderr)
    raise SystemExit(3)
finally:
    conn.close()
if not Path(spine_db).is_file():
    print("spine missing", file=sys.stderr)
    raise SystemExit(3)
conn = sqlite3.connect(f"file:{spine_db}?mode=ro&immutable=1", uri=True)
try:
    rows = conn.execute(
        "SELECT signal_session, assessment_date FROM expected_sessions"
        " WHERE research_program_id = ?",
        (program,),
    ).fetchall()
except sqlite3.OperationalError as exc:
    print(exc, file=sys.stderr)
    raise SystemExit(3)
finally:
    conn.close()
assessments = dict(rows)
for session in pairs:
    if session not in assessments:
        print(f"pair session {session} absent from spine", file=sys.stderr)
        raise SystemExit(3)
print(";".join(f"{s} {assessments[s]}" for s in pairs))
PYEOF
)

cd "$REPO" || { echo "cd fail" >&2; exit 80; }

record() {  # <stage> <rc> <detail>
    mkdir -p "$(dirname "$HISTORY")" 2>/dev/null
    if ! printf '{"date":"%s","stage":"%s","rc":%s,"detail":"%s"}\n' \
            "$(date +%Y%m%d)" "$1" "$2" "$3" >> "$HISTORY"; then
        echo "[v3-nightly] 警告: 阶段记录写盘失败 ($HISTORY)" >&2
    fi
}

typed_code() {  # 从 CLI 失败 JSON 提取权威 code (契约: {"ok": false, "code": ...})
    printf '%s' "$1" | grep -o '"code": "[a-z_]*"' | head -1 | cut -d'"' -f4
}

case "${1:-}" in
    ""|--selftest-once) : ;;
    *) echo "用法: v3_trial_nightly.sh [--selftest-once]" >&2; exit 64 ;;
esac

# ---- 解释器 preflight (R54 Op1 语义) ----
if ! "$PY" -c pass >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] [v3-nightly] 解释器不可用 — 放弃本轮夜间链"
    record "preflight" 7 "interpreter_unavailable"
    exit 97
fi

FAILS=0

# ---- 阶段 1: bar 源刷新 (幂等续传, 失败只记录 — advance 面会在 bar 缺失时 fail-closed) ----
echo "[$(date '+%F %T')] [v3-nightly] === 阶段 fetch: bar 源刷新 ==="
"$PY" "$FETCH"
rc=$?
if [ "$rc" -eq 0 ]; then
    record "fetch" 0 "ok"
else
    echo "[$(date '+%F %T')] [v3-nightly] bar 源刷新失败 rc=$rc (明日 advance 将缺今日 bar, 请人工介入)"
    record "fetch" "$rc" "fetch_failed"
    FAILS=$((FAILS + 1))
fi

# ---- seed/decide 共用双门: decide 窗口 (23:00 北京后) + 今日 manifest 在位 ----
MANIFEST="$REPORTS_DIR/daily_action_readiness_${TODAY_COMPACT}.json"
# 10# 强制十进制: 00-09 时段的 HHMM 前导零否则落 bash 八进制报错语义
if [ "$((10#$NOW_HHMM))" -lt "$((10#$DECIDE_GATE))" ]; then
    GATE_REASON="skipped_gate_closed"
elif [ ! -f "$MANIFEST" ]; then
    GATE_REASON="skipped_no_manifest"
else
    GATE_REASON=""
fi

# ---- 阶段 2: seed 首夜 bootstrap (decide 的栈构造硬前提, runbook 日度步 2) ----
# trial 开工 (decisions 库在位 = 首 decide 已发生) 后 regime 修正链归 decide
# 所有, 再播必 seed_conflict (单 id 单线程序列) — 结构性 skip, 不留每夜噪音。
if [ -n "$GATE_REASON" ]; then
    echo "[$(date '+%F %T')] [v3-nightly] seed 跳过: $GATE_REASON"
    record "seed" 0 "$GATE_REASON"
elif [ -f "$TRIAL_ROOT/decisions.sqlite3" ]; then
    echo "[$(date '+%F %T')] [v3-nightly] seed 跳过: trial 已开工 (decisions 库在位), regime 链归 decide"
    record "seed" 0 "skipped_trials_underway"
else
    echo "[$(date '+%F %T')] [v3-nightly] === 阶段 seed: $TODAY_DASH regime 播种 ==="
    OUT=$("$PY" "$BOOTSTRAP_CLI" seed-evidence \
        --identity-dir "$IDENTITY_DIR" \
        --trial-root "$TRIAL_ROOT" \
        --calendar "$CALENDAR" \
        --now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --execute \
        --readiness-manifest "$MANIFEST" \
        --signal-session "$TODAY_DASH" \
        --data-dir "$DATA_DIR" 2>&1)
    rc=$?
    printf '%s\n' "$OUT"
    if [ "$rc" -eq 0 ]; then
        record "seed" 0 "ok"
    else
        CODE=$(typed_code "$OUT")
        echo "[$(date '+%F %T')] [v3-nightly] seed 类型化拒绝 rc=$rc code=${CODE:-unknown}"
        record "seed" "$rc" "${CODE:-seed_failed}"
        FAILS=$((FAILS + 1))
    fi
fi

# ---- 阶段 3: decide 今日信号会话 (窗口 + manifest 双门) ----
if [ -n "$GATE_REASON" ]; then
    echo "[$(date '+%F %T')] [v3-nightly] decide 跳过: $GATE_REASON"
    record "decide" 0 "$GATE_REASON"
else
    echo "[$(date '+%F %T')] [v3-nightly] === 阶段 decide: $TODAY_DASH ==="
    OUT=$("$PY" "$TRIAL_CLI" decide \
        --identity-dir "$IDENTITY_DIR" \
        --trial-root "$TRIAL_ROOT" \
        --trial-id "$TRIAL_ID" \
        --research-program "$RESEARCH_PROGRAM" \
        --calendar "$CALENDAR" \
        --now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        --execute \
        --readiness-manifest "$MANIFEST" \
        --signal-session "$TODAY_DASH" \
        --data-dir "$DATA_DIR" 2>&1)
    rc=$?
    printf '%s\n' "$OUT"
    if [ "$rc" -eq 0 ]; then
        record "decide" 0 "ok"
    else
        CODE=$(typed_code "$OUT")
        echo "[$(date '+%F %T')] [v3-nightly] decide 类型化拒绝 rc=$rc code=${CODE:-unknown}"
        record "decide" "$rc" "${CODE:-decide_failed}"
        FAILS=$((FAILS + 1))
    fi
fi

# ---- 阶段 4: advance 执行窗口推进 (runbook 日度步 4; 只推进已有 pair 的会话) ----
echo "[$(date '+%F %T')] [v3-nightly] === 阶段 advance: pair 执行窗口推进 ==="
LATEST_BAR="$(ls "$BAR_SOURCE"/daily_*.csv 2>/dev/null \
    | sed -n 's/.*daily_\([0-9]\{8\}\)\.csv/\1/p' | sort | tail -1)"
LATEST_BAR_DASH=""
if [ -n "$LATEST_BAR" ]; then
    LATEST_BAR_DASH="${LATEST_BAR:0:4}-${LATEST_BAR:4:2}-${LATEST_BAR:6:2}"
fi
PAIR_ROWS="$("$ENUM_PY" -c "$PAIR_ENUM_PY" \
    "$TRIAL_ROOT/decisions.sqlite3" "$TRIAL_ROOT/spine.sqlite3" "$RESEARCH_PROGRAM")"
rc=$?
if [ "$rc" -ne 0 ]; then
    echo "[$(date '+%F %T')] [v3-nightly] advance pair 枚举失败 rc=$rc (决策库/spine 分歧, fail-closed)"
    record "advance" "$rc" "pair_enumeration_failed"
    FAILS=$((FAILS + 1))
elif [ -z "$PAIR_ROWS" ]; then
    echo "[$(date '+%F %T')] [v3-nightly] advance 跳过: 尚无 pair (决策库缺失或零决策)"
    record "advance" 0 "skipped_no_pairs"
elif [ -z "$LATEST_BAR_DASH" ]; then
    echo "[$(date '+%F %T')] [v3-nightly] advance 跳过: bar 源无快照 ($BAR_SOURCE)"
    record "advance" 0 "skipped_no_bars"
else
    IFS=';' read -r -a PAIR_ITEMS <<< "$PAIR_ROWS"
    for item in "${PAIR_ITEMS[@]}"; do
        S="${item%% *}"; ASSESS="${item##* }"
        THROUGH="$ASSESS"
        if [ "$LATEST_BAR_DASH" \< "$THROUGH" ]; then THROUGH="$LATEST_BAR_DASH"; fi
        if [ ! "$S" \< "$THROUGH" ]; then
            echo "[$(date '+%F %T')] [v3-nightly] advance 跳过 $S: through=$THROUGH 未越过信号会话 (T+1 bar 未到)"
            record "advance" 0 "skipped_no_new_bars:$S"
            continue
        fi
        echo "[$(date '+%F %T')] [v3-nightly] advance $S → $THROUGH (评估窗至 $ASSESS)"
        OUT=$("$PY" "$TRIAL_CLI" advance \
            --identity-dir "$IDENTITY_DIR" \
            --trial-root "$TRIAL_ROOT" \
            --trial-id "$TRIAL_ID" \
            --research-program "$RESEARCH_PROGRAM" \
            --calendar "$CALENDAR" \
            --now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            --execute \
            --signal-session "$S" \
            --through-session "$THROUGH" \
            --bar-source "$BAR_SOURCE" 2>&1)
        rc=$?
        printf '%s\n' "$OUT"
        if [ "$rc" -eq 0 ]; then
            record "advance" 0 "ok:$S->$THROUGH"
        else
            CODE=$(typed_code "$OUT")
            echo "[$(date '+%F %T')] [v3-nightly] advance 类型化拒绝 rc=$rc code=${CODE:-unknown} ($S)"
            record "advance" "$rc" "${CODE:-advance_failed}:$S"
            FAILS=$((FAILS + 1))
        fi
    done
fi

# ---- 阶段 5: finalize-missed (幂等 NO_RUN 补记) ----
echo "[$(date '+%F %T')] [v3-nightly] === 阶段 finalize: 错过会话补记 ==="
OUT=$("$PY" "$TRIAL_CLI" finalize-missed \
    --identity-dir "$IDENTITY_DIR" \
    --trial-root "$TRIAL_ROOT" \
    --trial-id "$TRIAL_ID" \
    --research-program "$RESEARCH_PROGRAM" \
    --calendar "$CALENDAR" \
    --now "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --execute 2>&1)
rc=$?
printf '%s\n' "$OUT"
if [ "$rc" -eq 0 ]; then
    record "finalize" 0 "ok"
else
    CODE=$(typed_code "$OUT")
    echo "[$(date '+%F %T')] [v3-nightly] finalize 类型化拒绝 rc=$rc code=${CODE:-unknown}"
    record "finalize" "$rc" "${CODE:-finalize_failed}"
    FAILS=$((FAILS + 1))
fi

echo "[$(date '+%F %T')] [v3-nightly] === 夜间链结束 (失败阶段数: $FAILS) ==="
exit "$FAILS"
