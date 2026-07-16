# AYAZ — Claude Code Çalışma Notları

> Bu dosya yeni bir oturumu anında brifinglemek içindir. Proje = kullanıcının
> **"Digital marketing platform startup"** dediği ürün. GitHub: `aieasycep/AYAZ`
> · yerel: `~/AYAZ` · branch: `claude/marketing-platform-startup-ch6zq3`.
> TR-öncelikli, AI'lı dijital pazarlama kokpiti (SaaS).

## Çalışma modeli — Lider + Uzman Ajanlar (ÖNEMLİ)
Sen **takım lideri / orkestratör**sün. `.claude/agents/` altında **11 kalıcı uzman**
var (product-strategist, solution-architect, integrations-engineer, backend-engineer,
frontend-engineer, mobile-engineer, data-analytics-engineer, devops-engineer,
ux-designer, qa-engineer, security-compliance). Ağır işi (araştırma, çok dosya okuma,
deneme-yanılma) **Task/Agent ile bu uzmanlara delege et**; onlar kendi izole
context'lerinde çalışıp yalnızca **karar-hazır özet** döner → ana context yağsız kalır,
kayıplı compaction seyrekleşir. Ana thread'i **sadece kararlara** ayır. Detay:
`docs/00-team-charter.md`.

> Not: Bu 11 kuruluş kadrosu. Cloud oturumunda sonradan dinamik açılan uzmanlar dosyaya
> yazılmadı; gerektiğinde yeni rolü `.claude/agents/`'a kalıcı ajan olarak ekle
> (ör. `growth-marketer`, `content-strategist`).

## Kullanıcı tercihi
- **Otonom çalış**: izin sorma, en doğru kararı ver ve uygula; sorumluluk kullanıcıda.
  (Oturum `bypassPermissions` ile başlar — `.claude/settings.local.json`.)
- **Kapsamlı + özgün UI** iste; minimal değil. "Yapıldı" demeden önce **görsel doğrula**
  (headless/browser ile ekran görüntüsü). Test + gerçek davranışla doğrula.
- TR iş mantığında Türkçe yorum; TR sayı/tarih/₺ biçimi.

## Durum (2026-07-11)
- Yerel/origin senkron. Modüller **M1–M10 + 7 farklılaştırıcı** hazır.
- **Canlı ortamlar:** gerçek ürün ayaz-beryl.vercel.app (Vercel `ayaz` projesi, claude
  branch oto-deploy) + ayaz-backend.onrender.com. **Temiz test instance:**
  ayaz-clean.vercel.app + ayaz-backend-clean.onrender.com (boş Neon DB). ⚠️ ayaz-clean
  frontend'i git-oto-deploy DEĞİL → `cd ~/AYAZ/frontend && vercel deploy --prod --yes`
  gerekir. Detay hafızada: [[ayaz-canli-deploy]], [[ayaz-google-oauth-kurulumu]].
- **🟢 GOOGLE ADS GERÇEK VERİ CANLI KANITLANDI** (temiz instance, 2026-07-11): panelde
  ai@easycep.com → Cereyan_Easycep → 2 gerçek kampanya (₺116K+₺105K, 8.73x/49.21x ROAS).
  Dev token Render env'de. **KRİTİK fix: Google Ads API v18→v23 (v18 sunset→404).** Sürüm
  sunset dersi + envanter: [[ayaz-konektor-api-surumleri]].
- **Meta Ads:** backend kod TAM hazır (uzun-ömürlü token 2-hop + hesap çözümü + v25.0 +
  **60-gün rolling refresh durability**). Canlı kurulum kullanıcıda (FB Business app +
  META_APP_ID/SECRET). Detay: [[ayaz-meta-oauth-kurulumu]].
- **Bu oturumda ayrıca:** 12-ay backfill (sync days 90→365 + frontend Son 6/12 ay preset +
  akıllı ilk-sync), report_builder UTC flake fix. Hepsi push'lı.

## ✅ Gerçek Google Ads verisi akışı — CANLI KANITLANDI (2026-07-11)
Backend kod + dev token env + canlı panel doğrulaması TAMAM (2 gerçek kampanya görüldü).
Detay + görsel kanıt: hafıza [[ayaz-google-oauth-kurulumu]]. Kod özeti:

**Bu oturumda yapılan (kod tarafı — tam test paketi yeşil):**
- `config.py` → `google_ads_developer_token` alanı.
- `sync.py` → `inject_operator_credentials()` global operatör kimliklerini (client_id/
  secret/developer_token) `config.extra`'ya enjekte eder (vault'taki kullanıcı
  refresh_token'ı `setdefault` ile korunur). `sync_tasks.py` artık vault'u geçiriyor.
- customer_id oto-çözümü: konektörde `list_accessible_customers()` + `list_child_customers()`;
  `resolve_google_ads_targets()` **MCC yöneticiyse leaf hesaba iner** (login_customer_id
  header'ı türetilir), standalone ise kendini alır. Tek net hedef → oto-ata; **belirsizse
  (>1) boş bırak → panel hesap-seçiciyi gösterir**; çözülemezse fetch'e girmeden `idle`
  bırakır (sahte `error` + kota yakımı yok).
- `discover_accounts` endpoint'i de operatör kimliğini enjekte edip leaf listesini döner.
- `authenticate()` artık try/except İÇİNDE → dev token boşsa `sync_status=error` (sonsuz
  idle-retry yok). Senkron sync endpoint: `POST /api/v1/connectors/accounts/{id}/sync`
  (Redis'siz çalışır).

**KALAN (kullanıcı / elle):**
- **Dev token'ı env'e koy:** eyaytech@gmail.com API Center → "Jetonu göster" (SMS 2FA,
  kullanıcı telefonu) → `GOOGLE_ADS_DEVELOPER_TOKEN` olarak Render `ayaz-backend-clean`'e.
  (Render CLI env desteklemiyor → Render REST API; token `~/.render/cli.yaml`'da,
  `Authorization: Bearer`; tek-anahtar PUT `/v1/services/{id}/env-vars/{key}`.)
  Bu env gelince: panelden "Google'ı Bağla" → "Hesapları bul" (varsa) → "Senkronize et"
  ile gerçek veri akar.
- **(Ops.) Redis/Celery:** clean backend REDIS_URL boş → arka plan (saatlik) sync koşmaz;
  senkron endpoint "şimdi senkronize et"i zaten karşılıyor. İstenirse Upstash Redis free bağla.

## Meta (Facebook) Ads verisi akışı — backend kod fazı BİTTİ (2026-07-10)
Google ile aynı olgunlukta; ekiple + adversarial review (2 bulgu) + gerçek E2E + tam paket
yeşil. **Frontend agnostik — sıfır değişiklik.**
- `meta_ads.authenticate()` artık sadece `access_token` ister (tavuk-yumurta çözüldü →
  discover/hesap-seçici OAuth sonrası çalışır).
- **OAuth broker uzun-ömürlü token 2-hop:** `exchange_code()` Meta için `authorization_code`
  → sonra `fb_exchange_token` ile kısa-ömürlü (~1-2 saat) token'ı uzun-ömürlüye (~60 gün)
  çevirir; `refresh()` de `fb_exchange_token` kullanır. Scope least-privilege:
  `ads_read`+`business_management` (`ads_management` düşürüldü, read-only ürün).
- `sync.py`: `resolve_meta_ads_targets()` (`/me/adaccounts`, düz — MCC yok) +
  `_apply_meta_targeting()`; idle-guard platform-anahtarlı (`_ACCOUNT_ID_SECRET_KEY`) →
  ad account çözülemezse fetch'e girmeden `idle` (Google'la ortak).

**KALAN — kullanıcı / elle (Meta):** Facebook Developer hesabı → **Business tipi App** (App
ID/Secret) → **Facebook Login** + **Marketing API** ürünlerini ekle → Redirect URI kaydet
(`.../oauth/meta_ads/callback`) → kendini App Roles'e ekle (test için) → `META_APP_ID`/
`META_APP_SECRET`'i Render'a env koy (Google dev-token yöntemi). Gerçek müşteriler için:
**Business Verification** (Google'da yok, sert ön-koşul) + **App Review** (`ads_read`).

**Meta token durability (60 gün) — KOD ÇÖZÜLDÜ (2026-07-11, seçenek b):** `token_expires_at`
saklanıyor + sync-zamanında 7 günden yakın expiry'de `oauth_broker.refresh("meta_ads")` ile
rolling refresh + vault'a geri yazım (Google'ın her-sync self-heal deseninin Meta karşılığı).
Operatör client_id/secret vault'a SIZMIYOR (enjeksiyon öncesi snapshot; explicit test). ⚠️ Yine
de `fb_exchange_token`'ın süresiz uzatıp uzatmadığı canlı Meta'sız belirsiz — en sağlam yol hâlâ
Business Manager **System User token** (süresiz, kullanıcı kurulum adımı, öneri).

Ayrıca lansmanda: Google app'i **Yayınla + doğrula** (şimdi Testing modu, sadece elle
eklenen test kullanıcıları bağlanabilir).

> Yol haritası: `docs/05-comprehensive-roadmap.md`, geçmiş: `docs/CHANGELOG.md`,
> kullanıcıdan beklenenler: `docs/06-user-todo.md`.

## Lokal koşma (Docker'sız, SQLite — kurulu ve çalışır)
Python 3.12 venv: `backend/.venv`. `backend/.env` SQLite'a ayarlı (DEBUG=false,
RATE_LIMIT_ENABLED=false). Şema alembic yerine `Base.metadata.create_all` ile kurulur
(modeller cross-dialect GUID). Demo giriş: **demo@ayaz.app / demo12345**.

```bash
# Backend (backend/ dizininden — sqlite göreli yol için):
cd ~/AYAZ/backend && ./.venv/bin/uvicorn ayaz.main:app --host 127.0.0.1 --port 8000
# Şema+seed sıfırdan gerekirse:
#   ./.venv/bin/python -c "import ayaz.main; from ayaz.database import engine; from ayaz.models.base import Base; Base.metadata.create_all(engine)"
#   ./.venv/bin/python -m scripts.seed_demo
# Frontend (:3000, Next 14.2.5 — proje bu sürümde; global Next 15 ile başlatma):
cd ~/AYAZ/frontend && npm run dev
```
Frontend API tabanı `NEXT_PUBLIC_API_BASE` (varsayılan `http://localhost:8000`).
Gerçek Postgres/alembic akışı için `docker-compose.yml` (Postgres 16 + Redis 7).

## Repo not
- Ayrı repo olan `~/digitall` (Turborepo mikroservis monorepo'su) ile KARIŞTIRMA — bu
  ayrı bir kod tabanı (FastAPI monolit + Next.js).
