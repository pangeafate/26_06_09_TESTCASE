# syntax=docker/dockerfile:1
# HelixPay app image — Python 3.12 + uv. Serves the frozen ASGI app
# (FastAPI + streamable-HTTP MCP under /mcp) on port 8000.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1

# uv — fast, reproducible installs (copied from the official distroless image).
COPY --from=ghcr.io/astral-sh/uv:0.8.15 /uv /uvx /bin/

WORKDIR /app

# Copy the source. A tight .dockerignore keeps the venv, git, caches, tests, and
# secrets out of the build context. `COPY .` (not per-directory) means the image
# builds whether or not every sibling agent's directory exists yet, and picks up
# helixpay/, data/, prompts/, and eval/ at integration without edits here.
COPY . .

# Install the package and its runtime dependencies into the system environment.
RUN uv pip install --system .

# Drop privileges: run the server as a non-root user. The app writes nothing to
# the image filesystem (state lives in the db container's volume), so read-only
# /app owned by root is fine; port 8000 is unprivileged.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# Default process: serve the API + MCP. `make ingest` / `make demo` override this
# with one-off `docker compose run --rm app ...` commands.
CMD ["uvicorn", "helixpay.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
