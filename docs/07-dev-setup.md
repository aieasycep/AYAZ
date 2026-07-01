# Developer Setup

Everything runs on the host except Postgres and Redis, which run in Docker.

## Prerequisites

- Python 3.11+
- Node 20+
- Docker + Docker Compose

## 1. Start infrastructure

From the repo root, bring up Postgres 16 (port 5432) and Redis 7 (port 6379):

```bash
docker compose up -d
```

## 2. Backend

Install dependencies (from repo root):

```bash
cd backend
pip install -e ".[dev]"
```

Copy and configure the environment file (defaults work with the docker-compose stack):

```bash
cp backend/.env.example backend/.env
```

Run database migrations:

```bash
cd backend
alembic upgrade head
```

Seed demo data (idempotent):

```bash
cd backend
python -m scripts.seed_demo
```

Start the API server with hot-reload:

```bash
cd backend
uvicorn ayaz.main:app --reload
```

API is available at `http://localhost:8000`. Swagger UI (DEBUG mode): `http://localhost:8000/docs`.

## 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend is available at `http://localhost:3000`.

## 4. Running tests

Backend tests are hermetic (SQLite in-process) — no running database required:

```bash
cd backend
pytest -q
```

Run a specific file:

```bash
cd backend
pytest tests/test_auth_service.py -v
```

## 5. Demo login

After seeding, log in with:

- **Email:** `demo@ayaz.app`
- **Password:** `demo12345`

## 6. Environment variables

Key variables (see `backend/.env.example` for the full list):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://ayaz:ayaz@localhost:5432/ayaz` | SQLAlchemy connection string |
| `JWT_SECRET` | `changeme` | Must be changed before deploy |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `ENVIRONMENT` | `development` | `development` / `staging` / `production` |
| `DEBUG` | `true` | Enables Swagger UI and SQLAlchemy echo |
