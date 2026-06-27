# AYAZ

**TR-first AI dijital pazarlama kokpiti — dağınık pazarlama araçlarını tek çatı altında birleştirir.**

AYAZ; reklam, analitik, feed, server-side ölçümleme, raporlama ve faturalandırmayı **tek
bir kokpitte** birleştiren, abonelik tabanlı bir SaaS platformudur. Amaç, bir pazarlama
yöneticisinin "10 sekme + tutarsız sayı" derdini bitirip tüm kanalları **tek doğruluk
kaynağında** toplamak, üstüne Türkçe konuşan, veriye gömülü bir **AI Copilot** koyarak
yalnızca "ne oldu"yu değil "ne yapmalısın"ı da söylemek. Çekirdek (konektörler + birleşik
veri modeli) bir kez inşa edilir; tüm modüller aynı temizlenmiş veriyi tüketir.

> Kod adı: **AYAZ** · Hedef pazar: **önce Türkiye, sonra global** · Durum: **çekirdek (M1–M10)
> + 7 farklılaştırıcı tamamlandı; canlı veri/ödeme için müşteri kimlikleri bekleniyor.**

---

## Özellikler (Features)

### Çekirdek modüller (M1–M10)

| Modül | Bir cümlede |
|---|---|
| **M1 — Bağlantı Hub'ı** | Çok platformlu konektörler (10 platform), OAuth Broker, otomatik sync, sağlık izleme. |
| **M2 — Birleşik Veri + Metrik Katmanı** | Normalize tek doğruluk kaynağı; CTR/CPC/CPA/ROAS tek tanımdan türetilir. |
| **M3 — Dashboard & Raporlama** | Özelleştirilebilir panolar, zamanlı/paylaşılabilir white-label müşteri raporu. |
| **M4 — AI İçgörü & Uyarı** | Anomali tespiti (8 dedektör; olumlu "kazanım" içgörüsü dahil) + Türkçe doğal-dil içgörü + e-posta/Slack uyarı + uygulama-içi bildirim merkezi. |
| **M5 — Feed Yönetimi** | Tek feed → kurallarla kanal-özel çıktı + her kanal için ayrı public feed URL'i. |
| **M6 — Reklam Yönetimi & Optimizasyon** | Kanal-üstü kampanya görünümü + optimizasyon önerisi (okuma + öneri; yazma faz 2). |
| **M7 — Server-side Ölçümleme (CAPI)** | Meta CAPI + TikTok Events + GA4 MP iletimi, hash/consent/dedup ile KVKK rızası. |
| **M8 — Çoklu Hesap / Ajans** | Workspace, müşteri yönetimi, üye/rol, white-label, workspace switcher. |
| **M9 — Otomasyon & Kurallar** | "ROAS < x ise durdur" tarzı kural motoru + audit + zamanlı görevler. |
| **M10 — Abonelik & Faturalama** | Planlar, entitlement/gating, kullanım; iyzico (TR) + Stripe (global) sağlayıcı. |

### 7 Farklılaştırıcı (rakipleri geçmek için)

| # | Farklılaştırıcı | Bir cümlede |
|---|---|---|
| 1 | **AI Copilot + aksiyon araçları** | Birleşik veri üstünde Türkçe konuşan, kaynak-gösterimli, tool-use'lu asistan. |
| 2 | **Cross-channel bütçe optimizatörü** | "Meta'dan ₺X'i Google'a kaydır → tahmini +%Y dönüşüm" — marjinal-ROAS tabanlı öneri. |
| 3 | **Hedef takibi + forecasting/pacing** | Hedef koy ("bu ay ₺500K"), AYAZ ulaşır mı tahmin eder ve sapınca uyarır. |
| 4 | **Alarm → kök-neden → tek-tık düzeltme** | Alarm → hangi entity tetikledi → önerilen kural taslağı → tek tık. |
| 5 | **Doğal dilde rapor/pano oluşturucu** | "Meta vs Google son 30 gün ROAS" → Copilot panoyu kursun. |
| 6 | **Kreatif performans analizi** | Hangi reklam/kreatif tutuyor, hangisi yoruldu (fatigue) + AI yorumu. |
| 7 | **Proaktif AI günlük brifing** | "Dün ne oldu / neye dikkat / ne yap" — her sabah otomatik özet. |

> Ertelenen (#8): Hafif atıf / Marketing-Mix + benchmark/kohort — gerçek müşteri verisi
> ve kritik kütle sonrası. Detay: [`docs/09-differentiation.md`](docs/09-differentiation.md).

---

## Teknoloji yığını (Tech stack)

**Backend:** Python · FastAPI · PostgreSQL · SQLAlchemy · Alembic (migrations) ·
Celery + Redis (kuyruk/scheduler) · HashiCorp Vault (token kasası).
**Frontend:** Next.js · React · TypeScript (PWA — yüklenebilir mobil deneyim).
**AI:** Anthropic Claude API (Türkçe içgörü/narrator + Copilot tool-use; mock fallback'li).
**Entegrasyonlar:** iyzico (TR) + Stripe (global) ödeme · döviz kuru API'leri.

## Mimari (Architecture)

Çok kiracılı (multi-tenant) tek platform. Konektörler dış platformlardan veriyi çeker →
Celery/Redis kuyruğu üzerinden ETL worker'ları extract→normalize→load yapar → Birleşik Veri
Ambarı + Metric Layer tek tip metrik üretir → tüm modül servisleri (dashboard, içgörü,
reklam, feed, CAPI, Copilot) **yalnızca bu temiz veriyi okur**, kaynak API'lere dokunmaz.
OAuth token'ları yalnızca Vault'ta şifreli tutulur; loglara/DB'ye düz asla yazılmaz.
Detaylı diyagram ve karar matrisi: [`docs/04-architecture.md`](docs/04-architecture.md).

---

## Repo düzeni (Repo layout)

```
AYAZ/
├── backend/        # FastAPI uygulaması, modeller, servisler, konektörler, Alembic, testler
│   ├── ayaz/
│   │   ├── api/v1/      # 19 router (auth, dashboard, ads, insights, feeds, tracking, notifications, ...)
│   │   ├── models/      # SQLAlchemy modelleri (OLTP + analytics fact/dim + modül tabloları)
│   │   ├── services/    # İş mantığı (metrics, insights, ads, copilot, optimizer, ...)
│   │   ├── connectors/  # 10 platform konektörü + Connector SDK (base/registry)
│   │   ├── security/    # Auth/RBAC, hardening yardımcıları
│   │   └── tasks/       # Celery görevleri (sync, scheduler)
│   ├── alembic/         # 15 migration
│   ├── scripts/         # seed_demo.py (idempotent demo verisi)
│   └── tests/           # ~1420 backend testi
├── frontend/       # Next.js + React + TS web uygulaması (19 sayfa, PWA)
│   ├── src/app/        # Sayfalar (dashboard, ads, insights, assistant, billing, ...)
│   ├── src/components/  # Paylaşılan bileşenler
│   └── public/          # manifest.json + sw.js + ikonlar (PWA)
├── docs/           # Ürün, mimari, strateji, yol haritası, özellik kataloğu, changelog
├── e2e/            # Uçtan uca test artefaktları
├── docker-compose.yml  # Postgres 16 + Redis 7 (yerel altyapı)
└── Makefile        # install / test / build / dev / migrate / seed kısayolları
```

---

## Hızlı başlangıç (Quick start)

Tam adımlar ve env değişkenleri: [`docs/07-dev-setup.md`](docs/07-dev-setup.md).
Backend detayları: [`backend/README.md`](backend/README.md).

```bash
# 1. Altyapı: Postgres 16 + Redis 7
docker compose up -d

# 2. Backend bağımlılıkları + env
cd backend && pip install -e ".[dev]" && cp .env.example .env

# 3. Migration + demo seed (idempotent)
alembic upgrade head
python -m scripts.seed_demo

# 4. API sunucusu (http://localhost:8000 · Swagger: /docs DEBUG modunda)
uvicorn ayaz.main:app --reload

# 5. Frontend (yeni terminal · http://localhost:3000)
cd frontend && npm install && npm run dev
```

`make install`, `make migrate`, `make seed`, `make dev-backend`, `make dev-frontend`,
`make test` kısayolları da mevcuttur.

**Demo girişi:** `demo@ayaz.app` / `demo12345` (seed sonrası).

---

## Durum & sayılar (Status & numbers)

| Ölçüt | Değer |
|---|---|
| Backend testleri | ~1420 (`pytest`, SQLite ile hermetik — DB gerekmez) |
| Frontend testleri | 49 (Vitest + Testing Library) + E2E smoke (Playwright, 19 rota) |
| API endpoint'leri | ~123 (19 v1 router + `/health`) |
| Alembic migration | 15 |
| Web sayfası | 19 (landing + `/settings` dahil) |
| Tema | Açık + Koyu (Dark mode) + Sistem |
| Hızlı erişim | Komut paleti (⌘K), bildirim merkezi, başlangıç rehberi |
| Konektör | 10 platform (Google Ads, Meta, GA4, Search Console, TikTok, LinkedIn, Microsoft, Criteo, Pinterest, Meta CAPI) |
| PWA | Evet (manifest + service worker → yüklenebilir mobil deneyim) |

**Canlı (kod + fixture/mock ile çalışır):** tüm M1–M10 modülleri, 7 farklılaştırıcı,
auth/RBAC, multi-tenant, Vault, scheduler, dashboard, raporlama, Copilot (mock fallback).

**Müşteri kimliği bekleyenler (canlıya almak için):**
- **Canlı reklam/analitik verisi** — her platform için OAuth/uygulama kimlikleri.
- **Gerçek ödeme** — iyzico + Stripe hesabı; webhook imza doğrulaması go-live'da zorunlu.
- **Türkçe AI üretimi (gerçek)** — Anthropic API anahtarı (yoksa mock narrator çalışır).
- **Altyapı/alan adı + KVKK** — TR/EU barındırma, e-posta sağlayıcısı, hukuki metinler.

Tam liste: [`docs/06-user-todo.md`](docs/06-user-todo.md) · Güvenlik denetimi:
[`docs/08-security-review.md`](docs/08-security-review.md).

---

## Dokümantasyon haritası

| Belge | İçerik |
|---|---|
| [`docs/01-vision.md`](docs/01-vision.md) | Ürün vizyonu, problem, ICP, wedge |
| [`docs/03-strategy.md`](docs/03-strategy.md) | Pazar/rakip stratejisi |
| [`docs/04-architecture.md`](docs/04-architecture.md) | Sistem mimarisi, veri modeli, yığın, riskler |
| [`docs/05-comprehensive-roadmap.md`](docs/05-comprehensive-roadmap.md) | Modül haritası + dalga planı + durum |
| [`docs/06-user-todo.md`](docs/06-user-todo.md) | Kullanıcıdan beklenen kimlik/altyapı işleri |
| [`docs/08-security-review.md`](docs/08-security-review.md) | Güvenlik denetimi (18 bulgu) |
| [`docs/09-differentiation.md`](docs/09-differentiation.md) | Rekabet hendeği + 7 farklılaştırıcı |
| [`docs/10-features.md`](docs/10-features.md) | **Özellik kataloğu** — modül × endpoint × sayfa |
| [`docs/CHANGELOG.md`](docs/CHANGELOG.md) | Yapım geçmişi (Faz 0 → Dalga 20) |
| [`docs/00-team-charter.md`](docs/00-team-charter.md) | AI yazılım ekibi ve roller |

> Bu proje bir **AI yazılım ekibi** tarafından geliştirildi: takım lideri (orkestratör) işi
> uzman ajanlara dağıtır; her ajan kendi izole context'inde çalışır. Roller:
> [`docs/00-team-charter.md`](docs/00-team-charter.md) · Ajan tanımları: [`.claude/agents/`](.claude/agents/).
