# uv-based build. Layer the dependency sync before the source copy so code edits
# do not invalidate the (slow) dependency layer.
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
RUN uv sync --frozen --no-dev

# Cloud Run injects $PORT; default to 8080 for local runs.
ENV PORT=8080
EXPOSE 8080

# --proxy-headers trusts the platform's X-Forwarded-Proto so request URLs (and the x402
# challenge's resource.url) reflect the public https origin rather than the internal http hop.
CMD ["sh", "-c", "uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips=*"]
