"""Contract checks against OpenAPI documents (NASA utm-apis and our own): a small JSON-Schema
validator covering what API contracts actually use (type, required, properties, items, enum,
nullable, oneOf/anyOf/allOf, local $ref, format hints), plus helpers to load a document and pick
a schema or a response schema by path and status.

Deliberately dependency-free; the aim is to fail loudly on a message that does not match the
published contract, not to be a complete JSON Schema implementation.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_FORMATS = {
    "date-time": re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"),
    "uuid": re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"),
    "uri": re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:"),
}


def load_document(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text()
    try:
        return json.loads(text)
    except ValueError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as e:
            raise ValueError("YAML documents need PyYAML; convert to JSON or install pyyaml") from e
        return yaml.safe_load(text)


def resolve_ref(doc: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref is supported: {ref}")
    node: Any = doc
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[part]
    return node


def schema_for(doc: dict[str, Any], name: str) -> dict[str, Any]:
    comps = doc.get("components", {}).get("schemas", {}) or doc.get("definitions", {})
    if name not in comps:
        raise KeyError(f"schema {name} not in document; known: {', '.join(sorted(comps))[:300]}")
    return comps[name]


def response_schema(doc: dict[str, Any], path: str, method: str = "get", status: str = "200") -> dict[str, Any] | None:
    op = doc.get("paths", {}).get(path, {}).get(method.lower())
    if not op:
        raise KeyError(f"{method.upper()} {path} not in document")
    resp = op.get("responses", {}).get(status) or op.get("responses", {}).get("default")
    if not resp:
        return None
    content = resp.get("content", {})
    for ctype in ("application/json", "*/*"):
        if ctype in content and "schema" in content[ctype]:
            return content[ctype]["schema"]
    return resp.get("schema")  # OpenAPI 2


def validate(instance: Any, schema: dict[str, Any], doc: dict[str, Any] | None = None, path: str = "$") -> list[str]:
    """Problems as 'path: message' strings; empty means valid."""
    doc = doc or {}
    problems: list[str] = []
    if "$ref" in schema:
        try:
            schema = {**resolve_ref(doc, schema["$ref"]), **{k: v for k, v in schema.items() if k != "$ref"}}
        except (KeyError, ValueError) as e:
            return [f"{path}: unresolvable $ref {schema['$ref']} ({e})"]
    if instance is None and (schema.get("nullable") or (isinstance(schema.get("type"), list) and "null" in schema["type"])):
        return []
    for key in ("allOf", "anyOf", "oneOf"):
        if key in schema:
            results = [validate(instance, s, doc, path) for s in schema[key]]
            ok = [r for r in results if not r]
            if key == "allOf" and any(results):
                problems += [p for r in results for p in r]
            elif key == "anyOf" and not ok:
                problems.append(f"{path}: matches none of anyOf ({'; '.join(results[0][:2])})")
            elif key == "oneOf" and len(ok) != 1:
                problems.append(f"{path}: matches {len(ok)} of oneOf, expected exactly 1")
    t = schema.get("type")
    types = t if isinstance(t, list) else ([t] if t else [])
    if types and not any(_is_type(instance, x) for x in types):
        problems.append(f"{path}: expected {'|'.join(types)}, got {type(instance).__name__}")
        return problems
    if "enum" in schema and instance not in schema["enum"]:
        problems.append(f"{path}: {instance!r} not in enum {schema['enum'][:8]}")
    if isinstance(instance, dict):
        for req in schema.get("required", []):
            if req not in instance:
                problems.append(f"{path}: missing required '{req}'")
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                problems += validate(v, props[k], doc, f"{path}.{k}")
            elif schema.get("additionalProperties") is False:
                problems.append(f"{path}: unexpected property '{k}'")
            elif isinstance(schema.get("additionalProperties"), dict):
                problems += validate(v, schema["additionalProperties"], doc, f"{path}.{k}")
    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, v in enumerate(instance):
                problems += validate(v, items, doc, f"{path}[{i}]")
        if "minItems" in schema and len(instance) < schema["minItems"]:
            problems.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            problems.append(f"{path}: more than {schema['maxItems']} items")
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            problems.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            problems.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            problems.append(f"{path}: does not match pattern {schema['pattern']}")
        fmt = schema.get("format")
        if fmt in _FORMATS and not _FORMATS[fmt].match(instance):
            problems.append(f"{path}: not a valid {fmt}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            problems.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            problems.append(f"{path}: above maximum {schema['maximum']}")
    return problems


def _is_type(v: Any, t: str) -> bool:
    return {"string": isinstance(v, str), "number": isinstance(v, (int, float)) and not isinstance(v, bool),
            "integer": isinstance(v, int) and not isinstance(v, bool), "boolean": isinstance(v, bool),
            "object": isinstance(v, dict), "array": isinstance(v, list), "null": v is None}.get(t, True)


def check_samples(doc: dict[str, Any], samples: list[tuple[str, Any]], schema_name: str | None = None,
                  path: str | None = None, method: str = "get", status: str = "200") -> dict[str, Any]:
    """Validate several (label, instance) pairs against one schema; a conformance report."""
    schema = schema_for(doc, schema_name) if schema_name else response_schema(doc, path or "", method, status)
    if schema is None:
        raise KeyError("no schema found for the requested endpoint/response")
    rows = []
    for label, inst in samples:
        probs = validate(inst, schema, doc)
        rows.append({"sample": label, "ok": not probs, "problems": probs[:20]})
    return {"schema": schema_name or f"{method.upper()} {path} {status}", "samples": len(rows), "conformant": sum(1 for r in rows if r["ok"]), "rows": rows}


__all__ = ["check_samples", "load_document", "resolve_ref", "response_schema", "schema_for", "validate"]
