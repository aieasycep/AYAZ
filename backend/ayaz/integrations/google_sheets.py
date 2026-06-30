"""Google Sheets integration adapter — append rows via the Sheets API."""

from __future__ import annotations

from ayaz.integrations.base import (
    ActionContext,
    ActionSpec,
    AuthType,
    Capability,
    Integration,
    IntegrationMetadata,
)


class GoogleSheetsIntegration(Integration):
    """Google Sheets integration — write rows to spreadsheets."""

    metadata = IntegrationMetadata(
        key="google_sheets",
        display_name="Google Sheets",
        category="productivity",
        description_tr="Rapor ve metrikleri Google E-Tablolar'a aktarın.",
        auth_type=AuthType.oauth2_bundle,
        provider="google_workspace",
        oauth_scopes=("https://www.googleapis.com/auth/spreadsheets",),
        capabilities=(Capability.action,),
        icon="S",
        icon_bg="#0F9D58",
        aliases=("e-tablo", "excel", "sheets", "rapor aktar", "spreadsheet"),
        min_plan="starter",
    )

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="gsheets_append_row",
                description_tr=(
                    "[EYLEM] Google E-Tablolar'daki belirtilen sayfaya yeni satır ekler. "
                    "Veriyi tabloya kaydetmek için kullan."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheets dosyasının ID'si (URL'den alınır)",
                        },
                        "sheet_name": {
                            "type": "string",
                            "description": "Sayfa adı, ör. 'Sheet1' veya 'Kampanya Verileri'",
                        },
                        "values": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Eklenecek satır değerleri listesi",
                        },
                    },
                    "required": ["spreadsheet_id", "sheet_name", "values"],
                },
                is_write=True,
                required_scopes=("https://www.googleapis.com/auth/spreadsheets",),
            )
        ]

    def execute_action(self, name: str, args: dict, *, ctx: ActionContext) -> dict:
        if name != "gsheets_append_row":
            raise NotImplementedError(f"Unknown action: {name!r}")

        import httpx

        tokens = ctx.vault_get()
        access_token = tokens.get("access_token", "")
        spreadsheet_id = args["spreadsheet_id"]
        sheet_name = args["sheet_name"]
        values = args["values"]

        range_notation = f"{sheet_name}!A1"
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
            f"/values/{range_notation}:append"
        )

        with httpx.Client(timeout=15) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"valueInputOption": "USER_ENTERED"},
                json={"values": [values]},
            )

        resp.raise_for_status()
        data = resp.json()

        ctx.audit(
            name,
            args,
            {"updated_range": data.get("updates", {}).get("updatedRange")},
            "ok",
        )
        return {
            "ok": True,
            "spreadsheet_id": spreadsheet_id,
            "updated_range": data.get("updates", {}).get("updatedRange"),
        }
