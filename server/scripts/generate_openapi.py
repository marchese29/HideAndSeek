#!/usr/bin/env python3
"""Generate OpenAPI spec from the FastAPI app and write it to openapi/openapi.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from hideandseek.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = REPO_ROOT / 'openapi' / 'openapi.yaml'

HEADER = (
    '# AUTO-GENERATED from FastAPI server — DO NOT EDIT\n'
    '# Regenerate with: cd server && uv run python scripts/generate_openapi.py\n'
)


def main():
    spec = app.openapi()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        f.write(HEADER)
        yaml.dump(spec, f, default_flow_style=False, sort_keys=False)
    print(f'OpenAPI spec written to {OUTPUT_PATH}')


if __name__ == '__main__':
    main()
