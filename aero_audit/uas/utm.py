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
        doc = json.loads(text)
    except ValueError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as e:
            raise ValueError("YAML documents need PyYAML; convert to JSON or install pyyaml") from e
        doc = yaml.safe_load(text)
    if isinstance(doc, dict):
        doc["__file__"] = str(Path(path).resolve())  # lets external $ref resolve to sibling documents
    return doc


_SIBLINGS: dict[str, dict[str, Any]] = {}


def resolve_ref(doc: dict[str, Any], ref: str) -> Any:
    """Local ``#/…`` refs, and external ``<url-or-path>#/…`` refs when a document with the same base name (json or yaml)
    sits beside the loaded document: NASA's utm-apis spread definitions over utm-domain-*.yaml files that way."""
    target = doc
    if not ref.startswith("#/"):
        base, _, frag = ref.partition("#")
        folder = Path(doc.get("__file__", "")).parent if doc.get("__file__") else None
        stem = Path(base.split("?")[0]).stem
        found = None
        if folder is not None:
            for cand in (folder / f"{stem}.json", folder / f"{stem}.yaml", folder / f"{stem}.yml"):
                if cand.is_file():
                    key = str(cand)
                    if key not in _SIBLINGS:
                        _SIBLINGS[key] = load_document(cand)
                    found = _SIBLINGS[key]
                    break
        if found is None:
            raise ValueError(f"unresolvable $ref {ref} (external documents resolve only to a sibling file named {stem}.json/.yaml)")
        target, ref = found, "#" + frag
    node: Any = target
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[part]
    return node


UTM_APIS_RAW = "https://raw.githubusercontent.com/nasa/utm-apis/master/"
UTM_DOMAIN_FILES = ("utm-domains/utm-domain-commons.yaml", "utm-domains/utm-domain-geojson.yaml", "utm-domains/utm-domain-metadata.yaml",
                    "utm-domains/utm-domain-performance-auth.yaml", "uss-api/swagger.yaml", "oper-api/operator-api.yaml")


async def fetch_domains(dest_dir: str | Path = "data/uas", files: tuple[str, ...] = UTM_DOMAIN_FILES) -> list[Path]:
    """Download NASA's UTM contracts (keyless GitHub raw) and store them as JSON beside each other, so external refs resolve."""
    import hashlib
    import time

    import httpx

    from ..config import settings
    from ..ingest.http import get_json  # noqa: F401 - keeps the transport fallback import path warm

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    out = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for rel in files:
            r = await client.get(UTM_APIS_RAW + rel, headers={"User-Agent": settings.user_agent})
            r.raise_for_status()
            import yaml  # type: ignore[import-not-found]

            doc = yaml.safe_load(r.text)
            p = dest / (Path(rel).stem + ".json")
            text = json.dumps(doc, indent=1, default=str)  # YAML parses dates into datetime objects
            p.write_text(text)
            p.with_suffix(".json.provenance.json").write_text(json.dumps({"source": UTM_APIS_RAW + rel, "fetched_at": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
                                                                          "sha256": hashlib.sha256(text.encode()).hexdigest(), "terms": "nasa/utm-apis (NASA open source; contracts only, no data)"}, indent=1))
            out.append(p)
    return out


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


__all__ = ["UTM_APIS_RAW", "UTM_DOMAIN_FILES", "check_samples", "fetch_domains", "load_document", "resolve_ref", "response_schema", "schema_for", "validate"]
