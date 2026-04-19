from __future__ import annotations

from src.utils.numeric import clamp_unit_interval  # noqa: F401 — re-exported for backward compatibility


def derive_confidence(*components: float) -> float:
    if not components:
        return 0.0
    return clamp_unit_interval(max(float(component or 0.0) for component in components))


def trim_reasons(reasons: list[str], limit: int = 3) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        normalized_reason = str(reason or "").strip()
        if not normalized_reason or normalized_reason in seen:
            continue
        normalized.append(normalized_reason)
        seen.add(normalized_reason)
    return normalized[:limit]