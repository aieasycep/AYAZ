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
- **Dalga 10 (talebe bağlı):** Mobil uygulama — kullanıcı "ihtiyaç halinde" dediği için talep gelince.

> **M1–M10 çekirdek modüllerin tamamı tamamlandı.** Kalan: güvenlik sertleştirme (Dalga 9) ve talebe bağlı mobil.

> Sıralama değer/risk'e göre ekip tarafından güncellenebilir. Her dalga: tasarla → uzman ajanlarla yap → entegre et → test/doğrula → commit + push.
