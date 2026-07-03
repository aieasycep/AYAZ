"""Kullanım Kalkanı (Usage Shield) servisi — sürpriz fatura önleme.

Bu servis, her kiracı için plan limitlerini gerçek zamanlı kullanımla
karşılaştırır ve üç tür uyarı üretir:

1. ``approaching_limit``  — kullanım ≥ %80 (yaklaşan limit)
2. ``at_limit``           — kullanım ≥ %100 (limitin dolması)
3. ``idle_connectors``    — N günden uzun süredir senkronize olmayan veya
                            hata durumundaki bağlantılar boş slot tüketiyor

Bildirimler Notification tablosuna yazılır (``source_ref`` tekilleştirmesi
ile spam engellenir).  ``check_and_notify`` fonksiyonu idempotent olacak
biçimde tasarlanmıştır: Celery beat'ten veya doğrudan API'den çağrılabilir.

Kiracı izolasyonu
-----------------
Her sorgu açıkça ``tenant_id`` filtresi içerir.

Bildirim anahtarları (source_ref)
----------------------------------
``"shield:approaching_limit:<tenant_id>"``
``"shield:at_limit:<tenant_id>"``
``"shield:idle_connector:<account_id>"``

Aynı anahtar için bir bildirim ancak ``NOTIFY_WINDOW_HOURS`` saat geçtikten
sonra yeniden oluşturulur (spam-guard penceresi).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ayaz.models.notifications import Notification
from ayaz.services.trformat import tr_pct
from ayaz.models.oltp import ConnectedAccount, SyncStatus
from ayaz.services.billing import PLANS, entitlements

# ── Yapılandırma sabitleri ─────────────────────────────────────────────────────

# Bir konektörün son senkronizasyonundan bu yana geçmesi gereken gün sayısı
# (bu eşiği geçerse "atıl" sayılır).
IDLE_THRESHOLD_DAYS: int = 3

# Bildirim spam koruması: bir kaynaktan gelen bildirim bu kadar saat sonra
# yeniden üretilebilir.
NOTIFY_WINDOW_HOURS: int = 24

# Yaklaşan limit eşiği (yüzde).
APPROACHING_THRESHOLD_PCT: float = 80.0


# ── Veri yapıları ─────────────────────────────────────────────────────────────


@dataclass
class ConnectorInfo:
    """Atıl konektör bilgisi — shield paneli yanıtında kullanılır."""

    account_id: uuid.UUID
    platform: str
    display_name: str
    sync_status: str
    last_synced_at: str | None  # ISO-8601 ya da None
    reason: str  # "idle" | "error"


@dataclass
class ShieldReport:
    """Tek kiracı için kullanım kalkanı raporu."""

    tenant_id: uuid.UUID
    plan_code: str
    plan_name: str

    # Veri kaynağı kullanımı
    data_sources_used: int
    data_sources_max: int | str  # int veya "unlimited"
    data_sources_pct: float | None  # None if unlimited

    # Durum bayrakları
    approaching_limit: bool
    at_limit: bool

    # Atıl konektörler
    idle_connectors: list[ConnectorInfo] = field(default_factory=list)

    # Aktif uyarılar (bildirilen)
    active_warnings: list[str] = field(default_factory=list)


# ── İçsel yardımcılar ─────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _recent_notif_exists(
    db: Session,
    tenant_id: uuid.UUID,
    source_ref: str,
    window_hours: int = NOTIFY_WINDOW_HOURS,
) -> bool:
    """Belirtilen source_ref ile son ``window_hours`` içinde bildirim oluşturulduysa True döner."""
    cutoff = _utcnow() - timedelta(hours=window_hours)
    result = db.scalar(
        select(func.count(Notification.id)).where(
            Notification.tenant_id == tenant_id,
            Notification.source_ref == source_ref,
            Notification.created_at >= cutoff,
        )
    )
    return bool(result and result > 0)


def _create_notif(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    type_: str,
    severity: str,
    title: str,
    body: str,
    link: str,
    source_ref: str,
) -> Notification:
    """Notification kaydı oluşturur (flush eder, commit etmez)."""
    notif = Notification(
        tenant_id=tenant_id,
        type=type_,
        severity=severity,
        title=title,
        body=body,
        link=link,
        source_ref=source_ref,
    )
    db.add(notif)
    db.flush()
    return notif


# ── Ana servis fonksiyonları ──────────────────────────────────────────────────


def compute_shield(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    idle_threshold_days: int = IDLE_THRESHOLD_DAYS,
) -> ShieldReport:
    """Kiracı için kullanım kalkanı raporunu hesaplar (yazmaz).

    Bu fonksiyon salt okunurdur; DB'ye herhangi bir kayıt yazmaz.

    Parameters
    ----------
    db:
        SQLAlchemy Session (salt okunur).
    tenant_id:
        Kiracı UUID.
    idle_threshold_days:
        Son senkronizasyondan bu yana kaç gün geçmişse atıl sayılır.

    Returns
    -------
    ShieldReport
        Hesaplanan kullanım ve uyarı raporu.
    """
    ents = entitlements(db, tenant_id)
    plan_code = ents["plan_code"]
    plan_name = ents["plan_name"]
    max_ds: int | str = ents["limits"].get("max_data_sources", 1)

    # Mevcut veri kaynağı sayısı
    used: int = db.scalar(
        select(func.count()).where(ConnectedAccount.tenant_id == tenant_id)
    ) or 0

    # Yüzde hesabı (unlimited ise None)
    if max_ds == "unlimited":
        pct: float | None = None
        approaching = False
        at_lim = False
    else:
        max_int = int(max_ds)
        pct = (used / max_int * 100.0) if max_int > 0 else 100.0
        approaching = pct >= APPROACHING_THRESHOLD_PCT
        at_lim = used >= max_int

    # Atıl konektörleri tespit et
    idle_connectors: list[ConnectorInfo] = []
    now = _utcnow()
    stale_cutoff = now - timedelta(days=idle_threshold_days)

    all_accounts = db.scalars(
        select(ConnectedAccount).where(ConnectedAccount.tenant_id == tenant_id)
    ).all()

    for acct in all_accounts:
        reason: str | None = None

        if acct.sync_status == SyncStatus.error:
            reason = "error"
        elif acct.sync_status == SyncStatus.paused:
            # Paused = aktif olmayan ama bu bir hata değil, yine de boş slot
            reason = "idle"
        elif acct.watermark:
            # watermark = son başarılı senkronizasyonun ISO-8601 zamanı
            try:
                wm_dt = datetime.fromisoformat(acct.watermark)
                if wm_dt.tzinfo is None:
                    wm_dt = wm_dt.replace(tzinfo=timezone.utc)
                if wm_dt < stale_cutoff:
                    reason = "idle"
            except ValueError:
                pass  # Geçersiz watermark — atla
        elif acct.watermark is None and acct.sync_status not in (
            SyncStatus.syncing,
            SyncStatus.success,
        ):
            # Hiç senkronize olmamış ve aktif değil
            reason = "idle"

        if reason:
            idle_connectors.append(
                ConnectorInfo(
                    account_id=acct.id,
                    platform=acct.platform.value if hasattr(acct.platform, "value") else str(acct.platform),
                    display_name=acct.display_name,
                    sync_status=acct.sync_status.value if hasattr(acct.sync_status, "value") else str(acct.sync_status),
                    last_synced_at=acct.watermark,
                    reason=reason,
                )
            )

    # Aktif uyarı listesi (raporda görüntülenecek)
    warnings: list[str] = []
    if at_lim:
        warnings.append("at_limit")
    elif approaching:
        warnings.append("approaching_limit")
    if idle_connectors:
        warnings.append("idle_connectors")

    return ShieldReport(
        tenant_id=tenant_id,
        plan_code=plan_code,
        plan_name=plan_name,
        data_sources_used=used,
        data_sources_max=max_ds,
        data_sources_pct=pct,
        approaching_limit=approaching,
        at_limit=at_lim,
        idle_connectors=idle_connectors,
        active_warnings=warnings,
    )


def check_and_notify(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    idle_threshold_days: int = IDLE_THRESHOLD_DAYS,
    notify_window_hours: int = NOTIFY_WINDOW_HOURS,
) -> dict[str, Any]:
    """Kullanım kalkanını hesaplar ve gerekli bildirimleri oluşturur.

    İdempotent: aynı kiracı için ``notify_window_hours`` içinde aynı bildirim
    tekrar oluşturulmaz.

    Parameters
    ----------
    db:
        SQLAlchemy Session (yazma yetkisi gerekli).
    tenant_id:
        Kiracı UUID.
    idle_threshold_days:
        Atıl konektör eşiği (gün).
    notify_window_hours:
        Spam koruma penceresi (saat).

    Returns
    -------
    dict
        ``{"notifications_created": int, "report": ShieldReport}``
    """
    report = compute_shield(db, tenant_id, idle_threshold_days=idle_threshold_days)
    created = 0

    # ── Yaklaşan limit bildirimi ───────────────────────────────────────────────
    if report.approaching_limit and not report.at_limit:
        ref = f"shield:approaching_limit:{tenant_id}"
        if not _recent_notif_exists(db, tenant_id, ref, notify_window_hours):
            used = report.data_sources_used
            mx = report.data_sources_max
            pct_str = tr_pct(report.data_sources_pct, 0) if report.data_sources_pct is not None else ""
            _create_notif(
                db,
                tenant_id=tenant_id,
                type_="system",
                severity="warning",
                title="Plan limitine yaklaşıyorsunuz",
                body=(
                    f"Veri kaynağı limitinizin {pct_str}'ine ulaştınız "
                    f"({used}/{mx} kaynak kullanımda). "
                    "Limiti aşmadan önce planınızı yükseltmeyi düşünebilirsiniz."
                ),
                link="/billing",
                source_ref=ref,
            )
            created += 1

    # ── Limit doldu bildirimi ─────────────────────────────────────────────────
    if report.at_limit:
        ref = f"shield:at_limit:{tenant_id}"
        if not _recent_notif_exists(db, tenant_id, ref, notify_window_hours):
            used = report.data_sources_used
            mx = report.data_sources_max
            _create_notif(
                db,
                tenant_id=tenant_id,
                type_="system",
                severity="critical",
                title="Veri kaynağı limitiniz doldu",
                body=(
                    f"Plan limitinize ulaştınız ({used}/{mx} kaynak). "
                    "Yeni veri kaynağı ekleyemezsiniz. "
                    "Hizmet kesintisini önlemek için lütfen planınızı yükseltin."
                ),
                link="/billing",
                source_ref=ref,
            )
            created += 1

    # ── Atıl konektör bildirimleri ─────────────────────────────────────────────
    for conn in report.idle_connectors:
        ref = f"shield:idle_connector:{conn.account_id}"
        if not _recent_notif_exists(db, tenant_id, ref, notify_window_hours):
            if conn.reason == "error":
                severity = "critical"
                title = f"Bağlantı hatası: {conn.display_name or conn.platform}"
                body = (
                    f"'{conn.display_name or conn.platform}' bağlantısı hata "
                    f"durumunda ve plan limitinizden bir slot kullanıyor. "
                    "Lütfen bağlantıyı kontrol edin veya kaldırın."
                )
            else:
                severity = "warning"
                days_info = f"{idle_threshold_days}+ gün" if idle_threshold_days else "uzun süre"
                title = f"Atıl konektör: {conn.display_name or conn.platform}"
                body = (
                    f"'{conn.display_name or conn.platform}' bağlantısı "
                    f"{days_info}dır senkronize olmadı "
                    f"(son sync: {conn.last_synced_at or 'hiç'}) "
                    "ama plan limitinizden bir slot tüketiyor. "
                    "Kullanmıyorsanız kaldırmayı düşünebilirsiniz."
                )
            _create_notif(
                db,
                tenant_id=tenant_id,
                type_="system",
                severity=severity,
                title=title,
                body=body,
                link="/connectors",
                source_ref=ref,
            )
            created += 1

    if created:
        db.commit()

    return {"notifications_created": created, "report": report}
