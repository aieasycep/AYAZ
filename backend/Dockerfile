# ── AYAZ Backend — production image ───────────────────────────────────────────
# python:3.11-slim keeps the image small; we only add the gcc/libpq build deps
# that psycopg[binary] and passlib[bcrypt] need, then remove them.
FROM python:3.11-slim AS base

# System-level build dependencies.
# libpq-dev   → psycopg (binary wheel still links against libpq at runtime)
# gcc/build-essential → any wheels without a pre-built binary
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc \
      libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only the packaging metadata first so pip's layer cache survives code
# changes that don't add/remove dependencies.
COPY pyproject.toml ./

# Install the package in non-editable (production) mode.
# The source tree is copied after, so the install only resolves deps here;
# the actual ayaz package is installed in the COPY + re-install step below.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir .

# Now copy the full application source.
COPY ayaz/ ./ayaz/
COPY alembic/ ./alembic/
COPY alembic.ini ./
# Operational scripts (demo seed + conditional seeder) — needed so the deploy
# start command can run `python -m scripts.seed_if_enabled` after migrations.
COPY scripts/ ./scripts/

# Re-run pip install to make sure the ayaz package itself is installed
# (setuptools needs the source to be present).
RUN pip install --no-cache-dir .

EXPOSE 8000

# Honor $PORT so Render / Railway can override without a custom Dockerfile.
CMD ["sh", "-c", "uvicorn ayaz.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
