#!/usr/bin/env python3
"""
AYAZ End-to-End Smoke Test Suite
=================================
Catches runtime-crash class of bugs: pages that build fine but crash at
runtime due to API shape mismatches (Next.js "Application error" banners,
uncaught exceptions surfaced in console, etc.).

Run: python e2e/smoke.py
     AYAZ_API=http://127.0.0.1:8000 AYAZ_WEB=http://localhost:3000 python e2e/smoke.py
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, BrowserContext

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AYAZ_API = os.environ.get("AYAZ_API", "http://127.0.0.1:8000")
AYAZ_WEB = os.environ.get("AYAZ_WEB", "http://localhost:3000")

DEMO_EMAIL = os.environ.get("AYAZ_DEMO_EMAIL", "demo@ayaz.app")
DEMO_PASSWORD = os.environ.get("AYAZ_DEMO_PASSWORD", "demo12345")

# Resolve the Chromium executable path:
#   1. $PLAYWRIGHT_CHROMIUM_EXECUTABLE if set and the path exists
#   2. The in-container hardcoded fallback if it exists
#   3. None → Playwright uses its own installed browser (CI path)
_ENV_CHROMIUM = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
_HARDCODED_CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

if _ENV_CHROMIUM and Path(_ENV_CHROMIUM).exists():
    CHROMIUM_EXECUTABLE: str | None = _ENV_CHROMIUM
elif Path(_HARDCODED_CHROMIUM).exists():
    CHROMIUM_EXECUTABLE = _HARDCODED_CHROMIUM
else:
    CHROMIUM_EXECUTABLE = None

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

# Settle time after networkidle — lets React effects and deferred renders fire
SETTLE_SECONDS = float(os.environ.get("AYAZ_SETTLE_SECONDS", "2.0"))

# Console messages matching these patterns are fatal (crash indicators).
# Intentionally narrow: we ignore React hydration warnings, missing favicon, etc.
FATAL_CONSOLE_PATTERNS = [
    "uncaught",
    "typeerror",
    "referenceerror",
    "syntaxerror",
    "cannot read propert",   # "Cannot read properties of undefined"
    "cannot read propert",   # "Cannot read property"
    "is not a function",
    "is not defined",
    "failed to fetch",
    "unhandled promise rejection",
    "application error",
    "client-side exception",
    "error: ",               # explicit Error: prefix in console.error
]

# Benign substrings — if any of these appear the message is NOT fatal even if
# it matched a fatal pattern above.
BENIGN_CONSOLE_ALLOWLIST = [
    "warning:",
    "warn:",
    "devtools",
    "favicon",
    "sourcemap",
    "download the react devtools",
    "react-dom.development",
    "[hmr]",
    "fast refresh",
    "webpack",
    "next/dist",
    "_next/",
]

# ---------------------------------------------------------------------------
# Route definitions
# Each entry: (path, requires_auth, expected_marker)
# expected_marker: Turkish substring that MUST appear in page text when healthy.
# Landing page is public; all others require the demo token.
# ---------------------------------------------------------------------------

ROUTES = [
    # (path,               auth_required, expected_turkish_marker)
    ("/",                  False, "dijital pazarlamanız"),
    ("/signup",            False, "Hesap Oluştur"),
    ("/dashboard",         True,  "Zaman Serisi"),
    ("/assistant",         True,  "Yeni sohbet"),
    ("/briefing",          True,  "Günlük Brifing"),
    ("/insights",          True,  "İçgörüler"),
    ("/connections",       True,  "Bağlantılar"),
    ("/feeds",             True,  "Feed Yönetimi"),
    ("/ads",               True,  "Reklam Yönetimi"),
    ("/optimizer",         True,  "Bütçe Optimizasyonu"),
    ("/goals",             True,  "Hedefler"),
    ("/reports",           True,  "Raporlar"),
    ("/report-builder",    True,  "Rapor Oluşturucu"),
    ("/creatives",         True,  "Kreatifler"),
    ("/automation",        True,  "Otomasyon"),
    ("/tracking",          True,  "Ölçümleme"),
    ("/billing",           True,  "Faturalama"),
    ("/workspaces",        True,  "Çalışma Alanları"),
    ("/settings",          True,  "Hesap"),
    ("/notifications",     True,  "Bildirimler"),
]

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def fetch_access_token(email: str, password: str) -> str:
    """POST /api/v1/auth/login and return the access_token string."""
    url = f"{AYAZ_API}/api/v1/auth/login"
    payload = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        raise RuntimeError(
            f"Auth login failed HTTP {exc.code}: {body_text}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach backend at {AYAZ_API}: {exc.reason}\n"
            "Is the backend running? See e2e/README.md for startup instructions."
        ) from exc

    token = body.get("access_token")
    if not token:
        raise RuntimeError(
            f"Login response missing 'access_token'. Got keys: {list(body.keys())}"
        )
    return token


def inject_token_script(token: str) -> str:
    """Return a JS init-script string that writes the token to localStorage."""
    safe_token = json.dumps(token)  # properly escaped JSON string literal
    return f"localStorage.setItem('ayaz_token', {safe_token});"


# ---------------------------------------------------------------------------
# Console error collector
# ---------------------------------------------------------------------------

def is_fatal_console_message(text: str) -> bool:
    """Return True if a console message indicates a runtime crash."""
    lower = text.lower()
    # If it matches any benign pattern, it's not fatal.
    for benign in BENIGN_CONSOLE_ALLOWLIST:
        if benign in lower:
            return False
    # Check fatal patterns.
    for pattern in FATAL_CONSOLE_PATTERNS:
        if pattern in lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Per-route test
# ---------------------------------------------------------------------------

def check_route(
    page: Page,
    path: str,
    expected_marker: str,
    route_label: str,
) -> tuple[bool, list[str]]:
    """
    Navigate to path, assert absence of crash banners, presence of expected
    Turkish marker, and no fatal console errors.

    Returns (passed: bool, failure_reasons: list[str]).
    """
    url = f"{AYAZ_WEB}{path}"
    fatal_console: list[str] = []

    def on_console(msg):
        # Collect fatal-level console messages regardless of msg.type to catch
        # errors emitted via console.error or logged exception strings.
        text = msg.text
        if msg.type in ("error", "warning") or is_fatal_console_message(text):
            if is_fatal_console_message(text):
                fatal_console.append(f"[{msg.type}] {text}")

    page.on("console", on_console)

    # Also catch uncaught page errors (unhandled promise rejections, etc.)
    page_errors: list[str] = []

    def on_page_error(exc):
        page_errors.append(str(exc))

    page.on("pageerror", on_page_error)

    try:
        page.goto(url, wait_until="networkidle", timeout=30_000)
    except Exception as exc:
        return False, [f"Navigation failed: {exc}"]

    # Short settle for deferred React effects / data fetches
    time.sleep(SETTLE_SECONDS)

    body_text = page.inner_text("body")
    # Raw DOM text (case-preserved). `inner_text` reflects CSS text-transform, so
    # an uppercased section title renders as "ZAMAN SERİSİ" and a case-sensitive
    # marker like "Zaman Serisi" would spuriously fail (the Turkish dotted-İ also
    # defeats naive lower-casing). Match the marker against both, so a purely
    # visual text-transform never breaks a content-presence assertion.
    body_text_raw = page.text_content("body") or ""
    failures: list[str] = []

    # ---- Assertion 1: no Next.js crash banner --------------------------------
    CRASH_STRINGS = ["Application error", "client-side exception"]
    for crash_str in CRASH_STRINGS:
        if crash_str.lower() in body_text.lower():
            failures.append(f"Crash banner detected: '{crash_str}' found in page body")
            break

    # ---- Assertion 2: expected Turkish marker present -----------------------
    if expected_marker not in body_text and expected_marker not in body_text_raw:
        failures.append(
            f"Expected Turkish marker not found: '{expected_marker}'"
        )

    # ---- Assertion 3: no fatal console errors -------------------------------
    if fatal_console:
        failures.append(
            "Fatal console errors:\n"
            + "\n".join(f"    {e}" for e in fatal_console)
        )

    # ---- Assertion 4: no uncaught page errors -------------------------------
    if page_errors:
        failures.append(
            "Uncaught page errors (pageerror events):\n"
            + "\n".join(f"    {e}" for e in page_errors)
        )

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"\nAYAZ Smoke Test Suite")
    print(f"  Backend : {AYAZ_API}")
    print(f"  Frontend: {AYAZ_WEB}")
    print(f"  Chromium: {CHROMIUM_EXECUTABLE or '(playwright installed browser)'}")
    print()

    # --- Step 1: Obtain demo token via API -----------------------------------
    print("Obtaining demo auth token...", flush=True)
    try:
        token = fetch_access_token(DEMO_EMAIL, DEMO_PASSWORD)
        print(f"  Token obtained (length={len(token)})\n")
    except RuntimeError as exc:
        print(f"\nFATAL: {exc}\n")
        return 2

    token_init_script = inject_token_script(token)

    # --- Step 2: Launch browser ----------------------------------------------
    results: list[tuple[str, bool, list[str]]] = []

    with sync_playwright() as p:
        launch_kwargs: dict = {"headless": True}
        if CHROMIUM_EXECUTABLE is not None:
            launch_kwargs["executable_path"] = CHROMIUM_EXECUTABLE
        browser = p.chromium.launch(**launch_kwargs)

        # Public context (no token) — for the landing page
        public_context: BrowserContext = browser.new_context()

        # Authenticated context — token injected before every navigation
        auth_context: BrowserContext = browser.new_context()
        auth_context.add_init_script(token_init_script)

        for path, requires_auth, expected_marker in ROUTES:
            route_label = path if path != "/" else "/ (landing)"
            print(f"  Testing {route_label} ...", end=" ", flush=True)

            context = auth_context if requires_auth else public_context

            # Fresh page per route so state/console don't bleed across tests
            page = context.new_page()
            try:
                passed, failures = check_route(
                    page, path, expected_marker, route_label
                )
            except Exception as exc:
                passed = False
                failures = [f"Unexpected exception: {exc}"]

            if not passed:
                # Save screenshot for debugging
                screenshot_name = path.strip("/").replace("/", "_") or "landing"
                screenshot_path = ARTIFACTS_DIR / f"FAIL_{screenshot_name}.png"
                try:
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    failures.append(f"Screenshot saved: {screenshot_path}")
                except Exception as sc_exc:
                    failures.append(f"Screenshot failed: {sc_exc}")

            page.close()
            results.append((route_label, passed, failures))
            status = "PASS" if passed else "FAIL"
            print(status)

        public_context.close()
        auth_context.close()
        browser.close()

    # --- Step 3: Report ------------------------------------------------------
    col_w = max(len(r[0]) for r in results) + 2
    sep = "-" * (col_w + 8)
    print(f"\n{sep}")
    print(f"{'ROUTE':<{col_w}} STATUS")
    print(sep)
    any_failed = False
    for route_label, passed, failures in results:
        status = "PASS" if passed else "FAIL"
        print(f"{route_label:<{col_w}} {status}")
        if not passed:
            any_failed = True
            for reason in failures:
                for line in reason.splitlines():
                    print(f"    {line}")
    print(sep)

    passed_count = sum(1 for _, p, _ in results if p)
    failed_count = len(results) - passed_count
    print(f"\nResults: {passed_count} passed, {failed_count} failed out of {len(results)} routes.\n")

    if any_failed:
        print("SMOKE TEST FAILED -- see failure details and artifacts above.\n")
        return 1

    print("SMOKE TEST PASSED -- all routes healthy.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
