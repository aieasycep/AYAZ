"""Notification delivery — M4 Alert engine.

Architecture
------------
``Notifier`` is the abstract base for all delivery channels.  Two stub
implementations are provided:

``EmailNotifier``
    Logs the payload; real SMTP/SendGrid sending is deferred until credentials
    are provisioned.  No network calls are made.

``SlackNotifier``
    Logs the payload; real Slack webhook posting is deferred.  No network calls
    are made.

Public entry point
------------------
    deliver_new_critical(db, tenant_id)

Queries for all ``Insight`` rows with status="new" and severity="critical" for
the tenant, then looks up active ``AlertRule`` rows that match the insight's
metric and channel.  Routes each matched insight to the appropriate notifier.

Idempotency
-----------
Insights are marked ``status="seen"`` after a successful delivery attempt so
they are not delivered again on the next call.  (A delivered-but-not-yet-seen
insight remains "seen" — dashboard users can still dismiss it.)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ayaz.models.insights import AlertRule, Insight

logger = logging.getLogger(__name__)


# ── Notifier interface ────────────────────────────────────────────────────────


class Notifier(ABC):
    """Abstract delivery channel.

    Concrete implementations must override :meth:`deliver`.
    """

    @abstractmethod
    def deliver(self, destination: str, insight: Insight, rule: AlertRule) -> None:
        """Deliver a notification for ``insight`` to ``destination``.

        Parameters
        ----------
        destination:
            Channel-specific address: email address for :class:`EmailNotifier`,
            Slack webhook URL for :class:`SlackNotifier`.
        insight:
            The Insight row to notify about.
        rule:
            The matching AlertRule that triggered this delivery.
        """


# ── Email stub ────────────────────────────────────────────────────────────────


class EmailNotifier(Notifier):
    """Stub email notifier — logs payload; no real SMTP.

    Production implementation will integrate with SendGrid or SMTP relay.
    Replace this class body with the real implementation in Faz 2.
    """

    def deliver(self, destination: str, insight: Insight, rule: AlertRule) -> None:
        """Log the email payload (stub — no real sending)."""
        logger.info(
            "[EmailNotifier] STUB — would send email to %s\n"
            "  Subject : [AYAZ] %s\n"
            "  Body    : %s\n"
            "  Rule    : %s (id=%s)\n"
            "  Insight : id=%s severity=%s category=%s period=%s→%s",
            destination,
            insight.title,
            insight.body,
            rule.name,
            rule.id,
            insight.id,
            insight.severity,
            insight.category,
            insight.period_start,
            insight.period_end,
        )


# ── Slack stub ────────────────────────────────────────────────────────────────


class SlackNotifier(Notifier):
    """Stub Slack notifier — logs payload; no real HTTP POST.

    Production implementation will POST to the Slack webhook URL stored in
    ``rule.destination``.  Replace this class body in Faz 2.
    """

    def deliver(self, destination: str, insight: Insight, rule: AlertRule) -> None:
        """Log the Slack message payload (stub — no real sending)."""
        severity_emoji = {
            "info": ":information_source:",
            "warning": ":warning:",
            "critical": ":rotating_light:",
        }.get(insight.severity, ":bell:")

        slack_text = (
            f"{severity_emoji} *{insight.title}*\n"
            f"{insight.body}\n"
            f"_Dönem: {insight.period_start} → {insight.period_end} | "
            f"Kanal: {insight.channel or 'tüm kanallar'}_"
        )

        logger.info(
            "[SlackNotifier] STUB — would POST to webhook %s\n"
            "  Payload : %s\n"
            "  Rule    : %s (id=%s)",
            destination,
            slack_text,
            rule.name,
            rule.id,
        )


# ── Notifier factory ──────────────────────────────────────────────────────────


def _get_notifier(delivery: str) -> Notifier | None:
    """Return the appropriate Notifier for the given ``delivery`` string.

    Returns ``None`` for delivery == "none" (record-only rules).
    """
    if delivery == "email":
        return EmailNotifier()
    if delivery == "slack":
        return SlackNotifier()
    return None  # "none" — no external delivery


# ── Rule matching ─────────────────────────────────────────────────────────────


def _rule_matches(rule: AlertRule, insight: Insight) -> bool:
    """Return True if ``rule`` matches ``insight``.

    Matching logic:
    - rule.metric must equal insight.metric.
    - rule.channel_filter (if set) must equal insight.channel.
    - rule.delivery must not be "none" (no-op rules are skipped in delivery).
    - rule.is_active must be True.
    """
    if not rule.is_active:
        return False
    if rule.metric != insight.metric:
        return False
    if rule.delivery == "none":
        return False
    if rule.channel_filter is not None and rule.channel_filter != insight.channel:
        return False
    return True


# ── Public entry point ────────────────────────────────────────────────────────


def deliver_new_critical(
    db: Session,
    tenant_id: Any,
) -> dict[str, int]:
    """Route new critical Insights to active AlertRule destinations.

    Steps
    -----
    1. Load all ``Insight`` rows with status="new", severity="critical" for the
       tenant (ordered by score descending so the highest-priority insight
       is delivered first if there are ordering constraints downstream).
    2. Load all active ``AlertRule`` rows for the tenant that have delivery
       != "none".
    3. For each insight, find all matching rules.
    4. Deliver via the appropriate notifier.
    5. Mark the insight status="seen" after at least one delivery attempt.
    6. Flush (caller is responsible for commit).

    Parameters
    ----------
    db:
        SQLAlchemy Session (write access required).
    tenant_id:
        Tenant UUID — every query is scoped to this.

    Returns
    -------
    dict with ``delivered`` (number of insight×rule delivery actions taken)
    and ``insights_notified`` (number of distinct insights touched).
    """
    # 1. New critical insights
    critical_insights = db.scalars(
        select(Insight)
        .where(
            Insight.tenant_id == tenant_id,
            Insight.status == "new",
            Insight.severity == "critical",
        )
        .order_by(Insight.score.desc())
    ).all()

    if not critical_insights:
        return {"delivered": 0, "insights_notified": 0}

    # 2. Active alert rules with a real delivery target
    active_rules = db.scalars(
        select(AlertRule).where(
            AlertRule.tenant_id == tenant_id,
            AlertRule.is_active.is_(True),
            AlertRule.delivery != "none",
        )
    ).all()

    delivered = 0
    insights_notified = 0

    for insight in critical_insights:
        matched = False

        for rule in active_rules:
            if not _rule_matches(rule, insight):
                continue

            destination = rule.destination or ""
            if not destination:
                logger.warning(
                    "[notifications] Rule %s has delivery=%s but no destination",
                    rule.id,
                    rule.delivery,
                )
                continue

            notifier = _get_notifier(rule.delivery)
            if notifier is None:
                continue

            try:
                notifier.deliver(destination, insight, rule)
                delivered += 1
                matched = True
            except Exception:
                logger.exception(
                    "[notifications] Delivery failed: insight=%s rule=%s",
                    insight.id,
                    rule.id,
                )

        # Mark as seen even if no rule matched (so it isn't re-queued forever)
        if critical_insights:
            insight.status = "seen"
            insights_notified += 1

    db.flush()

    logger.info(
        "[notifications] Done: delivered=%d insights_notified=%d",
        delivered,
        insights_notified,
    )
    return {"delivered": delivered, "insights_notified": insights_notified}
