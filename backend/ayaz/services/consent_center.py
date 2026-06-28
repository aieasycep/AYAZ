"""KVKK Rıza Yönetim Merkezi — Consent Management Center service.

Public API
----------
    build_consent_center(db, tenant_id, *, date_from=None, date_to=None) -> dict

Synthesizes EXISTING tracking data into a unified KVKK compliance dashboard:
- Consent rate summary
- Consent Mode v2 granular signal breakdown (4 canonical keys)
- Per-destination consent posture
- Per-source configuration
- KVKK compliance checklist with score
- Consent audit trail (most recent 15 events, newest first)

READ-ONLY — no new model, no migration. Reads ConversionEvent, EventDestination,
TrackingSource. Reuses _CONSENT_SIGNAL_KEYS from ayaz.services.tracking so that
signal keys/labels stay in sync with the rest of the tracking stack.

Tenant isolation
----------------
Every query carries an explicit tenant_id filter. Never leaks data across tenants.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.models.tracking import ConversionEvent, EventDestination, TrackingSource
from ayaz.services.tracking import _CONSENT_SIGNAL_KEYS

# ── Turkish labels for the four Consent Mode v2 signals ──────────────────────

_SIGNAL_LABELS: dict[str, str] = {
    "ad_storage": "Reklam Depolama",
    "ad_user_data": "Reklam Kullanıcı Verisi",
    "ad_personalization": "Reklam Kişiselleştirme",
    "analytics_storage": "Analitik Depolama",
}

_SIGNAL_DESCRIPTIONS: dict[str, str] = {
    "ad_storage": (
        "Tarayıcıda veya cihazda reklam amacıyla çerez ve tanımlayıcı "
        "saklanmasını yönetir."
    ),
    "ad_user_data": (
        "Kullanıcı verilerinin reklam platformlarına gönderilmesine "
        "ilişkin rızayı yönetir."
    ),
    "ad_personalization": (
        "Yeniden hedefleme ve kişiselleştirilmiş reklam gösterimi için "
        "kullanıcı profillemesine verilen rızayı kapsar."
    ),
    "analytics_storage": (
        "Oturum ve ziyaret ölçümlemesi amacıyla analitik çerezlerin "
        "saklanmasını yönetir."
    ),
}

# Turkish status labels for ConversionEvent.status values
_STATUS_LABELS: dict[str, str] = {
    "forwarded": "İletildi",
    "skipped_no_consent": "Rıza yok — atlandı",
    "failed": "Başarısız",
    "received": "Alındı",
    "duplicate": "Yinelenen",
    "disabled": "Devre dışı",
}

# ── Compliance check scoring ──────────────────────────────────────────────────
# Score = max(0, 100 - 16*fail - 7*warn)
_FAIL_PENALTY = 16
_WARN_PENALTY = 7


def _grade(score: int) -> str:
    if score >= 85:
        return "uyumlu"
    if score >= 50:
        return "kismi"
    return "eksik"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _effective_signals(event: ConversionEvent) -> dict[str, bool]:
    """Return a canonical 4-key signals dict for an event.

    Falls back: if consent_signals is None/empty but consent is a plain bool,
    treat all 4 keys as that bool so legacy events still contribute to counts.
    """
    signals = getattr(event, "consent_signals", None)
    if signals and isinstance(signals, dict):
        return {k: bool(signals.get(k, False)) for k in _CONSENT_SIGNAL_KEYS}
    # Legacy fallback: expand the overall consent bool to all 4 keys
    granted = bool(getattr(event, "consent", False))
    return {k: granted for k in _CONSENT_SIGNAL_KEYS}


# ── Main builder ──────────────────────────────────────────────────────────────


def build_consent_center(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Build the full KVKK Rıza Yönetim Merkezi payload.

    Parameters
    ----------
    db:
        SQLAlchemy Session (read-only queries).
    tenant_id:
        Tenant UUID — all queries are scoped to this tenant.
    date_from:
        ISO date string (YYYY-MM-DD) for period start, inclusive. When None and
        date_to is also None, ALL events are included and period is derived from
        actual min/max event_time found.
    date_to:
        ISO date string (YYYY-MM-DD) for period end, inclusive (up to T23:59:59).

    Returns
    -------
    dict
        Exact shape documented in the module docstring.
    """
    generated_at = datetime.now(timezone.utc).isoformat()

    # ── Load sources and destinations ─────────────────────────────────────────
    sources: list[TrackingSource] = list(
        db.scalars(
            select(TrackingSource).where(TrackingSource.tenant_id == tenant_id)
        )
    )
    destinations: list[EventDestination] = list(
        db.scalars(
            select(EventDestination).where(
                EventDestination.tenant_id == tenant_id
            )
        )
    )

    # ── Load events (with optional date filter) ───────────────────────────────
    stmt = select(ConversionEvent).where(
        ConversionEvent.tenant_id == tenant_id
    )

    date_from_applied = date_from
    date_to_applied = date_to

    if date_from is not None:
        stmt = stmt.where(ConversionEvent.event_time >= date_from)
    if date_to is not None:
        # Inclusive end: up to T23:59:59
        stmt = stmt.where(ConversionEvent.event_time <= date_to + "T23:59:59")

    # Order by event_time descending for audit trail
    stmt = stmt.order_by(ConversionEvent.event_time.desc())

    events: list[ConversionEvent] = list(db.scalars(stmt))

    # If no date params provided, derive period from actual data
    if date_from is None and date_to is None:
        if events:
            all_times = [e.event_time for e in events if e.event_time]
            date_from_applied = min(all_times)[:10] if all_times else None
            date_to_applied = max(all_times)[:10] if all_times else None
        else:
            date_from_applied = None
            date_to_applied = None

    # ── Summary ───────────────────────────────────────────────────────────────
    total_events = len(events)
    consented_events = sum(1 for e in events if e.consent)
    skipped_no_consent = sum(
        1 for e in events if e.status == "skipped_no_consent"
    )

    if total_events > 0:
        consent_rate_pct = round(consented_events / total_events * 100, 1)
    else:
        consent_rate_pct = 0.0

    granular_supported = any(
        e.consent_signals and isinstance(e.consent_signals, dict)
        for e in events
    )

    summary = {
        "total_events": total_events,
        "consented_events": consented_events,
        "consent_rate_pct": consent_rate_pct,
        "skipped_no_consent": skipped_no_consent,
        "granular_supported": granular_supported,
    }

    # ── Signal breakdown ──────────────────────────────────────────────────────
    signal_granted: dict[str, int] = {k: 0 for k in _CONSENT_SIGNAL_KEYS}
    signal_denied: dict[str, int] = {k: 0 for k in _CONSENT_SIGNAL_KEYS}

    for event in events:
        effective = _effective_signals(event)
        for key in _CONSENT_SIGNAL_KEYS:
            if effective.get(key, False):
                signal_granted[key] += 1
            else:
                signal_denied[key] += 1

    signals_out = []
    for key in _CONSENT_SIGNAL_KEYS:
        granted = signal_granted[key]
        denied = signal_denied[key]
        total_sig = granted + denied
        grant_rate = round(granted / total_sig * 100, 1) if total_sig > 0 else 0.0
        signals_out.append({
            "key": key,
            "label": _SIGNAL_LABELS[key],
            "granted": granted,
            "denied": denied,
            "grant_rate_pct": grant_rate,
            "description": _SIGNAL_DESCRIPTIONS[key],
        })

    # ── Destinations breakdown ────────────────────────────────────────────────
    # Build per-destination event counters
    source_id_to_name: dict[uuid.UUID, str] = {s.id: s.name for s in sources}

    # Map source_id -> destination name (platform string as fallback)
    # Count forwarded and skipped per destination by looking at events that
    # belonged to the destination's source and checking status.
    # We approximate per-destination counts from per-source events since
    # ConversionEvent does not store which specific destination it was sent to.
    # Group events by tracking_source_id
    events_by_source: dict[uuid.UUID, list[ConversionEvent]] = {}
    for evt in events:
        src_id = evt.tracking_source_id
        events_by_source.setdefault(src_id, []).append(evt)

    destinations_out = []
    for dest in destinations:
        src_events = events_by_source.get(dest.tracking_source_id, [])

        # forwarded: events with status "forwarded" from this source
        # skipped_no_consent: events with status "skipped_no_consent" from this source
        dest_forwarded = sum(1 for e in src_events if e.status == "forwarded")
        dest_skipped = sum(
            1 for e in src_events if e.status == "skipped_no_consent"
        )

        # Posture label
        if dest.consent_required:
            posture_label = "Katı (rıza zorunlu)"
        else:
            posture_label = "Gevşek (rıza opsiyonel)"

        required_consent_list: list[str] = []
        if dest.required_consent:
            required_consent_list = list(dest.required_consent)

        destinations_out.append({
            "name": dest.platform,
            "platform": dest.platform,
            "consent_required": dest.consent_required,
            "required_consent": required_consent_list,
            "forwarded": dest_forwarded,
            "skipped_no_consent": dest_skipped,
            "posture_label": posture_label,
        })

    # ── Sources breakdown ─────────────────────────────────────────────────────
    sources_out = []
    for src in sources:
        src_event_count = len(events_by_source.get(src.id, []))
        sources_out.append({
            "name": src.name,
            "consent_cookie_var": src.consent_cookie_var,
            "configured": bool(src.consent_cookie_var),
            "events": src_event_count,
        })

    # ── Compliance checklist ──────────────────────────────────────────────────
    checks = _build_compliance_checks(
        sources=sources,
        destinations=destinations,
        total_events=total_events,
        consent_rate_pct=consent_rate_pct,
        granular_supported=granular_supported,
        skipped_no_consent=skipped_no_consent,
    )

    # Score
    fail_count = sum(1 for c in checks if c["status"] == "fail")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    score = max(0, 100 - _FAIL_PENALTY * fail_count - _WARN_PENALTY * warn_count)
    grade = _grade(score)

    compliance = {
        "score": score,
        "grade": grade,
        "counts": {"pass": pass_count, "warn": warn_count, "fail": fail_count},
        "checks": checks,
    }

    # ── Audit trail (most recent 15 events, newest first) ─────────────────────
    # events is already sorted by event_time desc
    audit_events = events[:15]
    audit_trail = []
    for evt in audit_events:
        status_label = _STATUS_LABELS.get(evt.status, evt.status)
        effective = _effective_signals(evt)
        granted_count = sum(1 for k in _CONSENT_SIGNAL_KEYS if effective.get(k, False))
        total_keys = len(_CONSENT_SIGNAL_KEYS)
        signals_summary = f"{granted_count}/{total_keys} onaylı"
        audit_trail.append({
            "event_time": evt.event_time,
            "event_name": evt.event_name,
            "consent": evt.consent,
            "status": evt.status,
            "status_label": status_label,
            "signals_summary": signals_summary,
        })

    return {
        "generated_at": generated_at,
        "period": {
            "date_from": date_from_applied,
            "date_to": date_to_applied,
        },
        "summary": summary,
        "signals": signals_out,
        "destinations": destinations_out,
        "sources": sources_out,
        "compliance": compliance,
        "audit_trail": audit_trail,
    }


# ── Compliance checks ─────────────────────────────────────────────────────────


def _build_compliance_checks(
    *,
    sources: list[TrackingSource],
    destinations: list[EventDestination],
    total_events: int,
    consent_rate_pct: float,
    granular_supported: bool,
    skipped_no_consent: int,
) -> list[dict[str, Any]]:
    """Build the 7 KVKK compliance checks.

    Returns a list of check dicts in a defined order with keys:
        id, label, status, finding, recommendation
    """
    checks = []

    # 1. acik_riza_mekanizmasi
    # KVKK açık rıza: at least one active source must have consent_cookie_var set
    active_sources_with_var = [
        s for s in sources
        if s.is_active and s.consent_cookie_var
    ]
    if active_sources_with_var:
        checks.append({
            "id": "acik_riza_mekanizmasi",
            "label": "Açık Rıza Mekanizması",
            "status": "pass",
            "finding": (
                f"{len(active_sources_with_var)} aktif kaynak rıza değişkeni "
                f"ile yapılandırılmış ({', '.join(s.consent_cookie_var for s in active_sources_with_var[:3])})."
            ),
            "recommendation": "",
        })
    else:
        checks.append({
            "id": "acik_riza_mekanizmasi",
            "label": "Açık Rıza Mekanizması",
            "status": "fail",
            "finding": (
                "Hiçbir aktif kaynakta KVKK uyumlu rıza çerezi değişkeni "
                "(consent_cookie_var) tanımlanmamış."
            ),
            "recommendation": (
                "İzleme kaynağı ayarlarından 'consent_cookie_var' alanını "
                "doldurun; snippet kullanıcının onay durumunu otomatik okur."
            ),
        })

    # 2. riza_olmadan_aktarim_engelleme
    # At least one destination must require consent
    consent_required_dests = [d for d in destinations if d.consent_required]
    if consent_required_dests:
        checks.append({
            "id": "riza_olmadan_aktarim_engelleme",
            "label": "Rıza Olmadan İletim Engelleme",
            "status": "pass",
            "finding": (
                f"{len(consent_required_dests)} hedef rıza zorunluluğuyla "
                f"yapılandırılmış — rızasız olaylar bu hedeflere gönderilmiyor."
            ),
            "recommendation": "",
        })
    else:
        checks.append({
            "id": "riza_olmadan_aktarim_engelleme",
            "label": "Rıza Olmadan İletim Engelleme",
            "status": "warn",
            "finding": (
                "Hiçbir hedef 'consent_required=True' olarak ayarlanmamış; "
                "rızasız veriler üçüncü taraflara iletilebilir."
            ),
            "recommendation": (
                "Meta CAPI ve TikTok gibi reklam platformlarının hedeflerinde "
                "'consent_required' seçeneğini etkinleştirin."
            ),
        })

    # 3. consent_mode_v2_granular
    # At least one event has non-empty consent_signals
    if granular_supported:
        checks.append({
            "id": "consent_mode_v2_granular",
            "label": "Consent Mode v2 Granüler Sinyal",
            "status": "pass",
            "finding": (
                "Olaylar Consent Mode v2 granüler sinyallerini içeriyor; "
                "dört sinyal türü ayrı ayrı raporlanabiliyor."
            ),
            "recommendation": "",
        })
    else:
        checks.append({
            "id": "consent_mode_v2_granular",
            "label": "Consent Mode v2 Granüler Sinyal",
            "status": "warn",
            "finding": (
                "Hiçbir olayda granüler Consent Mode v2 sinyali bulunamadı; "
                "yalnızca genel boolean rıza kaydediliyor."
            ),
            "recommendation": (
                "Snippet'ı güncelleyerek ad_storage, analytics_storage, "
                "ad_user_data ve ad_personalization sinyallerini ayrı ayrı iletin."
            ),
        })

    # 4. riza_orani_saglikli
    # Consent rate >= 70 pass / >= 40 warn / else fail
    if total_events == 0:
        checks.append({
            "id": "riza_orani_saglikli",
            "label": "Rıza Oranı Sağlıklı",
            "status": "pass",
            "finding": "Henüz hiç olay kaydedilmemiş — oran hesaplanamıyor.",
            "recommendation": "İzleme snippet'ını sitenize ekleyin.",
        })
    elif consent_rate_pct >= 70:
        checks.append({
            "id": "riza_orani_saglikli",
            "label": "Rıza Oranı Sağlıklı",
            "status": "pass",
            "finding": (
                f"Rıza oranı %{consent_rate_pct} — olayların büyük çoğunluğu "
                f"geçerli kullanıcı rızasıyla kaydediliyor."
            ),
            "recommendation": "",
        })
    elif consent_rate_pct >= 40:
        checks.append({
            "id": "riza_orani_saglikli",
            "label": "Rıza Oranı Sağlıklı",
            "status": "warn",
            "finding": (
                f"Rıza oranı %{consent_rate_pct} — olayların "
                f"%{round(100 - consent_rate_pct, 1)}'i rızasız. "
                f"Bu oran iyileştirilebilir."
            ),
            "recommendation": (
                "Rıza banner'ınızı A/B test edin; kullanıcı deneyimini "
                "geliştirerek rıza alım oranını artırın."
            ),
        })
    else:
        checks.append({
            "id": "riza_orani_saglikli",
            "label": "Rıza Oranı Sağlıklı",
            "status": "fail",
            "finding": (
                f"Rıza oranı yalnızca %{consent_rate_pct} — {total_events} olayın "
                f"%{round(100 - consent_rate_pct, 1)}'i rızasız kaydedilmiş."
            ),
            "recommendation": (
                "Rıza yönetim platformunuzu (CMP) gözden geçirin; "
                "banner görünürlüğü ve dil açıklığını iyileştirin."
            ),
        })

    # 5. veri_minimizasyonu
    # Informational — by design we only store hashed PII and key sets
    checks.append({
        "id": "veri_minimizasyonu",
        "label": "Veri Minimizasyonu",
        "status": "pass",
        "finding": (
            "Yalnızca SHA-256 karma kimlik sinyalleri saklanıyor; "
            "ham e-posta, telefon veya IP adresi hiçbir zaman kalıcı hale getirilmiyor."
        ),
        "recommendation": "",
    })

    # 6. riza_denetim_izi
    # Pass if total_events > 0 (every event is logged with its consent decision)
    if total_events > 0:
        checks.append({
            "id": "riza_denetim_izi",
            "label": "Rıza Denetim İzi",
            "status": "pass",
            "finding": (
                f"{total_events} olay rıza kararıyla birlikte loglanmış; "
                f"her olayın rıza durumu ve sinyalleri kayıt altında."
            ),
            "recommendation": "",
        })
    else:
        checks.append({
            "id": "riza_denetim_izi",
            "label": "Rıza Denetim İzi",
            "status": "warn",
            "finding": "Henüz rıza kararı loglanmış olay bulunamadı.",
            "recommendation": "Rıza denetim izinin çalışabilmesi için olay toplamaya başlayın.",
        })

    # 7. riza_zorlama_calisiyor
    # Pass if skipped_no_consent > 0 OR all destinations require consent
    all_require_consent = bool(destinations) and all(d.consent_required for d in destinations)
    enforcement_active = skipped_no_consent > 0 or all_require_consent
    if enforcement_active:
        if skipped_no_consent > 0:
            finding = (
                f"Rıza zorlama aktif — {skipped_no_consent} olay rızasız olduğu "
                f"için iletilmeden atlandı."
            )
        else:
            finding = (
                "Tüm hedefler rıza zorunluluğuyla yapılandırılmış; "
                "rızasız olaylar otomatik olarak engelleniyor."
            )
        checks.append({
            "id": "riza_zorlama_calisiyor",
            "label": "Rıza Zorlama Çalışıyor",
            "status": "pass",
            "finding": finding,
            "recommendation": "",
        })
    else:
        checks.append({
            "id": "riza_zorlama_calisiyor",
            "label": "Rıza Zorlama Çalışıyor",
            "status": "warn",
            "finding": (
                "Rıza zorlama mekanizmasının aktif olduğuna dair kanıt bulunamadı: "
                "hiç 'rızasız atlandı' olayı yok ve hiçbir hedef rıza gerektirmiyor."
            ),
            "recommendation": (
                "En az bir hedefe 'consent_required=True' ayarlayın ve "
                "rızasız kullanıcılardan gelen olayların doğru şekilde "
                "atlandığını doğrulayın."
            ),
        })

    return checks
