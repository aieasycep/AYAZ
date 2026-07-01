"""Slack integration adapter — action-only (send messages to channels)."""

from __future__ import annotations

from ayaz.integrations.base import (
    ActionContext,
    ActionSpec,
    AuthType,
    Capability,
    Integration,
    IntegrationMetadata,
)


class SlackIntegration(Integration):
    """Slack integration — sends messages to channels via the Slack Web API."""

    metadata = IntegrationMetadata(
        key="slack",
        display_name="Slack",
        category="messaging",
        description_tr="Performans uyarılarını ve raporları Slack kanalına gönderin.",
        auth_type=AuthType.oauth2,
        provider="slack",
        oauth_scopes=("chat:write", "channels:read"),
        capabilities=(Capability.action,),
        icon="#",
        icon_bg="#4A154B",
        aliases=("bildirim", "mesaj", "uyarı kanalı", "kanal"),
        min_plan="growth",
    )

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="slack_send_message",
                description_tr=(
                    "[EYLEM] Belirtilen Slack kanalına mesaj gönderir. "
                    "Kullanıcı 'Slack'e gönder/bildir/uyar' dediğinde kullan."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "channel": {
                            "type": "string",
                            "description": "Kanal adı, ör. #pazarlama veya #genel",
                        },
                        "text": {
                            "type": "string",
                            "description": "Gönderilecek mesaj metni",
                        },
                    },
                    "required": ["channel", "text"],
                },
                is_write=True,
                required_scopes=("chat:write",),
            )
        ]

    def execute_action(self, name: str, args: dict, *, ctx: ActionContext) -> dict:
        if name != "slack_send_message":
            raise NotImplementedError(f"Unknown action: {name!r}")

        import httpx

        tokens = ctx.vault_get()
        access_token = tokens.get("access_token", "")
        channel = args["channel"]
        text = args["text"]

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"channel": channel, "text": text},
            )

        resp.raise_for_status()
        data = resp.json()

        if not data.get("ok"):
            error = data.get("error", "unknown_error")
            ctx.audit(name, args, {"error": error}, "error")
            return {"ok": False, "error": error}

        ctx.audit(name, args, {"ok": True, "channel": channel}, "ok")
        return {"ok": True, "channel": channel, "ts": data.get("ts")}
