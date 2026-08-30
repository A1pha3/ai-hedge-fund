#!/bin/bash
# 研究数据面统一日更驱动器 (2026-08-29, R58 数据新鲜度工作线; owner 批准 18:30 规格)
#
# 由 daily_daemon.sh 的 18:30 触发点调用 (也可手动单跑):
#   1. bars      — 权威研究面板续传 (scripts/btst_court_fetch.py, 幂等跳过已有日;
#                  23:05 v3 夜间链的 fetch 阶段保持不动, 本阶段只是把新鲜度提前到
#                  晚间研究时段)
#   2. lhb       — 龙虎榜续传 (scripts/fetch_lhb_daily.py; 修复旧 except:pass 静默
#                  死亡 — 2026-07-07 起停更 53 天)
#   3. court     — court 事件表重建 (scripts/btst_court_build.py, 纯本地 raw,
#                  指纹幂等; R72: 无自动化则 bench 重评触发器永不到期)
#   4. freshness — 新鲜度门 (scripts/research_freshness.py 只读仪表; 六数据集
#                  latest vs 权威日历期望会话, rc=陈旧数据集数)
#
# price_cache/fund_flow_cache/industry_index 由 18:01 v2 管道保鲜, 本驱动器不重复
# 拉取 — 仪表只观测。
#
# 每阶段一条 JSONL 记录进 logs/cron/research_refresh_history.jsonl
# (date/stage/rc/detail); 单阶段失败不中止后续, 整体 rc = 失败阶段数。
# 解释器 preflight 失败 → 恰一条失败记录 + exit 97 + 零阶段调用
# (镜像 daily_daemon R54 Op1 / v3_trial_nightly 同款语义)。
#
# selftest 注入面 (--selftest-once + V3R_* 环境变量) 供 hermetic 测试:
# 零锁、零 pid、零生产数据写入。生产默认 (V3R_* 未设) 即官方参数。

set -u

REPO="${V3R_REPO:-/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork}"
PY="${V3R_PY:-$REPO/.venv/bin/python}"
BARS_FETCH="${V3R_BARS_FETCH:-scripts/btst_court_fetch.py}"
LHB_FETCH="${V3R_LHB_FETCH:-scripts/fetch_lhb_daily.py}"
FRESHNESS="${V3R_FRESHNESS:-scripts/research_freshness.py}"
COURT_BUILD="${V3R_COURT_BUILD:-scripts/btst_court_build.py}"
HISTORY="${V3R_HISTORY:-$REPO/logs/cron/research_refresh_history.jsonl}"
TODAY="${V3R_TODAY:-$(date +%Y%m%d)}"

case "${1:-}" in
    ""|--selftest-once) : ;;
    *) echo "用法: research_data_refresh.sh [--selftest-once]" >&2; exit 64 ;;
esac

cd "$REPO" || { echo "cd fail" >&2; exit 80; }

record() {  # <stage> <rc> <detail>
    mkdir -p "$(dirname "$HISTORY")" 2>/dev/null
    if ! printf '{"date":"%s","stage":"%s","rc":%s,"detail":"%s"}\n' \
            "$(date +%Y%m%d)" "$1" "$2" "$3" >> "$HISTORY"; then
        echo "[research-refresh] 警告: 阶段记录写盘失败 ($HISTORY)" >&2
    fi
}

typed_code() {  # 从 CLI 失败 JSON 提取权威 code (契约: {"ok": false, "code": ...})
    printf '%s' "$1" | grep -o '"code": "[a-z_]*"' | head -1 | cut -d'"' -f4
}

# ---- 解释器 preflight (R54 Op1 语义) ----
if ! "$PY" -c pass >/dev/null 2>&1; then
    echo "[$(date '+%F %T')] [research-refresh] 解释器不可用 — 放弃本轮数据刷新"
    record "preflight" 7 "interpreter_unavailable"
    exit 97
fi

FAILS=0

# ---- 阶段 1: bars 权威研究面板续传 (幂等) ----
echo "[$(date '+%F %T')] [research-refresh] === 阶段 bars: 权威研究面板续传 ==="
OUT=$("$PY" "$BARS_FETCH" 2>&1)
rc=$?
printf '%s\n' "$OUT" | tail -5
if [ "$rc" -eq 0 ]; then
    record "bars" 0 "ok"
else
    echo "[$(date '+%F %T')] [research-refresh] bars 续传失败 rc=$rc (23:05 夜链将重试; 明晨研究面可能陈旧)"
    record "bars" "$rc" "bars_fetch_failed"
    FAILS=$((FAILS + 1))
fi

# ---- 阶段 2: 龙虎榜续传 (期望会话锚定今日) ----
echo "[$(date '+%F %T')] [research-refresh] === 阶段 lhb: 龙虎榜续传 ==="
OUT=$("$PY" "$LHB_FETCH" --today "$TODAY" 2>&1)
rc=$?
printf '%s\n' "$OUT" | tail -5
if [ "$rc" -eq 0 ]; then
    record "lhb" 0 "ok"
else
    CODE=$(typed_code "$OUT")
    echo "[$(date '+%F %T')] [research-refresh] lhb 续传失败 rc=$rc code=${CODE:-unknown}"
    record "lhb" "$rc" "${CODE:-lhb_fetch_failed}"
    FAILS=$((FAILS + 1))
fi

# ---- 阶段 3: court 事件表重建 (纯本地 raw; 指纹幂等) ----
echo "[$(date '+%F %T')] [research-refresh] === 阶段 court: 事件表重建 ==="
OUT=$("$PY" "$COURT_BUILD" 2>&1)
rc=$?
printf '%s\n' "$OUT" | tail -3
if [ "$rc" -eq 0 ]; then
    record "court_build" 0 "ok"
else
    CODE=$(typed_code "$OUT")
    echo "[$(date '+%F %T')] [research-refresh] court 重建失败 rc=$rc (研究面停留旧表; 次夜重试)"
    record "court_build" "$rc" "${CODE:-court_build_failed}"
    FAILS=$((FAILS + 1))
fi

# ---- 阶段 4: 新鲜度门 (只读仪表; rc=陈旧数据集数) ----
echo "[$(date '+%F %T')] [research-refresh] === 阶段 freshness: 新鲜度门 ==="
OUT=$("$PY" "$FRESHNESS" --today "$TODAY" 2>&1)
rc=$?
printf '%s\n' "$OUT"
if [ "$rc" -eq 0 ]; then
    record "freshness" 0 "ok"
else
    CODE=$(typed_code "$OUT")
    echo "[$(date '+%F %T')] [research-refresh] 新鲜度门未过 rc=$rc code=${CODE:-unknown}"
    record "freshness" "$rc" "${CODE:-freshness_gate_failed}"
    FAILS=$((FAILS + 1))
fi

echo "[$(date '+%F %T')] [research-refresh] === 数据刷新结束 (失败阶段数: $FAILS) ==="
exit "$FAILS"
