from __future__ import annotations


def clamp_unit_interval(value: float) -> float:
    return max(0.0, min(1.0, float(value or 0.0)))


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