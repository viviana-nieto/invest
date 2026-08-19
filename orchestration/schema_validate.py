"""Minimal, dependency-free schema validation for LLM output.

Supports the subset the skills need: object/array/string/number/boolean types,
`required` keys, and per-property `type`. Enough to enforce the JSON contract in
`orchestration/schema.json` without pulling in the `jsonschema` package.
"""

from __future__ import annotations

_PY_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def validate(data, schema, path="$") -> list[str]:
    """Return a list of human-readable error strings ([] == valid)."""
    errors: list[str] = []
    expected = schema.get("type")

    if expected:
        py = _PY_TYPES.get(expected)
        if py and not isinstance(data, py):
            errors.append(f"{path}: expected {expected}, got {type(data).__name__}")
            return errors  # type mismatch — deeper checks would be noise

    if expected == "object" or isinstance(data, dict):
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}: missing required key '{key}'")
        for key, subschema in schema.get("properties", {}).items():
            if key in data:
                errors.extend(validate(data[key], subschema, f"{path}.{key}"))

    if (expected == "array" or isinstance(data, list)) and "items" in schema:
        for i, item in enumerate(data):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]"))

    return errors


def is_valid(data, schema) -> bool:
    return not validate(data, schema)
