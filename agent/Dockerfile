# Foundry Hosted Agent image (linux/amd64; Foundry's readiness probe hits port 8088).
#   docker build --platform linux/amd64 -t <acr>.azurecr.io/attendance-alert-agent:<tag> .
FROM python:3.11-slim

# Runtime libraries the bundled mssql-python ODBC driver links against.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libltdl7 libkrb5-3 libgssapi-krb5-2 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.11.26 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

# Run the venv's interpreter directly: Foundry sets HOME to a directory this user cannot write,
# so nothing at runtime may need a writable home or cache (no `uv run`, no .pyc writes).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8088
EXPOSE 8088
CMD ["python", "-m", "src.main"]
