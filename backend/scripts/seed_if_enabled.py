"""Conditionally run the demo seed during deploy.

Intended for the Render (or any PaaS) *release / pre-deploy* phase, AFTER
``alembic upgrade head``.  When the ``SEED_DEMO`` environment variable is
truthy (``1``/``true``/``yes``/``on``), this runs the fully idempotent demo
seed so a freshly-provisioned database shows the rich demo data (tenant
``demo@ayaz.app``) instead of empty screens — handy for review/demo
deployments.

Safety
------
- Default behaviour (``SEED_DEMO`` unset/false) is a **no-op** — real
  production deploys are unaffected.
- The seed itself is idempotent (re-running does not duplicate data).
- This script **never fails the deploy**: any seeding error is logged and the
  process still exits ``0`` so the new app version can go live regardless.

Usage
-----
    python -m scripts.seed_if_enabled        # from the backend/ directory

In ``render.yaml`` this is chained after migrations::

    preDeployCommand: alembic upgrade head && python -m scripts.seed_if_enabled
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running as a plain script as well as ``python -m scripts.seed_if_enabled``.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_TRUTHY = {"1", "true", "yes", "on"}


def main() -> int:
    flag = os.environ.get("SEED_DEMO", "").strip().lower()
    if flag not in _TRUTHY:
        print("[seed_if_enabled] SEED_DEMO not enabled — skipping demo seed.")
        return 0

    print("[seed_if_enabled] SEED_DEMO enabled — running idempotent demo seed...")
    try:
        from scripts.seed_demo import run_seed

        run_seed()
        print("[seed_if_enabled] Demo seed complete.")
    except Exception as exc:  # noqa: BLE001 — never block the deploy on a seed error
        print(
            f"[seed_if_enabled] WARNING: demo seed failed ({exc!r}); "
            "continuing so the app can still go live.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
