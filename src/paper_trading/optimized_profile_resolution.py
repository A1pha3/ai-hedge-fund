from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypedDict


class OptimizedProfileResolution(TypedDict):
    mode: str
    profile_name: str
    profile_overrides: dict[str, object]
    source_type: str | None
    source_path: str | None
    validated_by: str | None
    trade_date: str | None
    status: str
    fallback_reason: str | None
    manifest_path: str


def resolve_btst_optimized_profile_manifest(manifest_path: str | Path) -> OptimizedProfileResolution:
    resolved_path = Path(manifest_path).expanduser().resolve()
    if not resolved_path.exists():
        return {
            "mode": "default_fallback",
            "profile_name": "default",
            "profile_overrides": {},
            "source_type": None,
            "source_path": None,
            "validated_by": None,
            "trade_date": None,
            "status": "missing",
            "fallback_reason": "optimized_profile_manifest_missing",
            "manifest_path": str(resolved_path),
        }

    # If the path exists but is not a regular readable file (directory, symlink to dir, or unreadable by permissions)
    # treat it as a fallback instead of raising an uncaught exception from read_text().
    if not resolved_path.is_file() or not os.access(resolved_path, os.R_OK):
        return {
            "mode": "default_fallback",
            "profile_name": "default",
            "profile_overrides": {},
            "source_type": None,
            "source_path": None,
            "validated_by": None,
            "trade_date": None,
            "status": "missing",
            "fallback_reason": "optimized_profile_manifest_unreadable",
            "manifest_path": str(resolved_path),
        }

    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Malformed JSON or invalid encoding must not raise to callers; return an explicit default fallback
        return {
            "mode": "default_fallback",
            "profile_name": "default",
            "profile_overrides": {},
            "source_type": None,
            "source_path": None,
            "validated_by": None,
            "trade_date": None,
            "status": "invalid",
            "fallback_reason": "optimized_profile_manifest_malformed",
            "manifest_path": str(resolved_path),
        }
    except OSError:
        # Unreadable file (permissions, directory, etc.) should fall back
        return {
            "mode": "default_fallback",
            "profile_name": "default",
            "profile_overrides": {},
            "source_type": None,
            "source_path": None,
            "validated_by": None,
            "trade_date": None,
            "status": "missing",
            "fallback_reason": "optimized_profile_manifest_unreadable",
            "manifest_path": str(resolved_path),
        }

    if not isinstance(payload, dict):
        # invalid shape
        return {
            "mode": "default_fallback",
            "profile_name": "default",
            "profile_overrides": {},
            "source_type": None,
            "source_path": None,
            "validated_by": None,
            "trade_date": None,
            "status": "invalid",
            "fallback_reason": "optimized_profile_manifest_invalid",
            "manifest_path": str(resolved_path),
        }

    profile_name = str(payload.get("profile_name") or "").strip()
    # Validate the raw profile_overrides field without defaulting to an empty dict.
    # Previously using `or {}` allowed falsy non-dict values like [] or '' to be replaced
    # with {} which then passed the dict isinstance check. We must treat only real
    # dicts as valid for an optimized manifest.
    profile_overrides = payload.get("profile_overrides")
    status = str(payload.get("status") or "").strip()
    source_path = str(payload.get("source_path") or "").strip() or None

    # Normalize relative source paths against the manifest location to avoid failures when cwd changes
    resolved_source_path = None
    if source_path is not None:
        src_path_obj = Path(source_path)
        if src_path_obj.is_absolute():
            resolved_source_path = src_path_obj.expanduser().resolve()
        else:
            # Use manifest directory as the stable base for relative paths
            resolved_source_path = (resolved_path.parent / src_path_obj).expanduser().resolve()

    # Basic validation: must have a profile name, status ready, and dict overrides
    if not profile_name or status != "ready" or not isinstance(profile_overrides, dict):
        return {
            "mode": "default_fallback",
            "profile_name": "default",
            "profile_overrides": {},
            "source_type": str(payload.get("source_type") or "").strip() or None,
            "source_path": str(resolved_source_path) if resolved_source_path is not None else source_path,
            "validated_by": str(payload.get("validated_by") or "").strip() or None,
            "trade_date": str(payload.get("trade_date") or "").strip() or None,
            "status": status or "invalid",
            "fallback_reason": "optimized_profile_manifest_invalid",
            "manifest_path": str(resolved_path),
        }

    # If a source_path was provided, verify the resolved path exists and points at a regular readable file
    if resolved_source_path is not None:
        # treat directories, symlinks-to-dirs, or unreadable files as missing/invalid sources
        if not resolved_source_path.exists() or not resolved_source_path.is_file() or not os.access(resolved_source_path, os.R_OK):
            return {
                "mode": "default_fallback",
                "profile_name": "default",
                "profile_overrides": {},
                "source_type": str(payload.get("source_type") or "").strip() or None,
                "source_path": str(resolved_source_path),
                "validated_by": str(payload.get("validated_by") or "").strip() or None,
                "trade_date": str(payload.get("trade_date") or "").strip() or None,
                "status": status,
                "fallback_reason": "optimized_profile_source_missing",
                "manifest_path": str(resolved_path),
            }

    return {
        "mode": "optimized",
        "profile_name": profile_name,
        "profile_overrides": dict(profile_overrides),
        "source_type": str(payload.get("source_type") or "").strip() or None,
        "source_path": str(resolved_source_path) if resolved_source_path is not None else source_path,
        "validated_by": str(payload.get("validated_by") or "").strip() or None,
        "trade_date": str(payload.get("trade_date") or "").strip() or None,
        "status": status,
        "fallback_reason": None,
        "manifest_path": str(resolved_path),
    }
