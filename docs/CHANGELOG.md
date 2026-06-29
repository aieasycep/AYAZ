# AYAZ — Yapım Geçmişi (CHANGELOG)

> Proje, otonom bir AI yazılım ekibi tarafından **fazlar (Faz)** ve **dalgalar (Dalga)**
> hâlinde geliştirildi. Her dalga: tasarla → uzman ajanlarla yap → entegre et → test/doğrula → commit.
> Kaynak: git geçmişi (`git log`). En yeni en üstte.

---

## Faz 0 — Araştırma & Strateji (kuruluş)
- AYAZ ekibi ve otonom çalışma çerçevesi kuruldu (orkestratör + uzman ajanlar).
- 6 referans araç araştırıldı (Channable, Funnel.io, Looker Studio, SignalSight, Adin.ai, heyBooster).
- Strateji, mimari ve birleşik yol haritası sentezlendi; ICP "genel dijital pazarlamacı" olarak netleşti.

## Faz 1 — Backend Temeli
- FastAPI iskeleti, multi-tenant veri modeli, auth (bcrypt + JWT), Connector SDK + fixtures harness.
- İlk gerçek konektör: **Google Ads** (golden-file test deseni).
- Uçtan uca ilk dilim + 4 yeni konektör + ilk web paneli; Alembic ilk migration sağlamlaştırıldı.

---

## Dalga 1 — Foundation
- Backend temeli, ilk konektörler, sync + metrik + dashboard API, web paneli, canlı doğrulama.

## Dalga 2 — Feed + OAuth/Vault + Scheduler (M5)
- **Feed Yönetimi (M5)** + her kanal için public feed URL'i.
- OAuth Broker + şifreli Vault + Celery scheduler altyapısı.
- Feed ve Bağlantılar UI'ları.

## Dalga 3 — AI İçgörü & Uyarı (M4) + konektör genişleme
- AI İçgörü & Uyarı motoru (M4): 6 dedektör + Türkçe narrator + uyarı kuralları.
- 4 yeni konektör: LinkedIn, Microsoft/Bing, Criteo, Pinterest. İçgörü UI + CPC cilası.

## Dalga 4 — Raporlama (M3+) + Reklam okuma (M6)
- Zamanlı / paylaşılabilir / white-label raporlar.
- Reklam Yönetimi okuma + optimizasyon önerisi (M6, salt-okuma) + ilgili UI'lar.

## Dalga 5 — Otomasyon & Kurallar (M9)
- Kural motoru ("ROAS < x ise durdur") + audit + Celery beat.
- Zengin demo seed verisi + Otomasyon UI.

## Dalga 6 — Server-side / CAPI (M7)
- Toplama endpoint'i + hash/consent/dedup + 3 platform iletimi (Meta CAPI, TikTok Events, GA4 MP).
- KVKK rızası + Tracking UI.

## Dalga 7 — Abonelik & Faturalama (M10)
- Planlar, entitlement/gating, kullanım; iyzico + Stripe sağlayıcı stub'ları.
- CI hattı + sağlamlaştırma + Faturalama UI.

## Dalga 8 — Ajans / Çoklu-Workspace (M8)
- Workspace yönetimi + üye davet/rol + white-label marka + workspace switcher.
- **M1–M10 çekirdek modüllerinin tamamı 🟢 tamamlandı.**

## Dalga 9 — Güvenlik Denetimi
- Tam güvenlik denetimi: 18 bulgu (6 düzeltildi, 12 öneri → `08-security-review.md`).
- Go-live güvenlik maddeleri kullanıcı-todo'ya eklendi.

---

## Farklılaşma Fazı (Dalga 10–14)

## Dalga 10 — AYAZ AI Copilot (#1, flagship)
- Türkçe konuşan, veriye gömülü, **tool-use'lu** Copilot v1 (salt-okunur, grounded, kaynak-gösterimli).
- Tool-spec katmanı (mevcut modül servisleri tool olarak sarmalandı) + sohbet oturumu + Copilot UI.
- Farklılaşma stratejisi belgesi (`09-differentiation.md`).

## Dalga 11 — Bütçe Optimizasyonu (#2) + Hedef/Forecasting (#3)
- Cross-channel bütçe yeniden-dağıtım önerisi + tahmini-etki bandı (`/optimizer`).
- Hedef takibi + pacing/forecast ("yetişiyor musun") (`/goals`).

## Dalga 12 — Copilot v2 (aksiyon araçları) + Alarm→Düzeltme (#4)
- Copilot'a aksiyon araçları (kural taslağı vb.) + onay akışı.
- Alarm → kök-neden (entity drill-down) → tek-tık düzeltme döngüsü (M4→M6→M9).

## Dalga 13 — NL Rapor Oluşturucu (#5) + Kreatif Analizi (#6)
- Doğal-dilden rapor/pano oluşturucu (`/report-builder`, `POST /reports/build`).
- Kreatif performans analizi + fatigue tespiti (`/creatives`).

## Dalga 14 — Proaktif AI Günlük Brifing (#7)
- "Dün ne oldu / neye dikkat / ne yap" otomatik günlük brifing (`/briefing`).
- **7 farklılaştırıcının tamamı canlı** → otonom farklılaşma fazı tamamlandı.

---

## Üretim & Cilalama Fazı (Dalga 15–20)

## Dalga 15 — Pazarlama / Landing + Onboarding
- Herkese açık pazarlama/landing sayfası + ilk kullanıcı için onboarding boş-durum deneyimi.
- Düzeltme: brifing sayfası client-side crash (`performance_delta` sözleşme uyumu).

## Dalga 16 — Üretim Güvenlik Sertleştirme
- Rate limiting (auth/login, public collect/feed/report), JWT iptal/refresh, webhook imza doğrulaması.
- (12 nolu migration: revoked tokens.)

## Dalga 17 — PWA + Mobil-Optimize Deneyim
- Yüklenebilir "mobil uygulama" deneyimi: `manifest.json` + service worker (`sw.js`) + ikonlar.

## Dalga 18 — Frontend↔Backend Sözleşme Denetimi
- Frontend ile backend arası API sözleşmesi denetlendi; 14 runtime bug düzeltildi.

## Dalga 19 — Backend Doğruluk Turu
- Kritik cross-tenant veri sızıntısı kapatıldı + ek sağlamlaştırmalar.

## Dalga 20 — Dönem Karşılaştırma + CSV Export
- Dashboard, reklam ve kreatif görünümlerinde dönem-üstü karşılaştırma.
- Dashboard / reklam / kreatif CSV export.

## Dalga 21 — Dokümantasyon + E2E Smoke Suite
- README, CHANGELOG ve özellik kataloğu (`10-features.md`) baştan yazıldı.
- Playwright tabanlı uçtan uca smoke suite (`e2e/`) — 17 rota; "Application error"
  sınıfı runtime çökme hatalarını yakalar (token enjeksiyonlu auth).
- **CI düzeltmesi:** SQLite test motorunda `postgresql.UUID` kaynaklı, derlenmiş-
  sorgu-cache'i ile tetiklenen `'float' object has no attribute 'replace'` hatası;
  taşınabilir `GUID` TypeDecorator ile kökten çözüldü (Postgres'te native UUID,
  diğer motorlarda `CHAR(32)`).

## Dalga 22 — Hesap & Ayarlar
- Yeni `/settings` sayfası: Profil (ad/e-posta), Şifre Değiştir, Tercihler.
- Yeni endpoint'ler: `PATCH /auth/me`, `POST /auth/change-password`,
  `GET|PATCH /auth/preferences` (dil/saat dilimi/e-posta bildirimleri).
- `users` tablosuna 4 tercih kolonu (migration 0013); change-password için
  rate-limit. 28 yeni test (toplam suite 1231 geçiyor).

## Dalga 23 — Hata Sınırları & Zarif Durumlar
- App Router hata/yükleme/404 dosyaları: `error.tsx`, `global-error.tsx`,
  `not-found.tsx`, `loading.tsx` (Türkçe, erişilebilir).
- Paylaşılan bileşenler: `ErrorBoundary` (widget-bazlı çökme yalıtımı) +
  `StateViews` (`LoadingState`/`ErrorState`/`EmptyState`).
- Dashboard, içgörü ve reklam sayfaları bu bileşenleri benimsedi; ana veri
  widget'ları ErrorBoundary ile sarıldı (runtime-çökme sınıfına karşı sertleştirme).
- Yerel/demo çalıştırma: SQLite-uyumlu DB engine (Postgres yolu değişmedi).

## Dalga 24 — Dark Mode + Tema
- Koyu tema: `[data-theme="dark"]` token override'ları + `prefers-color-scheme`
  ile "Sistem" desteği; ThemeProvider (localStorage `ayaz_theme`) + FOUC önleyici
  inline script.
- Nav'da tema değiştirici (güneş/ay) ve `/settings → Tercihler`'de Tema seçimi
  (Açık/Koyu/Sistem).
- ~30 modül CSS'inde sabit renkler semantik token'lara taşındı; açık tema
  görünümü birebir korundu (canlı demo ile doğrulandı).

## Dalga 25 — Tarih Aralığı Ön-Ayarları
- Paylaşılan `DateRangePresets` bileşeni: Son 7/30/90 gün, Bu ay, Geçen ay
  (yerel saatle hesaplanır, aktif ön-ayar vurgulanır, erişilebilir).
- Dashboard, reklam ve kreatif sayfalarına eklendi; tek tıkla seç+uygula.
- Dashboard son aralığı `localStorage`'da hatırlar (`ayaz_dashboard_range`).

## Dalga 26 — Bildirim Merkezi
- Tenant-kapsamlı `Notification` modeli (migration 0014) + servis + router:
  `GET /notifications`, `/unread-count`, `POST /{id}/read`, `/read-all`.
  İçgörülerden `source_ref` ile tekilleştirerek tembel üretim. 20 test (suite 1251).
- Nav'da bildirim zili + okunmamış rozeti; açılır panel (önem rengi, göreli zaman,
  tıklayınca okundu işaretle + ilgili sayfaya git); açık/koyu temada çalışır.

## Dalga 27 — Komut Paleti (⌘K)
- Global komut paleti: ⌘K/Ctrl+K ile aç, tüm sayfalara hızlı geçiş + komutlar
  (tema değiştir, oturum kapat). Diakritik-duyarsız arama, tam klavye gezinme,
  erişilebilir (dialog/listbox); açık/koyu tema. Yalnızca oturum-içi sayfalarda.

## Dalga 28 — En Çok Değişenler (Top Movers) + Test İzolasyonu
- `GET /api/v1/dashboard/top-movers` — kanal/kampanya bazında, önceki döneme göre
  en çok değişen metrikler (artan + azalan), mutlak değişime göre sıralı. Mevcut
  dönem-karşılaştırma mantığı yeniden kullanıldı; Decimal para; şema değişmedi.
- Test sağlamlığı: `conftest.py`'ye autouse `dependency_overrides` temizleyici
  eklendi — modüller arası override sızıntısından kaynaklanan flaky (sıraya
  bağlı) test hatası kökten giderildi. 41 yeni test (suite 1292, 3 kez stabil).
- Dashboard'a "En Çok Değişenler" widget'ı (kanal/kampanya + metrik seçici,
  ▲/▼ renk-kodlu delta rozeti); ErrorBoundary ile sarıldı.

## Dalga 79 — Postgres Deploy Düzeltmesi + Demo Seed (KRİTİK)
- KRİTİK: `alembic upgrade head` **Postgres'te tamamen kırıktı** — gerçek bir Postgres örneğinde
  uçtan uca doğrulandı ve iki ölümcül hata bulunup düzeltildi (demo/testler SQLite + create_all
  kullandığı için fark edilmemişti):
  1. **FK tip uyuşmazlığı**: 0014+ migration'ları GUID kolonlarında `sa.CHAR(32)` kullanıyordu ama
     0001–0013 native `postgresql.UUID` kullanıyor → `notifications.tenant_id (char32)` →
     `tenants.id (uuid)` FK'i Postgres'te kurulamıyordu. 0014/0021/0023/0024/0025/0026'da GUID
     kolonları `postgresql.UUID(as_uuid=True)`'ya çevrildi.
  2. **Bozuk JSON/String `server_default`**: `server_default="'[]'"` gibi iç-tırnaklı defaultlar
     SQLAlchemy tarafından çift-tırnaklanıp `DEFAULT '''[]'''` üretiyordu → JSON kolonlarda
     "invalid input syntax for type json" ile deploy patlıyordu. 6 migration'da 16 default iç-tırnağı
     temizlendi (`"'[]'"`→`"[]"`, `"'draft'"`→`"draft"`, ...).
- Doğrulama: yerel Postgres 16'da `alembic upgrade head` artık **0026 head'e temiz uyguluyor** +
  `SEED_DEMO=true` ile demo seed Postgres'te sorunsuz çalışıyor (447 fact, 100 olay, 3 taslak, vb.).
- Yeni: `scripts/seed_if_enabled.py` — `SEED_DEMO` truthy ise migration sonrası idempotent demo
  seed'i çalıştırır (deploy'u asla bozmaz, default no-op). render.yaml preDeployCommand güncellendi
  (`alembic upgrade head && python -m scripts.seed_if_enabled`) + `SEED_DEMO` env değişkeni eklendi —
  böylece 10:00 review deploy'unda arayüz boş değil dolu görünür.
- Kalite: backend test paketi yeşil (migration düzeltmeleri create_all tabanlı testleri etkilemez;
  0026 migration smoke testleri yeşil).

## Dalga 78 — Gruplu Navigasyon (kritik UX düzeltmesi)
- KRİTİK düzeltme: nav 32 bağlantıya ulaşınca `.nav { overflow:hidden }` masaüstünde çoğu öğeyi
  KIRPIYORDU — birçok sayfa üst menüden erişilemiyordu. Üst menü 7 mantıksal **kategori
  açılır menüsüne** dönüştürüldü (Genel Bakış / Analiz / Reklam & Kreatif / İçerik & Sosyal /
  Planlama & Bütçe / Veri & Raporlar / Ayarlar); tüm 32 rota artık erişilebilir.
- `NAV_LINKS` (düz liste) korundu — CommandPalette (⌘K) hâlâ onu kullanıyor; ek `NAV_GROUPS` eklendi.
  Mobil çekmece gruplu bölümlere ayrıldı. Dropdown: dışarı tıkla/Escape/rota değişiminde kapanır, a11y.
- Test: `appnav-groups` bütünlük testi (her rota tam bir grupta, çift yok, 7 grup / 32 link). 6 yeni test.
- Kalite: frontend **417 yeşil**, tsc temiz, build yeşil (backend değişmedi).

## Dalga 77 — Copilot Modül Farkındalığı (funnel / KVKK / kıyaslama / denetim)
- AI Copilot ("Veriye Sor") genişletildi: artık **Dönüşüm Hunisi**, **KVKK Rıza**, **Sektör
  Kıyaslama** ve **Hesap Sağlık Taraması** hakkında soruları yanıtlıyor — ürünün merkezi AI
  farklılaştırıcısı yeni modülleri de kapsıyor (yeni nav öğesi yok).
- Backend: copilot_tools'a 4 yeni okuma aracı (`get_funnel_summary`, `get_consent_summary`,
  `get_benchmark_summary`, `get_audit_summary`) + `_TOOLS`/`TOOL_SPECS` kaydı; copilot.py'ye 4
  Türkçe özet fonksiyonu + 4 niyet dalı (greedy "nasıl" performans dalından ÖNCE; anahtar kelime
  çakışması yok). Yanıtlar tek-mention temiz cümleler. 54 yeni test.
- Kalite: backend **2540 yeşil** (kopilot 167 test yeşil), frontend değişmedi (411 yeşil).

## Dalga 76 — Müşteri Yolculuğu / Dönüşüm Hunisi (Conversion Funnel)
- Görsel pazarlama analitiği farklılaştırıcısı: **Dönüşüm Hunisi** — 5 adımlı e-ticaret hunisi
  (Sayfa Görüntüleme → Ürün Görüntüleme → Sepete Ekleme → Ödeme Başlatma → Satın Alma) adım-adım
  dönüşüm + düşüş + en büyük düşüş tespiti. Mevcut ölçümleme (ConversionEvent) verisinden.
- Backend: `GET /funnel/overview` (yeni tablo yok) — aşama sayıları + önceki adımdan dönüşüm % +
  düşüş % + girişe oran + genel dönüşüm + en büyük düşüş; tüm sıfıra bölme korumalı. 33 yeni test.
- Frontend: `/funnel` — genel dönüşüm + en büyük düşüş kahramanı, genişliği girişe-orana göre azalan
  huni barları, adım başına dönüşüm/düşüş rozetleri + geçiş bağlayıcıları; açık/koyu tema. 13 yeni
  test. Navigasyona **Huni** eklendi (Ölçümleme'den sonra).
- Demo: ConversionEvent dağılımı temiz azalan huniye dengelendi (40/26/18/10/6).
- Kalite: backend **2486 yeşil**, frontend **411 yeşil**, tsc temiz, build yeşil.

## Dalga 75 — Rol Görünümü (Role-based Views)
- Vizyonun çekirdeği — "her ekip tek panelden kendi işini yapsın": **Rol Görünümü** her persona için
  (Performans / Marka & İçerik / Müşteri Hizmetleri / Planlama & Bütçe / Yönetim) ayrı kokpit sunar:
  role-özel KPI'lar + dikkat gerektirenler + öncelikli ekranlar + hızlı işlemler.
- Backend: `GET /role-views/roles` + `GET /role-views/{role}` (yeni tablo yok) — mevcut okuma
  fonksiyonlarını (copilot_tools + recommendations) role göre sentezler; her metric-builder ayrı
  try/except ile dayanıklı. 104 yeni test.
- Frontend: `/roles` — rol seçici kartlar (localStorage'da kalıcı) + role-özel metrik kutuları,
  dikkat listesi (önem rozetli), öncelikli ekran kartları (neden açıklamalı), hızlı işlem butonları;
  açık/koyu tema. 16 yeni test. Navigasyona **Rol Görünümü** eklendi (Komuta Merkezi'nden sonra).
- Düzeltme: TO (CTR) yüzde olarak (×100) gösterilir; marcom öncelikli ekranı geçerli `/creative-lens`'e
  yönlendirilir.
- Kalite: backend **2453 yeşil**, frontend **398 yeşil**, tsc temiz, build yeşil.

## Dalga 74 — Bütçe Senaryo Simülatörü (Budget Scenario Simulator)
- Planlama farklılaştırıcısı: **Bütçe Senaryo Simülatörü** — kanallar arası bütçeyi kaydırın,
  geçmiş verimliliğe göre tahmini Gösterim/Tıklama/Dönüşüm/Gelir/ROAS'ı **anında** görün. "Temmuz
  planı" vizyonunun interaktif what-if uzantısı. Baz dağılıma göre delta + kanal projeksiyon tablosu
  + baz/senaryo karşılaştırma grafiği + şeffaf varsayım notları.
- Backend: `GET /budget-simulator/baseline` + `POST /budget-simulator/simulate` (yeni tablo yok) —
  `budget_planner._fetch_channel_metrics` reuse; kanal verimliliği (TBM/BGBM/dönüşüm oranı/ROAS/AOV/
  EBM) + doğrusal projeksiyon + baz karşılaştırma deltaları. 56 yeni test.
- Frontend: `/budget-simulator` — kanal başına kaydırıcı + sayısal giriş, canlı KPI kartları (delta
  rozetli), recharts baz/senaryo grafiği, projeksiyon tablosu, "eşit dağıt/sıfırla" yardımcıları;
  açık/koyu tema. 10 yeni test. Navigasyona **Bütçe Senaryosu** eklendi (Planlama'dan sonra).
- Kalite: backend **2349 yeşil**, frontend **382 yeşil**, tsc temiz, build yeşil.

## Dalga 73 — AI Reklam Metni Stüdyosu (Ad Copy Studio)
- Marcom/kreatif farklılaştırıcısı: **AI Reklam Metni Stüdyosu** — brief'ten (ürün, değer önerisi,
  ton, anahtar kelime, hedef kitle) platforma özel reklam metinleri üretir (Google Ads / Meta /
  TikTok) ve her alanı **karakter sınırına göre canlı doğrular**. Şablon üretici her zaman çalışır;
  opsiyonel Claude (`settings.claude_narrator_model`) varsa "yapay zeka" kaynaklı üretir. Üretilenler
  **taslak kütüphanesine** kaydedilebilir (kayıtlı/arşiv).
- Backend: yeni `ad_copy_drafts` tablosu + `POST /ad-studio/generate`, `POST/GET/PATCH/DELETE
  /ad-studio/drafts`. Platform-bağımsız tek-tip `fields` şekli (key/label/value/char_count/max_len/
  within_limit) — frontend jenerik render eder. 4 ton (profesyonel/samimi/heyecanlı/bilgilendirici),
  varyant başına farklı açı (fayda/aciliyet/sosyal kanıt). 52 yeni test.
- Frontend: `/ad-studio` — brief formu + varyant kartları (alan başına karakter sayacı + kopyala) +
  taslak kütüphanesi (görüntüle/arşivle/sil); açık/koyu tema. 23 yeni test. Navigasyona **Reklam
  Stüdyosu** eklendi (Kreatif Lensi'nden sonra).
- Demo: 3 kayıtlı taslak (Google/Meta/TikTok, demo ürün için) seed'lendi.
- Kalite: backend **2293 yeşil**, frontend **372 yeşil**, tsc temiz, build yeşil.

## Dalga 72 — KVKK Rıza Yönetim Merkezi (Consent Center)
- TR-first farklılaştırıcı: **KVKK Rıza Yönetim Merkezi** — tüm rıza ayarları, Consent Mode v2
  granüler sinyalleri ve KVKK uyumu **tek ekranda**. Rıza oranı + KVKK uyum skoru (0-100, uyumlu/
  kısmi/eksik) + 4 sinyal kırılımı + hedef-noktası rıza duruşu + 7 maddelik uyum kontrol listesi +
  rıza denetim izi. Global araçların sunmadığı, Türkçe ve KVKK çerçeveli bir uyum vitrini.
- Backend: `GET /consent/center` (yeni tablo yok) — mevcut ölçümleme/rıza altyapısını sentezler
  (`consent_signals`, `consent_required`, `consent_cookie_var`, `skipped_no_consent`). Granüler
  sinyal kırılımı (legacy fallback) + duruş etiketleri + uyum skoru/notu + son 15 olay denetim izi.
  50 yeni test.
- Frontend: `/consent` — rıza oranı + uyum skoru kahramanı, 4 sinyal kartı (oran barı), hedef duruş
  tablosu, kaynak yapılandırması, denetim-tarzı uyum kontrol listesi, rıza denetim izi tablosu;
  açık/koyu tema. 14 yeni test. Navigasyona **Rıza Merkezi** eklendi (Ölçümleme'den sonra).
- Demo: kaynak `consent_cookie_var` yapılandırıldı + olaylara `consent_signals` granüler veri
  eklendi (ad_personalization daha düşük onay oranıyla gerçekçi kırılım); skor **100 / uyumlu**.
- Kalite: backend **2241 yeşil**, frontend **349 yeşil**, tsc temiz, build yeşil.

## Dalga 71 — Proaktif Öneri Merkezi + AI Haftalık Strateji
- Yeni "birleşik zeka" katmanı: **Öneri Merkezi** — denetim, bütçe tempo, kıyaslama, hedef, gelen
  kutusu ve içerik sinyalleri **tek bir önceliklendirilmiş aksiyon akışında** birleşir. Her öneri:
  kategori + etki/çaba + gerçek sayılı Türkçe gerekçe + derin bağlantı + **Kabul Et / Ertele / Reddet**
  iş akışı (kalıcı durum). Üstte **AI Haftalık Strateji** (doğal-dil özet + 4 odak alanı + üst öneriler;
  şablon her zaman çalışır, opsiyonel Claude `settings.claude_narrator_model`).
- Backend: yeni `recommendation_states` tablosu (taşınabilir GUID, `status` open/accepted/snoozed/
  dismissed, tekil tenant+key); `GET /recommendations/feed`, `GET /recommendations/weekly-strategy`,
  `POST /recommendations/{key}/action`. Anahtarlar deterministik (`kategori:alt-tür`) — yeniden
  üretilebilir + seed'lenebilir. Mevcut okuma fonksiyonları reuse (audit/budget/benchmark/copilot_tools).
  49 yeni test.
- Frontend: `/recommendations` — haftalık strateji vitrini + filtre sekmeleri (Açık/Kabul/Ertele/
  Reddet/Tümü, canlı sayaç) + kategori/etki/çaba rozetli öneri kartları + iyimser durum güncelleme;
  açık/koyu tema. 24 yeni test. Navigasyona **Öneriler** eklendi (Kıyaslama'dan sonra).
- Demo: 1 kabul + 1 ertele durumu seed'lendi (deterministik anahtarlarla eşleşir) — tüm sekmeler dolu.
- Kalite: backend **2191 yeşil**, frontend **335 yeşil**, tsc temiz, build yeşil.

## Dalga 70 — Sektör Kıyaslama (Benchmark)
- Yeni farklılaştırıcı: **Sektör Kıyaslama** — son 30 gün reklam metrikleri TR e-ticaret **referans
  aralıklarına** göre konumlanır (güçlü/ortalama/zayıf). Pazarlamacının sevdiği "sektöre göre neredeyim".
- Backend: `GET /benchmark/overview` (yeni tablo yok) — 5 metrik (TO, TBM, ROAS, Dönüşüm Oranı, BGBM)
  hesabı (`_aggregate_by_channel_raw` reuse) + referans aralık sınıflandırma (düşük-daha-iyi metrikler
  için ters mantık) + kanal-bazlı ROAS/CTR konumu + Türkçe değerlendirme. 31 yeni test.
- Frontend: `/benchmark` — her metrik için aralık barı + konum işareti + rozet + değerlendirme; kanal
  kıyas tablosu; referans-aralığı uyarısı. 11 yeni test. Navigasyona **Kıyaslama** eklendi.
- Kalite: backend **2142 yeşil**, frontend **311 yeşil**, build yeşil.

## Dalga 69 — Kurulum Sihirbazı (Onboarding Wizard) — sellability
- Yeni satılabilirlik özelliği: **Kurulum Sihirbazı** — yeni kurumsal müşteri birkaç adımda hazır olur.
  Mevcut veriden hangi adımların tamamlandığını **otomatik tespit eder** ve kalanlara yönlendirir.
- Backend: `GET /onboarding/status` (yeni tablo yok) — 5 adımın varlık kontrolü (hesap bağlama,
  hedef, ölçümleme, bütçe planı, ilk içerik) → tamamlanma yüzdesi + her adım için CTA bağlantısı.
  Kiracı-izole, adım-bazlı try/except dayanıklı. 18 yeni test.
- Frontend: `/onboarding` — ilerleme kahramanı (yüzde barı) + adım listesi (tamamlandı ✓ / sıradaki
  vurgulu + CTA butonu) + tamamlanınca kutlama kartı. 10 yeni test. Navigasyona **Kurulum** eklendi.
- Kalite: backend **2111 yeşil**, frontend **300 yeşil**, build yeşil.

## Dalga 68 — Hesap Sağlık Taraması (Account Audit) — "tek tıkla ücretsiz denetim"
- Yeni farklılaştırıcı: **Hesap Sağlık Taraması** — reklam/ölçümleme/bütçe/içerik/hedef/içgörü modüllerini
  tek tıkla tarar, **0-100 sağlık puanı** + kategorize edilmiş bulgu listesi (geç/uyarı/sorun) +
  her bulgu için **çözüm önerisi** üretir. Pazarlama açısı: "ücretsiz hesap denetimi".
- Backend: `GET /audit/run` (yeni tablo yok) — `audit.run_account_audit` 6 kategori, 16+ kontrol
  (zarar eden reklam ROAS<1, bütçe yoğunlaşması, düşük CTR; hedefsiz/başarısız/düşük-eşleşme/rıza-düşüşü
  izleme; bütçe planı; onay bekleyen/planlanmamış içerik; risk altı hedef; kritik/uyarı içgörü). Puan:
  100 − 12×sorun − 4×uyarı; grade mükemmel/iyi/orta/zayıf. Her kategori try/except ile dayanıklı. 36 yeni test.
- Frontend: `/audit` — dairesel puan göstergesi + grade + özet + sayımlar + "Yeniden Tara" + kategori
  kartlarında geç/uyarı/sorun ikonlu kontrol listesi ve "Öneri:" blokları. İlk açılışta otomatik tarar. 9 yeni test.
  Navigasyona **Denetim** eklendi.
- Kalite: backend **2093 yeşil**, frontend **290 yeşil**, build yeşil.

## Dalga 67 — Komuta Merkezi (Command Center) — birleşik vitrin ekranı
- Yeni bayrak-gemisi ekran: **Komuta Merkezi** — tüm modüllerden "şu an dikkat gerektirenler"i
  tek akışta toplar; üstte KPI + altta modül durum kartları. "Tek panel" vaadinin vitrini, ilk nav öğesi.
- Backend: `GET /command-center/overview` (yeni tablo yok) — `command_center.build_command_center`
  mevcut copilot_tools okuma fonksiyonlarını + `plan_actuals`'ı yeniden kullanır; **dikkat sentezi**:
  kritik içgörüler→kritik, olumsuz mesajlar→uyarı, onay bekleyen içerik→bilgi, risk altı hedefler→uyarı,
  bütçe tempo sapması→uyarı; severity sıralı, link'li (modül sayfasına). 31 yeni backend testi.
  (Düzeltme: bütçe tempo, en güncel plan yerine **cari ay** planından hesaplanır.)
- Frontend: `/command-center` — manşet + MoM delta'lı KPI şeridi + "Dikkat Gerektirenler" tıklanır akış +
  "Modül Durumu" kart ızgarası (Bütçe/Gelen Kutusu/İçerik/Hedefler/İçgörüler). 11 yeni frontend testi.
  Navigasyona **Komuta Merkezi** (ilk öğe) eklendi.
- Kalite: backend **2057 yeşil**, frontend **281 yeşil**, build yeşil. Farklılaştırma backlog'u: `14-differentiation-backlog.md`.

## Dalga 66 — Bütçe: Plan vs Gerçekleşen (Planlama faz-2)
- Bütçe planını ay içi **gerçekleşen** harcama/performansla karşılaştırır — planlama döngüsünü kapatır.
- Backend: `GET /budget/plans/{id}/actuals` — planın `period_month`'u için gerçekleşen kanal metriklerini
  (`_fetch_channel_metrics` reuse) çeker; kanal-bazlı planlanan vs gerçekleşen bütçe, **tempo** (gerçekleşen/
  planlanan), pay sapması, gerçekleşen ROAS/gelir/dönüşüm + plan-seviyesi **harcama temposu vs süre temposu**
  (erken/geç/uygun) Türkçe değerlendirmeyle. `_month_bounds` ile devam eden ay kısmi raporlanır. 7 yeni backend testi.
- Frontend: `/planning`'de her kayıtlı planda **"Gerçekleşen"** butonu → Plan vs Gerçekleşen paneli
  (tempo barı + süre işareti + değerlendirme + KPI kartları + kanal tablosu [tempo barı + sapma rozeti]). 3 yeni frontend testi.
- Demo: ek bir **mevcut ay** planı (₺450.000, gerçek harcamaya yakın → "%94,4 / %93,3 plana uygun").
- Kalite: backend **2026 yeşil**, frontend **270 yeşil**, build yeşil.

## Dalga 65 — Marcom Kreatif Lensi (Marcom/Kreatif personası)
- Yeni sayfa: **Kreatif Lensi** — marka/marcom ekibi için kreatif performansını **etkileşim/trafik diliyle**
  (ROAS jargonu olmadan) gösteren görünüm. Salt-okunur; mevcut reklam verisinden (yeni tablo yok).
- Backend: `GET /marcom/creative-insights` — mevcut `ad_performance`'ı yeniden kullanır; kreatifleri
  tıklamaya göre sıralar, her biri için sade Türkçe içgörü (gösterim/tıklama/TO/trafik payı +
  yüksek/orta/düşük ilgi tieri) + doğal-dil manşet üretir. CTR yüzde olarak döner. 23 yeni backend testi.
- Frontend: `/creative-lens` — etkileşim KPI kartları + kreatif kartları (kanal/kampanya + istatistik +
  trafik payı barı + içgörü) + her kartta **"Organik içeriğe çevir →"** köprüsü (M11'e). 11 yeni frontend testi.
  Navigasyona **Kreatif Lensi** eklendi.
- Kalite: backend **2019 yeşil**, frontend **267 yeşil**, build yeşil. **Persona seti tamam:**
  Performans + Planlama + Müşteri Hizmetleri + CEO/CMO + Marcom — hepsi tek panel + tek Copilot.

## Dalga 64 — Copilot çapraz-modül farkındalığı (birleşik kokpit)
- AI Kopilot artık **tüm yeni modülleri** biliyor: bütçe planı, sosyal gelen kutusu ve yönetici özeti.
  3 yeni araç (`get_budget_status`, `get_inbox_summary`, `get_executive_summary`) hem stub hem Claude
  yolunda (TOOL_SPECS). "Bütçe planım ne durumda?", "Gelen kutusunda kaç açık mesaj var?",
  "Yönetici özeti ver / genel durum nasıl?" doğal dille yanıtlanır. Türkçe özetler + intent yönlendirme
  (yeni intent'ler performans intent'inden ÖNCE, çakışma yok) + yetenek mesajı güncellendi. 10 yeni test.
- Böylece her persona (planlama/CS/yönetici) kendi modülünü **tek Copilot'tan** sorgulayabiliyor —
  birleşik kokpit + tek asistan vaadi tüm yeni modüllerde tam.
- Kalite: backend **1996 yeşil**, frontend 256 yeşil.

## Dalga 63 — Yönetici (CMO) Görünümü (CEO/CMO personası)
- Yeni sayfa: **Yönetici Görünümü** — CEO/CMO için "pazarlamada neler oluyor"un tek-ekran üst-düzey özeti.
  Salt-okunur; mevcut veriden derlenir (yeni tablo/migration yok).
- Backend: `GET /executive/overview` — KPI'lar (harcama/gelir/ROAS/dönüşüm) + **önceki eş-uzunluk
  döneme göre MoM delta**, kanal ROI kırılımı (pay%), hedef ilerlemesi, en kritik içgörüler ve
  doğal-dil **manşet**. Mevcut servisleri yeniden kullanır (`_aggregate_by_channel_raw`,
  `_get_goal_progress`, `_get_insights`). 32 yeni backend testi.
- Frontend: `/executive` — manşet bandı + MoM delta rozetli KPI kartları + kanal ROI grafiği/tablosu +
  hedefler + duruma göre renkli içgörüler. 15 yeni frontend testi. Navigasyona **Yönetici** eklendi.
- Kalite: backend **1986 yeşil**, frontend **256 yeşil**, build yeşil. Persona yol haritası 3/5 tamam.

## Dalga 62 — M13 Sosyal Gelen Kutusu (Müşteri Hizmetleri / RADAAR paritesi)
- Yeni modül: **Sosyal Gelen Kutusu** — müşteri hizmetleri ekibi tüm sosyal kanallardan gelen
  DM/yorum/bahsetmeleri tek yerden görür, **panelden yanıtlar**, atar, etiketler, durum verir.
  RADAAR'ın güçlü olduğu alan. İş akışı tamamen kimliksiz; **canlı senkron + gönderim bilinçli
  kimlik-kilitli** (yanıt AYAZ'da kaydedilir, `delivered=false`; canlı gönderim OAuth gelince açılır).
- Backend: `SocialMessage` + `SocialReply` modelleri (migration 0024); `classify_sentiment`
  (TR/EN anahtar-kelime → olumlu/nötr/olumsuz), `suggest_reply` (şablon + Claude, anahtarsız çalışır),
  `compute_inbox_stats`. 10 endpoint (`/inbox/*`): listele/oluştur/thread/sil + yanıtla + ata + durum +
  etiket + suggest-reply + stats. 47 yeni backend testi.
- Frontend: `/inbox` iki-panelli arayüz — sol: filtreli mesaj listesi (kanal+tür+duygu rozetleri, durum,
  atanan); sağ: konuşma + yanıt thread'i (gönderim-kilit notuyla) + yanıt composer ("YZ Yanıt Öner" + Yanıtla)
  + İşlemler (Ata/Durum/Etiketler). Üstte Açık/Beklemede/Çözüldü + duygu dağılımı. 24 yeni frontend testi.
  Navigasyona **Gelen Kutusu** eklendi. Demo: 12 mesaj + 4 yanıt. Handle @@ gösterimi düzeltildi.
- Kalite: backend **1954 yeşil**, frontend **241 yeşil**, build yeşil.

## Dalga 61 — M12 Aylık Bütçe Planlayıcı (Planlama personası)
- Yeni modül: **Bütçe Planlayıcı** — "gelecek ay için toplam bütçe gir → sistem geçmiş performansa
  göre platform VE kampanya bazında dağıtsın". Kullanıcının net olarak istediği özellik; tamamen kimliksiz.
- Backend: `BudgetPlan` modeli (migration 0023) + saf alokasyon algoritması (`compute_allocation`):
  hedefe göre (Dengeli / ROAS'ı maksimize / Dönüşümü maksimize) kanal-ağırlıklandırma + **iteratif
  koruma** (her aktif kanala min %5, en çok %60; tavanlar sabitlenip kalan yeniden dağıtılıyor) +
  kampanya-altı kırılım + beklenen dönüşüm/gelir/ROAS projeksiyonu. 7 endpoint (`/budget/*`):
  preview (canlı önizleme, DB yazmaz) + plan CRUD + recompute. 42 yeni backend testi.
- Frontend: `/planning` sayfası — plan formu (ay + toplam bütçe + hedef + geçmiş veri penceresi),
  yazarken canlı önizleme (debounce), plan-seviyesi projeksiyon kartları, platform alokasyon barları
  (pay% + ROAS + beklenen gelir/dönüşüm + geçmişe göre ▲/▼ delta), açılır kampanya kırılımı,
  "nasıl hesaplandı" notları, plan kaydet + kayıtlı planlar listesi. 13 yeni frontend testi.
  Navigasyona **Planlama** eklendi. Demo: 1 örnek plan (₺150.000, Temmuz). Pay% formatı düzeltildi.
- Kalite: backend **1907 yeşil**, frontend **217 yeşil**, build yeşil.

## Dalga 60 — M7 Dayanıklılık (hata sınıflandırma + yeniden gönderme)
- Araştırmadaki son büyük SignalSight maddesi: başarısız iletimlerde **dayanıklılık**.
  `classify_forward_error` her hatayı **kalıcı** (400/401/403/422, "invalid", "token expired" — düzeltme
  gerekir) vs **geçici** (429/5xx/timeout/rate limit — yeniden denenebilir) vs **bilinmiyor** olarak
  sınıflandırır. `retry_event` + `POST /tracking/events/{id}/retry` başarısız olayı consent-uygun
  hedeflere yeniden gönderir, `retry_count` artırır (migration 0022). Stats'a **deliverability** bloğu
  (başarısızlar kalıcı/geçici/retryable kırılımı). Olay yanıtına `error_category`/`error_retryable`/`retry_count`.
  12 yeni backend testi.
- Frontend: Olay Günlüğü'nde hata kategori rozeti (Geçici/Kalıcı) + **Yeniden Gönder** butonu +
  yeniden-deneme sayacı; İletim Sağlığı'nda "N geçici · M kalıcı" notu. Durum filtresi eşlemesi
  düzeltildi (UI 'error' → backend 'failed'); olay hata mesajı artık konsolda görünüyor. Diakritik cilası.
- Kalite: backend **1865 yeşil**, frontend **204 yeşil**, build yeşil. **M7 ölçümleme stüdyosu + dayanıklılık tamam.**

## Dalga 59 — Copilot İçerik Planlayıcı farkındalığı (birleşik kokpit)
- AI Kopilot artık İçerik Planlayıcı'yı biliyor: yeni `get_content_status` aracı (durum bazlı sayılar +
  yaklaşan zamanlanmış gönderiler) hem stub hem Claude yolunda. "Kaç içerik onay bekliyor?",
  "sosyal medya gönderilerim ne durumda?", "yaklaşan yayınlar neler?" doğal dille yanıtlanır.
  Tool registry + TOOL_SPECS + Türkçe özet (`_summarise_content`) + intent yönlendirme + yetenek
  mesajı güncellendi. 7 yeni test (copilot suite 103 yeşil). Birleşik kokpit vaadini derinleştirir.

## Dalga 58 — İçerik Takvimi (aylık görünüm, RADAAR imzası)
- İçerik Planlayıcı'ya **Pano / Takvim** görünüm anahtarı + aylık takvim ızgarası (Pzt-Paz, TR ay adları).
  Planlı içerikler `scheduled_at` tarihine göre renk-kodlu (durum bazlı) çiplerle yerleştirilir; çipe
  tıklayınca composer açılır. Ay ileri/geri gezinme, bugünü vurgulama, "N planlı içerik" sayacı.
  Frontend-only (API zaten tarih veriyor). RADAAR'ın imza özelliği; planlayıcı modülü tamamlandı.

## Dalga 57 — Kreatif → İçerik köprüsü (M6 → M11, AYAZ'a özgü farklılaştırıcı)
- Araştırmanın işaret ettiği benzersiz köprü: **en iyi performans gösteren reklam kreatifini tek tıkla
  organik içerik taslağına çevir**. Ücretli performans içgörüsü → organik içerik döngüsünü kapatır
  (hiçbir rakipte yok). Tamamen kimliksiz.
- Backend: `POST /content/from-creative` — reklam temasını (ad_name + kampanya) organik altyazıya uyarlar
  (AI/şablon caption), reklam platformunu organik kanallara eşler (`map_ad_channel_to_social`: meta→IG+FB,
  google→YouTube, tiktok→TikTok…), hashtag ekler, **taslak** olarak oluşturur. ROAS/harcama yalnızca
  kreatif seçiminde kullanılır, asla altyazıya yazılmaz. `clean_ad_name` reklam jargonunu temizler. 10 yeni test.
- Frontend: İçerik Planlayıcı'da **"✨ Kreatiften Oluştur"** butonu + seçici modal — `/creatives/performance`
  top kreatiflerini ROAS ile listeler, tek tıkla taslak üretir. 1 yeni frontend testi.
- Kalite: backend content suite **46 yeşil**, frontend **203 yeşil**, build yeşil.

## Dalga 56 — M11 İçerik Planlayıcı (RADAAR-esinli organik sosyal içerik)
- Yeni modül: **İçerik Planlayıcı** — organik sosyal içerik takvimi/composer + onay akışı + AI açıklama.
  RADAAR araştırmasındaki birincil **kimliksiz** dilim. Kategori köprüsü: AYAZ artık ücretli reklam +
  ölçümleme + **organik içerik planlamayı** tek açık-metrikli kokpitte topluyor (hiçbir rakip 3'ünü birden yapmıyor).
- Backend: `ContentPost` modeli (title/body/channels/scheduled_at/status/approval_note/media_url/ai_assisted;
  migration 0021). 11 endpoint (`/content/*`): CRUD + iş akışı geçişleri (submit→pending_approval,
  approve, reject, schedule) + `POST /content/ai-caption` (AI açıklama+hashtag, anahtar yoksa deterministik
  Türkçe şablon — her zaman çalışır). **Canlı `publish` bilinçli olarak 501 ile kilitli** (her ağ için ayrı
  OAuth + app review gerekir). 6 kanal (instagram/facebook/x/linkedin/tiktok/youtube). 36 yeni backend testi.
- Frontend: `/content` sayfası — 5 sütunlu **durum panosu (kanban)** (Taslak/Onay Bekliyor/Onaylandı/
  Zamanlandı/Yayınlandı), composer modal (başlık/açıklama/kanal seçimi/yayın tarihi/görsel + "AI ile
  Açıklama Öner"), duruma göre kart aksiyonları, "Yayınla" kimlik-gerekli rozetiyle kilitli. Navigasyona
  **İçerik** eklendi. 28 yeni frontend testi. Demo seed: 6 örnek içerik (tüm durumlar/kanallar).
- Toplam: backend suite **1836 yeşil**, frontend **202 yeşil**, build yeşil.

## Dalga 55 — M7 Eşleşme Kalitesi (Event Match Quality / EMQ)
- SignalSight-esinli **eşleşme kalitesi skoru**: her olay ingest anında **ham** payload'tan
  (hash'lemeden ÖNCE) puanlanır → `compute_match_quality` ağırlıklı 0-100 skor + tier
  (weak/medium/good/excellent) + hangi kimlik sinyallerinin geldiği. Ağırlıklar: em 22, ph 18,
  fbc 15, fbp 10, external_id 10, IP/UA 6+6, ad/soyad/posta/şehir/il/ülke/cinsiyet (toplam=100).
  **KVKK:** yalnızca hangi alanların *geldiği* saklanır — IP/UA gibi ham değerler **asla**.
  `ConversionEvent.match_quality` (JSON, migration 0020). `hash_identity` artık `external_id`'yi
  hash'ler, `fbc`/`fbp` (PII olmayan tıklama/tarayıcı kimlikleri) passthrough eder → gerçek eşleşme artar.
  Stats yanıtına `match_quality` bloğu (ortalama skor + tier dağılımı + sinyal-bazlı kapsama %). 18 yeni test.
  Frontend: **Eşleşme Kalitesi** paneli — ortalama skor göstergesi + tier dağılım barları +
  sinyal kapsama barları + yüksek-değerli eksik sinyaller için **İyileştirme Önerileri**. Demo seed
  niyet-bazlı kimlik dağılımı (Purchase zengin, PageView zayıf). M7 ölçümleme stüdyosu tamam.

## Dalga 54 — M7 Consent Mode v2 / Granular KVKK Rıza (backend)
- Boolean rıza → 4 granular sinyal (ad_storage/ad_user_data/ad_personalization/analytics_storage).
  Collect bool VEYA obje kabul eder (geri uyumlu); `consent_signals` JSON saklanır. Hedef-bazlı
  `required_consent` (platform varsayılanları: meta/tiktok→ad_user_data, ga4→analytics_storage) →
  sinyaller karşılanmazsa iletmez. `consent_cookie_var` (SignalSight cookie-değişkeni) snippet'e gömülü.
  GA4 GCS passthrough (G1xx). Migration 0019. 44 yeni test (suite 1782).
  Frontend: kaynakta **Çerez Rıza Değişkeni** kartı (SignalSight Cookie Consent) + her hedefte
  **Zorunlu Rıza Sinyalleri** (4 sinyal, platform varsayılanı gösterimli). 18 yeni frontend testi (174).

## Dalga 53 — M7 Olay-bazlı Aç/Kapa (Event Configuration toggle, backend)
- SignalSight Event Configuration STATUS anahtarı: `POST /tracking/sources/{id}/event-config`
  `{event_name, enabled}` → kapalı olaylar kaydedilir ama CAPI'ye **iletilmez** (status="disabled").
  `TrackingSource.disabled_events` (JSON, migration 0018); stats `by_event[].enabled` ile durum yansır.
  Ingest sırası: dedup → disabled → consent → forward. 21 yeni test (suite 1738).
  Frontend: Olay Dağılımı tablosuna DURUM aç/kapa anahtarı (role=switch, Açık/Kapalı, optimistik) +
  kapalı satır soluk. SignalSight Event Configuration STATUS anahtarı. 6 yeni frontend testi (156).

## Dalga 52 — M7 Ölçümleme Sağlık & Olay İstatistikleri (backend)
- SignalSight panel ilhamı (Event Configuration + tracker report), AYAZ verisi üzerine (migration yok):
  `GET /tracking/sources/{id}/stats` — Total Events/Errors + duruma göre kırılım + consent-bloklu +
  **olay-bazlı sayım** (Add to cart vb.) + günlük trend (zero-filled). Olay listesine status/event_name
  filtreleri (debug konsolu için). Saf `compute_tracking_stats`. 31 yeni test (suite 1717).
  Frontend `/tracking`: **İletim Sağlığı** kartları (Toplam Olay/Hata/Rıza ile Engellenen) +
  **Olay Dağılımı** tablosu (olay × adet × hata + satır içi sparkline + günlük bar grafiği) +
  filtrelenebilir **debug konsolu** (durum/olay filtresi). DateRangePresets ile tarih aralığı.
  20 yeni frontend testi (150). (TR diakritikleri elden geçirildi.)
  Demo seed: M7 tracking verisi eklendi (1 kaynak + 2 hedef + 100 olay/14 gün, gerçek durum karışımı) — modül artık demoda görünür.

## Dalga 51 — Deploy Hazırlığı (canlı link için)
- Turnkey deploy: `backend/Dockerfile` + `frontend/Dockerfile` (standalone) + `.dockerignore`'lar,
  tek-VPS `docker-compose.prod.yml` (postgres+redis+migrate+backend+frontend), Render blueprint
  (`render.yaml`), `.env.prod.example` ve `docs/12-deploy.md` (Render+Vercel / VPS / yerel — env tablosu).
  next.config'e `output:'standalone'`. (Docker imajları bu ortamda build-test edilemedi — rehberde not.)

## Dalga 50 — Omnipresent "Veriye Sor" (Copilot hızlı erişim)
- Adin'in her-yerde 'Ask your data' barı ilhamı (ama açık + Türkçe): nav'da ve komut
  paletinde (⌘K) 'Veriye Sor' → QuickAsk modalı → soruyu yaz → Copilot konuşması oluşturulur
  → `/assistant?c=<id>` ile cevaba yönlendirir. Asistan sayfasına derin-link desteği. 4 yeni test (136).

## Dalga 49 — AI Ürün-Zenginleştirme (backend)
- Channable 'Optimize' ilhamı, insan-onaylı: `POST /feeds/sources/{id}/enrich` eksik
  alanları (renk/marka/kategori/materyal/başlık) kaynak metinden ÖNERİR (kaydetmez);
  `.../enrich/apply` yalnızca onaylanan değerleri `FeedProduct.data`'ya yazar.
  LLM + deterministik mock-fallback (anahtarsız çalışır). 55 yeni test (suite 1686).
  Frontend: kaynakta 'AI ile Zenginleştir' paneli — alan seçimi → öneri tablosu (mevcut→önerilen + güven çipi, yüksek-güven ön-işaretli) → 'Onaylananları Uygula'. 11 yeni frontend testi (132).

## Dalga 48 — Feed Kalite Kapısı (backend)
- Yayından önce kanal-bazlı doğrulama: `GET /feeds/channels/{id}/quality` — kural-uygulanmış
  çıktıyı kanal türünün zorunlu/önerilen alanlarına göre denetler → kalite skoru + sorun listesi
  (missing_required_field, duplicate_id, invalid_price, title_too_long, missing_image…).
  Saf `compute_feed_quality`; Channable 'reddedilen ürün = kayıp satış' boşluğunu kapatır.
  Frontend: kural stüdyosunda 'Kalite Kontrolü' — skor (iyi/orta/zayıf renkli) + '{valid}/{total} geçerli' + sorun listesi (önem çipli). 38 yeni frontend testi (121).

## Dalga 47 — Performans Skorlama Katmanı (backend)
- Adin gösterge ilhamı ama ŞEFFAF: `GET /dashboard/scores` — Genel Etkinlik + Verimlilik/
  Etkileşim/Dönüşüm 0–100 skorları, **kendi geçmiş döneme göre** (sahte benchmark yok).
  Her skorda 'basis' açıklaması (neden bu skor). Saf `compute_scores` fonksiyonu. 72 yeni test (suite 1580).
  Frontend: dashboard'da 'Performans Skoru' bölümü — SVG dairesel gösterge (Genel Etkinlik) +
  3 bileşen kartı (skor barı + 'basis' açıklaması), rating renkleri (iyi/orta/zayıf), dark mode. 14 yeni frontend testi (115).

## Dalga 46 — İçgörü Geri-Bildirim Döngüsü (backend)
- Adin'in 'Mark as Applied + 👍/👎' kartı ilhamı: `Insight`'a `applied_at` + `reaction`
  (migration 0017). `POST /insights/{id}/apply` ({applied}) ve `/insights/{id}/react`
  ({reaction: up|down|null}); liste filtreleri `applied` ve `reaction`. Kapalı geri-bildirim +
  'uygulananlar' görünümü. 27 yeni test (suite 1508).
  Frontend: `/insights` kartlarında 'Uygulandı' toggle + 👍/👎 (optimistik) + 'Uygulananlar' filtresi. 12 yeni frontend testi (toplam 99).

## Dalga 45 — Türkçe Doğal Dil → Feed Kuralı (backend)
- `POST /feeds/channels/{id}/rules/from-text`: Türkçe cümleden taslak FeedRule üretir
  (kaydetmez) + açıklama + güven + canlı etki (simulate). Claude + deterministik
  Türkçe mock-parser (API anahtarsız da çalışır; report_builder deseni).
  Frontend: kural formunda "Türkçe cümleyle yaz → Kural Üret" girişi (taslağı forma doldurur,
  açıklama+güven+etki gösterir; düşük güvende uyarı). 12 yeni frontend testi (toplam 88).
- Desenler: stok filtresi, fiyat eşiği, başlığa ekleme (calculated), set_value,
  find_replace, rename_field; alan eş-anlamlıları (fiyat/başlık/marka/stok…). 22 yeni test (suite 1481).

## Dalga 44 — Feed Kural Stüdyosu (görsel editör)
- Channable panel kareleri (062/064) referansıyla `/feeds` kural editörü yükseltildi:
  per-kural **duraklat** (greyed + 'Duraklatıldı' rozeti), **'Etkiyi Hesapla' barı**
  (Toplam before→after + kural başına 'X değişti · Y hariç'), kaydetmeden **Önizle**
  (simulate + before→after örnek diff), ve **kural-linter çipleri** (no_effect/excludes_all/
  shadowed/duplicate, önem renkli). feeds-api'ye impact/simulate/lint/patch/delete eklendi.
- Yan fayda: create-rule formundaki config anahtar adları backend şemasıyla birebir düzeltildi.
  21 yeni frontend testi (toplam 76).

## Dalga 43 — Feed Kural Stüdyosu (backend çekirdeği)
- Channable'ın en sevilen UX'i (canlı panel teardown'undan): per-kural **pause**
  (`is_paused`, migration 0016; apply_rules duraklatılanı atlar), **etki önizleme**
  (`/feeds/channels/{id}/rules/impact` — kural başına kaç ürün etkilendi/hariç tutuldu),
  kaydetmeden **dry-run** (`.../rules/simulate`) ve **kural-linter** (`.../rules/lint` —
  no-effect/excludes-all/shadowed/duplicate). 41 yeni test (suite 1459).

## Dalga 42 — Self-serve Kayıt (PLG kapısı)
- Rakip analizinde tespit edildi: landing'deki tüm "Ücretsiz Başla" CTA'ları `/login`'e
  gidiyordu ve **kayıt sayfası/`signup()` yoktu** — ziyaretçi UI'dan hesap açamıyordu.
- Yeni `/signup` sayfası (ad/şirket/e-posta/şifre+tekrar, istemci doğrulama, 409/422/429
  hata eşleme) + `signup()` istemci fonksiyonu + landing CTA'ları `/signup`'a bağlandı +
  login↔signup geçiş linkleri. 6 yeni birim test (toplam 58) + e2e smoke `/signup` kapsamı.

## Dalga 41 — E2E Smoke CI'da
- Playwright E2E smoke suite CI'ya bağlandı (`e2e-smoke` işi): SQLite ile backend
  bootstrap (create_all + seed) + frontend build/start + `playwright install chromium`
  → 19 rota. `smoke.py` chromium yolu CI-uyumlu (env/hardcoded/default fallback).
  `scripts/create_all_sqlite.py` eklendi; `models/__init__` artık `Notification`'ı da içerir.

## Dalga 40 — Gözlemlenebilirlik & Hazırlık Probu
- `X-Request-ID` middleware (gelen başlığı yansıtır/üretir) + yapılandırılmış istek
  logu (method/path/status/süre/request_id; gövde/başlık/sır loglanmaz; /health DEBUG).
- `GET /health/ready` DB bağlantısını (`SELECT 1`) kontrol eden hazırlık probu (200/503).
  Mevcut `/health` liveness aynen korundu. 18 yeni test (suite 1418).

## Dalga 39 — Frontend Birim Testleri
- Vitest + React Testing Library + jsdom kuruldu (önceden frontend birim testi yoktu).
  49 test: api normalize yardımcıları (briefing/goals), tarih ön-ayar matematiği,
  göreli zaman biçimleyici, StateViews bileşen render. CI'ye "Frontend — tests" işi eklendi.

## Dalga 38 — Erişilebilirlik (a11y)
- Global `:focus-visible` klavye-odak halkası (açık/koyu temada görünür) ve
  `prefers-reduced-motion` desteği (hareket azaltıldığında animasyon/geçişler kısılır).
  `<html lang="tr">` + ikon butonlarda aria-label zaten mevcuttu.

## Dalga 37 — Şifre Değişiminde Yeniden Giriş (UX)
- `/settings` şifre değiştirme başarısında: oturum geçersizleştiği için kullanıcı
  bilgilendirilip otomatik çıkış + `/login`'e yönlendirilir (Dalga 36'nın doğal UX tamamlayıcısı).

## Dalga 36 — Kimlik/Güvenlik Sertleştirme
- **Şifre değişince tüm oturumlar geçersiz:** JWT'ye `iat` eklendi; `users`'a
  `credentials_changed_at` (migration 0015). Şifre değişiminden önce verilmiş
  tokenlar 401 (eski/legacy token uyumu korunur).
- `PATCH /auth/preferences`: `timezone` artık IANA tz veritabanına göre doğrulanır (422).
- Copilot araç hatalarında iç imza sızdırılmıyor (genel mesaj + sunucu logu).
- Copilot `get_top_movers` ters tarih aralığına karşı korumalı. 26 yeni test (suite 1400).

## Dalga 35 — Bildirimler Sayfası
- Yeni `/notifications` sayfası: tüm bildirimleri listele, Tümü/Okunmamış + önem
  (Bilgi/Uyarı/Kritik) filtreleri, tümünü okundu işaretle, tıklayınca okundu+ilgili
  sayfaya git. Zil panelinden "Tümünü gör" + komut paletinden erişilir (üst nav
  kalabalıklaşmaz). E2E smoke 19/19 yeşil.

## Dalga 34 — E2E Regresyon Düzeltmeleri (hidrasyon)
- E2E smoke suite canlı demo yığınına karşı çalıştırıldı; iki sorun yakalandı:
  (1) `/dashboard` React hidrasyon hatası (#418/#422) — tarih aralığı/başlangıç
  rehberi `localStorage`'ı ilk render'da okuyordu (SSR↔client uyuşmazlığı).
  Düzeltildi: deterministik ilk durum + localStorage yalnızca mount sonrası.
  (2) `/assistant` smoke işareti kırılgandı → her zaman görünen "Yeni sohbet"e çevrildi.
  Artık 18/18 rota sağlıklı. (Unit test + build'in kaçırdığı runtime hatası.)

## Dalga 33 — Copilot: Bildirim & Hedef Araçları
- Copilot'a iki salt-okunur araç daha: `get_notifications` (okunmamış/son bildirimler)
  ve `get_goal_progress` (hedeflere ilerleme/tahmin/durum). Mevcut servisler yeniden
  kullanıldı (notifications_center, goals). 23 yeni test (suite 1374).

## Dalga 32 — Başlangıç Rehberi (Onboarding)
- Dashboard'da kapatılabilir "Başlangıç" kontrol listesi: hesap bağla → hedef koy →
  otomasyon kuralı → AI Asistan'ı dene. Tamamlanma mevcut endpoint'lerden türetilir;
  ilerleme çubuğu + adım CTA'ları. Tümü bitince/gizlenince görünmez (localStorage).

## Dalga 31 — Yeni İçgörü Dedektörleri (M4 derinleştirme)
- `detect_conversion_rate_drop` (dönüşüm oranı düşüşü) ve `detect_positive_movement`
  (olumlu "kazanım" içgörüsü — çoğu rakip yalnızca alarm verir; AYAZ kazanımları da
  kutlar, brifing tonunu dengeler). Narrator'a Türkçe metinler eklendi; dedup korunur.
  36 yeni test (suite 1351). Bu içgörüler bildirim merkezi + günlük brifingi de besler.

## Dalga 30 — Copilot: En Çok Değişenler Aracı
- Copilot'a `get_top_movers` aracı (salt-okunur) eklendi: "son 30 günde en çok ne
  değişti?" gibi sorulara veriyle yanıt. Sıralama mantığı `metrics.compute_top_movers`
  ortak yardımcısına çıkarıldı (dashboard endpoint'i + Copilot tek kaynağı kullanır).
  23 yeni test (suite 1315).

## Dalga 29 — Türkçe Diakritik Tutarlılığı
- Dashboard, reklam, kreatif, feed, içgörü, brifing, faturalama ve top-movers
  ekranlarındaki ASCII-leştirilmiş Türkçe metinler doğru diakritiklerle düzeltildi
  (~50 dizi; ör. Gösterim, Dönüşüm, Başlangıç, Dışa aktarma, Oluşturuldu, İşlem).
  Yalnızca kullanıcıya görünen metinler; mantık anahtarları/`value` alanları korundu.

---

> **Mevcut durum:** Çekirdek M1–M10 + 7 farklılaştırıcı + güvenlik sertleştirme + PWA tamam.
> Kalan ilerleme artık kullanıcı girdisine bağlı: canlı platform kimlikleri, gerçek ödeme
> (iyzico/Stripe), Anthropic API anahtarı, üretim altyapısı/KVKK. Detay: `06-user-todo.md`.
