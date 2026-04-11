import asyncio
import json
import os
import re

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from app.backend.services.agent_service import create_agent_function
from src.agents.portfolio_manager import portfolio_management_agent
from src.agents.risk_manager import risk_management_agent
from src.graph.state import AgentState
from src.main import start
from src.utils.analysts import ANALYST_CONFIG
from src.utils.llm import build_parallel_provider_execution_plan


def extract_base_agent_key(unique_id: str) -> str:
    """
    Extract the base agent key from a unique node ID.

    Args:
        unique_id: The unique node ID with suffix (e.g., "warren_buffett_abc123")

    Returns:
        The base agent key (e.g., "warren_buffett")
    """
    # For agent nodes, remove the last underscore and 6-character suffix
    parts = unique_id.split("_")
    if len(parts) >= 2:
        last_part = parts[-1]
        # If the last part is a 6-character alphanumeric string, it's likely our suffix
        if len(last_part) == 6 and re.match(r"^[a-z0-9]+$", last_part):
            return "_".join(parts[:-1])
    return unique_id  # Return original if no suffix pattern found


def _build_analyst_nodes() -> dict[str, tuple[str, callable]]:
    return {key: (f"{key}_agent", config["agent_func"]) for key, config in ANALYST_CONFIG.items()}


def _register_agent_nodes(graph: StateGraph, agent_ids: list[str], analyst_nodes: dict[str, tuple[str, callable]]) -> set[str]:
    portfolio_manager_nodes: set[str] = set()
    for unique_agent_id in agent_ids:
        base_agent_key = extract_base_agent_key(unique_agent_id)
        if base_agent_key == "portfolio_manager":
            portfolio_manager_nodes.add(unique_agent_id)
            continue
        if base_agent_key not in ANALYST_CONFIG:
            continue

        _node_name, node_func = analyst_nodes[base_agent_key]
        agent_function = create_agent_function(node_func, unique_agent_id)
        graph.add_node(unique_agent_id, agent_function)
    return portfolio_manager_nodes


def _register_manager_nodes(graph: StateGraph, portfolio_manager_nodes: set[str]) -> dict[str, str]:
    risk_manager_nodes: dict[str, str] = {}
    for portfolio_manager_id in portfolio_manager_nodes:
        portfolio_manager_function = create_agent_function(portfolio_management_agent, portfolio_manager_id)
        graph.add_node(portfolio_manager_id, portfolio_manager_function)

        suffix = portfolio_manager_id.split("_")[-1]
        risk_manager_id = f"risk_management_agent_{suffix}"
        risk_manager_nodes[portfolio_manager_id] = risk_manager_id

        risk_manager_function = create_agent_function(risk_management_agent, risk_manager_id)
        graph.add_node(risk_manager_id, risk_manager_function)
    return risk_manager_nodes


def _build_graph_connections(graph_edges: list, agent_ids_set: set[str]) -> tuple[set[str], dict[str, str], list[tuple[str, str]]]:
    nodes_with_incoming_edges: set[str] = set()
    direct_to_portfolio_managers: dict[str, str] = {}
    regular_edges: list[tuple[str, str]] = []

    for edge in graph_edges:
        if edge.source not in agent_ids_set or edge.target not in agent_ids_set:
            continue

        source_base_key = extract_base_agent_key(edge.source)
        target_base_key = extract_base_agent_key(edge.target)
        nodes_with_incoming_edges.add(edge.target)

        if source_base_key in ANALYST_CONFIG and source_base_key != "portfolio_manager" and target_base_key == "portfolio_manager":
            direct_to_portfolio_managers[edge.source] = edge.target
            continue

        regular_edges.append((edge.source, edge.target))

    return nodes_with_incoming_edges, direct_to_portfolio_managers, regular_edges


def _connect_graph(
    graph: StateGraph,
    agent_ids: list[str],
    nodes_with_incoming_edges: set[str],
    regular_edges: list[tuple[str, str]],
    direct_to_portfolio_managers: dict[str, str],
    risk_manager_nodes: dict[str, str],
    portfolio_manager_nodes: set[str],
) -> None:
    for source, target in regular_edges:
        graph.add_edge(source, target)

    for agent_id in agent_ids:
        if agent_id not in nodes_with_incoming_edges:
            base_agent_key = extract_base_agent_key(agent_id)
            if base_agent_key in ANALYST_CONFIG and base_agent_key != "portfolio_manager":
                graph.add_edge("start_node", agent_id)

    for analyst_id, portfolio_manager_id in direct_to_portfolio_managers.items():
        risk_manager_id = risk_manager_nodes[portfolio_manager_id]
        graph.add_edge(analyst_id, risk_manager_id)

    for portfolio_manager_id, risk_manager_id in risk_manager_nodes.items():
        graph.add_edge(risk_manager_id, portfolio_manager_id)

    for portfolio_manager_id in portfolio_manager_nodes:
        graph.add_edge(portfolio_manager_id, END)


# Helper function to create the agent graph
def create_graph(graph_nodes: list, graph_edges: list) -> StateGraph:
    """Create the workflow based on the React Flow graph structure."""
    graph = StateGraph(AgentState)
    graph.add_node("start_node", start)

    analyst_nodes = _build_analyst_nodes()
    agent_ids = [node.id for node in graph_nodes]
    agent_ids_set = set(agent_ids)
    portfolio_manager_nodes = _register_agent_nodes(graph, agent_ids, analyst_nodes)
    risk_manager_nodes = _register_manager_nodes(graph, portfolio_manager_nodes)
    nodes_with_incoming_edges, direct_to_portfolio_managers, regular_edges = _build_graph_connections(graph_edges, agent_ids_set)
    _connect_graph(
        graph=graph,
        agent_ids=agent_ids,
        nodes_with_incoming_edges=nodes_with_incoming_edges,
        regular_edges=regular_edges,
        direct_to_portfolio_managers=direct_to_portfolio_managers,
        risk_manager_nodes=risk_manager_nodes,
        portfolio_manager_nodes=portfolio_manager_nodes,
    )

    graph.set_entry_point("start_node")
    return graph


async def run_graph_async(graph, portfolio, tickers, start_date, end_date, model_name, model_provider, request=None):
    """Async wrapper for run_graph to work with asyncio."""
    # Use run_in_executor to run the synchronous function in a separate thread
    # so it doesn't block the event loop
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: run_graph(graph, portfolio, tickers, start_date, end_date, model_name, model_provider, request))  # Use default executor
    return result


def run_graph(
    graph: StateGraph,
    portfolio: dict,
    tickers: list[str],
    start_date: str,
    end_date: str,
    model_name: str,
    model_provider: str,
    request=None,
) -> dict:
    """
    Run the graph with the given portfolio, tickers,
    start date, end date, show reasoning, model name,
    and model provider.
    """
    per_provider_limit_raw = os.getenv("ANALYST_CONCURRENCY_LIMIT", "2")
    try:
        per_provider_limit = max(1, int(per_provider_limit_raw))
    except ValueError:
        per_provider_limit = 2

    request_api_keys = request.api_keys if request and hasattr(request, "api_keys") else None
    agent_names = request.get_agent_ids() if request and hasattr(request, "get_agent_ids") else []
    execution_plan = build_parallel_provider_execution_plan(
        agent_names=agent_names,
        base_model_name=model_name,
        base_model_provider=model_provider,
        api_keys=request_api_keys,
        per_provider_limit=per_provider_limit,
    )

    return graph.invoke(
        {
            "messages": [
                HumanMessage(
                    content="Make trading decisions based on the provided data.",
                )
            ],
            "data": {
                "tickers": tickers,
                "portfolio": portfolio,
                "start_date": start_date,
                "end_date": end_date,
                "analyst_signals": {},
            },
            "metadata": {
                "show_reasoning": False,
                "model_name": model_name,
                "model_provider": model_provider,
                "agent_llm_overrides": execution_plan["agent_llm_overrides"],
                "request": request,  # Pass the request for agent-specific model access
            },
        },
    )


def parse_hedge_fund_response(response):
    """Parses a JSON string and returns a dictionary."""
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        print(f"JSON decoding error: {e}\nResponse: {repr(response)}")
        return None
    except TypeError as e:
        print(f"Invalid response type (expected string, got {type(response).__name__}): {e}")
        return None
    except Exception as e:
        print(f"Unexpected error while parsing response: {e}\nResponse: {repr(response)}")
        return None
