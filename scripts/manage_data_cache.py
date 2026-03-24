from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.enhanced_cache import clear_cache, get_cache_runtime_info


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and manage the local multi-layer data cache.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    stats_parser = subparsers.add_parser("stats", help="Print cache runtime info and counters")
    stats_parser.add_argument("--output", default=None, help="Optional path to write the JSON payload")

    clear_parser = subparsers.add_parser("clear", help="Clear all cache layers for the current environment")
    clear_parser.add_argument("--yes", action="store_true", help="Required safety flag for destructive clear")
    return parser


def _stats_command(output: str | None) -> dict:
    payload = get_cache_runtime_info()
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _clear_command(confirm: bool) -> dict:
    if not confirm:
        raise SystemExit("Refusing to clear cache without --yes")
    before = get_cache_runtime_info()
    clear_cache()
    after = get_cache_runtime_info()
    return {
        "status": "cleared",
        "before": before,
        "after": after,
    }


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "stats":
        payload = _stats_command(args.output)
    else:
        payload = _clear_command(args.yes)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()