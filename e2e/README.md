# AYAZ End-to-End Smoke Tests

Catches the runtime-crash class of frontend bugs: pages that build without
errors but crash at runtime because the backend API shape does not match what
the page component expects (the Next.js "Application error" / "client-side
exception" banner).

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.9+ | In the project virtualenv or system Python |
| `playwright` pip package | Already installed; do NOT run `playwright install` |
| Chromium binary | `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` (pre-installed) |
| PostgreSQL | Running and accessible to the backend |
| Node 18+ | For the Next.js frontend build |

---

## Start the stack

Run each block in a separate terminal (or background them with `&`).

### 1. Backend

```bash
cd /home/user/AYAZ/backend
alembic upgrade head
python -m scripts.seed_demo
uvicorn ayaz.main:app --host 127.0.0.1 --port 8000
```

The seed script creates the demo user `demo@ayaz.app` / `demo12345` and
populates reference data required by the pages.

### 2. Frontend

```bash
cd /home/user/AYAZ/frontend
npm run build
npx next start -p 3000
```

> For a faster iteration loop during development you can use `npm run dev`
> instead, but the build+start path is preferred for smoke testing because it
> catches tree-shaking and SSR errors that dev mode hides.

---

## Run the smoke suite

From the **repository root**:

```bash
python e2e/smoke.py
```

Or with explicit environment variables:

```bash
AYAZ_API=http://127.0.0.1:8000 \
AYAZ_WEB=http://localhost:3000 \
python e2e/smoke.py
```

The suite prints a PASS/FAIL table to stdout and exits 0 on success, non-zero
on any failure.

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `AYAZ_API` | `http://127.0.0.1:8000` | Backend base URL |
| `AYAZ_WEB` | `http://localhost:3000` | Frontend base URL |
| `AYAZ_DEMO_EMAIL` | `demo@ayaz.app` | Demo account email |
| `AYAZ_DEMO_PASSWORD` | `demo12345` | Demo account password |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE` | `/opt/pw-browsers/chromium-1194/chrome-linux/chrome` | Path to Chromium binary |
| `AYAZ_SETTLE_SECONDS` | `2.0` | Extra wait after networkidle (increase on slow machines) |

---

## Demo credentials

| Field | Value |
|---|---|
| Email | `demo@ayaz.app` |
| Password | `demo12345` |

These are created by `backend/scripts/seed_demo.py`.

---

## How auth injection works

The UI login flow is unreliable in dev/build modes (redirects, hydration races).
The suite avoids it entirely:

1. Before the browser is opened, the suite POSTs to
   `POST /api/v1/auth/login` with the demo credentials and captures the
   `access_token` from the JSON response.
2. A Playwright `add_init_script` is registered on the authenticated browser
   context. This script runs **before** every page's JavaScript executes and
   calls `localStorage.setItem('ayaz_token', '<token>')`.
3. When a protected page loads, it reads `localStorage.ayaz_token` (the key
   the frontend uses) and behaves as if the user is already logged in.

The public landing page (`/`) uses a separate context with no token so that
the unauthenticated rendering path is also exercised.

---

## Routes covered

| Route | Auth | Expected Turkish marker |
|---|---|---|
| `/` | No | `dijital pazarlamanız` |
| `/dashboard` | Yes | `Zaman Serisi` |
| `/assistant` | Yes | `AYAZ Asistan` |
| `/briefing` | Yes | `Günlük Brifing` |
| `/insights` | Yes | `İçgörüler` |
| `/connections` | Yes | `Bağlantılar` |
| `/feeds` | Yes | `Feed Yönetimi` |
| `/ads` | Yes | `Reklam Yönetimi` |
| `/optimizer` | Yes | `Bütçe Optimizasyonu` |
| `/goals` | Yes | `Hedefler` |
| `/reports` | Yes | `Raporlar` |
| `/report-builder` | Yes | `Rapor Oluşturucu` |
| `/creatives` | Yes | `Kreatifler` |
| `/automation` | Yes | `Otomasyon` |
| `/tracking` | Yes | `Ölçümleme` |
| `/billing` | Yes | `Faturalama` |
| `/workspaces` | Yes | `Çalışma Alanları` |

---

## Failure artifacts

Screenshots of any failing page are saved to `e2e/artifacts/FAIL_<route>.png`
for visual post-mortem.

---

## What is and is not asserted

### Asserted (will fail the suite)

- The page body contains the Next.js crash banner text ("Application error",
  "client-side exception").
- The expected Turkish heading/marker for that route is absent from the
  rendered body text (catches blank pages, redirect loops, empty state that
  hides a crash).
- Any `console.error` or page-level uncaught exception whose text matches a
  crash pattern (`TypeError`, `ReferenceError`, `Cannot read properties of`,
  `is not a function`, `Failed to fetch`, unhandled promise rejection, etc.).

### Intentionally ignored (benign)

- React DevTools install prompt.
- Webpack / Next.js HMR messages.
- Missing favicon 404.
- Source map warnings.
- Generic `Warning:` / `warn:` prefixed messages.

---

## Extending the suite

To add a new route, append one tuple to the `ROUTES` list in `e2e/smoke.py`:

```python
("/new-page", True, "Beklenen Türkçe Başlık"),
```

The third element is the Turkish substring that must appear on the healthy
page. Find it by inspecting the page's `<h1>` or prominent heading in
`frontend/src/app/<route>/page.tsx`.
