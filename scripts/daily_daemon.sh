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
# 用法 (在项目目录):
#   nohup bash scripts/daily_daemon.sh >> logs/cron/daemon.log 2>&1 &
#   (启动后即进入循环; 加 --now 参数可先立即执行一轮再进入每日循环)
#
# 停止: kill <pid> (pid 记录于 logs/.daily_daemon.pid)
# 单实例: flock 锁, 重复启动会被拒绝

set -u
REPO="/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork"
TRIGGER_HH=18
TRIGGER_MM=1
PY="$REPO/.venv/bin/python"
cd "$REPO" || { echo "cd fail" >&2; exit 80; }
mkdir -p logs/cron

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

run_once() {
    echo "[$(date '+%F %T')] === 每日管道开始 ==="
    "$PY" scripts/run_daily_pipeline.py
    local rc=$?
    echo "[$(date '+%F %T')] === 每日管道结束 rc=$rc ==="
    return $rc
}

# --now: 启动时立即执行一轮 (验证/补跑用)

if [ "${1:-}" = "--now" ]; then
    run_once
fi

# 每日顺带: 清理 90 天前的 pipeline 日志 (发现3: 无保留策略会无限累积)
find logs/cron -name 'pipeline_*.log' -mtime +90 -delete 2>/dev/null

while true; do
    # 距下一个触发点的秒数
    SLEEP=$("$PY" -c "
import datetime as dt
now = dt.datetime.now()
t = now.replace(hour=$TRIGGER_HH, minute=$TRIGGER_MM, second=0, microsecond=0)
if now >= t:
    t += dt.timedelta(days=1)
print(int((t - now).total_seconds()))")
    echo "[$(date '+%F %T')] 下次触发: $(date -v+${SLEEP}S '+%F %T') (sleep ${SLEEP}s)"
    # 分片 sleep (60s 粒度): bash 的 SIGTERM 要等当前前台命令结束才处理,
    # 整段 sleep 会导致 kill 等待最长 24h — 分片后每 60s 是一个停止检查点 (发现1)
    REMAIN=$SLEEP
    while [ "$REMAIN" -gt 0 ]; do
        CHUNK=60
        [ "$REMAIN" -lt 60 ] && CHUNK=$REMAIN
        sleep "$CHUNK"
        REMAIN=$((REMAIN - CHUNK))
    done
    run_once
    find logs/cron -name 'pipeline_*.log' -mtime +90 -delete 2>/dev/null
done
