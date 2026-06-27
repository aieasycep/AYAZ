# AYAZ — Kapsamlı Ürün Yol Haritası

> Hedef: **bir dijital pazarlama uzmanının ihtiyaçlarının büyük çoğunluğunu tek platformda** karşılamak.
> Basit bir dashboard DEĞİL — uçtan uca bir dijital pazarlama işletim sistemi.
> Bu belge yaşayan kapsamdır; ekip her dalga sonunda günceller. Otonom ilerleme: ekip
> kararları kendi alır, kullanıcıya bağımlı işler `06-user-todo.md`'de toplanır.

## Modül Haritası ve Durum

| Modül | Açıklama | Referans | Durum |
|---|---|---|---|
| **M1 — Bağlantı Hub'ı** | Çok platformlu konektörler, OAuth, otomatik sync, sağlık izleme | Funnel.io | 🟢 10 konektör + OAuth + Vault + scheduler (canlı veri için kimlik bekliyor) |
| **M2 — Birleşik Veri + Metrik Katmanı** | Normalize tek doğruluk kaynağı, türetilmiş metrikler | Funnel.io | 🟢 Çekirdek hazır |
| **M3 — Dashboard & Raporlama** | Özelleştirilebilir panolar, görseller, kıyas, zamanlı PDF/e-posta, paylaşılabilir/white-label müşteri raporu | Looker Studio | 🟢 Pano + zamanlı/paylaşılabilir white-label rapor (PDF ileride) |
| **M4 — AI İçgörü & Uyarı** | Anomali tespiti, Türkçe doğal-dil içgörü/öneri, e-posta/Slack uyarı | heyBooster | 🟢 Hazır (6 dedektör + Türkçe narrator + uyarı kuralları) |
| **M5 — Feed Yönetimi** | Tek feed → kurallarla kanal-özel çıktı + her kanal için ayrı feed URL'i (Google Shopping, Meta katalog, vb.) | Channable | 🟢 Hazır (public feed URL dahil) |
| **M6 — Reklam Yönetimi & Optimizasyon** | Kanal-üstü kampanya görünümü, düzenleme, bütçe/teklif kuralları, optimizasyon önerisi | Adin.ai | 🟢 Okuma + öneri hazır (yazma/optimizasyon faz 2) |
| **M7 — Server-side Ölçümleme (CAPI)** | Meta CAPI, TikTok Events, GA4 MP + KVKK rıza | SignalSight | 🟢 Hazır (toplama endpoint + hash/consent/dedup + 3 platform iletimi) |
| **M8 — Çoklu Hesap / Ajans** | Workspace, müşteri yönetimi, white-label, roller | — | 🟢 Hazır (workspace + üye/rol + white-label + switcher) |
| **M9 — Otomasyon & Kurallar** | "ROAS < x ise kampanyayı durdur" tarzı kural motoru, zamanlı görevler, bildirim | — | 🟢 Hazır (kural motoru + audit + celery beat) |
| **M10 — Abonelik & Faturalama** | iyzico/Stripe, planlar, entitlement, kullanım | — | 🟢 Plan/entitlement/gating + sağlayıcı stub hazır (canlı için kimlik bekler) |
| **Platform** | Auth/RBAC/multi-tenant, OAuth Broker + Vault, scheduler, observability, KVKK | — | 🟢 Auth + OAuth Broker + şifreli Vault + Celery scheduler hazır |

Durum: 🟢 hazır · 🟡 kısmi · 🔵 yapımda (bu dalga) · 🔴 planlı

## Dalga Planı (otonom yürütülür)

- **Dalga 1 (tamamlandı):** Backend temeli, 6 konektör, sync+metrik+dashboard API, web paneli, canlı doğrulama.
- **Dalga 2 (tamamlandı):** OAuth Broker + Vault + Celery scheduler · **Feed Yönetimi (M5)** + public feed URL · Feed/Bağlantılar UI.
- **Dalga 3 (tamamlandı):** AI İçgörü & Uyarı motoru (M4) · 4 yeni konektör (LinkedIn, Microsoft, Criteo, Pinterest) · İçgörü UI + CPC cilası.
- **Dalga 4 (tamamlandı):** Zamanlı/paylaşılabilir & white-label raporlar (M3+) · Reklam Yönetimi okuma + öneri (M6) · ilgili UI'lar.
- **Dalga 5 (tamamlandı):** Otomasyon & Kurallar motoru (M9) · demo seed zenginleştirme · Otomasyon UI · canlı ekran görüntüleri.
- **Dalga 6 (tamamlandı):** Server-side/CAPI ölçümleme (M7) + KVKK rıza + UI.
- **Dalga 7 (tamamlandı):** Abonelik & faturalama (M10) · CI + sağlamlaştırma · Faturalama UI.
- **Dalga 8 (tamamlandı):** Çoklu hesap / Ajans / white-label (M8) — workspace yönetimi + üye davet + marka.
- **Dalga 9 (tamamlandı):** Güvenlik denetimi + güvenli sertleştirmeler (18 bulgu; 6 düzeltildi, 12 öneri → `08-security-review.md`).
- **Dalga 10 (tamamlandı) — Farklılaşma başlangıcı:** Rekabet hendeği stratejisi + **AYAZ AI Copilot** (Türkçe, veriye gömülü, tool-use'lu asistan) backend + UI.
- **Dalga 11 (tamamlandı):** Cross-channel bütçe optimizatörü (#2) + hedef takibi & forecasting/pacing (#3).
- **Dalga 12 (tamamlandı):** Copilot v2 (aksiyon araçları) + alarm→kök-neden→tek-tık düzeltme döngüsü (#4).
- **Dalga 13 (tamamlandı):** Doğal-dil rapor/pano oluşturucu (#5) + kreatif performans analizi (#6).
- **Dalga 14 (tamamlandı):** Proaktif AI günlük brifing (#7) — 7 farklılaştırıcının tamamı canlı.
- **Dalga 15 (tamamlandı):** Herkese açık pazarlama/landing sayfası + onboarding boş-durum.
- **Dalga 16 (tamamlandı):** Üretim güvenlik sertleştirme (rate limiting + JWT iptal + webhook imzası).
- **Dalga 17 (tamamlandı):** PWA + mobil-optimize deneyim (yüklenebilir "mobil uygulama").
- **Dalga 18 (tamamlandı):** Frontend↔Backend sözleşme denetimi (14 runtime bug düzeltildi).
- **Dalga 19 (tamamlandı):** Backend doğruluk turu — kritik cross-tenant sızıntı + sağlamlaştırma.
- **Dalga 20 (tamamlandı):** Dönem karşılaştırma + CSV export (dashboard/reklam/kreatif).
- **Dalga 21 (tamamlandı):** Dokümantasyon tazeleme + Playwright E2E smoke suite + CI UUID düzeltmesi (taşınabilir `GUID` tipi).
- **Dalga 22 (tamamlandı):** Hesap & Ayarlar — `/settings` (profil + şifre değiştir + bildirim/dil tercihleri) + ilgili `/auth` endpoint'leri.
- **Dalga 23 (tamamlandı):** Global hata sınırları + zarif yükleniyor/boş/hata durumları + 404; paylaşılan `ErrorBoundary`/`StateViews`; SQLite-uyumlu DB engine.
- **Dalga 24 (tamamlandı):** Dark mode + tema değiştirici (Açık/Koyu/Sistem); CSS token tabanlı tema, FOUC önleyici; canlı demo ile doğrulandı.
- **Dalga 25 (tamamlandı):** Tarih aralığı ön-ayarları (Son 7/30/90 gün, Bu ay, Geçen ay) — dashboard/reklam/kreatif; dashboard aralığı hatırlanır.
- **Dalga 26 (tamamlandı):** Uygulama-içi bildirim merkezi — `Notification` modeli + `/notifications` API + nav'da zil/rozet/panel (içgörülerden tembel üretim).
- **Dalga 27 (tamamlandı):** Komut paleti (⌘K/Ctrl+K) — tüm sayfalara hızlı geçiş + komutlar; klavye-öncelikli, erişilebilir.
- **Mobil uygulama:** PWA ile yüklenebilir deneyim sağlandı (Dalga 17); native uygulama talebe bağlı.

> **M1–M10 çekirdek modüllerin tamamı + 7 farklılaştırıcı + güvenlik denetimi/sertleştirme + PWA tamamlandı.**
> Tam yapım geçmişi: `CHANGELOG.md`. Özellik kataloğu (modül × endpoint × sayfa): `10-features.md`.

## Farklılaşma Hedefleri (rakipleri geçmek için)
Rakipler stack'in tek katmanını satıyor; AYAZ hepsini birleştirdi. İlerleme:
1. ✅ **AI Copilot** — birleşik veriye gömülü Türkçe asistan (Dalga 10) + **aksiyon araçları** (Dalga 12).
2. ✅ **Cross-channel bütçe optimizasyonu** — bütçe dağıtım önerisi + projeksiyon (Dalga 11).
3. ✅ **Hedef takibi + forecasting/pacing** (Dalga 11).
4. ✅ **Alarm→kök-neden→tek-tık düzeltme** döngüsü (Dalga 12).
5. ✅ **Doğal dilde rapor/pano oluşturucu** — "Meta vs Google son 30 gün" → panoyu kursun (Dalga 13).
6. ✅ **Kreatif performans analizi** — hangi reklam tutuyor + AI yorumu (Dalga 13).
7. ✅ **Proaktif AI günlük brifing** — dün ne oldu / neye dikkat / ne yap (Dalga 14).
8. ⬜ **Atıf / Marketing Mix (hafif)** + benchmark/cohort — kritik kütle + gerçek veri sonrası (stratejist ertelemesi).

> Otonom farklılaşma fazı **tamamlandı**: 7 farklılaştırıcı canlı. Kalan #8 gerçek müşteri verisi
> gerektirir; geri kalan ilerleme artık kullanıcı girdisine bağlı (canlı kimlikler, mobil, öncelik).

> Sıralama değer/risk'e göre ekip tarafından güncellenebilir. Her dalga: tasarla → uzman ajanlarla yap → entegre et → test/doğrula → commit + push.
