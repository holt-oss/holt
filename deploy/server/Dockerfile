# Holt API server (server/) plus the engine it wraps (src/holt).
# Build context: the repository root.
#   docker build -f deploy/server/Dockerfile .
FROM python:3.12-slim AS build
# The venv must sit at the same path in both stages: its scripts' shebangs are absolute.
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so source edits don't reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY server/pyproject.toml server/pyproject.toml
RUN uv sync --frozen --no-dev --package holt-server --no-install-workspace

COPY src/ src/
COPY server/ server/
RUN uv sync --frozen --no-dev --package holt-server --no-editable

FROM python:3.12-slim
LABEL holt.stage="holt-new"
RUN useradd --create-home --uid 10001 holt
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8000
USER holt
WORKDIR /home/holt
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1
CMD ["holt-server"]
