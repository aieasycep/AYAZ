# AYAZ — Yol Haritası (Birleşik)

> Strateji (`03-strategy.md`) + Mimari (`04-architecture.md`) sentezinden türetildi · 2026-06-26 (rev. ICP düzeltmesi).
> İlk **satılabilir sürüm = Faz 1 + Faz 2** (kanal-üstü panel + Türkçe otomatik içgörü = kama).
> ICP: genel dijital pazarlamacı. Konektörler reklam/analitik platformları; pazaryeri/feed kapsam dışı.

## Faz 0 — Kuruluş ✅
- [x] Ekip kuruldu (`.claude/agents/`, 11 uzman)
- [x] Çalışma modeli & anayasa (`00-team-charter.md`)
- [x] 6 referans aracın araştırması (`research/tools-inventory.md`)
- [x] Ürün stratejisi + mimari brifingleri
- [x] ICP netleştirildi (genel dijital pazarlamacı; pazaryeri/feed kapsam dışı)
- [ ] Repo'ya yazma yetkisi açıldıktan sonra push + draft PR

## Faz 1 — Temel + MVP veri/dashboard (Tek panel vaadi)
**Altyapı:** multi-tenant auth + org/RBAC · OLTP şeması · Secrets Vault · Connector SDK + fixtures test harness · kuyruk/scheduler · OAuth Broker · iyzico/Stripe faturalama kancası
**Ürün:** ilk 5 konektör (**Google Ads, Meta, GA4, Search Console, TikTok**) → artımlı sync → `fact_daily_metrics` + dim'ler → Metric Layer (₺/TZ normalize) → hazır kanal-üstü dashboard + tarih/filtre + temel paylaşım
**Çıktı:** Pazarlama yöneticisi tüm kanalları tek yerde görür.

## Faz 2 — Farklılaştırıcı: Otomatik İçgörü & Uyarı (kamanın "wow"u)
- [ ] Kural motoru + zaman serisi anomali tespiti (ROAS düşüşü, duran kampanya, harcama sıçraması, ölçüm hatası)
- [ ] LLM (Claude) ile Türkçe doğal-dil özet + önceliklendirilmiş aksiyon önerisi
- [ ] e-posta / Slack uyarı teslimi
- [ ] Scheduled PDF + paylaşılabilir/gömülebilir müşteri raporları
- [ ] KVKK rıza temeli
- **Satılabilir v1 burada tamamlanır → beta / ilk müşteriler**

## Faz 3 — Konektör genişleme + ajans/white-label
- [ ] Konektör genişleme (LinkedIn, Microsoft/Bing, Criteo, Pinterest + talebe göre)
- [ ] Ajans / white-label rapor modu (çoklu müşteri yönetimi)

## Faz 4 — Server-side / CAPI Ölçümleme
- [ ] Meta CAPI + TikTok Events + Google + identity matching/dedup + KVKK consent yönetimi (first-party data gateway)

## Faz 5 — Reklam yazma / optimizasyon
- [ ] Write-API ile kampanya yönetimi (önce Google/Meta) → read + kural-bazlı aksiyon önerisi → kural tabanlı optimizer → forecasting/MMM

## Faz 6 — Mobil Uygulama
- [ ] KPI özetleri, anomali push bildirimleri, onay/hızlı aksiyon (web backend'i yeniden kullanır)

## Opsiyonel — Feed / Creative Otomasyonu (Channable-tarzı)
- [ ] Yalnızca e-ticaret müşteri talebi olursa: ürün feed'inden otomatik PPC + dinamik creative üretimi. **Pazaryeri listeleme/satış kapsam dışı.**

---
**Önceliklendirme ilkesi:** Önce temeli (konektör + birleşik veri) bir kez kur; düşük-riskli okuma kamasıyla güven kazan; sonra yazma/optimizasyon gibi yüksek-riskli modülleri artımlı ekle.
