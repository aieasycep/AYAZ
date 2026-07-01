"""Kurulum Sihirbazı (Onboarding Wizard) service — step detection.

build_onboarding_status(db, tenant_id) -> dict
----------------------------------------------
Inspects existing tenant data across five modules and returns a structured
completion report used by the onboarding wizard endpoint.  Each step is
detected by querying the relevant model table; a ``try/except`` per step
guarantees the whole call succeeds even when a table migration hasn't run
yet in a development environment.

Step order (canonical, must not change)
---------------------------------------
1. connect_accounts  — ConnectedAccount
2. set_goal          — Goal
3. tracking          — TrackingSource
4. budget_plan       — BudgetPlan
5. first_content     — ContentPost

Return contract (exact keys required by the API layer)
-------------------------------------------------------
{
    "total_steps": int,
    "completed_steps": int,
    "percent": int,           # 0-100, rounded
    "all_done": bool,
    "steps": [
        {
            "key": str,
            "title": str,
            "description": str,
            "done": bool,
            "cta_label": str,
            "cta_link": str,
        },
        ...                   # in the order above — always 5 items
    ],
}

Tenant isolation
----------------
Every query explicitly filters ``WHERE tenant_id = :tenant_id``.  No
cross-tenant data can ever be returned.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

# ── Step catalogue ─────────────────────────────────────────────────────────────

# Each entry: (key, title, description, cta_label, cta_link, model_import_path)
# The model is imported lazily inside _count() to keep this module importable
# even if individual model files have issues.

_STEP_DEFS: list[dict[str, str]] = [
    {
        "key": "connect_accounts",
        "title": "Hesaplarınızı bağlayın",
        "description": "Reklam ve analitik hesaplarınızı bağlayın (Google, Meta, TikTok…).",
        "cta_label": "Bağlantılar",
        "cta_link": "/connections",
        "model_module": "ayaz.models.oltp",
        "model_class": "ConnectedAccount",
    },
    {
        "key": "set_goal",
        "title": "İlk hedefinizi koyun",
        "description": "ROAS, dönüşüm veya gelir hedefi tanımlayın.",
        "cta_label": "Hedefler",
        "cta_link": "/goals",
        "model_module": "ayaz.models.goals",
        "model_class": "Goal",
    },
    {
        "key": "tracking",
        "title": "Ölçümlemeyi kurun",
        "description": (
            "Server-side dönüşüm ölçümlemesi (CAPI) için izleme kaynağı oluşturun."
        ),
        "cta_label": "Ölçümleme",
        "cta_link": "/tracking",
        "model_module": "ayaz.models.tracking",
        "model_class": "TrackingSource",
    },
    {
        "key": "budget_plan",
        "title": "Bütçe planı oluşturun",
        "description": "Gelecek ayın bütçesini platform bazında planlayın.",
        "cta_label": "Planlama",
        "cta_link": "/planning",
        "model_module": "ayaz.models.budget",
        "model_class": "BudgetPlan",
    },
    {
        "key": "first_content",
        "title": "İlk içeriğinizi planlayın",
        "description": "Sosyal içerik takviminizi oluşturmaya başlayın.",
        "cta_label": "İçerik",
        "cta_link": "/content",
        "model_module": "ayaz.models.content",
        "model_class": "ContentPost",
    },
]


# ── Internal helpers ───────────────────────────────────────────────────────────


def _count_rows(db: Session, model_module: str, model_class: str, tenant_id: uuid.UUID) -> int:
    """Return the number of rows for *tenant_id* in the given model table.

    Returns 0 on any exception (missing table, import error, query failure)
    so that a single broken step never fails the entire wizard response.
    """
    try:
        import importlib
        module = importlib.import_module(model_module)
        model = getattr(module, model_class)
        stmt = select(func.count()).select_from(model).where(
            model.tenant_id == tenant_id
        )
        result: int = db.scalar(stmt) or 0
        return result
    except Exception:  # noqa: BLE001 — defensive; intentionally broad
        return 0


# ── Public API ─────────────────────────────────────────────────────────────────


def build_onboarding_status(
    db: Session,
    tenant_id: uuid.UUID,
) -> dict[str, Any]:
    """Build the onboarding wizard completion report for *tenant_id*.

    Parameters
    ----------
    db:
        Active SQLAlchemy session scoped to the current request.
    tenant_id:
        UUID of the tenant whose setup progress is being queried.

    Returns
    -------
    dict with keys: total_steps, completed_steps, percent, all_done, steps.
    See module docstring for the full shape.
    """
    steps: list[dict[str, Any]] = []

    for step_def in _STEP_DEFS:
        count = _count_rows(
            db=db,
            model_module=step_def["model_module"],
            model_class=step_def["model_class"],
            tenant_id=tenant_id,
        )
        done = count > 0
        steps.append(
            {
                "key": step_def["key"],
                "title": step_def["title"],
                "description": step_def["description"],
                "done": done,
                "cta_label": step_def["cta_label"],
                "cta_link": step_def["cta_link"],
            }
        )

    total_steps: int = len(steps)
    completed_steps: int = sum(1 for s in steps if s["done"])
    percent: int = round(completed_steps / total_steps * 100) if total_steps > 0 else 0

    return {
        "total_steps": total_steps,
        "completed_steps": completed_steps,
        "percent": percent,
        "all_done": completed_steps == total_steps,
        "steps": steps,
    }
