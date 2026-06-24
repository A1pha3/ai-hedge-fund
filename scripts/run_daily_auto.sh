#!/usr/bin/env bash
# scripts/run_daily_auto.sh — nightly auto_screening + realized-returns backfill.
#
# Solves system problem #2 (no daily scheduling): without a daily cron, the
# pipeline doesn't accumulate tracking_history, so records never reach the
# 6-day threshold where update_tracking_history Phase 2 backfills realized
# T+1/T+5/.../T+30 returns → calibration/reconcile starve (the gap that R162/
# R163/R164 fixed the data path for, but accumulation requires daily runs).
#
# Install (choose one):
#   crontab -e  →  30 21 * * 1-5  /path/to/ai-hedge-fund-fork/scripts/run_daily_auto.sh
#   launchd     →  wrap in a .plist with StartCalendarInterval { Hour=21, Minute=30, Weekday=1-5 }
#
# Usage:
#   scripts/run_daily_auto.sh [--top-n N] [--trade-date YYYYMMDD]
#   (default: --top-n 10, trade-date = today)

set -euo pipefail

# Resolve repo root (this script lives in scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Load .env (TUSHARE_TOKEN etc.) — fail loud if missing, don't silently use no-token
if [[ ! -f .env ]]; then
  echo "[daily_auto] FATAL: .env not found at $REPO_ROOT/.env — data providers need TUSHARE_TOKEN" >&2
  exit 2
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

# Pick venv (uv-managed .venv per CLAUDE.md)
PYTHON="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  echo "[daily_auto] FATAL: .venv/bin/python not found — run 'uv sync' first" >&2
  exit 3
fi

# Args
TOP_N="10"
TRADE_DATE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --top-n) TOP_N="$2"; shift 2 ;;
    --trade-date) TRADE_DATE="$2"; shift 2 ;;
    *) echo "[daily_auto] unknown arg: $1" >&2; exit 4 ;;
  esac
done

# Log dir + rotation (keep last 14 days)
LOG_DIR="${REPO_ROOT}/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/auto_cron_$(date +%Y%m%d).log"
find "$LOG_DIR" -name "auto_cron_*.log" -mtime +14 -delete 2>/dev/null || true

echo "[$(date -Iseconds)] [daily_auto] start (top_n=$TOP_N trade_date=${TRADE_DATE:-today})" | tee -a "$LOG_FILE"

# Step 1: --auto (generates report + appends tracking_history for the date).
#   Also triggers Phase 2 backfill for any records now ≥6 days old.
#   NOTE: --auto 内部从 inputs.end_date 解析交易日期 (src/main.py:2989
#   `trade_date = inputs.end_date.replace("-","")`), CLI 层暴露的是 --end-date
#   (格式 YYYY-MM-DD), 不是 --trade-date. 早期版本误用 --trade-date=YYYYMMDD
#   会被 argparse 拒绝 (rc=2) → --auto 静默不跑. 这里把 --trade-date YYYYMMDD
#   转成 --end-date YYYY-MM-DD.
DATE_ARG=""
if [[ -n "$TRADE_DATE" ]]; then
  if [[ ! "$TRADE_DATE" =~ ^[0-9]{8}$ ]]; then
    echo "[daily_auto] FATAL: --trade-date must be YYYYMMDD, got '$TRADE_DATE'" >&2
    exit 5
  fi
  END_DATE="${TRADE_DATE:0:4}-${TRADE_DATE:4:2}-${TRADE_DATE:6:2}"
  DATE_ARG="--end-date=$END_DATE"
fi

if ! "$PYTHON" src/main.py --auto --top-n="$TOP_N" $DATE_ARG >>"$LOG_FILE" 2>&1; then
  echo "[$(date -Iseconds)] [daily_auto] --auto FAILED (rc=$?) — see $LOG_FILE" | tee -a "$LOG_FILE" >&2
  exit 11
fi
echo "[$(date -Iseconds)] [daily_auto] --auto OK" | tee -a "$LOG_FILE"

# Step 2: explicit backfill pass (re-runs update_tracking_history for today,
#   catching any records that crossed the 6-day threshold since --auto's own
#   Phase 2). Belt-and-suspenders: the realized path (R162/R163/R164) is the
#   whole point of daily runs.
if ! "$PYTHON" -c "
import sys
from pathlib import Path
from datetime import datetime
from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.recommendation_tracker import update_tracking_history
today = datetime.now().strftime('%Y%m%d')
n = update_tracking_history(reports_dir=resolve_report_dir(), trade_date=today)
print(f'[daily_auto] backfill pass updated {n} records')
" >>"$LOG_FILE" 2>&1; then
  echo "[$(date -Iseconds)] [daily_auto] backfill pass FAILED (non-fatal — --auto already ran its own Phase 2)" | tee -a "$LOG_FILE" >&2
fi

echo "[$(date -Iseconds)] [daily_auto] done" | tee -a "$LOG_FILE"
