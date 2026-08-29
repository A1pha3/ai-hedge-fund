#!/bin/bash
# 每日管道常驻守护 (2026-08-18, 用户手动启动)
#
# 背景: 哨点实测 30 个交易日断跑 19 天 — 策略价值以"每天运行"为前提。
# 本脚本常驻运行, 每天 18:00 自动执行 --auto → --daily-action 串行链
# (18:00 = 收盘 15:00 后数据源已就绪、17:00 规则通过、当日信号当日出、
#  次日开盘成交)。
#
# 为什么不用 launchd/cron: 外置卷 (/Volumes/...) 受 macOS TCC 保护,
# launchd/cron 启动的进程读卷上文件会被拒; 本脚本由用户终端手动启动,
# 继承终端授权, 无权限问题。
#
# 解释器故障韧性 (2026-08-28 R54): 08-27 .venv python 被 TCC 拒绝
# (pyvenv.cfg PermissionError) 致当日管道全天漏跑 — 静默、无补跑、无记录。
# 本版修复三面:
#   1. 调度数学改纯 bash — SLEEP 计算不再依赖 $PY (旧版解释器故障时
#      SLEEP 计算同步瘫痪, 300s 空转循环 4 小时)。
#   2. run_once 解释器 preflight — 管道执行前先 "$PY -c pass" 探活;
#      失败时以 daemon 自身 (printf) 显式写失败行进 status_history.jsonl
#      (date/daemon_error/rc/attempt), 并当晚有界重试 (默认 10 次 × 30min),
#      全部失败留终态 gave_up 行, 退出码 97。绝不静默跳过当日。
#   3. selftest 注入面 (--selftest-once / --print-config /
#      --selftest-next-trigger / --selftest-dispatch) — 环境变量
#      (DAEMON_REPO/DAEMON_PY/DAEMON_PIPELINE/DAEMON_STATUS_HISTORY/
#      DAEMON_MAX_ATTEMPTS/DAEMON_RETRY_INTERVAL/DAEMON_TRIGGER_HH/
#      DAEMON_TRIGGER_MM/DAEMON_NIGHT_HH/DAEMON_NIGHT_MM) 可覆盖全部配置
#      供 hermetic 测试; selftest 路径在单实例锁之前解析, 绝不触碰生产锁
#      与 pid 文件。生产默认 (环境变量未设) 行为不变。
#
# 双触发调度 (2026-08-28 R54 Op2): 每天 18:01 v2 每日管道 +
# 23:05 v3 Trial 夜间运维链 (scripts/v3_trial_nightly.sh: bar 刷新 →
# decide 今日会话 → finalize-missed)。两触发互相独立, 各自失败不波及对方。
# 已知边界 (v1 同语义): 机器休眠/关机错过触发点不补跑。
#
# 用法 (在项目目录):
#   nohup bash scripts/daily_daemon.sh >> logs/cron/daemon.log 2>&1 &
#   (启动后即进入循环; 加 --now 参数可先立即执行一轮再进入每日循环)
#
# 停止: kill <pid> (pid 记录于 logs/.daily_daemon.pid)
# 单实例: mkdir 原子锁 + PID 活性检查/陈旧锁自愈

set -u

# ---- 配置 (环境变量仅为 selftest 注入面; 生产默认保持旧行为) ----
REPO="${DAEMON_REPO:-/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork}"
PY="${DAEMON_PY:-$REPO/.venv/bin/python}"
PIPELINE="${DAEMON_PIPELINE:-scripts/run_daily_pipeline.py}"
STATUS_HISTORY="${DAEMON_STATUS_HISTORY:-logs/cron/status_history.jsonl}"
MAX_ATTEMPTS="${DAEMON_MAX_ATTEMPTS:-10}"
RETRY_INTERVAL="${DAEMON_RETRY_INTERVAL:-1800}"
TRIGGER_HH="${DAEMON_TRIGGER_HH:-18}"
TRIGGER_MM="${DAEMON_TRIGGER_MM:-1}"
RESEARCH_HH="${DAEMON_RESEARCH_HH:-18}"
RESEARCH_MM="${DAEMON_RESEARCH_MM:-30}"
NIGHT_HH="${DAEMON_NIGHT_HH:-23}"
NIGHT_MM="${DAEMON_NIGHT_MM:-5}"

cd "$REPO" || { echo "cd fail" >&2; exit 80; }

# ---- selftest 模式判定 (必须先于生产锁: selftest 绝不触碰锁/pid) ----
SELFTEST=0
case "${1:-}" in
    --selftest-once|--print-config|--selftest-next-trigger|--selftest-dispatch) SELFTEST=1 ;;
esac

# ---- 调度数学: 纯 bash (R54: 不依赖应用解释器) ----
# next_trigger_seconds <now_epoch> <hh> <mm> → 距下次触发的秒数 (>=1)
next_trigger_seconds() {
    local now="$1" hh="$2" mm="$3"
    local h m s cur tgt d
    read -r h m s <<< "$(date -r "$now" '+%H %M %S')"
    cur=$(( 10#$h * 3600 + 10#$m * 60 + 10#$s ))
    tgt=$(( 10#$hh * 3600 + 10#$mm * 60 ))
    d=$(( tgt - cur ))
    [ "$d" -le 0 ] && d=$(( d + 86400 ))
    echo "$d"
}

# ---- 解释器探活与失败记录 (R54) ----
interpreter_ok() {
    "$PY" -c "pass" >/dev/null 2>&1
}

record_failure() {  # <attempt> <rc> <daemon_error_code>
    local attempt="$1" rc="$2" code="$3"
    mkdir -p "$(dirname "$STATUS_HISTORY")" 2>/dev/null
    if ! printf '{"date":"%s","daemon_error":"%s","rc":%s,"attempt":%s}\n' \
            "$(date +%Y%m%d)" "$code" "$rc" "$attempt" >> "$STATUS_HISTORY"; then
        echo "[$(date '+%F %T')] 警告: 失败记录写盘失败 ($STATUS_HISTORY)" >&2
    fi
}

sleep_chunked() {  # 60s 粒度分片, 保证 kill 及时到达 (发现1)
    local remain="$1"
    while [ "$remain" -gt 0 ]; do
        local chunk=60
        [ "$remain" -lt 60 ] && chunk=$remain
        sleep "$chunk"
        remain=$(( remain - chunk ))
    done
}

run_once() {
    local attempt=1 rc
    while :; do
        interpreter_ok
        rc=$?
        if [ "$rc" -eq 0 ]; then
            echo "[$(date '+%F %T')] === 每日管道开始 ==="
            "$PY" "$PIPELINE"
            rc=$?
            echo "[$(date '+%F %T')] === 每日管道结束 rc=$rc ==="
            return $rc
        fi
        echo "[$(date '+%F %T')] 解释器不可用 (attempt=$attempt/$MAX_ATTEMPTS, preflight rc=$rc)"
        record_failure "$attempt" "$rc" "interpreter_unavailable"
        if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
            echo "[$(date '+%F %T')] === 每日管道放弃: 解释器持续不可用 (共 $attempt 次) ==="
            record_failure "$attempt" "$rc" "interpreter_unavailable_gave_up"
            return 97
        fi
        sleep_chunked "$RETRY_INTERVAL"
        attempt=$(( attempt + 1 ))
    done
}

run_nightly() {
    echo "[$(date '+%F %T')] === v3 夜间链开始 ==="
    bash scripts/v3_trial_nightly.sh
    local rc=$?
    echo "[$(date '+%F %T')] === v3 夜间链结束 rc=$rc ==="
    return $rc
}

run_research_refresh() {
    echo "[$(date '+%F %T')] === 研究数据刷新开始 ==="
    bash scripts/research_data_refresh.sh
    local rc=$?
    echo "[$(date '+%F %T')] === 研究数据刷新结束 rc=$rc ==="
    return $rc
}

# ---- selftest 注入面 (零锁、零 pid、零循环) ----
if [ "$SELFTEST" -eq 1 ]; then
    case "$1" in
        --print-config)
            echo "REPO=$REPO"
            echo "PY=$PY"
            echo "PIPELINE=$PIPELINE"
            echo "STATUS_HISTORY=$STATUS_HISTORY"
            echo "MAX_ATTEMPTS=$MAX_ATTEMPTS"
            echo "RETRY_INTERVAL=$RETRY_INTERVAL"
            echo "TRIGGER_HH=$TRIGGER_HH"
            echo "TRIGGER_MM=$TRIGGER_MM"
            echo "NIGHT_HH=$NIGHT_HH"
            echo "NIGHT_MM=$NIGHT_MM"
            echo "RESEARCH_HH=$RESEARCH_HH"
            echo "RESEARCH_MM=$RESEARCH_MM"
            exit 0 ;;
        --selftest-next-trigger)
            # $2=hh $3=mm $4=now_epoch (缺省 = 真实 now)
            next_trigger_seconds "${4:-$(date +%s)}" "${2:-$TRIGGER_HH}" "${3:-$TRIGGER_MM}"
            exit 0 ;;
        --selftest-dispatch)
            # $2=now_epoch: 三触发取最早, 输出 pipeline | research | nightly
            now="${2:-$(date +%s)}"
            s_pipe=$(next_trigger_seconds "$now" "$TRIGGER_HH" "$TRIGGER_MM")
            s_research=$(next_trigger_seconds "$now" "$RESEARCH_HH" "$RESEARCH_MM")
            s_night=$(next_trigger_seconds "$now" "$NIGHT_HH" "$NIGHT_MM")
            if [ "$s_pipe" -le "$s_research" ] && [ "$s_pipe" -le "$s_night" ]; then
                echo "pipeline"
            elif [ "$s_research" -le "$s_night" ]; then
                echo "research"
            else
                echo "nightly"
            fi
            exit 0 ;;
        --selftest-once)
            run_once
            exit $? ;;
    esac
fi

# ---- 单实例锁 (macOS 无 flock → mkdir 原子锁 + PID 活性检查/陈旧锁自愈) ----
LOCKDIR="logs/.daily_daemon.lock.d"
if mkdir "$LOCKDIR" 2>/dev/null; then
    echo $$ > "$LOCKDIR/pid"
else
    OLD_PID=$(cat "$LOCKDIR/pid" 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "[$(date '+%F %T')] 另一个 daemon 实例已在运行 (pid=$OLD_PID), 退出"
        exit 1
    fi
    echo "[$(date '+%F %T')] 清理陈旧锁 (pid=$OLD_PID 已死), 接管"
    rm -rf "$LOCKDIR"
    mkdir "$LOCKDIR" && echo $$ > "$LOCKDIR/pid" || { echo "锁接管失败" >&2; exit 1; }
fi
trap 'rm -rf "$LOCKDIR"' EXIT
echo $$ > logs/.daily_daemon.pid
echo "[$(date '+%F %T')] daemon 启动, pid=$$ (每天 $(printf '%02d:%02d' "$TRIGGER_HH" "$TRIGGER_MM") 触发; 停止: kill $$)"

# --now: 启动时立即执行一轮 (验证/补跑用)
if [ "${1:-}" = "--now" ]; then
    run_once
fi

# 每日顺带: 清理 90 天前的 pipeline 日志 (发现3: 无保留策略会无限累积)
find logs/cron -name 'pipeline_*.log' -mtime +90 -delete 2>/dev/null

while true; do
    # 三触发取最早 (18:01 v2 管道 / 18:30 研究数据刷新 / 23:05 v3 夜间链)
    now=$(date +%s)
    S_PIPE=$(next_trigger_seconds "$now" "$TRIGGER_HH" "$TRIGGER_MM")
    S_RESEARCH=$(next_trigger_seconds "$now" "$RESEARCH_HH" "$RESEARCH_MM")
    S_NIGHT=$(next_trigger_seconds "$now" "$NIGHT_HH" "$NIGHT_MM")
    S_MIN="$S_PIPE"; WHAT=每日管道; KIND=pipe
    if [ "$S_RESEARCH" -lt "$S_MIN" ]; then
        S_MIN="$S_RESEARCH"; WHAT=研究数据刷新; KIND=research
    fi
    if [ "$S_NIGHT" -lt "$S_MIN" ]; then
        S_MIN="$S_NIGHT"; WHAT=v3夜间链; KIND=night
    fi
    SLEEP="$S_MIN"
    # 合法性防御 (发现 B): 保留为纵深 — 非法值时空转风暴
    if ! [[ "$SLEEP" =~ ^[1-9][0-9]*$ ]] || [ "$SLEEP" -gt 90000 ]; then
        echo "[$(date '+%F %T')] SLEEP 非法 ('$SLEEP') — 等 300s 后重算 (防空转风暴)"
        sleep 300
        continue
    fi
    echo "[$(date '+%F %T')] 下次触发 ($WHAT): $(date -v+${SLEEP}S '+%F %T') (sleep ${SLEEP}s)"
    sleep_chunked "$SLEEP"
    if [ "$KIND" = pipe ]; then
        run_once
    elif [ "$KIND" = research ]; then
        run_research_refresh
    else
        run_nightly
    fi
    find logs/cron -name 'pipeline_*.log' -mtime +90 -delete 2>/dev/null
done
