from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from src.llm.defaults import get_default_model_config
from src.llm.models import get_provider_routes
from src.utils.analysts import ANALYST_ORDER, get_analyst_nodes
from src.utils.llm import build_parallel_provider_execution_plan


load_dotenv(override=True)


def _ordered_agent_names(limit: int | None = None) -> list[str]:
    analyst_nodes = get_analyst_nodes()
    ordered_agent_names = [node_name for _, analyst_key in ANALYST_ORDER if analyst_key in analyst_nodes for node_name in [analyst_nodes[analyst_key][0]]]
    if limit is not None:
        return ordered_agent_names[:limit]
    return ordered_agent_names


def _serialize_routes(enabled_only_for: str | None) -> list[dict[str, str]]:
    routes = get_provider_routes(None, enabled_only_for=enabled_only_for)
    return [
        {
            "provider_name": route.provider_name,
            "display_name": route.display_name,
            "route_id": route.route_id,
            "model_name": route.model_name,
            "transport_family": route.transport_family,
        }
        for route in routes
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect active LLM routing and provider concurrency plan from the current environment.")
    parser.add_argument("--model-name", default=None, help="Optional model name override; omitted means current default model")
    parser.add_argument("--model-provider", default=None, help="Optional model provider override; omitted means current default provider")
    parser.add_argument("--per-provider-limit", type=int, default=2, help="Base per-provider concurrency input used by the planner")
    parser.add_argument("--agent-count", type=int, default=8, help="Number of analyst agents to simulate in the execution plan preview")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    default_model_name, default_model_provider = get_default_model_config()
    model_name = args.model_name or default_model_name
    model_provider = args.model_provider or default_model_provider
    agent_names = _ordered_agent_names(args.agent_count)

    execution_plan = build_parallel_provider_execution_plan(
        agent_names=agent_names,
        base_model_name=model_name,
        base_model_provider=model_provider,
        api_keys=None,
        per_provider_limit=args.per_provider_limit,
    )

    payload = {
        "default_model": {
            "model_name": default_model_name,
            "model_provider": default_model_provider,
        },
        "requested_model": {
            "model_name": model_name,
            "model_provider": model_provider,
        },
        "inspected_agent_names": agent_names,
        "available_parallel_routes": _serialize_routes("parallel"),
        "available_priority_routes": _serialize_routes("priority"),
        "execution_plan_provenance": execution_plan["execution_provenance"],
        "sample_agent_assignments": {
            agent_name: execution_plan["agent_llm_overrides"].get(agent_name, {"model_provider": model_provider, "model_name": model_name})
            for agent_name in agent_names
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()