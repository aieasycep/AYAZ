# AYAZ — Piyasada Farklılaştırma Backlog'u (otonom çalışma planı)

> Hedef: yarın sabah 10:00 TRT'ye kadar otonom geliştirme. Ürünü piyasada
> farklılaştıracak, **kimliksiz (no-cred)**, görünür ve test+build yeşil
> dalgalar. Her dalga: tasarla → uzman ajanlarla yap → entegre et → test →
> ekran görüntüsü → commit → push (PR #1). Sıra değer/etki + "10:00 UI review"
> görünürlüğüne göre.

## Tamamlanan persona çekirdeği (Dalga 55–66)
Performans, Planlama (Bütçe + Plan vs Gerçekleşen), Müşteri Hizmetleri (Sosyal
Gelen Kutusu), CMO (Yönetici Görünümü), Marcom (İçerik + Takvim + Kreatif Lensi
+ köprü) + tek Copilot (tüm modül farkındalığı).

## Farklılaştırma dalgaları (sıra)
1. **Komuta Merkezi (Command Center)** — rol-farkında birleşik ana ekran: tüm
   modüllerden "şu an dikkat" aksiyon akışı + KPI + modül durum kartları.
   "Tek panel" vaadinin vitrini. (Dalga 67) — reuse: copilot_tools read fns.
2. **Hesap Sağlık Taraması (Account Audit)** — tek tıkla denetim: kampanya/
   kreatif/ölçümleme/consent/bütçe tara → skorlu sorun + çözüm listesi.
   Pazarlama açısı: "ücretsiz hesap denetimi". (Dalga 68)
3. **Rol-bazlı görünümler & izinler** — her ekip kendi ekranına düşer; ince
   izin. ✅ rol görünümü (Dalga 75); ince-izin/RBAC ileride.
4. **AI Haftalık Strateji / Proaktif Öneri Merkezi** — haftalık doğal-dil
   strateji + öneri kuyruğu (kabul/ertele/reddet). ✅ (Dalga 71)
5. **KVKK / Consent Yönetim Merkezi** — TR-first: tüm consent ayarları + rıza
   denetim izi tek yerde. ✅ (Dalga 72)
6. **Onboarding Sihirbazı** — ilk kurulum: hesap bağla → hedef koy → ilk
   içerik/bütçe; sellability. ✅ (Dalga 69)
7. **Çoklu-dil (TR/EN)** — global hedef için arayüz dil anahtarı.
8. **Benchmark / sektör kıyas** — sentetik sektör ortalamasına göre konum. ✅ (Dalga 70)
9. **Bildirim/Alarm Merkezi UI** + kural derinleştirme.
10. **Veri dışa aktarma / paylaşılabilir özet** derinleştirme.

> Not: gerçekleşen sıra — Dalga 67 Komuta Merkezi, 68 Denetim, 69 Onboarding,
> 70 Kıyaslama, 71 Öneri Merkezi, 72 KVKK Rıza Merkezi, 73 AI Reklam Metni
> Stüdyosu, 74 Bütçe Senaryo Simülatörü, 75 Rol Görünümü, 76 Dönüşüm Hunisi.
> Bildirim/Alarm Merkezi (9) zaten mevcut (NotificationBell + /notifications +
> notifications_center). Kalan no-cred adaylar: Çoklu-dil (7, riskli — kullanıcı
> incelemesinde), Veri dışa aktarma (10), RBAC ince-izin (3).

## Kurallar
- Sadece no-cred; canlı/kimlik gerektiren kısımlar net "kimlik bekliyor" gate'li.
- Her dalga: backend test + frontend test + build yeşil; Türkçe diakritik doğru.
- Demo seed ile her özellik dolu görünür (10:00 UI review için).
- Deploy konfigleri hazır (render.yaml); kullanıcı 10:00'da render.com kurar.
