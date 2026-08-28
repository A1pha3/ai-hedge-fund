#!/bin/bash
# v3 官方 Trial 夜间运维链 (2026-08-28, R54 Op2)
#
# R53b 登记的 next_trigger ("今晚 23:30 定时任务执行 decide 08-28") 在代码面
# 不存在 — 本脚本是 runbook 2b/2c + 该 next_trigger 的自动化落地, 由
# daily_daemon.sh 的 23:05 触发点串行调用 (也可手动单跑)。
#
# 三阶段 (顺序执行, 单阶段失败不中止后续, 整体 rc = 失败阶段数):
#   1. fetch    — bar 源幂等续传 (scripts/btst_court_fetch.py, runbook 2b 前置)
#   2. decide   — 今日信号会话决策 (v3_trial_session.py decide --execute)
#                 门: 本地时刻 >= 23:00 (decide 窗 15:00 UTC 开) 且今日
#                 readiness manifest 在位; 缺一为 skipped 记录而非失败 —
#                 decide 窗口只开 24h, 错过即由 finalize-missed 走 NO_RUN,
#                 绝不回头补 decide (R41 前向唯序纪律)。
#   3. finalize — 错过会话 NO_RUN 补记 (v3_trial_session.py finalize-missed --execute)
#
# 每阶段一条 JSONL 记录进 logs/cron/v3_nightly_history.jsonl
# (date/stage/rc/detail); decide/finalize 的 rc=2 typed 拒绝如实转记 code。
# 解释器 preflight 失败 → 恰一条失败记录 + exit 97 + 零阶段调用
# (镜像 daily_daemon R54 Op1 语义)。
#
# selftest 注入面 (--selftest-once + V3N_* 环境变量) 供 hermetic 测试:
# 零锁、零 pid、零生产 trial root 触碰。生产默认 (V3N_* 未设) 即官方栈参数。

set -u

REPO="${V3N_REPO:-/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork}"
PY="${V3N_PY:-$REPO/.venv/bin/python}"
TRIAL_CLI="${V3N_TRIAL_CLI:-scripts/v3_trial_session.py}"
FETCH="${V3N_FETCH:-scripts/btst_court_fetch.py}"
IDENTITY_DIR="${V3N_IDENTITY_DIR:-data/v3_governance_identity}"
TRIAL_ROOT="${V3N_TRIAL_ROOT:-data/v3_trial_root}"
TRIAL_ID="${V3N_TRIAL_ID:-trial-btst-regime-r1}"
RESEARCH_PROGRAM="${V3N_RESEARCH_PROGRAM:-research.btst.regime}"
CALENDAR="${V3N_CALENDAR:-data/reports/trade_calendar.json}"
DATA_DIR="${V3N_DATA_DIR:-data}"
REPORTS_DIR="${V3N_REPORTS_DIR:-data/reports}"
HISTORY="${V3N_HISTORY:-logs/cron/v3_nightly_history.jsonl}"
DECIDE_GATE="${V3N_DECIDE_GATE:-2300}"
NOW_HHMM="${V3N_NOW_HHMM:-$(date +%H%M)}"
TODAY_COMPACT="${V3N_TODAY:-$(date +%Y%m%d)}"
TODAY_DASH="${TODAY_COMPACT:0:4}-${TODAY_COMPACT:4:2}-${TODAY_COMPACT:6:2}"

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

# ---- 阶段 2: decide 今日信号会话 (窗口 + manifest 双门) ----
MANIFEST="$REPORTS_DIR/daily_action_readiness_${TODAY_COMPACT}.json"
# 10# 强制十进制: 00-09 时段的 HHMM 前导零否则落 bash 八进制报错语义
if [ "$((10#$NOW_HHMM))" -lt "$((10#$DECIDE_GATE))" ]; then
    echo "[$(date '+%F %T')] [v3-nightly] decide 跳过: 未到窗口 ($NOW_HHMM < $DECIDE_GATE 北京)"
    record "decide" 0 "skipped_gate_closed"
elif [ ! -f "$MANIFEST" ]; then
    echo "[$(date '+%F %T')] [v3-nightly] decide 跳过: 今日 readiness manifest 不在位 ($MANIFEST) — 日度管道未跑或失败?"
    record "decide" 0 "skipped_no_manifest"
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

# ---- 阶段 3: finalize-missed (幂等 NO_RUN 补记) ----
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
