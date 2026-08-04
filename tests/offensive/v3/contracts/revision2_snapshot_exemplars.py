"""Read-only helpers for Revision 2 literal contract snapshots.

Expected schemas, payloads, hashes, aliases, enums, and port signatures live in
checked-in JSON.  This module only resolves the statically named runtime objects
and renders their current shape for comparison with those literals.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import types
from enum import Enum
from typing import Any, ForwardRef, TypeVar, get_args, get_origin, get_type_hints

from pydantic import BaseModel, TypeAdapter

from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    OutcomeEvidence,
    SignalEvidence,
    SnapshotEvidence,
)
from src.screening.offensive.v3.contracts.decision import PlanEvidence


_MODEL_SPECIALIZATIONS: dict[str, type[BaseModel]] = {
    "src.screening.offensive.v3.contracts.evidence.EvidenceRecord[OutcomeEvidence]": EvidenceRecord[
        OutcomeEvidence
    ],
    "src.screening.offensive.v3.contracts.evidence.EvidenceRecord[PlanEvidence]": EvidenceRecord[
        PlanEvidence
    ],
    "src.screening.offensive.v3.contracts.evidence.EvidenceRecord[SignalEvidence]": EvidenceRecord[
        SignalEvidence
    ],
    "src.screening.offensive.v3.contracts.evidence.EvidenceRecord[SnapshotEvidence]": EvidenceRecord[
        SnapshotEvidence
    ],
}


def resolve_name(qualified_name: str) -> Any:
    """Resolve one literal fully qualified name without discovering expectations."""

    specialized = _MODEL_SPECIALIZATIONS.get(qualified_name)
    if specialized is not None:
        return specialized
    module_name, _, attribute_name = qualified_name.rpartition(".")
    if not module_name:
        raise ValueError(f"not a fully qualified name: {qualified_name}")
    return getattr(importlib.import_module(module_name), attribute_name)


def compact_json_bytes(value: Any) -> bytes:
    """Independent stdlib canonical JSON used to verify frozen hash literals."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(compact_json_bytes(value)).hexdigest()


def independent_domain_hash(*, domain: str, schema_major: int, payload: Any) -> str:
    return sha256_json(
        {
            "domain": domain,
            "payload": payload,
            "schema_major": schema_major,
        }
    )


def schema_snapshot(model_type: type[BaseModel]) -> dict[str, Any]:
    schema = model_type.model_json_schema()
    return {
        "additional_properties": schema.get("additionalProperties"),
        "fields": list(model_type.model_fields),
        "required": schema.get("required", []),
        "schema": schema,
        "schema_sha256": sha256_json(schema),
    }


def annotation_name(annotation: Any) -> str:
    """Render annotations without addresses or interpreter-specific repr noise."""

    if annotation is inspect.Signature.empty:
        return "<empty>"
    if annotation is None or annotation is type(None):
        return "builtins.None"
    if annotation is Any:
        return "typing.Any"
    if isinstance(annotation, TypeVar):
        return f"TypeVar({annotation.__name__})"
    if isinstance(annotation, ForwardRef):
        return f"ForwardRef({annotation.__forward_arg__})"
    origin = get_origin(annotation)
    if origin is not None:
        origin_name = annotation_name(origin)
        arguments = ",".join(annotation_name(item) for item in get_args(annotation))
        return f"{origin_name}[{arguments}]"
    if annotation is types.UnionType:
        return "types.UnionType"
    module = getattr(annotation, "__module__", None)
    qualname = getattr(annotation, "__qualname__", None)
    if module and qualname:
        return f"{module}.{qualname}"
    return str(annotation)


def enum_snapshot(enum_type: type[Enum]) -> dict[str, Any]:
    value_types = {type(item.value) for item in enum_type}
    return {
        "members": [{"name": item.name, "value": item.value} for item in enum_type],
        "value_type": (
            annotation_name(next(iter(value_types)))
            if len(value_types) == 1
            else "mixed"
        ),
    }


def alias_snapshot(alias: Any) -> dict[str, Any]:
    schema = TypeAdapter(alias).json_schema()
    return {
        "schema": schema,
        "schema_sha256": sha256_json(schema),
    }


def _typevar_snapshot(parameter: TypeVar) -> dict[str, Any]:
    return {
        "bound": annotation_name(parameter.__bound__),
        "constraints": [annotation_name(item) for item in parameter.__constraints__],
        "contravariant": parameter.__contravariant__,
        "covariant": parameter.__covariant__,
        "name": parameter.__name__,
    }


def port_snapshot(port_type: type[Any]) -> dict[str, Any]:
    methods: dict[str, Any] = {}
    for name, member in port_type.__dict__.items():
        if name.startswith("_") or not inspect.isfunction(member):
            continue
        signature = inspect.signature(member)
        hints = get_type_hints(member)
        methods[name] = {
            "parameters": [
                {
                    "annotation": annotation_name(
                        hints.get(parameter.name, parameter.annotation)
                    ),
                    "default": (
                        "<empty>"
                        if parameter.default is inspect.Signature.empty
                        else repr(parameter.default)
                    ),
                    "kind": parameter.kind.name,
                    "name": parameter.name,
                }
                for parameter in signature.parameters.values()
            ],
            "return": annotation_name(hints.get("return", signature.return_annotation)),
        }
    return {
        "is_protocol": bool(getattr(port_type, "_is_protocol", False)),
        "is_runtime_protocol": bool(getattr(port_type, "_is_runtime_protocol", False)),
        "methods": methods,
        "parameters": [
            _typevar_snapshot(parameter)
            for parameter in getattr(port_type, "__parameters__", ())
        ],
    }
