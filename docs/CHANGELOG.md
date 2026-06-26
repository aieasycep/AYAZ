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

---

> **Mevcut durum:** Çekirdek M1–M10 + 7 farklılaştırıcı + güvenlik sertleştirme + PWA tamam.
> Kalan ilerleme artık kullanıcı girdisine bağlı: canlı platform kimlikleri, gerçek ödeme
> (iyzico/Stripe), Anthropic API anahtarı, üretim altyapısı/KVKK. Detay: `06-user-todo.md`.
