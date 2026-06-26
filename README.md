# AYAZ

**Dijital pazarlama araçlarını tek çatı altında toplayan, abonelik tabanlı SaaS platformu.**

AYAZ; reklam, sosyal medya, e-posta, SEO, analitik ve CRM gibi dağınık dijital
pazarlama araçlarını tek bir kokpitte birleştirmeyi, ekiplere "10 sekme yerine tek
ekran" deneyimi sunmayı ve bunu abonelik modeliyle sunmayı hedefler. İhtiyaç halinde
mobil uygulama ile genişler.

> Kod adı: **AYAZ** · Durum: **Kuruluş / araştırma fazı**

## Bu repo nasıl çalışıyor?

Bu proje, bir **AI yazılım ekibi** tarafından geliştiriliyor. Takım lideri
(orkestratör) işi uzman ajanlara dağıtır; her ajan **kendi izole context'inde**
çalışır, böylece ana akış temiz kalır.

- **Ekip & roller:** [`docs/00-team-charter.md`](docs/00-team-charter.md)
- **Ürün vizyonu:** [`docs/01-vision.md`](docs/01-vision.md)
- **Yol haritası:** [`docs/02-roadmap.md`](docs/02-roadmap.md)
- **Birleştirilecek araçların envanteri:** [`docs/research/tools-inventory.md`](docs/research/tools-inventory.md)
- **Ekip ajan tanımları:** [`.claude/agents/`](.claude/agents/)

## Durum (2026-06-26)

Faz 0 tamamlandı: 6 referans araç (Channable, Funnel.io, Looker Studio, SignalSight,
Adin.ai, heyBooster) araştırıldı; strateji, mimari ve birleşik yol haritası çıkarıldı.

- **Kama (wedge):** Tek panelde kanal-üstü performans + Türkçe otomatik içgörü (salt-okunur).
- **Çekirdek karar:** Konektör + birleşik veri + dashboard + içgörü sıfırdan; LLM/ödeme/kur entegre.
- **İlk satılabilir sürüm:** Faz 1 (veri+dashboard) + Faz 2 (otomatik içgörü).

**ICP:** Bir şirketin dijital pazarlamasını yöneten kişi (her sektör) — reklam/analitik/
içgörü odağı. Konektörler reklam/analitik platformları (Google Ads, Meta, GA4, Search
Console, TikTok); pazaryeri/feed satışı kapsam dışı.

**Sıradaki adım:** Faz 1 altyapısının geliştirilmesine başlanması.
