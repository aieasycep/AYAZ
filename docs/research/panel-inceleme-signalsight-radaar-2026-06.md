# AYAZ — Ek Rakip Analizi: SignalSight · RADAAR

> AYAZ (TR-öncelikli, çok-kanallı dijital pazarlama kokpiti) için iki ek rakibin **giriş yapılmış
> canlı panellerinde** ekran ekran yapılan UX/IA araştırması.
> **Tarih:** 2026-06-28 · **Hesaplar:** SignalSight → EASYCEP BİLİŞİM A.Ş. · RADAAR → "Easycep Official" (workspace EasyCep).
> Önceki 3-araç analizi: `AYAZ-rakip-analizi-funnel-adin-channable.md`. Ekran görüntüleri: `screenshots-signalsight-radaar/`.

## Konumlandırma (AYAZ açısından)
- **SignalSight** = AYAZ'ın **"server-side ölçümleme"** ayağının doğrudan rakibi: first-party tracking +
  **CAPI ağ geçidi** (Meta/TikTok'a sunucu-taraflı dönüşüm) + consent-mode + lead/landing modülleri.
- **RADAAR** = AYAZ'ın **organik sosyal + içerik + AI Copilot** ayağının rakibi: çok-kanallı sosyal medya
  yönetimi (yayınlama + sosyal inbox + dinleme + analitik). TR kökenli, TR-dilli arayüz.
- İkisi de tek başına AYAZ'ın "tek çatı" vaadini karşılamıyor; ikisi de AYAZ'ın farklı modüllerine güçlü referans.

---

## SignalSight

- **Ne yapar / kime (ICP):** Web/offline olaylarını yakalayıp reklam platformlarına **sunucu-taraflı (CAPI)**
  yönlendiren first-party tracking + dönüşüm ağ geçidi; ayrıca lead formları ve landing page. iOS/çerez kaybıyla
  sinyal kaybeden **e-ticaret/performans pazarlamacıları**. Modüler servisler halinde satılıyor.
  (Hesap: EASYCEP BİLİŞİM A.Ş., konsol + app iki subdomain.)

- **Menü/IA:**
  - **DASHBOARD** (Overview): Sources → Destinations akış görünümü, "New Reports Available" (AI rapor), Recent Activities.
  - **BUSINESS:** Details · **Subscriptions** · Teammates · Invoices · Payment Methods (faturalama `console.signalsight.io`).
  - **SIGNAL:** **Trackers** · Sources.
  - **LEADS** (lead formları — abonelik gerektiriyor, "On Hold").
  - **LANDING PAGE** (landing page builder — Free).
  - Get Help · Notifications (10).

- **Çekirdek iş akışı (ekran ekran):**
  1. **Dashboard:** Görsel **Sources → Destinations**. Sources = "Web Site Javascript (2)"; Destinations =
     **Meta Pixel** + **Meta Conversions (CAPI)**. "Otomatik üretilen AI raporun hazır" kartı (2 rapor: EasyCep, EasyCep Offline).
  2. **Trackers (SIGNAL):** Görsel **Sources → Tracker → Destinations** boru hattı + "ADD TRACKER". Tracker'lar:
     **EASYCEP OFFLINE** (offline yükleme → Facebook), **EASYCEP TIKTOK** (web → TikTok, 2 olay),
     **EASYCEP** (web → Facebook 2 + TikTok 1). Her tracker'da göz (önizleme) / ayar / istatistik.
  3. **Tracker ayarı (3 sekme):**
     - **Test Events:** canlı olay doğrulayıcı — `test_event_code` ile pixel testi; Events / Requests; "web, app ve
       server olaylarının doğru geldiğini doğrula" (Auto Refresh).
     - **Event Configuration:** *"Enable or disable individual events to include them in your CAPI setup."*
       Gerçek olaylar on/off + günlük sayım + trend grafiği: **Add to cart 1266, Initiate Checkout 861, sd 728, Page View 603**.
     - **Cookie Consent:** bir cookie değişkeni adı tanımlıyorsun; SignalSight consent durumunu kontrol edip
       **yalnız consent=true/1 ise olay gönderiyor** (consent-mode / KVKK-GDPR).
  4. **Tracker raporu:** **Total Events 4861, Total Errors 0**, tarih/Pixel/Status filtreleri, olay grafiği,
     **AI REPORT** (PDF) + indirilebilir rapor ("EASY CEP'(N)IN PIKSELI ...").
  5. **Subscriptions (fiyat):** Servis bazlı tablo — Signal Service Tier 1 **$119** (9,3K, Active), Lead Service Tier 1
     **$299** (On Hold), Landing Page Service **Free** (Active). Her servise ayrı "LOGIN".

- **Öne çıkan/ayrıştırıcı özellikler:**
  - **CAPI ağ geçidi** (Meta Pixel + Meta Conversions + TikTok Events API), olay başına on/off.
  - **Consent-mode** (cookie değişkeni ile olay tetikleme) — gizlilik-uyumlu sunucu-taraflı izleme.
  - **Canlı olay debugger** (Test Events / Requests) + **olay-iletim sağlığı** (Total Events/Errors).
  - **AI rapor** (PDF) ve **offline conversions** (offline kaynak → Meta).
  - Lead + Landing page modülleri (aynı çatı altında huni tamamlayıcı).

- **Kullanıcıyı mutlu eden UX detayları:**
  - Görsel **Sources → Tracker → Destinations** boru hattı (akış bir bakışta anlaşılıyor).
  - Event Configuration'da gerçek sayılar + trend; "neyi gönderiyorum" şeffaf.
  - test_event_code ile güvenli test; Total Errors=0 güveni.

- **Eksik/zayıf/kafa karıştıran yanlar:**
  - **i18n/hata sızıntısı:** "Lead Forms Packages.DeactivationReason.null" gibi ham anahtarlar görünüyor.
  - **Modüller silo:** her servise ayrı LOGIN, app + console iki subdomain — bütünlük zayıf.
  - **Leads ücret duvarı arkasında** ("Lead Service Activation" modalı), Lead Service "On Hold".
  - Yalnız Meta + TikTok destinations (Google Ads/Enhanced Conversions, GA4 yok gibi); TR platformları yok.
  - Arayüz yer yer ham/eski; navigasyon menüsü toggle davranışı kararsız.

- **AYAZ için fikir tohumları:**
  1. **CAPI ağ geçidini AYAZ'a yerel göm** (SignalSight ayrı $119 servis olarak satıyor) — Meta+TikTok+**Google Enhanced Conversions**+GA4.
  2. **Görsel Source → Tracker → Destination** kurgusu + **olay başına on/off + günlük sayım/trend**.
  3. **Consent-mode'u KVKK-native yap** (cookie değişkeni + TR rıza metinleri) — kutudan çıkan uyum.
  4. **Canlı olay debugger** (Test Events/Requests) + **iletim sağlığı paneli** (Total Events/Errors).
  5. **Offline conversions** (mağaza/çağrı merkezi → Meta) — TR omnichannel için değerli.
  6. **AI olay-kalite raporu** (eksik parametre, düşük eşleşme oranı, hata teşhisi).

- **Ekran görüntüsü ref / fiyat:** Bkz. `screenshots-signalsight-radaar/` (Dashboard, Trackers, Test Events, Event
  Configuration, Cookie Consent, Tracker Report, Subscriptions). **Fiyat:** modüler servis — Signal **$119/ay** (kullanım-tier),
  Lead **$299/ay**, Landing Page **Free**.

---

## RADAAR

- **Ne yapar / kime (ICP):** Çok-kanallı **sosyal medya yönetim platformu** — yayınlama/planlama, birleşik sosyal
  inbox, dinleme, analitik. Marka, ajans ve girişimler. **TR kökenli, TR-dilli arayüz** (dash.radaar.io).
  (Hesap: "Easycep Official", workspace EasyCep, **Profesyonel** plan, 11 bağlı kanal.)

- **Menü/IA:**
  - **Genel** (Overview): onboarding checklist, Görüşmeler, Dijital İzleme, Yaklaşan Paylaşımlar.
  - **Gelen Kutusu:** **Görüşmeler** (birleşik sosyal inbox) · **Kişiler** (sosyal CRM).
  - **Dijital İzleme** (sosyal dinleme/mention).
  - **Yayınlama 4.0:** **İçerik Takvimi** · İçerik Havuzu · **Akışlar** (RSS) · Keşfet · Yardımcı Araçlar.
  - **Raporlama 2.0:** **Kanallar** · Özel · Eskisi.
  - **Şifre Yöneticisi** · **Yardımcı Araçlar** · Ayarlar · **Görev Yöneticisi** · Ödemeler · Hesabım · Yardım Merkezi.

- **Çekirdek iş akışı (ekran ekran):**
  1. **Genel (dashboard):** "Başlamadan Önce" checklist (Kimlik Doğrulama → Kanal bağla → Ekip → İlk Paylaşım);
     **Görüşmeler** (gelen mesaj/yorum), **Dijital İzleme** (#easycep mention'ları), **Yaklaşan Paylaşımlar** (takvim).
  2. **Yayınlama → İçerik Takvimi:** Aylık takvim; onay akışı durumları **Taslak → Onay Bekleyen → Takvimlendi →
     İşlemde → Paylaşıldı → Hatalı**. Besteci menüsü: Yeni Paylaşım, **Tekrar Eden Paylaşım**, **Toplu Yükleme**,
     **Tetikleyiciler (BETA — otomasyon)**, **Yapay Zeka İçerik Üreticisi (BETA — AI)**, Dışa Aktar.
  3. **Besteci (Yeni Paylaşım):** Tarih/saat; **Kanallar** seçimi → **11 bağlı kanal** (Instagram, Twitter/X, Facebook,
     YouTube, LinkedIn ⚡, TikTok ⚡, çoklu **Google Business** lokasyonu ⚡); içerik tipleri (görsel/video/galeri/link/
     metin/story/carousel); medya yükleme (maks 25MB); **Taslak / Yayınla**. (⚡ = mobil/bildirimli yayın gerektiren ağlar.)
  4. **Gelen Kutusu → Görüşmeler:** Tüm kanallardan yorum/DM/mention **tek kuyrukta**; filtreler (Klasör/Tip/Kanal/
     Kaynak/Öncelik/Etiket); **atama** (ör. "asya parlar"), duygu işaretleri, "..." aksiyonları; **Kişiler** = sosyal CRM.
     (Gerçek EasyCep müşteri mesajları: şikâyetler, sorular.)
  5. **Raporlama → Kanallar:** Kanal-bazlı analitik (Genel Bakış / Kitle / Paylaşımlar / Görüntüleme / Erişim /
     Etkileşim). Gerçek: **620 paylaşım, 86.316 takipçi (↓-100), 6 takip**, takipçi büyüme grafiği, bağlantı tıklamaları.
     Özel + Eskisi rapor; export/yazdır/paylaş.

- **Öne çıkan/ayrıştırıcı özellikler:**
  - **Çok geniş kanal desteği** (Instagram/FB/X/LinkedIn/YouTube/TikTok/Pinterest + WhatsApp/Telegram/SMS/Google Business).
  - **Onay akışı** (Taslak→Onay Bekleyen→...→Paylaşıldı) — ajans/ekip iş birliği.
  - **Birleşik sosyal inbox + sosyal CRM (Kişiler)** + atama/etiket/öncelik.
  - **Tetikleyiciler** (otomasyon) ve **Yapay Zeka İçerik Üreticisi** (AI post generator).
  - **Şifre Yöneticisi** (sosyal hesap kimlikleri), **Görev Yöneticisi**, RSS **Akışlar**, içerik havuzu.

- **Kullanıcıyı mutlu eden UX detayları:**
  - Tek bestiyle **11 kanala** aynı anda; içerik tipleri + story/carousel.
  - "Değişiklikleri Kaydetme?" çıkış koruması (kazara taslak kaybını önler).
  - Onboarding checklist; TR-dilli, sade akış; takvimde durum renk kodları.

- **Eksik/zayıf/kafa karıştıran yanlar:**
  - Yalnız **organik sosyal**; ücretli reklam, feed, dönüşüm/tracking yok.
  - Analitik standart (derin attribution/ROAS yok); bazı güçlü özellikler **BETA**.
  - Çok modül (Şifre Yöneticisi, Görev Yöneticisi) odak dağıtabilir.
  - ⚡ kanallarda (TikTok/IG/GBP) doğrudan API yerine mobil/bildirimli yayın sürtünmesi.

- **AYAZ için fikir tohumları:**
  1. **Çok-kanallı içerik takvimi + besteci** (tek bestiyle N kanal, içerik tipleri, story/carousel) — organik ayak.
  2. **Onay akışı** (Taslak→Onay→Takvim→Paylaşıldı) — TR ajansları için ekip/müşteri onayı.
  3. **Birleşik sosyal inbox + sosyal CRM** (atama/etiket/öncelik/duygu) — sosyal müşteri hizmetleri.
  4. **AI İçerik Üreticisi + Tetikleyiciler** — AYAZ AI Copilot'un organik-içerik üretme + otomasyon kolu.
  5. **TR kanal genişliği** (WhatsApp/Telegram/SMS/Google Business mağaza lokasyonları) — TR KOBİ gerçeği.
  6. **RSS Akışlar + içerik havuzu** ile içerik beslemesi.

- **Ekran görüntüsü ref / fiyat:** Bkz. `screenshots-signalsight-radaar/` (Dashboard, İçerik Takvimi, Besteci, Kanallar(11),
  Görüşmeler/inbox, Raporlama, Pricing). **Fiyat:** **Standard $9.99 / Professional $29.99 (en popüler — EasyCep'in planı) /
  Advanced $149.99/ay**; 14 gün ücretsiz deneme; yıllık %30 indirim. Self-serve.

---

## AYAZ için 4 birleşik çıkarım (SignalSight + RADAAR)

1. **AYAZ tek çatıda 3 ayağı birleştirebilir:** paid (Funnel/Adin/Channable tarafı) + **server-side ölçüm (SignalSight tarafı)**
   + **organik sosyal & içerik (RADAAR tarafı)**. Hiçbir rakip üçünü birden vermiyor — AYAZ'ın asıl wedge'i bu.
2. **Server-side + KVKK native:** SignalSight'ın CAPI/consent yaklaşımını al, **KVKK-uyumlu + Google/GA4 dahil + TR
   platformlara** genişlet; ayrı $119 servis yerine AYAZ'a **gömülü** sun.
3. **Organik sosyalde TR kanal genişliği + onay akışı + sosyal inbox/CRM** (RADAAR'dan) — ama AYAZ'da **paid verisiyle aynı
   raporda** birleşik (organik+paid tek görünüm).
4. **AI Copilot iki yönlü:** RADAAR'ın AI içerik üreticisi (üretim) + SignalSight'ın AI olay/rapor (analiz) →
   AYAZ'da **TR-dilli, hem içerik üreten hem ölçüm/dönüşüm teşhisi yapan** tek copilot.

---
*Hazırlayan: Claude (Claude Code) · Kaynak: 2026-06-28 canlı panel gezintisi (EasyCep hesapları).*
