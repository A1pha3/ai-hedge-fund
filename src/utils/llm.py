"""Helper functions for LLM"""

import json
import os
import re
import time

from pydantic import BaseModel

from src.graph.state import AgentState
from src.llm.models import get_model, get_model_info
from src.utils.progress import progress


DEFAULT_ZHIPU_FALLBACK_MODEL = "glm-4.7"
DEFAULT_ZHIPU_CODING_PLAN_FALLBACK_MODEL = "glm-4.7"


def _build_llm(model_name: str, model_provider: str, api_keys: dict | None, pydantic_model: type[BaseModel]):
    """Builds an LLM client and applies structured output when supported."""
    model_info = get_model_info(model_name, model_provider)
    llm = get_model(model_name, model_provider, api_keys)

    if not (model_info and not model_info.has_json_mode()):
        llm = llm.with_structured_output(
            pydantic_model,
            method="json_mode",
        )

    return llm, model_info


def _is_rate_limit_error(error: Exception) -> bool:
    """Detects provider quota/rate-limit failures that should trigger fallback."""
    message = str(error).lower()
    return any(
        marker in message
        for marker in [
            "429",
            "rate_limit",
            "rate limit",
            "too many requests",
            "usage limit exceeded",
        ]
    )


def _merge_api_keys(base_api_keys: dict | None, override_api_keys: dict | None) -> dict | None:
    """Creates a merged API key mapping for fallback providers."""
    if not base_api_keys and not override_api_keys:
        return None
    merged = dict(base_api_keys or {})
    merged.update(override_api_keys or {})
    return merged


def _build_fallback_chain(primary_provider: str, api_keys: dict | None) -> list[dict[str, object]]:
    """Builds an ordered fallback chain for quota/rate-limit failures."""
    chain: list[dict[str, object]] = []

    zhipu_code_api_key = (api_keys or {}).get("ZHIPU_CODE_API_KEY") or os.getenv("ZHIPU_CODE_API_KEY")
    zhipu_api_key = (api_keys or {}).get("ZHIPU_API_KEY") or os.getenv("ZHIPU_API_KEY")

    if str(primary_provider) == "MiniMax":
        if zhipu_code_api_key:
            chain.append(
                {
                    "model_name": os.getenv("ZHIPU_CODING_FALLBACK_MODEL", DEFAULT_ZHIPU_CODING_PLAN_FALLBACK_MODEL),
                    "model_provider": "Zhipu",
                    "api_keys": {"ZHIPU_CODE_API_KEY": zhipu_code_api_key, "ZHIPU_USE_CODING_PLAN": True},
                    "status_message": "MiniMax limited, switching to Coding Plan Zhipu:glm-4.7",
                }
            )
        if zhipu_api_key:
            chain.append(
                {
                    "model_name": os.getenv("ZHIPU_FALLBACK_MODEL", DEFAULT_ZHIPU_FALLBACK_MODEL),
                    "model_provider": "Zhipu",
                    "api_keys": {"ZHIPU_API_KEY": zhipu_api_key},
                    "status_message": "Coding Plan limited, switching to standard Zhipu:glm-4.7",
                }
            )
        return chain

    if str(primary_provider) == "Zhipu":
        current_is_coding = bool((api_keys or {}).get("ZHIPU_USE_CODING_PLAN"))
        if current_is_coding and zhipu_api_key:
            chain.append(
                {
                    "model_name": os.getenv("ZHIPU_FALLBACK_MODEL", DEFAULT_ZHIPU_FALLBACK_MODEL),
                    "model_provider": "Zhipu",
                    "api_keys": {"ZHIPU_API_KEY": zhipu_api_key},
                    "status_message": "Coding Plan limited, switching to standard Zhipu:glm-4.7",
                }
            )

    return chain


def _compute_retry_delay(attempt: int, error: Exception) -> float:
    """Returns a bounded backoff delay for transient provider failures."""
    if _is_rate_limit_error(error):
        return min(2.0 * (attempt + 1), 10.0)
    return min(1.0 * (attempt + 1), 3.0)


def call_llm(
    prompt: any,
    pydantic_model: type[BaseModel],
    agent_name: str | None = None,
    state: AgentState | None = None,
    max_retries: int = 3,
    default_factory=None,
) -> BaseModel:
    """
    Makes an LLM call with retry logic, handling both JSON supported and non-JSON supported models.

    Args:
        prompt: The prompt to send to the LLM
        pydantic_model: The Pydantic model class to structure the output
        agent_name: Optional name of the agent for progress updates and model config extraction
        state: Optional state object to extract agent-specific model configuration
        max_retries: Maximum number of retries (default: 3)
        default_factory: Optional factory function to create default response on failure

    Returns:
        An instance of the specified Pydantic model
    """

    # Extract model configuration if state is provided and agent_name is available
    if state and agent_name:
        model_name, model_provider = get_agent_model_config(state, agent_name)
    else:
        # Use system defaults when no state or agent_name is provided
        model_name = "gpt-4.1"
        model_provider = "OPENAI"

    # Extract API keys from state if available
    api_keys = None
    if state:
        request = state.get("metadata", {}).get("request")
        if request and hasattr(request, "api_keys"):
            api_keys = request.api_keys

    llm, model_info = _build_llm(model_name, model_provider, api_keys, pydantic_model)
    active_model_name = model_name
    active_model_provider = model_provider
    active_api_keys = api_keys
    fallback_chain = _build_fallback_chain(active_model_provider, api_keys)
    fallback_index = 0

    # Call the LLM with retries
    for attempt in range(max_retries):
        try:
            # Call the LLM
            result = llm.invoke(prompt)

            # For non-JSON support models, we need to extract and parse the JSON manually
            if model_info and not model_info.has_json_mode():
                parsed_result = extract_json_from_response(result.content)
                if parsed_result:
                    return pydantic_model(**parsed_result)
                else:
                    raise ValueError(f"Could not extract valid JSON from response: {result.content[:200]}...")
            else:
                return result

        except Exception as e:
            if fallback_index < len(fallback_chain) and _is_rate_limit_error(e):
                fallback_config = fallback_chain[fallback_index]
                fallback_index += 1
                active_model_name = fallback_config["model_name"]
                active_model_provider = fallback_config["model_provider"]
                active_api_keys = _merge_api_keys(api_keys, fallback_config.get("api_keys"))
                llm, model_info = _build_llm(active_model_name, active_model_provider, active_api_keys, pydantic_model)
                if agent_name:
                    progress.update_status(agent_name, None, str(fallback_config["status_message"]))
                    continue

            if agent_name:
                progress.update_status(agent_name, None, f"Error - retry {attempt + 1}/{max_retries}")

            if attempt == max_retries - 1:
                print(f"Error in LLM call after {max_retries} attempts: {e}")
                # Use default_factory if provided, otherwise create a basic default
                if default_factory:
                    return default_factory()
                return create_default_response(pydantic_model)

            time.sleep(_compute_retry_delay(attempt, e))

    # This should never be reached due to the retry logic above
    return create_default_response(pydantic_model)


def create_default_response(model_class: type[BaseModel]) -> BaseModel:
    """Creates a safe default response based on the model's fields."""
    default_values = {}
    for field_name, field in model_class.model_fields.items():
        if field.annotation is str:
            default_values[field_name] = "Error in analysis, using default"
        elif field.annotation is float:
            default_values[field_name] = 0.0
        elif field.annotation is int:
            default_values[field_name] = 0
        elif hasattr(field.annotation, "__origin__") and field.annotation.__origin__ is dict:
            default_values[field_name] = {}
        else:
            # For other types (like Literal), try to use the first allowed value
            if hasattr(field.annotation, "__args__"):
                default_values[field_name] = field.annotation.__args__[0]
            else:
                default_values[field_name] = None

    return model_class(**default_values)


def _strip_reasoning_blocks(content: str) -> str:
    """Removes model reasoning wrappers before JSON extraction."""
    patterns = [
        r"<think\b[^>]*>.*?</think>",
        r"<thinking\b[^>]*>.*?</thinking>",
    ]

    cleaned = content
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _extract_balanced_json_candidates(content: str) -> list[str]:
    """Finds balanced JSON object candidates while ignoring braces inside strings."""
    candidates: list[str] = []
    brace_count = 0
    start_idx = -1
    in_string = False
    escape_next = False

    for index, char in enumerate(content):
        if in_string:
            if escape_next:
                escape_next = False
                continue
            if char == "\\":
                escape_next = True
                continue
            if char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue

        if char == "{":
            if brace_count == 0:
                start_idx = index
            brace_count += 1
            continue

        if char == "}" and brace_count > 0:
            brace_count -= 1
            if brace_count == 0 and start_idx != -1:
                candidates.append(content[start_idx : index + 1])
                start_idx = -1

    return candidates


def extract_json_from_response(content: str) -> dict | None:
    """Extracts JSON from markdown-formatted response, handling various response formats."""
    try:
        if not content:
            return None

        # Remove model reasoning wrappers before attempting to parse JSON.
        content = _strip_reasoning_blocks(content)
        content = content.strip()

        # Try direct JSON first after cleaning.
        if content.startswith("{") or content.startswith("["):
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass

        # Try to find JSON in markdown code block with 'json' marker
        json_start = content.find("```json")
        if json_start != -1:
            json_text = content[json_start + 7 :]  # Skip past ```json
            json_end = json_text.find("```")
            if json_end != -1:
                json_text = json_text[:json_end].strip()
                return json.loads(json_text)

        # Try to find JSON in markdown code block without 'json' marker
        json_start = content.find("```")
        if json_start != -1:
            json_text = content[json_start + 3 :]  # Skip past ```
            json_end = json_text.find("```")
            if json_end != -1:
                json_text = json_text[:json_end].strip()
                if json_text.startswith("{") or json_text.startswith("["):
                    return json.loads(json_text)

        # Try to find raw JSON object with balanced braces.
        for json_str in _extract_balanced_json_candidates(content):
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                continue

    except Exception as e:
        print(f"Error extracting JSON from response: {e}")
        if content:
            print(f"Content preview: {content[:500]}...")
    return None


def get_agent_model_config(state, agent_name):
    """
    Get model configuration for a specific agent from the state.
    Falls back to global model configuration if agent-specific config is not available.
    Always returns valid model_name and model_provider values.
    """
    request = state.get("metadata", {}).get("request")

    if request and hasattr(request, "get_agent_model_config"):
        # Get agent-specific model configuration
        model_name, model_provider = request.get_agent_model_config(agent_name)
        # Ensure we have valid values
        if model_name and model_provider:
            return model_name, model_provider.value if hasattr(model_provider, "value") else str(model_provider)

    # Fall back to global configuration (system defaults)
    model_name = state.get("metadata", {}).get("model_name") or "gpt-4.1"
    model_provider = state.get("metadata", {}).get("model_provider") or "OPENAI"

    # Convert enum to string if necessary
    if hasattr(model_provider, "value"):
        model_provider = model_provider.value

    return model_name, model_provider
