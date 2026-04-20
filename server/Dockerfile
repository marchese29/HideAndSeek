FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Copy workspace root + member pyproject.toml files (for dependency resolution)
COPY pyproject.toml uv.lock ./
COPY models/pyproject.toml models/pyproject.toml
COPY core/pyproject.toml core/pyproject.toml
COPY worker/pyproject.toml worker/pyproject.toml
COPY reconciler/pyproject.toml reconciler/pyproject.toml
COPY server/pyproject.toml server/pyproject.toml

# Install third-party deps (cached layer — only changes when pyproject.toml or lockfile change)
WORKDIR /app
RUN uv sync --frozen --no-dev --no-install-project --no-install-workspace

# Copy source for all packages
COPY models/src/ /app/models/src/
COPY core/src/ /app/core/src/
COPY worker/src/ /app/worker/src/
COPY reconciler/src/ /app/reconciler/src/
COPY server/src/ /app/server/src/
COPY server/scripts/ /app/server/scripts/

# Alembic migrations — required by the ECS one-shot migration task (CDK) and
# the docker-compose `migrate` service; invoked via `alembic upgrade head`.
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/

# Install all workspace packages (server, worker, reconciler, core, models)
RUN uv sync --frozen --no-dev --all-packages

WORKDIR /app/server

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "hideandseek.main:app", "--host", "0.0.0.0"]
