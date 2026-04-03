"""Shared prompt guardrails for LLM-based analyst agents."""


def with_fact_grounding_rules(system_prompt: str) -> str:
    """Append strict fact-grounding rules to an agent system prompt."""
    return (
        f"{system_prompt.rstrip()}\n\n"
        "CRITICAL RULES (STRICTLY ENFORCED):\n"
        "1. ONLY use data explicitly provided in the analysis or facts sections\n"
        "2. NEVER invent, estimate, interpolate, or make up any numbers or metrics\n"
        "3. If a data point is missing, null, or unavailable, state 'data not available'\n"
        "4. Do NOT cite facts, comparisons, or narratives that are not explicitly provided\n"
        "5. If the evidence is mixed or incomplete, lower confidence and explain the uncertainty\n"
    )
