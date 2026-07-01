# AYAZ — Rakip Panel İncelemesi (Funnel.io · Adin.ai · Channable)

> Not: Bu rapor herkese açık kaynaklardan derlendi; kullanıcının giriş yaptığı panellerin canlı UI'ı (ekran görüntüsü gelince) ayrıca incelenecek. Fiyat rakamlarının bir kısmı 3. taraf aggregator snippet'lerine dayanıyor ve birincil sayfalar (funnel.io, G2/TrustRadius) 403/Cloudflare ile bloklandı — confidence: orta.

---

## 1. Yönetici özeti

Üç rakibin teardown'u tek bir ortak resme çıkıyor: **hepsi güçlü ama hepsi aynı üç yerden yaralı.**

1. **Öngörülemez/opak fiyat** — Funnel'in Flexpoint travması (#1 şikayet), Channable'ın add-on labirenti (baz fiyat 8x şişiyor), Adin'in tamamen opak custom-quote modeli.
2. **Sales-led / gated değerlendirme** — Funnel free'yi kapattı (7-gün trial), Adin tamamen demo-gated (public docs bile yok), Channable aktivasyon-kilitli trial. Sürtünmesiz "kendi kendine dene" yolu yok.
3. **Dik öğrenme eğrisi + zayıf in-product rehberlik** — üçü de "önce teknik araç" hissi veriyor; küçük bir uzman grubu sahipleniyor, gerisi ticket açıyor.

**AYAZ'ın kazanma yolu rakiplerin ölçeğiyle (600+/3000+ konektör, MMM, warehouse) yarışmak değil; bu üç ortak zayıflığı üründe kanıtlanmış özelliklere çevirmek.** AYAZ'ın yapısal avantajları (sabit-katmanlı fiyat, Türkçe AI Copilot, tek-çatı bileşim) tam bu üç boşluğa oturuyor.

**Kritik bulgu (repo doğrulaması):** En yüksek değer/efor oranına sahip fikirlerin tamamı **canlı platform kimliği gerektirmeden** bugün yapılabilir durumda; çoğunun yapı taşları kodda zaten var ama "ürün" haline getirilmemiş. Repo doğrulaması sonucu 8 fikrin 7'si **supported**, 1'i **uncertain** çıktı.

**En önemli açık soru (değişmedi):** AYAZ dar-ama-üstün bir ICP'de mi (öngörülebilir fiyat + hız + Türkçe AI + müşteriye-dönük paylaşım) derinleşecek, yoksa konektör/measurement paritesi peşinde mi koşacak? Birincisi kazanılabilir; ikincisi kaynak yakar.

**Üç en yüksek öncelik (şimdi, kimliksiz):**
1. Gerçek self-serve PLG (kayıt UI'ı kırık — backend hazır, frontend'de signup yok).
2. Veri-güven katmanı (çift sayım/duplicate tespiti — aktif ve sessiz bir hata kaynağı).
3. Sürpriz-fatura kalkanı / kullanım görünürlük paneli (limit-yaklaşma + atıl konektör uyarısı).

---

## 2. Araç araç teardown

### 2.1 Funnel.io

| Boyut | Özet |
|---|---|
| **Ne / Kim (ICP)** | 600+ no-code konektörle pazarlama verisini tek "data hub"ta normalize edip 36+ BI/warehouse hedefine aktaran marketing intelligence platformu. ICP: orta-büyük markaların ve veri-olgun ajansların data/analytics ekipleri. Free plan kapanınca küçük ekip/agency net biçimde ICP dışına itildi. |
| **Güç** | Konektör genişliği (600+) + sürekli yeni kanal; güçlü auto-blending/normalizasyon; ham veri saklandığı için yeni transformation'lar tüm geçmişe anında uygulanıyor; Data Explorer; Activate (CAPI geri-yazma + 90-gün offline conversion); 2026'da Funnel Measure (MMM+MTA+incrementality); Funnel MCP server; güçlü governance (ISO 27001, SOC 2 Type 2, RBAC, audit log, data residency). G2 4.5 / Capterra 4.7. |
| **Zayıf** | **#1: Flexpoint öngörülemezliği** — maliyet katlanıyor, atıl konektör kredi yakar ("bane of my existence"). Free kapandı, trial 7 gün. Veri kalitesi: duplicate/double-counting, eksik KPI. Veri tazeliği: 24-48s gecikme, belirli saatte yenileme zor. Dik öğrenme eğrisi. Dahili dashboard'lar müşteriye-dönük değil → ikinci BI aracı. Trustpilot 2.4/5 (kurumsal memnuniyet yüksek ama kamuoyu itibarı zayıf — uçurum). |
| **UX** | 3-fazlı doğrusal model: Connect → Organize/Explore → Share/Export. Custom Dimensions hiyerarşisi (platform-specific + common rules), if/then/regex/lookup. Live validation. Trial bitince 400 FP'ye düşüş + otomatik pause (config korunur). |
| **Fiyat** | Hibrit: Plan tier (özellik gating) + Flexpoints (kapasite). Warehouse export sadece Business+; MMM/attribution ayrı satış. Free Ara 2025'te kapandı; Starter $400→$200 (Mar 2026); Business ~$800 resmi ama FP ile $1-2K+/ay; Enterprise custom (Vendr ort. ~$73.5K/yıl). Self-serve checkout yok. |

### 2.2 Adin.ai

| Boyut | Özet |
|---|---|
| **Ne / Kim (ICP)** | Medya planlama→satın alma→optimizasyon→raporlamayı tek AI-native "operating system"te birleştiren çok-kanallı (Google/Meta/TikTok/X + programatik/Reserved Media/dijital radyo/DOOH/CTV) reklam platformu. ICP: kurumsal in-house reklamverenler + medya ajansları (sales-led/demo-gated, self-serve değil). |
| **Güç** | AI Media Planner (saniyeler içinde full-funnel cross-channel plan + projeksiyon); AI Media Optimizer (gerçek zamanlı, auto-pilot/co-pilot); Smart Audience (prompt + filtre); AI Forecasting / Cross-Channel Scoring / MMM. **Ayrıştırıcılar:** AWS QLDB immutable audit trail ("AI + blockchain" şeffaflık); sosyal-ötesi kanal genişliği (CTV/DOOH/radyo); prompt+filtre hibrit giriş. |
| **Zayıf** | **Bağımsız yorum vakumu**: G2 0, Capterra 0, SourceForge 0.0, Reddit 0, Trustpilot 1 (şüpheli) — doğrulanabilir sosyal kanıt yok. Doğrulanmamış agresif iddialar ("5X ROAS", "100X"). Fiyat opaklığı + self-serve yokluğu → KOBİ için yüksek giriş bileti. Erken aşama riski (~40 kişi, pre-seed/seed; public docs/changelog yok). White-label/açık API teyit edilemedi. |
| **UX** | "SEE → MANAGE → CONTROL" birleşik dashboard; 5 adım: kitle tanımla→planla→tek-tık satın al→optimize et→raporla. Auto-pilot vs co-pilot kontrol modu. Prompt+smart-filter hibrit giriş. Satın-alma öncesi interaktif "See & Manage Hub". Onboarding sales-led. |
| **Fiyat** | Tam opak, sales-led, demo-gated, custom quote. En güçlü sinyal: Capterra "~$3,990/feature/month" → per-feature/modül paketleme. Aggregator aralığı ~$990–$40,000. (Not: "$39/user", "free trial", "723 review/4.8" büyük olasılıkla AdCreative.ai veri sızması — Adin'e ait değil, düşük güven.) |

### 2.3 Channable

| Boyut | Özet |
|---|---|
| **Ne / Kim (ICP)** | E-ticaret ürün verisini tek import'tan alıp no-code kural motoruyla 3.000+ kanala optimize feed olarak yayan, üzerine PPC otomasyonu + marketplace sipariş yönetimi + AI zenginleştirme ekleyen "list, advertise, optimize" platformu. ICP: SMB-orta e-ticaret retailer + feed/performans ajansları (yorumcuların ~%86'sı küçük şirket). |
| **Güç** | **Rule Engine (asıl moat)**: no-code if/then, zincirlenebilir, kanal-başına kural seti — en çok övülen yön. Per-channel feeds (3.000+ şablon). PPC tool (RSA/DSA/PMax, dynamic assets). Marketplace Integrator + Repricer. AI Suite (BYO-token + grounding + human-in-the-loop). Sezgisel görsel UI (ilk feed <1 saat). **Sınırsız kullanıcı** (güçlü ajans argümanı). Hızlı yerel-dilde destek (G2 ~8.9). |
| **Zayıf** | **TCO öngörülemezliği**: "add-on olmadan hiçbir şey yapamıyorsun", baz fiyat yanıltıcı, büyük katalogda 8x şişme. Dik öğrenme eğrisi (kural sistemi aşırı granüler, "tek EAN" sürtüşmesi). **Amazon derinliği zayıf** (order coupling pahalı; bir vakada %10 yanlış adres, 5 hafta çözülmedi); bol FBB senkron "çözülemez". PPC'de gerçek AI yok (kural-bazlı, bid/bütçe AI yok). Faturalama/iptal sürtüşmesi. Feed diff/bulk-edit boşlukları. |
| **UX** | Project > Channel hiyerarşisi; wizard: yeni feed → Categories → Rules → Mapping → Quality → Preview & export. Görsel Rule Engine (her güncellemede otomatik yeniden uygulama). Preview/Quality gate'leri. AI Feed Setup (dil-bağımsız eşleme). AI Categorization güven-sıralı (düşük güven "uncategorized"a düşer). Self-service onboarding. |
| **Fiyat** | İki-eksenli + modüler: Package (items×projects×channels, en küçük 500 item/1 proje/3 kanal) × Core (Standard ~$49/Plus ~$64/Pro ~$74) + add-on'lar (Marketplaces/Creatives/Insights ~$35 each, Repricer ayrı, CSS €29). **Value metric = item sayısı, varyantlar ayrı sayılır** (3×3 = 9 item) → büyük katalogda dik tırmanış. Tüm planlar sınırsız kullanıcı. Aktivasyon-kilitli trial. (Rakamlar 3rd-party, confidence: medium.) |

---

## 3. Ortak boşluklar (3 araçta da var, AYAZ'da yok/eksik)

| # | Boşluk | Rakip durumu | AYAZ durumu |
|---|---|---|---|
| G1 | **Konektör/kanal derinliği** | Funnel 600+, Channable 3000+ | 10 konektör — "tek çatı" iddiası için kademeli TR-yerel genişleme şart |
| G2 | **Kullanıcı-tanımlı metrik/boyut + harmonizasyon** | Funnel transformation katmanı, Channable rule engine, Adin smart-filter | Metric Layer var ama kullanıcı-tanımlı katman yok |
| G3 | **Veri-kalite/güven katmanı** | Hiçbirinde iyi değil; Funnel'in en büyük şikayeti | Yok (üstelik çift-sayım koruması da yok) |
| G4 | **Platforma geri-yazma / aktivasyon** | Funnel Activate + Adin optimizer + Channable PPC | Salt-okuma/öneri (M7 sadece ileri-yön CAPI) |
| G5 | **MMM / atıf / incrementality** | Funnel & Adin üst-segment ölçümleme | forecasting/pacing var, savunulabilir lift yok |
| G6 | **Warehouse/BI export + açık ekosistem (MCP/API)** | Funnel 36+ hedef + MCP | Sadece CSV export, dışa-açık API/MCP yok |
| G7 | **Self-serve değerlendirme derinliği (public docs/tur)** | Channable/Funnel ileride | PLG akışı sığ; kayıt UI'ı fiilen kırık |

---

## 4. AYAZ fikir/fırsat tablosu

Doğrulama sütunu repo incelemesi sonucudur (supported = değerli + yeni + yapılabilir; uncertain = değer/efor varsayımı tutmuyor; — = doğrulanmadı, malzeme-bazlı).

| Başlık | İlham | ayaz_status | Değer | Efor | Kimlik-bağımlı | Doğrulama |
|---|---|---|---|---|---|---|
| Gerçek self-serve PLG (kart-yok free + public docs + 30-dk değer) | Funnel/Adin/Channable (hepsi gated) | partial | high | medium | kısmen (gerçek <30dk TTV platform OAuth'a bağlı) | **supported** |
| Veri-güven katmanı (duplicate/çift-sayım + KPI tutarsızlık) | Funnel (kalite şikayeti) | missing | high | medium | hayır | **supported** |
| Doğal dil → feed kuralı + kural-linter (çakışma tespiti) | Channable ("tek EAN" sürtüşmesi) | partial | high | medium | hayır | **supported** |
| Türetilmiş metrik/boyut stüdyosu (custom metric + harmonizasyon) | Funnel (transformation katmanı) | missing | high | high | hayır | **supported** |
| Sürpriz-fatura kalkanı (kullanım izleme + limit/atıl uyarı) | Funnel (Flexpoint), Channable (TCO) | partial | high* | low | hayır | **supported** (öngörü kısmı kısmen gereksiz) |
| Toplantı-zamanlı garantili veri tazeliği | Funnel (24-48s gecikme boşluğu) | partial | medium | low | hayır | **supported** |
| Medya planlayıcı (bütçeden full-funnel plan) | Adin (AI Media Planner) | missing | high | high | hayır (ama veri-olgunluk riski) | **supported** (kendi-geçmiş priors + güven aralığı kısıtıyla) |
| MCP sunucusu (Claude/Cursor erişimi) | Funnel (MCP server) | missing | low-med | orta-yüksek | evet (token/API key + RLS yok) | **uncertain** |
| Warehouse/BI export hedefleri | Funnel (36+ hedef) | missing | medium | high | evet | — (üst-tier add-on) |
| CAPI geri-yazma + offline conversion (Activate) | Funnel (Activate) | partial | high | high | evet | — |
| Kurumsal güven/uyum paketi (immutable audit + RBAC + residency) | Adin (QLDB), Funnel (governance) | partial | medium | medium | hayır | — |
| Auto-pilot / co-pilot ikili otomasyon modu | Adin | partial | medium | low | hayır | — |
| Doğrulanmış sosyal kanıt + savunulabilir ROI/incrementality | Adin (ROAS abartısı boşluğu) | missing | medium | high | evet | — |
| Kanal genişliği: Trendyol/Hepsiburada Ads + CTV/DOOH | Adin (kanal genişliği) | missing | high | high | evet | — (TR-yerel kazma noktası) |
| Smart Audience (prompt + filtre kitle) | Adin, Channable | missing | medium | high | evet | — |
| Feed kalite-kapısı + önizleme + geçmişe-göre diff | Channable (diff boşluğu) | partial | medium | medium | hayır | — |
| AI ürün-zenginleştirme (kategori/attribute/çok-dilli, BYO-token) | Channable (AI Suite) | missing | medium | medium | hayır | — |
| Pazaryeri sipariş/stok/iade + repricer | Channable (Marketplace Integrator) | missing | low | high | evet | — (strateji-dışı, odak-dağıtma riski) |
| Sınırsız kullanıcı / koltuk-bağımsız fiyat mesajı | Channable, Funnel | partial | medium | low | hayır | — |

\* Sürpriz-fatura kalkanı: AYAZ sabit-katmanlı olduğu için "ay sonu faturam ne" öngörü çerçevesi kısmen gereksiz; asıl değer (1) limit-yaklaşma bildirimi, (2) atıl konektör uyarısı, (3) tek panelde konsolidasyon.

---

## 5. Önceliklendirilmiş yol önerisi

### (a) ŞİMDİ / kimliksiz yapılabilir — en yüksek değer/efor

Hepsi **supported**, hiçbiri canlı platform kimliği gerektirmiyor, çoğunun yapı taşları kodda hazır.

| Sıra | Fikir | Neden şimdi | Eksik olan asıl parça |
|---|---|---|---|
| 1 | **Self-serve PLG düzeltmesi** | Backend signup (`auth.py` POST /auth/signup) + free tier (`billing.py`) hazır AMA **frontend'de signup yok** — landing "Kredi kartı gerekmez" diyor, ziyaretçi UI'dan kayıt olamıyor. Tüm CTA'lar /login'e gidiyor. | Kayıt UI'ı + `signup()` client fn + public docs/help-center + ürün turu |
| 2 | **Veri-güven katmanı** | Çift-sayım **aktif ve sessiz** bir hata: fact grain'i `connected_account_id` içeriyor, mükerrer hesap bağlamada unique constraint yok → her SUM çift sayar. M4 dedektör çerçevesi şema migrasyonu gerektirmeden "data_quality" kategorisi ekleyebilir. | Duplicate/double-count dedektörleri + "bu sayı neden böyle" drill-down + mükerrer-bağlama kontrolü |
| 3 | **Sürpriz-fatura kalkanı** | Tüm primitifler yerel: entitlements, konektör sayıları, `sync_status`/`last_synced_at`, bildirim merkezi. Limit-yaklaşma 402-duvarını önler (gerçek funnel sürtünmesi). | Limit-yaklaşma bildirimi + atıl konektör uyarısı + tek "kalkan" paneli |
| 4 | **Toplantı-zamanlı veri tazeliği** | `ingested_at`/`watermark` var ama hiçbir UI okumuyor; `ReportSchedule` deseni birebir taklit edilebilir. Ajans toplantı ritmine birebir. | "Son güncelleme" rozeti + kullanıcı-ayarlı refresh + gecikme uyarısı + manuel "şimdi yenile" |
| 5 | **Doğal dil → feed kuralı + kural-linter** | `_extract_rule_params` + `report_builder._claude_parse` desenleri birebir kopyalanabilir; linter tamamen saf/offline (DB değişikliği bile gerekmez). | NL→FeedRule üretimi + çakışma/gölge tespiti + dry-run önizleme + frontend NL girişi |

### (b) FAZ-İKİ — yüksek değer, daha fazla efor (kimliksiz ama olgunluk ister)

| Fikir | Not |
|---|---|
| **Türetilmiş metrik/boyut stüdyosu** | supported; FeedRule formül motoru deseni (`feeds.py` safe-eval) metriğe taşınabilir. POAS/marj-ROAS TR e-ticarette gerçek ihtiyaç. Güvenli formül eval + tenant izolasyonu titizlik ister. |
| **Medya planlayıcı** | supported AMA **kısıtla**: önce kendi-geçmiş priors + açık güven aralığı; saf-yeni-kanal cold-start tahmini bugün kanıtlanamaz (benchmark/kohort zekâsı erteli). Aşırı kesinlik vaadi MMM-lite ile aynı güven-erozyonu riskini taşır. |
| **Auto-pilot/co-pilot ikili mod** | Düşük efor; M9 kural motoru + "tek-tık düzeltme" üzerine güven köprüsü. Reklam-yazma (M6 faz-2) için doğru zemin. |
| **Feed kalite-kapısı + diff** + **AI ürün-zenginleştirme** | Channable'ın somut boşlukları; Copilot'un grounded-citation guardrail'i feed verisine taşınabilir. |
| **Kurumsal güven/uyum paketi** | automation audit log + RBAC çekirdeği var; "tamper-evident" + KVKK residency rozetleri regüle TR sektörlerini açar. |

### (c) KİMLİK / ALTYAPI BEKLEYEN veya bilinçli kapsam kararı

| Fikir | Engel / Karar |
|---|---|
| **Trendyol/Hepsiburada Ads + CTV/DOOH** | Canlı platform kimliği + iş geliştirme; ama **TR-yerel en güçlü ayrıştırıcı** — go-live sonrası en yüksek öncelik adayı |
| **CAPI geri-yazma + offline conversion (Activate)** | Platform yazma yetkisi gerekir; KVKK-uyumlu first-party sinyal TR'de güçlü argüman |
| **Warehouse/BI export** | Yüksek efor; çekirdek değer değil → üst-tier/ajans add-on'u olmalı, MVP'ye girmemeli |
| **Doğrulanmış ROI/incrementality** | Olgunluk + canlı veri gerektirir; "5X ROAS" abartısına karşı savunulabilir alternatif |
| **Smart Audience** | Platform-yazma kimliği gerektirir; M6 faz-2 ile anlamlı |
| **MCP sunucusu** | **uncertain** — araç katmanı (`TOOL_SPECS`) hazır AMA token/API-key modeli ve Postgres RLS yok (pre-go-live). ICP için değer büyük ölçüde gösterişli (KOBİ Cursor kullanmaz, "sıfır öğrenme eğrisi" konumlandırmasının tersi). Sadece dar ileri/ajans dilimi için, kimlik+RLS oturduktan SONRA; çekirdek yolun önüne geçmemeli |
| **Pazaryeri sipariş/stok/iade + repricer** | **Önerilmez** — strateji dokümanında zaten kapsam-dışı; düşük değer/yüksek odak-dağıtma; "pazarlama kokpiti" kimliğinden sapma |

**Zaten var / önerilmez (kısa geçilenler):** Pazaryeri yönetimi (kapsam-dışı). MCP sunucusu (uncertain — ertelenmeli). Sınırsız-kullanıcı mesajı saf konumlandırma kararı, ürün eforu değil.

---

## 6. Konumlandırma: AYAZ bu 3'ünden nasıl ayrışmalı (TR-öncelikli)

**Tek cümle:** AYAZ, üç rakibin ortak yarasını (opak fiyat + gated değerlendirme + dik öğrenme eğrisi) panzehire çeviren, **Türkçe AI-native, öngörülebilir-fiyatlı, sürtünmesiz pazarlama kokpiti** olmalı — ölçek yarışına değil, dar-ama-üstün bir ICP'ye oynamalı.

**Üç ayrıştırma ekseni:**

1. **"No surprises" — üründe kanıtlanmış öngörülebilir fiyat.** Funnel Flexpoint, Channable add-on labirenti ve Adin custom-quote'a karşı sabit-katmanlı fiyat + kullanım kalkanı paneli + limit/atıl uyarıları. Konumlandırmayı slogan değil, ekran yap.

2. **Sürtünmesiz, Türkçe, sıfır-öğrenme-eğrisi.** Üçü de gated/dik. AYAZ: kart-yok self-serve kayıt + public Türkçe docs + in-context onboarding + "ilk dashboard < 30 dk" + Türkçe Copilot. ICP'nin (10 sekme arasında gezen TR KOBİ/ajans pazarlamacısı) tam ihtiyacı.

3. **Rapora güven + müşteriye-dönük paylaşım.** Veri-güven katmanı (çift-sayım/KPI tutarsızlık tespiti — hiçbir rakipte iyi değil) + toplantı-zamanlı tazelik garantisi + white-label ajans paylaşımı. Funnel'in "dahili dashboard müşteriye-dönük değil → ikinci BI" boşluğunu kapatır.

**TR-yerel kazma noktası (en yüksek yapısal ayrıştırıcı):** Trendyol/Hepsiburada Ads konektörleri + KVKK-uyumlu first-party aktivasyon (CAPI geri-yazma). Global rakiplerin yapısal olarak öncelik vermediği, "yerli ve anlıyor" algısını derinleştirecek alan — ama bunlar kimlik-bağımlı, go-live sonrası faz.

**Net karar:** Konektör derinliği (600+/3000+), warehouse export, MMM ve platforma-yazma paritesi peşinde koşmak kaynak yakar. Kazanma yolu, kimliksiz bugün yapılabilen üç supported özelliği (PLG düzeltmesi + veri-güven + fatura kalkanı) hızla canlıya alıp "öngörülebilir + hızlı + Türkçe + güvenilir" konumunu üründe kanıtlamak; parite kalemleri üst-tier/ajans expansion olarak sıraya girmeli.

---

**Kaynak/limit notu:** Bulgular WebSearch snippet'lerine dayanıyor; funnel.io, G2, TrustRadius gibi birincil sayfalar bu oturumlarda 403/Cloudflare ile bloklandı — bazı FP/fiyat rakamlarında (Sheets 10 vs 150 FP, Starter 400 vs 500 FP, fiyat tarihçesi) kaynaklar arası tutarsızlık var, confidence: orta. Adin.ai fiyat ve yorum sinyallerinin bir kısmı AdCreative.ai veri sızması olabilir (düşük güven, işaretlendi). AYAZ "ayaz_status" ve yapılabilirlik değerlendirmeleri repo doğrulamasına dayanır; doğrulanmamış (—) fikirler malzeme-bazlıdır, kod teyidi yapılmamıştır.
---

## Ek: Ham fikir listesi (workflow çıktısı)

- **Sürpriz-fatura kalkanı: kullanım/maliyet izleme paneli + öngörü** — _Funnel.io (Flexpoint öngörülemezliği), Channable (TCO/add-on şişmesi)_ · AYAZ: partial · değer high/efor low · kimlik-bağımlı: hayır
- **Veri-güven katmanı: çift sayım/duplicate + KPI tutarsızlık tespiti** — _Funnel.io (duplicate/double-counting, eksik KPI şikayetleri)_ · AYAZ: missing · değer high/efor medium · kimlik-bağımlı: hayır
- **Toplantı-zamanlı garantili veri tazeliği (scheduled freshness)** — _Funnel.io (veri tazeliği/scheduling boşluğu)_ · AYAZ: partial · değer medium/efor low · kimlik-bağımlı: hayır
- **Türetilmiş metrik/boyut stüdyosu (custom metric + harmonizasyon)** — _Funnel.io (transformation/harmonizasyon katmanı, custom metric/dimension)_ · AYAZ: missing · değer high/efor high · kimlik-bağımlı: hayır
- **Warehouse/BI export hedefleri (BigQuery/Sheets/Looker/Power BI)** — _Funnel.io (36+ export hedefi, warehouse destination)_ · AYAZ: missing · değer medium/efor high · kimlik-bağımlı: evet
- **Conversions API geri-yazma + offline dönüşüm bağlama (Activate)** — _Funnel.io (Activate / conversions API geri-yazma)_ · AYAZ: partial · değer high/efor high · kimlik-bağımlı: evet
- **MCP sunucusu: AYAZ verisine Claude/ChatGPT/Cursor'dan erişim** — _Funnel.io (Funnel MCP server)_ · AYAZ: missing · değer medium/efor medium · kimlik-bağımlı: hayır
- **Kurumsal güven/uyum paketi: immutable audit trail + RBAC + veri ikametgâhı rozeti** — _Adin.ai (QLDB immutable audit), Funnel.io (ISO/SOC2, RBAC, audit log, data residency)_ · AYAZ: partial · değer medium/efor medium · kimlik-bağımlı: hayır
- **Auto-pilot / Co-pilot ikili otomasyon modu** — _Adin.ai (auto-pilot vs co-pilot)_ · AYAZ: partial · değer medium/efor low · kimlik-bağımlı: hayır
- **Doğrulanmış sosyal kanıt + savunulabilir ROI/incrementality ölçümü** — _Adin.ai (doğrulanmamış ROAS iddiaları, sosyal kanıt boşluğu)_ · AYAZ: missing · değer medium/efor high · kimlik-bağımlı: evet
- **Medya planlayıcı: bütçeden full-funnel cross-channel plan üretimi** — _Adin.ai (AI Media Planner)_ · AYAZ: missing · değer high/efor high · kimlik-bağımlı: hayır
- **Kanal genişliği: CTV/DOOH/dijital radyo + Trendyol/Hepsiburada reklam** — _Adin.ai (CTV/DOOH/dijital radyo kanal genişliği)_ · AYAZ: missing · değer high/efor high · kimlik-bağımlı: evet
- **Smart Audience: prompt + akıllı-filtre ile kitle tanımı/yönetimi** — _Adin.ai (Smart Audience), Channable (smart-filter)_ · AYAZ: missing · değer medium/efor high · kimlik-bağımlı: evet
- **Doğal dil → feed kuralı + kural-linter (çakışma tespiti)** — _Channable (rule engine sürtüşmesi, 'tek EAN' problemi)_ · AYAZ: partial · değer high/efor medium · kimlik-bağımlı: hayır
- **Feed kalite-kapısı + önizleme + geçmişe-göre diff** — _Channable (preview/quality gate, feed diff boşluğu)_ · AYAZ: partial · değer medium/efor medium · kimlik-bağımlı: hayır
- **AI ürün-zenginleştirme: kategori + attribute + çok-dilli metin (BYO-token, grounded)** — _Channable (AI Suite: categorization, smart attributes, BYO-token grounding)_ · AYAZ: missing · değer medium/efor medium · kimlik-bağımlı: hayır
- **Pazaryeri sipariş/stok/iade yönetimi + repricer (Trendyol/Hepsiburada/Amazon)** — _Channable (Marketplace Integrator, Repricer)_ · AYAZ: missing · değer low/efor high · kimlik-bağımlı: evet
- **Sınırsız kullanıcı / koltuk-bağımsız fiyatlama mesajı** — _Channable (sınırsız kullanıcı), Funnel.io (FP-bazlı koltuk maliyeti)_ · AYAZ: partial · değer medium/efor low · kimlik-bağımlı: hayır
- **Gerçek self-serve PLG: kart-yok free tier + public docs + 30-dk değer akışı** — _Funnel.io (free kapandı, 7-gün trial), Adin.ai (demo-gated, public docs yok), Channable (aktivasyon-kilitli trial)_ · AYAZ: partial · değer high/efor medium · kimlik-bağımlı: hayır

### Ortak boşluklar

- Konektör derinliği: Funnel 600+, Channable 3000+ kanal; AYAZ 10 konektör. 'Tek çatı' iddiasının inandırıcılığı için kademeli genişleme (özellikle TR yerel kanallar) şart.
- Kullanıcı-tanımlı metrik/boyut + harmonizasyon stüdyosu: Funnel'in çekirdek ayrıştırıcısı, Channable'ın kural motoru, Adin'in smart-filter'ı — üçü de güçlü kullanıcı-tanımlı dönüşüm sunuyor; AYAZ'da Metric Layer var ama kullanıcı-tanımlı katman yok.
- Veri-kalite/güven katmanı: duplicate/double-count tespiti, KPI tutarsızlık uyarısı, 'bu sayı neden böyle' izlenebilirliği — hiçbir rakipte iyi değil ama Funnel'in en büyük şikayet alanı; AYAZ'da yok.
- Platforma geri-yazma / aktivasyon: Funnel Activate + Adin'in optimizer'ı + Channable'ın PPC'si hepsi platforma yazıyor; AYAZ salt-okuma/öneri (M6 yazma faz 2, M7 sadece ileri-yön CAPI).
- MMM / atıf / incrementality: Funnel ve Adin'in üst-segment ölçümleme katmanı; AYAZ'da forecasting/pacing var ama savunulabilir lift/atıf ölçümü yok.
- Warehouse/BI export ve açık ekosistem (MCP/API): Funnel'in 36+ hedefi ve MCP'si; AYAZ'da sadece CSV export, dışa-açık veri API/MCP yok.
- Self-serve değerlendirme materyali derinliği: üçü de farklı şekilde sales-led/gated ama yine de public docs/help-center/in-product rehberlik konusunda Channable/Funnel ileride; AYAZ'ın PLG akışı henüz sığ.
