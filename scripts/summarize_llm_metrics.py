from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _bucket() -> dict[str, float | int]:
    return {
        "attempts": 0,
        "successes": 0,
        "errors": 0,
        "rate_limit_errors": 0,
        "total_duration_ms": 0.0,
        "avg_duration_ms": 0.0,
    }


def _update(bucket: dict[str, float | int], entry: dict) -> None:
    bucket["attempts"] += 1
    bucket["successes"] += 1 if entry.get("success") else 0
    bucket["errors"] += 0 if entry.get("success") else 1
    bucket["rate_limit_errors"] += 1 if entry.get("is_rate_limit") else 0
    bucket["total_duration_ms"] += float(entry.get("duration_ms") or 0.0)
    if bucket["attempts"]:
        bucket["avg_duration_ms"] = round(float(bucket["total_duration_ms"]) / int(bucket["attempts"]), 3)


def summarize(jsonl_path: Path) -> dict:
    summary = {
        "file": str(jsonl_path),
        "totals": _bucket(),
        "providers": {},
        "routes": {},
        "transport_families": {},
        "models": {},
        "agents": {},
    }

    providers: dict[str, dict] = defaultdict(_bucket)
    routes: dict[str, dict] = defaultdict(_bucket)
    transport_families: dict[str, dict] = defaultdict(_bucket)
    models: dict[str, dict] = defaultdict(_bucket)
    agents: dict[str, dict] = defaultdict(_bucket)

    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            entry = json.loads(line)
            _update(summary["totals"], entry)
            _update(providers[str(entry.get("model_provider") or "unknown")], entry)
            _update(routes[str(entry.get("route_id") or "unknown")], entry)
            _update(transport_families[str(entry.get("transport_family") or "unknown")], entry)
            model_key = f"{entry.get('model_provider') or 'unknown'}:{entry.get('model_name') or 'unknown'}"
            _update(models[model_key], entry)
            _update(agents[str(entry.get("agent_name") or "unknown")], entry)

    summary["providers"] = dict(sorted(providers.items()))
    summary["routes"] = dict(sorted(routes.items()))
    summary["transport_families"] = dict(sorted(transport_families.items()))
    summary["models"] = dict(sorted(models.items()))
    summary["agents"] = dict(sorted(agents.items()))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize structured LLM metrics JSONL output.")
    parser.add_argument("jsonl_path", type=Path, help="Path to an llm_metrics_*.jsonl file")
    parser.add_argument("--output", type=Path, help="Optional path to save the aggregated summary JSON")
    args = parser.parse_args()

    summary = summarize(args.jsonl_path)
    if args.output:
        args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
