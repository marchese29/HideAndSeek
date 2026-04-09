#!/usr/bin/env python3
"""Generate OpenAPI spec from the FastAPI app and write it to openapi/openapi.yaml.

Injects SSE event schemas (gameplay events from core, game state snapshots
from server) into ``components/schemas`` so that ``openapi-typescript`` can
generate TypeScript types for them.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from hideandseek.main import app
from hideandseek.schemas.response import SSEExposed
from hideandseek_core.broadcast.events import GameplayEventSchema

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = REPO_ROOT / 'openapi' / 'openapi.yaml'

HEADER = (
    '# AUTO-GENERATED from FastAPI server — DO NOT EDIT\n'
    '# Regenerate with: cd server && uv run python scripts/generate_openapi.py\n'
)


def _excluded_field_names(model: type[BaseModel]) -> set[str]:
    """Return field names with ``exclude=True`` (not part of the wire format)."""
    return {name for name, info in model.model_fields.items() if info.exclude}


def inject_schemas(spec: dict, models: list[type[BaseModel]]) -> None:
    """Inject Pydantic model schemas into OpenAPI ``components/schemas``.

    Nested types that Pydantic places under ``$defs`` are hoisted to
    top-level schemas (skip-if-exists to avoid overwriting types already
    in the spec from REST endpoints).  Fields marked ``exclude=True``
    are stripped from the schema (they affect routing, not the wire format).
    """
    schemas = spec.setdefault('components', {}).setdefault('schemas', {})
    for model in models:
        name = model.__name__
        schema = model.model_json_schema(ref_template='#/components/schemas/{model}')
        for def_name, def_schema in schema.pop('$defs', {}).items():
            if def_name not in schemas:
                schemas[def_name] = def_schema
        excluded = _excluded_field_names(model)
        if excluded:
            schema.get('properties', {})
            for field_name in excluded:
                schema.get('properties', {}).pop(field_name, None)
            if 'required' in schema:
                schema['required'] = [r for r in schema['required'] if r not in excluded]
        schemas[name] = schema


def main():
    spec = app.openapi()

    all_sse_models = [
        *GameplayEventSchema.registered_schemas(),
        *SSEExposed.registered_schemas(),
    ]
    inject_schemas(spec, all_sse_models)  # type: ignore[arg-type]  # SSEExposed concrete classes are BaseModel

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        f.write(HEADER)
        yaml.dump(spec, f, default_flow_style=False, sort_keys=False)
    print(f'OpenAPI spec written to {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
