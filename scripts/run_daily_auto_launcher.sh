#!/bin/bash
# scripts/run_daily_auto_launcher.sh
# BOOT-VOLUME LAUNCHER for the daily auto_screening job (NS-5).
#
# ROOT CAUSE (2026-06-30, isolated by controlled launchd probes):
#   macOS launchd's GUI daemon is sandboxed and CANNOT open files on the external
#   /Volumes noowners APFS volume:
#     - plist path key on /Volumes       -> EX_CONFIG (78), silent stall
#     - execve a /Volumes script         -> rc 126, Operation not permitted
#     - bash `source .env` / `< file`    -> Operation not permitted
#   But launchd CAN spawn /bin/bash, and a RUNNING python process (.venv python
#   is a symlink to ~/.local/share/uv on the BOOT volume) reads /Volumes files
#   normally. So the launcher inlines a tiny python prelude that loads .env via
#   python-dotenv (permitted) then os.execvp's into src/main.py, inheriting env.
#
# This launcher lives on the BOOT volume (install: cp scripts/run_daily_auto_launcher.sh
# ~/.local/bin/). The launchd plist invokes it with NO WorkingDirectory and NO
# /Volumes StandardOutPath. run_daily_auto.sh stays in-repo for interactive use.
set -euo pipefail

REPO="/Volumes/mini_matrix/github/a1pha3/quant/ai-hedge-fund-fork"
PYTHON="$REPO/.venv/bin/python"

[[ -d "$REPO" ]] || { echo "[daily_auto_launcher] FATAL: $REPO missing — volume unmounted?" >&2; exit 2; }
[[ -f "$REPO/.env" ]] || { echo "[daily_auto_launcher] FATAL: .env missing — need TUSHARE_TOKEN" >&2; exit 2; }
[[ -x "$PYTHON" ]] || { echo "[daily_auto_launcher] FATAL: $PYTHON missing — run 'uv sync'" >&2; exit 3; }

cd "$REPO"

# Arg parsing (mirror run_daily_auto.sh).
TOP_N="10"; TRADE_DATE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --top-n) TOP_N="$2"; shift 2 ;;
    --trade-date)
      [[ "$2" =~ ^[0-9]{8}$ ]] || { echo "[daily_auto_launcher] --trade-date must be YYYYMMDD" >&2; exit 5; }
      TRADE_DATE="${2:0:4}-${2:4:2}-${2:6:2}"; shift 2 ;;
    *) echo "[daily_auto_launcher] unknown arg: $1" >&2; exit 4 ;;
  esac
done

# NOTE: under launchd we do NOT redirect to a /Volumes log file (bash redirects are
# sandbox-blocked -> Operation not permitted). Output flows to the plist's
# StandardOutPath (boot volume ~/Library/Logs/ai-hedge-fund/daily_auto.out.log).
# For interactive runs the shell has no such sandbox, so mirror to the repo log then.
LOG_DIR="$REPO/logs"; mkdir -p "$LOG_DIR" 2>/dev/null || true
LOG_FILE="$LOG_DIR/auto_cron_$(date +%Y%m%d).log"

echo "[$(date -Iseconds)] [daily_auto] start (top_n=$TOP_N trade_date=${TRADE_DATE:-today})"

# .env loader prelude (python reads /Volumes fine; bash cannot under launchd).
# Sets env then os.execvp replaces this process with src/main.py --auto.
DATE_ARG=""; [[ -n "$TRADE_DATE" ]] && DATE_ARG="--end-date=$TRADE_DATE"

"$PYTHON" -E -c "
import os, sys
from dotenv import load_dotenv
load_dotenv('$REPO/.env')
# load_dotenv does not overwrite existing env; export loaded vars explicitly.
from dotenv import dotenv_values
for k, v in dotenv_values('$REPO/.env').items():
    if v is not None:
        os.environ.setdefault(k, v)
argv = [sys.executable, 'src/main.py', '--auto', '--top-n', '$TOP_N']
date_arg = '$DATE_ARG'
if date_arg:
    argv += ['--end-date', date_arg]
os.execvp(sys.executable, argv)
" ; AUTO_RC=$?
if [[ $AUTO_RC -ne 0 ]]; then
  echo "[$(date -Iseconds)] [daily_auto] --auto FAILED (rc=$AUTO_RC)" >&2
  exit 11
fi
echo "[$(date -Iseconds)] [daily_auto] --auto OK"

# Step 2: backfill pass + Step 3: flywheel health (each loads .env inside python).
"$PYTHON" - <<PYEOF || true
from dotenv import dotenv_values; import os
for k,v in dotenv_values('$REPO/.env').items():
    v is not None and os.environ.setdefault(k,v)
from datetime import datetime
from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.recommendation_tracker import update_tracking_history
n = update_tracking_history(reports_dir=resolve_report_dir(), trade_date=datetime.now().strftime('%Y%m%d'))
print(f'[daily_auto] backfill pass updated {n} records')
PYEOF

"$PYTHON" - <<PYEOF || true
from dotenv import dotenv_values; import os, json
for k,v in dotenv_values('$REPO/.env').items():
    v is not None and os.environ.setdefault(k,v)
from src.screening.flywheel_health import assess_tracking_history
print('[daily_auto] flywheel:', json.dumps(assess_tracking_history(), ensure_ascii=False))
PYEOF

echo "[$(date -Iseconds)] [daily_auto] done"
