FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cached layer). --frozen: uv.lock is authoritative.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Install the project itself.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.14-slim-bookworm

WORKDIR /app
COPY --from=builder /app /app

# Run as non-root. uid 1000 matches the default first user on the host, so
# the ./app/data bind mount stays writable on both laptop (WSL) and VPS.
RUN groupadd -g 1000 app && useradd -m -u 1000 -g app app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000
# --no-access-log: access lines would contain the secret webhook path token;
# the app logs its own structured lines (sender, action) instead.
CMD ["uvicorn", "shopping_agent.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
