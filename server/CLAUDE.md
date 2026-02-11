# Server — FastAPI + UV

Python FastAPI backend for the HideAndSeek game.

## Commands

```bash
uv sync                    # Install/update dependencies
uv run uvicorn hideandseek.main:app --reload  # Run dev server (localhost:8000)
uv run pytest              # Run tests
uv run python scripts/generate_openapi.py     # Regenerate OpenAPI spec
```

## Project Structure

- `src/hideandseek/main.py` — FastAPI app entrypoint
- `src/hideandseek/routers/` — API route modules
- `tests/` — pytest tests (use `httpx` / `TestClient`)
- `scripts/generate_openapi.py` — dumps `app.openapi()` to `openapi/openapi.yaml`

## Conventions

- Add dependencies with `uv add <package>`.
- All routes go in `routers/` and are included via `app.include_router()`.
- Tests use `fastapi.testclient.TestClient`.
- OpenAPI spec is auto-generated — add routes to FastAPI, not the YAML file.
