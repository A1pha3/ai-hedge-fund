from src.agents.prompt_rules import with_fact_grounding_rules


def test_with_fact_grounding_rules_appends_no_fabrication_contract():
    prompt = with_fact_grounding_rules("You are an analyst.")

    assert prompt.startswith("You are an analyst.")
    assert "CRITICAL RULES (STRICTLY ENFORCED):" in prompt
    assert "NEVER invent, estimate, interpolate, or make up any numbers or metrics" in prompt
    assert "data not available" in prompt
