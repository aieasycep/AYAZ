"""Hesap Sağlık Taraması (Account Health Audit) API.

Single read-only endpoint that produces a 0-100 health score and a
categorised checklist of findings across all AYAZ modules.

    GET /audit/run

Tenant-scoped: requires a valid JWT with ``tid`` claim.  All data is
filtered to the requesting tenant — no cross-tenant leakage is possible.

No query parameters.  The service layer always uses the last 30 days as
the date window for time-scoped checks (e.g. ad performance, tracking).

Response shape
--------------
{
  "score": int,           # 0–100
  "grade": str,           # "mukemmel" | "iyi" | "orta" | "zayif"
  "summary": str,         # Turkish one/two-liner
  "counts": {             # totals across all checks
    "pass": int,
    "warn": int,
    "fail": int,
  },
  "categories": [
    {
      "key": str,
      "label": str,       # Turkish category label
      "checks": [
        {
          "id": str,
          "severity": str,          # "pass" | "warn" | "fail"
          "title": str,             # Turkish title
          "finding": str,           # Turkish finding description
          "recommendation": str,    # Turkish fix recommendation
        },
        ...
      ]
    },
    ...
  ]
}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ayaz.api.deps import get_current_membership, get_db
from ayaz.models.oltp import Membership
from ayaz.services.audit import run_account_audit

router = APIRouter(prefix="/audit", tags=["audit"])


# ── Response models ────────────────────────────────────────────────────────────


class CheckItem(BaseModel):
    id: str
    severity: str  # "pass" | "warn" | "fail"
    title: str
    finding: str
    recommendation: str


class AuditCategory(BaseModel):
    key: str
    label: str
    checks: list[CheckItem]


class AuditResponse(BaseModel):
    score: int
    grade: str  # "mukemmel" | "iyi" | "orta" | "zayif"
    summary: str
    counts: dict[str, int]  # {"pass": int, "warn": int, "fail": int}
    categories: list[AuditCategory]


# ── Endpoint ───────────────────────────────────────────────────────────────────


@router.get(
    "/run",
    response_model=AuditResponse,
    summary=(
        "Hesap Sağlık Taraması — tüm modüller genelinde tek tıkla tarama. "
        "0-100 sağlık puanı, harf notu ve kategorilere göre bulgular döndürür."
    ),
)
def run_audit(
    db: Session = Depends(get_db),
    membership: Membership = Depends(get_current_membership),
) -> AuditResponse:
    """Run a full read-only health scan across all AYAZ modules.

    Analyses ad performance, tracking / CAPI configuration, budget planning,
    content workflow, goal progress, and persisted insights for the current
    tenant.  Each check is tagged ``pass``, ``warn``, or ``fail``.

    Score formula
    -------------
    Starts at 100.  Each ``fail`` deducts 12 points; each ``warn`` deducts 4.
    Score is floored at 0.

    Grade bands
    -----------
    score >= 85  →  mukemmel
    score >= 65  →  iyi
    score >= 40  →  orta
    else         →  zayif

    Date window
    -----------
    Time-scoped checks (ads, tracking) use the last 30 days (UTC).

    Raises
    ------
    401 — if the JWT is missing or invalid.
    403 — if the tenant claim in the JWT does not match an active membership.
    """
    result = run_account_audit(db=db, tenant_id=membership.tenant_id)

    return AuditResponse(
        score=result["score"],
        grade=result["grade"],
        summary=result["summary"],
        counts=result["counts"],
        categories=[
            AuditCategory(
                key=cat["key"],
                label=cat["label"],
                checks=[CheckItem(**c) for c in cat["checks"]],
            )
            for cat in result["categories"]
        ],
    )
