FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Copy workspace root + member pyproject.toml files (for dependency resolution)
COPY pyproject.toml uv.lock ./
COPY models/pyproject.toml models/pyproject.toml
COPY core/pyproject.toml core/pyproject.toml
COPY worker/pyproject.toml worker/pyproject.toml
COPY server/pyproject.toml server/pyproject.toml

# Install third-party deps (cached layer — only changes when pyproject.toml or lockfile change)
WORKDIR /app/server
RUN uv sync --frozen --no-dev --no-install-project --no-install-workspace

# Copy source for all packages
COPY models/src/ /app/models/src/
COPY core/src/ /app/core/src/
COPY worker/src/ /app/worker/src/
COPY server/src/ src/
COPY server/scripts/ scripts/

# Install workspace packages
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "hideandseek.main:app", "--host", "0.0.0.0"]
