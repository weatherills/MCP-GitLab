"""MCP input schemas and descriptions for coarse, action-discriminated tools.

Schemas are flat (every visible action's parameters side by side plus an
`action` enum) rather than a `oneOf` per action: flat object schemas work across
MCP clients, and each action's own model still validates its arguments strictly.
"""

from collections.abc import Sequence
from typing import Any

from mcp_gitlab.tools.model import Access, Action, Tool

_LITERAL_KEYWORDS = frozenset({"default", "const", "enum", "examples"})
_SCHEMA_MAPS = frozenset({"properties", "$defs", "patternProperties"})


class SchemaConflictError(ValueError):
    """Two actions of one tool declare the same parameter with different schemas."""


def build_input_schema(tool: Tool, actions: Sequence[Action]) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "action": {
            "type": "string",
            "enum": [action.name for action in actions],
            "description": "Operation to perform; see the tool description for what each does.",
        }
    }
    used_by: dict[str, list[str]] = {}
    required_by: dict[str, list[str]] = {}
    defs: dict[str, Any] = {}

    for action in actions:
        schema = _clean(action.params.model_json_schema())
        for name, definition in schema.get("$defs", {}).items():
            if defs.setdefault(name, definition) != definition:
                raise SchemaConflictError(
                    f"{tool.name}: nested model '{name}' differs between actions."
                )
        required = set(schema.get("required", ()))
        for name, prop in schema.get("properties", {}).items():
            existing = properties.setdefault(name, prop)
            if _without_docs(existing) != _without_docs(prop):
                raise SchemaConflictError(
                    f"{tool.name}: parameter '{name}' is declared differently by actions "
                    f"{used_by[name] + [action.name]}; give it one shape or distinct names."
                )
            used_by.setdefault(name, []).append(action.name)
            if name in required:
                required_by.setdefault(name, []).append(action.name)

    everywhere = [name for name, users in required_by.items() if len(users) == len(actions)]
    for name, users in used_by.items():
        required_for = required_by.get(name, [])
        notes = []
        if len(users) < len(actions) and required_for != users:
            notes.append("used by: " + ", ".join(users))
        if required_for and name not in everywhere:
            notes.append("required for: " + ", ".join(required_for))
        if notes:
            properties[name] = _with_note(properties[name], "; ".join(notes))

    destructive = [action.name for action in actions if action.destructive]
    if destructive:
        properties["confirm"] = {
            "type": "boolean",
            "description": "Must be true to run destructive actions: "
            + ", ".join(destructive)
            + ".",
        }

    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": ["action", *everywhere],
        "additionalProperties": False,
    }
    if defs:
        result["$defs"] = defs
    return result


def describe_tool(tool: Tool, actions: Sequence[Action]) -> str:
    lines = [tool.description.strip(), "", "Actions:"]
    for action in actions:
        flags = []
        if action.access is Access.WRITE:
            flags.append("writes to GitLab")
        if action.destructive:
            flags.append("destructive: requires confirm=true")
        suffix = f" [{'; '.join(flags)}]" if flags else ""
        lines.append(f"- {action.name}: {action.description.strip()}{suffix}")
    return "\n".join(lines)


def _clean(schema: Any) -> Any:
    """Drop Pydantic's auto-generated `title` keywords; they add noise, not meaning."""
    if isinstance(schema, list):
        return [_clean(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "title" and isinstance(value, str):
            continue
        if key in _SCHEMA_MAPS and isinstance(value, dict):
            cleaned[key] = {name: _clean(sub) for name, sub in value.items()}
        elif key in _LITERAL_KEYWORDS:
            cleaned[key] = value
        else:
            cleaned[key] = _clean(value)
    return cleaned


def _without_docs(prop: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in prop.items() if key != "description"}


def _with_note(prop: dict[str, Any], note: str) -> dict[str, Any]:
    description = prop.get("description", "").strip()
    return {**prop, "description": f"{description} ({note})".strip()}
