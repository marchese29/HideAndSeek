# Root check command, mirroring hooks/*-checks.sh. See CLAUDE.md.

.PHONY: check check-python test check-mobile regen

check: check-python test check-mobile

check-python:
	@set -e; for p in models core worker reconciler server; do \
	  echo "==> $$p"; \
	  ( cd $$p && uv run ruff check . && uv run ruff format --check . && uv run pyright ); \
	done
	@echo "==> alembic (ruff only: pyright trips on geoalchemy2's dynamic op.drop_geospatial_* registration)"
	uv run ruff check alembic/
	uv run ruff format --check alembic/

test:
	cd server && uv run pytest

check-mobile:
	cd mobile && npx tsc --noEmit && npx expo lint && npx prettier --check .

regen:
	cd server && uv run python scripts/generate_openapi.py
	cd mobile && scripts/generate-api.sh
