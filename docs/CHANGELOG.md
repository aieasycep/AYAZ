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
