# AYAZ Backend

FastAPI backend for the AYAZ unified digital-marketing platform.

## Prerequisites

- Python 3.11+
- Docker + Docker Compose (for Postgres + Redis)
- `pip` or `uv`

## Quick start

### 1. Start infrastructure

```bash
# From repo root
docker compose up -d
```

Postgres will be available at `localhost:5432` and Redis at `localhost:6379`.

### 2. Install dependencies

```bash
cd backend
pip install -e ".[dev]"
```

Or with `uv`:

```bash
cd backend
uv pip install -e ".[dev]"
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env if needed — defaults work with the docker-compose stack
```

### 4. Run database migrations

```bash
cd backend
alembic upgrade head
```

### 5. Start the API server

```bash
uvicorn ayaz.main:app --reload
```

API docs (Swagger UI) available at `http://localhost:8000/docs` (only in DEBUG mode).

Health check: `GET http://localhost:8000/health`

## Running tests

Tests do NOT require a running database — the connector and auth tests are
fully in-process.

```bash
cd backend
pytest
```

Run with verbose output:

```bash
pytest -v
```

Run a specific test file:

```bash
pytest tests/test_sample_connector.py -v
```

## Project layout

```
backend/
  ayaz/
    config.py          # Pydantic-settings env config
    database.py        # SQLAlchemy engine + session factory
    main.py            # FastAPI app, router wiring, CORS
    models/
      base.py          # DeclarativeBase, TimestampMixin
      oltp.py          # Tenant, User, Membership, ConnectedAccount
      analytics.py     # Dim* tables + FactDailyMetrics
    api/
      deps.py          # FastAPI dependencies (auth, tenant context)
      v1/
        auth.py        # POST /auth/signup, /auth/login, GET /auth/me
        connectors.py  # GET/POST /connectors/accounts
    connectors/
      base.py          # Abstract Connector + UnifiedRecord + ConnectorCapabilities
      registry.py      # ConnectorRegistry (auto-registration)
      sample.py        # SampleConnector (fixture-backed, no network)
    services/
      auth.py          # bcrypt hashing + JWT issue/verify
  alembic/
    env.py             # Alembic environment
    versions/
      0001_initial_schema.py
  tests/
    fixtures/
      sample_metrics.json   # Sample ad platform response fixture
    test_sample_connector.py
    test_auth_service.py
    test_connector_registry.py
```

## Adding a new connector (Faz 1+)

1. Create `ayaz/connectors/<platform>.py`, subclass `Connector`, set `platform_key`.
2. Implement all abstract methods.
3. Add `tests/fixtures/<platform>_metrics.json` with a realistic API sample.
4. Add `tests/test_<platform>_connector.py` following the golden-file pattern.
5. Import the module in `ayaz/connectors/__init__.py` so it self-registers.

## Environment variables

See `.env.example` for the full list. Key variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://ayaz:ayaz@localhost:5432/ayaz` | SQLAlchemy connection string |
| `JWT_SECRET` | `changeme` | **Must be changed in production** |
| `JWT_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `ENVIRONMENT` | `development` | `development` / `staging` / `production` |
| `DEBUG` | `false` | Enables Swagger UI + SQLAlchemy echo |

## Architecture notes

- Multi-tenancy: every query filters on `tenant_id`. Postgres RLS policies
  (TODO Faz 1) will add DB-level enforcement using `current_setting('app.tenant_id')`.
- Secrets: connector OAuth tokens are never stored in the DB — only a Vault
  path reference (`vault_secret_ref`). HashiCorp Vault integration: TODO Faz 1.
- Derived metrics (CTR/CPC/CPA/ROAS) are computed by the Metric Layer, not
  stored in `fact_daily_metrics`.
