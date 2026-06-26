.PHONY: install test build dev-backend dev-frontend db-up migrate seed

# Install all dependencies (backend + frontend)
install:
	pip install -e "./backend[dev]"
	cd frontend && npm install

# Run backend test suite (hermetic — no DB required)
test:
	cd backend && pytest -q

# Build the Next.js frontend
build:
	cd frontend && npm run build

# Start the FastAPI backend with hot-reload
dev-backend:
	cd backend && uvicorn ayaz.main:app --reload

# Start the Next.js dev server
dev-frontend:
	cd frontend && npm run dev

# Bring up Postgres + Redis via Docker Compose
db-up:
	docker compose up -d

# Run Alembic migrations to latest
migrate:
	cd backend && alembic upgrade head

# Seed demo data (idempotent)
seed:
	cd backend && python -m scripts.seed_demo
