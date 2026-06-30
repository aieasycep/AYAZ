"""Gmail integration adapter — send emails via the Gmail API."""

from __future__ import annotations

from ayaz.integrations.base import (
    ActionContext,
    ActionSpec,
    AuthType,
    Capability,
    Integration,
    IntegrationMetadata,
)


class GmailIntegration(Integration):
    """Gmail integration — send emails via the Gmail API."""

    metadata = IntegrationMetadata(
        key="gmail",
        display_name="Gmail",
        category="messaging",
        description_tr="Rapor ve uyarıları Gmail ile e-posta olarak gönderin.",
        auth_type=AuthType.oauth2_bundle,
        provider="google_workspace",
        oauth_scopes=("https://mail.google.com/",),
        capabilities=(Capability.action,),
        icon="M",
        icon_bg="#EA4335",
        aliases=("e-posta", "email", "mail", "gmail"),
        min_plan="starter",
    )

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="gmail_send_email",
                description_tr=(
                    "[EYLEM] Gmail üzerinden e-posta gönderir. "
                    "Kullanıcı 'e-posta gönder/mail at' dediğinde kullan."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Alıcı e-posta adresi",
                        },
                        "subject": {
                            "type": "string",
                            "description": "E-posta konusu",
                        },
                        "body": {
                            "type": "string",
                            "description": "E-posta içeriği (düz metin)",
                        },
                    },
                    "required": ["to", "subject", "body"],
                },
                is_write=True,
                required_scopes=("https://mail.google.com/",),
            )
        ]

    def execute_action(self, name: str, args: dict, *, ctx: ActionContext) -> dict:
        if name != "gmail_send_email":
            raise NotImplementedError(f"Unknown action: {name!r}")

        import base64
        import email.mime.text

        import httpx

        tokens = ctx.vault_get()
        access_token = tokens.get("access_token", "")

        msg = email.mime.text.MIMEText(args["body"])
        msg["To"] = args["to"]
        msg["Subject"] = args["subject"]
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"raw": raw},
            )

        resp.raise_for_status()
        data = resp.json()

        ctx.audit(
            name,
            {"to": args["to"], "subject": args["subject"]},
            {"id": data.get("id")},
            "ok",
        )
        return {"ok": True, "message_id": data.get("id")}
