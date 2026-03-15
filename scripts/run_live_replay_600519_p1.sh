#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
REPLAY_SCRIPT="$ROOT_DIR/scripts/replay_layer_c_agent_contributors.py"
BASELINE_PATH="$ROOT_DIR/data/reports/rule_variant_backtests/baseline.timings.jsonl"
VARIANT_PATH="$ROOT_DIR/data/reports/rule_variant_backtests/neutral_mean_reversion_guarded_033_no_hard_cliff.timings.jsonl"
OUTPUT_DIR="$ROOT_DIR/data/reports"

show_usage() {
  cat <<'EOF'
Usage:
  scripts/run_live_replay_600519_p1.sh [20260224|20260226|all] [--resume] [--model-provider PROVIDER] [--model-name MODEL] [--output-dir DIR]

Examples:
  scripts/run_live_replay_600519_p1.sh 20260224
  scripts/run_live_replay_600519_p1.sh 20260224 --resume
  scripts/run_live_replay_600519_p1.sh all --resume
EOF
}

if [[ $# -eq 0 ]]; then
  TARGET_MODE="all"
else
  TARGET_MODE="$1"
  shift
fi

case "$TARGET_MODE" in
  20260224)
    TARGET_DATES=("20260224")
    ;;
  20260226)
    TARGET_DATES=("20260226")
    ;;
  all)
    TARGET_DATES=("20260224" "20260226")
    ;;
  -h|--help)
    show_usage
    exit 0
    ;;
  *)
    echo "Unsupported target: $TARGET_MODE" >&2
    show_usage >&2
    exit 1
    ;;
esac

RESUME_FLAG=()
MODEL_PROVIDER=""
MODEL_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resume)
      RESUME_FLAG=("--resume")
      shift
      ;;
    --model-provider)
      MODEL_PROVIDER="$2"
      shift 2
      ;;
    --model-name)
      MODEL_NAME="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      show_usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      show_usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python interpreter not found: $PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -f "$REPLAY_SCRIPT" ]]; then
  echo "Replay script not found: $REPLAY_SCRIPT" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

for trade_date in "${TARGET_DATES[@]}"; do
  output_path="$OUTPUT_DIR/live_replay_600519_${trade_date}_p1.json"
  cmd=(
    "$PYTHON_BIN"
    "$REPLAY_SCRIPT"
    --baseline "$BASELINE_PATH"
    --variant "$VARIANT_PATH"
    --dates "$trade_date"
    --ticker 600519
    --ticker-batch-size 1
    --output "$output_path"
  )

  if [[ -n "$MODEL_PROVIDER" ]]; then
    cmd+=(--model-provider "$MODEL_PROVIDER")
  fi

  if [[ -n "$MODEL_NAME" ]]; then
    cmd+=(--model-name "$MODEL_NAME")
  fi

  if [[ ${#RESUME_FLAG[@]} -gt 0 ]]; then
    cmd+=("${RESUME_FLAG[@]}")
  fi

  echo "Running replay for $trade_date -> $output_path"
  "${cmd[@]}"
done
