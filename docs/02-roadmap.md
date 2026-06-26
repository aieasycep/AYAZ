# AYAZ — Yol Haritası (Birleşik)

> Strateji (`03-strategy.md`) + Mimari (`04-architecture.md`) sentezinden türetildi · 2026-06-26.
> İlk **satılabilir sürüm = Faz 1 + Faz 2** (kanal-üstü panel + Türkçe otomatik içgörü = kama).

## Faz 0 — Kuruluş ✅
- [x] Ekip kuruldu (`.claude/agents/`, 11 uzman)
- [x] Çalışma modeli & anayasa (`00-team-charter.md`)
- [x] 6 referans aracın araştırması (`research/tools-inventory.md`)
- [x] Ürün stratejisi + mimari brifingleri
- [ ] **Açık soru:** Trendyol/Hepsiburada reklam verisine programatik erişim derinliği (sahip login + entegrasyon ekibi)
- [ ] Repo'ya yazma yetkisi açıldıktan sonra push + draft PR

## Faz 1 — Temel + MVP veri/dashboard (Tek panel vaadi)
**Altyapı:** multi-tenant auth + org/RBAC · OLTP şeması · Secrets Vault · Connector SDK + fixtures test harness · kuyruk/scheduler · OAuth Broker · iyzico/Stripe faturalama kancası
**Ürün:** ilk 5-7 konektör (Google Ads, Meta, GA4, Search Console, TikTok + Shopify/**Trendyol**) → artımlı sync → `fact_daily_metrics` + dim'ler → Metric Layer (₺/TZ normalize) → hazır kanal-üstü dashboard + tarih/filtre + temel paylaşım
**Çıktı:** Yönetici tüm kanalları tek yerde görür.

## Faz 2 — Farklılaştırıcı: Otomatik İçgörü & Uyarı (kamanın "wow"u)
- [ ] Kural motoru + zaman serisi anomali tespiti (ROAS düşüşü, duran kampanya, stok-tükendi+gösterim, ölçüm hatası)
- [ ] LLM (Claude) ile Türkçe doğal-dil özet + önceliklendirilmiş aksiyon önerisi
- [ ] e-posta / Slack / WhatsApp uyarı teslimi
- [ ] Scheduled PDF + paylaşılabilir/gömülebilir müşteri raporları
- [ ] KVKK rıza temeli
- **Satılabilir v1 burada tamamlanır → beta / ilk müşteriler**

## Faz 3 — Konektör genişleme + read-only reklam yönetimi + ajans
- [ ] Konektör 8-15 (WooCommerce, **Hepsiburada**, Bing, LinkedIn, Criteo, Pinterest, Merchant Center)
- [ ] Reklam yönetiminde read + basit kural-bazlı aksiyon önerileri (henüz tam optimizer değil)
- [ ] Ajans / white-label rapor modu

## Faz 4 — Server-side / CAPI Ölçümleme
- [ ] Meta CAPI + TikTok Events + Google + identity matching/dedup + KVKK consent yönetimi (first-party data gateway)

## Faz 5 — Reklam yazma/optimizasyon + Feed/Pazaryeri
- [ ] Write-API ile kampanya yönetimi (önce Google/Meta) → kural tabanlı optimizer → forecasting/MMM
- [ ] Feed yönetimi + TR pazaryeri feed çıkışı (Trendyol/Hepsiburada)

## Faz 6 — Mobil Uygulama
- [ ] KPI özetleri, anomali push bildirimleri, onay/hızlı aksiyon (web backend'i yeniden kullanır)

---
**Önceliklendirme ilkesi:** Önce temeli (konektör + birleşik veri) bir kez kur; düşük-riskli okuma kamasıyla güven kazan; sonra yazma/optimizasyon gibi yüksek-riskli modülleri artımlı ekle.
