#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKILL_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
SKILL_NAME=$(basename -- "$SKILL_DIR")
TARGET_ROOT=${COPILOT_SKILLS_DIR:-"$HOME/.copilot/skills"}
TARGET_PATH="$TARGET_ROOT/$SKILL_NAME"
FORCE=0

usage() {
  cat <<EOF
Usage: $(basename "$0") [--force] [--target-root PATH]

Create a symbolic link from this repository skill to the Copilot global skills directory.

Options:
  --force              Replace an existing file or directory at the target path.
  --target-root PATH   Override the target skills root. Default: $HOME/.copilot/skills
  -h, --help           Show this help message.

The command that will be executed is equivalent to:
  ln -s "$SKILL_DIR" "$TARGET_PATH"
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --force)
      FORCE=1
      shift
      ;;
    --target-root)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --target-root" >&2
        exit 1
      fi
      TARGET_ROOT=$2
      TARGET_PATH="$TARGET_ROOT/$SKILL_NAME"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

mkdir -p "$TARGET_ROOT"

if [ -L "$TARGET_PATH" ]; then
  CURRENT_TARGET=$(readlink "$TARGET_PATH" || true)
  if [ "$CURRENT_TARGET" = "$SKILL_DIR" ]; then
    echo "Symlink already exists: $TARGET_PATH -> $CURRENT_TARGET"
    exit 0
  fi
  if [ "$FORCE" -ne 1 ]; then
    echo "A different symlink already exists at $TARGET_PATH -> $CURRENT_TARGET" >&2
    echo "Re-run with --force to replace it." >&2
    exit 1
  fi
  rm -f "$TARGET_PATH"
elif [ -e "$TARGET_PATH" ]; then
  if [ "$FORCE" -ne 1 ]; then
    echo "A file or directory already exists at $TARGET_PATH" >&2
    echo "Re-run with --force to replace it." >&2
    exit 1
  fi
  rm -rf "$TARGET_PATH"
fi

ln -s "$SKILL_DIR" "$TARGET_PATH"
echo "Created symlink: $TARGET_PATH -> $SKILL_DIR"