"""DataForSEO integration adapter — backlinks, keyword ideas, rank check."""
from __future__ import annotations
import base64, logging
from typing import Any
import httpx
from ayaz.integrations.base import (
    ActionContext, ActionSpec, AuthType, Capability, Integration, IntegrationMetadata,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dataforseo.com/v3"

class DataForSEOIntegration(Integration):
    metadata = IntegrationMetadata(
        key="dataforseo",
        display_name="DataForSEO",
        category="seo",
        description_tr="Backlink analizi, anahtar kelime fikirleri ve sıra takibi için DataForSEO entegrasyonu.",
        auth_type=AuthType.api_key,
        provider="dataforseo",
        capabilities=(Capability.action,),
        icon="D",
        icon_bg="#0070f3",
        aliases=("backlink", "anahtar kelime", "sıra takibi", "keyword", "rank"),
        setup_guide_url="https://dataforseo.com/apis",
        min_plan="growth",
    )

    def validate_credentials(self, creds: dict[str, Any]) -> dict[str, Any]:
        login = creds.get("api_login", "")
        password = creds.get("api_password", "")
        if not login or not password:
            raise ValueError("api_login ve api_password gereklidir.")
        # test call
        token = base64.b64encode(f"{login}:{password}".encode()).decode()
        try:
            resp = httpx.get(
                f"{_BASE_URL}/appendix/user_data",
                headers={"Authorization": f"Basic {token}"},
                timeout=15,
            )
            if resp.status_code == 401:
                raise ValueError("API kimlik bilgileri reddedildi.")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(f"DataForSEO bağlantı hatası: {exc}") from exc
        return {"api_login": login, "api_password": password}

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="dataforseo_backlinks_summary",
                description_tr="[VERİ] Bir domain için backlink özetini döndürür.",
                input_schema={
                    "type": "object",
                    "properties": {"domain": {"type": "string", "description": "Analiz edilecek domain, ör. example.com"}},
                    "required": ["domain"],
                },
                is_write=False,
            ),
            ActionSpec(
                name="dataforseo_keyword_ideas",
                description_tr="[VERİ] Seed anahtar kelime için hacim ve zorluk verileri döndürür.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "seed": {"type": "string", "description": "Seed anahtar kelime"},
                        "language_code": {"type": "string", "default": "tr"},
                        "location_code": {"type": "integer", "default": 2792},
                    },
                    "required": ["seed"],
                },
                is_write=False,
            ),
            ActionSpec(
                name="dataforseo_rank_check",
                description_tr="[VERİ] Bir anahtar kelime için domain'in sıralamasını kontrol eder.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "domain": {"type": "string"},
                        "location_code": {"type": "integer", "default": 2792},
                    },
                    "required": ["keyword", "domain"],
                },
                is_write=False,
            ),
        ]

    def execute_action(self, name: str, args: dict[str, Any], *, ctx: ActionContext) -> dict[str, Any]:
        try:
            creds = ctx.vault_get()
        except KeyError:
            return {
                "status": "kimlik_bekliyor",
                "message": "DataForSEO API anahtarı henüz yapılandırılmamış. Entegrasyon Merkezi'nden bağlayın.",
            }

        login = creds.get("api_login", "")
        password = creds.get("api_password", "")
        if not login or not password:
            return {
                "status": "kimlik_bekliyor",
                "message": "DataForSEO kimlik bilgileri eksik. Entegrasyon Merkezi'nden yeniden bağlayın.",
            }

        token = base64.b64encode(f"{login}:{password}".encode()).decode()
        headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

        try:
            if name == "dataforseo_backlinks_summary":
                return self._backlinks_summary(args["domain"], headers)
            elif name == "dataforseo_keyword_ideas":
                return self._keyword_ideas(args["seed"], args.get("language_code", "tr"), args.get("location_code", 2792), headers)
            elif name == "dataforseo_rank_check":
                return self._rank_check(args["keyword"], args["domain"], args.get("location_code", 2792), headers)
            else:
                raise NotImplementedError(f"Bilinmeyen aksiyon: {name!r}")
        except httpx.HTTPError as exc:
            logger.warning("DataForSEO HTTP hatası action=%s: %s", name, exc)
            return {"status": "hata", "message": f"DataForSEO API hatası: {exc}"}

    def _backlinks_summary(self, domain: str, headers: dict) -> dict:
        payload = [{"target": domain, "limit": 1}]
        resp = httpx.post(f"{_BASE_URL}/backlinks/summary/live", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("tasks") or [{}])[0].get("result") or []
        if not items:
            return {"domain": domain, "backlinks": 0, "referring_domains": 0}
        r = items[0]
        return {
            "domain": domain,
            "backlinks": r.get("backlinks", 0),
            "referring_domains": r.get("referring_domains", 0),
            "rank": r.get("rank", 0),
        }

    def _keyword_ideas(self, seed: str, language_code: str, location_code: int, headers: dict) -> dict:
        payload = [{"keywords": [seed], "language_code": language_code, "location_code": location_code, "limit": 20}]
        resp = httpx.post(f"{_BASE_URL}/dataforseo_labs/google/keyword_ideas/live", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("tasks") or [{}])[0].get("result") or []
        keywords = []
        for item in items[:20]:
            for kw in (item.get("items") or []):
                keywords.append({
                    "keyword": kw.get("keyword"),
                    "search_volume": (kw.get("keyword_info") or {}).get("search_volume", 0),
                    "competition": (kw.get("keyword_info") or {}).get("competition", 0),
                    "cpc": (kw.get("keyword_info") or {}).get("cpc", 0),
                })
        return {"seed": seed, "keywords": keywords}

    def _rank_check(self, keyword: str, domain: str, location_code: int, headers: dict) -> dict:
        payload = [{"keyword": keyword, "location_code": location_code, "language_code": "tr", "se_domain": "google.com.tr"}]
        resp = httpx.post(f"{_BASE_URL}/serp/google/organic/live/advanced", json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        items = (data.get("tasks") or [{}])[0].get("result") or []
        rank = None
        for item in items:
            for r in (item.get("items") or []):
                if r.get("type") == "organic" and domain in str(r.get("domain", "")):
                    rank = r.get("rank_absolute")
                    break
        return {"keyword": keyword, "domain": domain, "rank": rank, "found": rank is not None}
