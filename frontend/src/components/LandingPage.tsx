'use client';

import Link from 'next/link';
import styles from './LandingPage.module.css';

// ---------------------------------------------------------------------------
// Static data — no API calls needed on the landing page
// ---------------------------------------------------------------------------

const FEATURES = [
  {
    icon: '📊',
    title: 'Birleşik Panel',
    desc: 'Google Ads, Meta, TikTok, e-posta ve daha fazlasından gelen tüm verileri tek ekranda görün.',
  },
  {
    icon: '🤖',
    title: 'AI Copilot (Türkçe)',
    desc: 'Yapay zeka, performansınızı Türkçe yorumlar ve bir sonraki aksiyonu size adım adım söyler.',
  },
  {
    icon: '🔔',
    title: 'Otomatik İçgörü & Uyarı',
    desc: 'Anormallikler ve fırsatlar tespit edildiğinde anında bildirim alın; fırsatları kaçırmayın.',
  },
  {
    icon: '💰',
    title: 'Bütçe Optimizasyonu',
    desc: "Bütçenizi kanallar arasında otomatik dağıtın, harcama israfını önleyin, ROAS'ı artırın.",
  },
  {
    icon: '🛍️',
    title: 'Feed Yönetimi',
    desc: "Ürün feed'lerinizi tek merkezden güncelleyin; onlarca platforma anında yayın.",
  },
  {
    icon: '📣',
    title: 'Reklam Yönetimi',
    desc: 'Tüm kanallardaki kampanyalarınızı oluşturun, düzenleyin ve duraklatın — tek arayüzden.',
  },
  {
    icon: '📋',
    title: 'Proaktif Günlük Brifing',
    desc: 'Her sabah size özel hazırlanan özet rapor; güne hazır başlayın.',
  },
  {
    icon: '🎯',
    title: 'Hedef & Forecasting',
    desc: 'KPI hedefleri belirleyin, AI destekli tahminlerle bütçe planlamanızı optimize edin.',
  },
  {
    icon: '📄',
    title: 'Rapor Oluşturucu',
    desc: 'Müşteri ve yönetici raporlarını saniyeler içinde oluşturun; PDF veya canlı link olarak paylaşın.',
  },
  {
    icon: '📡',
    title: 'Server-side Ölçümleme',
    desc: 'Çerez kısıtlamalarını aşın; dönüşümleri sunucu tarafında güvenilir biçimde izleyin.',
  },
];

const PRICING_PLANS = [
  {
    code: 'free',
    name: 'Free',
    price: '₺0',
    period: '/ay',
    badge: null,
    features: [
      '1 veri kaynağı',
      'Birleşik panel',
      '30 günlük veri geçmişi',
      'E-posta desteği',
    ],
    cta: 'Ücretsiz Başla',
    highlighted: false,
  },
  {
    code: 'starter',
    name: 'Starter',
    price: '₺1.490',
    period: '/ay',
    badge: null,
    features: [
      '5 veri kaynağı',
      'AI Copilot (Türkçe)',
      '6 aylık veri geçmişi',
      'Günlük brifing',
      'Öncelikli destek',
    ],
    cta: 'Başla',
    highlighted: false,
  },
  {
    code: 'growth',
    name: 'Growth',
    price: '₺4.900',
    period: '/ay',
    badge: 'Önerilen',
    features: [
      '20 veri kaynağı',
      'Tüm AI özellikleri',
      'Sınırsız veri geçmişi',
      'Bütçe optimizasyonu',
      'Feed & reklam yönetimi',
      'Server-side ölçümleme',
    ],
    cta: 'Başla',
    highlighted: true,
  },
  {
    code: 'agency',
    name: 'Agency',
    price: '₺12.900',
    period: '/ay',
    badge: null,
    features: [
      'Sınırsız veri kaynağı',
      'Çoklu çalışma alanı',
      'White-label raporlar',
      'API erişimi',
      'Özel onboarding',
      'SLA desteği',
    ],
    cta: 'Başla',
    highlighted: false,
  },
];

const DIFFERENTIATORS = [
  { icon: '🇹🇷', title: 'Türkçe AI', desc: 'Önerileri ana dilinizde alın.' },
  { icon: '🏠', title: 'Tek Çatı', desc: 'Her araç, tek abonelikte.' },
  { icon: '⚡', title: 'Proaktif Zekâ', desc: 'AI sizi beklemez, önce hareket eder.' },
  { icon: '🔐', title: 'KVKK Uyumlu', desc: 'Yerel ödeme, Türkiye sunucuları.' },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LandingPage() {
  return (
    <div className={styles.page}>
      {/* ---- Top Bar ---- */}
      <header className={styles.topbar}>
        <div className={styles.topbarInner}>
          <span className={styles.brand}>AYAZ</span>
          <nav className={styles.topNav}>
            <a href="#features" className={styles.topNavLink}>Özellikler</a>
            <a href="#pricing" className={styles.topNavLink}>Fiyatlandırma</a>
            <Link href="/login" className={styles.topNavLink}>Giriş Yap</Link>
            <Link href="/signup" className={styles.topNavCta}>Ücretsiz Başla</Link>
          </nav>
          <button className={styles.mobileMenuToggle} aria-label="Menü">
            <span />
            <span />
            <span />
          </button>
        </div>
      </header>

      {/* ---- Hero ---- */}
      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <div className={styles.heroBadge}>Türkiye'nin Dijital Pazarlama Paneli</div>
          <h1 className={styles.heroHeadline}>
            Tüm dijital pazarlamanız tek panelde —<br className={styles.heroBreak} />
            ve AI size ne yapmanız gerektiğini <span className={styles.heroAccent}>Türkçe</span> söyler
          </h1>
          <p className={styles.heroSub}>
            Google Ads, Meta, TikTok, e-posta ve daha fazlasını birleştiren AYAZ;
            datanızı analiz eder, fırsatları tespit eder ve sizi proaktif olarak yönlendirir.
          </p>
          <div className={styles.heroCtas}>
            <Link href="/signup" className={styles.ctaPrimary}>Ücretsiz Başla</Link>
            <a href="#features" className={styles.ctaSecondary}>Demoyu Gör</a>
          </div>
          <p className={styles.heroNote}>Kredi kartı gerekmez · Kurulum 5 dakika</p>
        </div>
        <div className={styles.heroGlow} aria-hidden="true" />
      </section>

      {/* ---- Problem → Solution ---- */}
      <section className={styles.problemSection}>
        <div className={styles.container}>
          <div className={styles.problemGrid}>
            <div className={styles.problemCol}>
              <h2 className={styles.problemTitle}>10 ayrı panel yerine tek çatı</h2>
              <p className={styles.problemSub}>Şu an nasıl çalışıyorsunuz?</p>
              <ul className={styles.painList}>
                <li className={styles.painItem}>
                  <span className={styles.painIcon}>✗</span>
                  Her platform için ayrı hesap, ayrı şifre, ayrı sekme
                </li>
                <li className={styles.painItem}>
                  <span className={styles.painIcon}>✗</span>
                  Veriler birbirini tutmuyor; hangisine inanacağınızı bilmiyorsunuz
                </li>
                <li className={styles.painItem}>
                  <span className={styles.painIcon}>✗</span>
                  Raporlar saatler alıyor, müşteri bekliyor
                </li>
                <li className={styles.painItem}>
                  <span className={styles.painIcon}>✗</span>
                  Bütçe israfı görünmüyor; reklam kendi başına harcıyor
                </li>
              </ul>
            </div>
            <div className={styles.solutionCol}>
              <p className={styles.solutionLabel}>AYAZ ile</p>
              <ul className={styles.solveList}>
                <li className={styles.solveItem}>
                  <span className={styles.solveIcon}>✓</span>
                  Tüm kanallar tek panelde, gerçek zamanlı
                </li>
                <li className={styles.solveItem}>
                  <span className={styles.solveIcon}>✓</span>
                  AI, çelişen verileri normalize eder ve tek doğruyu gösterir
                </li>
                <li className={styles.solveItem}>
                  <span className={styles.solveIcon}>✓</span>
                  Raporlar otomatik oluşturulur; tek tıkla paylaşılır
                </li>
                <li className={styles.solveItem}>
                  <span className={styles.solveIcon}>✓</span>
                  Bütçe uyarıları anında gelir; optimizasyon önerileri hazır bekler
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ---- Features ---- */}
      <section id="features" className={styles.featuresSection}>
        <div className={styles.container}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>Tek platformda her şey</h2>
            <p className={styles.sectionSub}>
              Ayrı araçlar için ayrı abonelik ödemeyin. AYAZ'da her şey dahil.
            </p>
          </div>
          <div className={styles.featuresGrid}>
            {FEATURES.map((f) => (
              <div key={f.title} className={styles.featureCard}>
                <div className={styles.featureIcon}>{f.icon}</div>
                <h3 className={styles.featureTitle}>{f.title}</h3>
                <p className={styles.featureDesc}>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---- Differentiators band ---- */}
      <section className={styles.diffSection}>
        <div className={styles.container}>
          <h2 className={styles.diffTitle}>Neden AYAZ?</h2>
          <div className={styles.diffGrid}>
            {DIFFERENTIATORS.map((d) => (
              <div key={d.title} className={styles.diffCard}>
                <span className={styles.diffIcon}>{d.icon}</span>
                <strong className={styles.diffCardTitle}>{d.title}</strong>
                <span className={styles.diffCardDesc}>{d.desc}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---- Pricing ---- */}
      <section id="pricing" className={styles.pricingSection}>
        <div className={styles.container}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>Şeffaf Fiyatlandırma</h2>
            <p className={styles.sectionSub}>
              Gizli ücret yok. İstediğiniz zaman plan değiştirin.
            </p>
          </div>
          <div className={styles.pricingGrid}>
            {PRICING_PLANS.map((plan) => (
              <div
                key={plan.code}
                className={`${styles.pricingCard} ${plan.highlighted ? styles.pricingCardHighlighted : ''}`}
              >
                {plan.badge && (
                  <div className={styles.pricingBadge}>{plan.badge}</div>
                )}
                <div className={styles.pricingName}>{plan.name}</div>
                <div className={styles.pricingPrice}>
                  <span className={styles.pricingAmount}>{plan.price}</span>
                  <span className={styles.pricingPeriod}>{plan.period}</span>
                </div>
                <ul className={styles.pricingFeatures}>
                  {plan.features.map((f) => (
                    <li key={f} className={styles.pricingFeatureItem}>
                      <span className={styles.pricingCheck}>✓</span>
                      {f}
                    </li>
                  ))}
                </ul>
                <Link
                  href="/signup"
                  className={`${styles.pricingCta} ${plan.highlighted ? styles.pricingCtaHighlighted : ''}`}
                >
                  {plan.cta}
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ---- Closing CTA ---- */}
      <section className={styles.closingSection}>
        <div className={styles.container}>
          <h2 className={styles.closingTitle}>Dijital pazarlamanızı bugün birleştirin</h2>
          <p className={styles.closingSub}>
            Dakikalar içinde bağlanın. Hemen analizlere başlayın.
          </p>
          <div className={styles.closingCtas}>
            <Link href="/signup" className={styles.ctaPrimary}>Ücretsiz Hesap Oluştur</Link>
            <Link href="/dashboard" className={styles.ctaSecondary}>Panele Git</Link>
          </div>
        </div>
      </section>

      {/* ---- Footer ---- */}
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div className={styles.footerBrand}>
            <span className={styles.footerLogo}>AYAZ</span>
            <span className={styles.footerTagline}>Dijital Pazarlama Paneli</span>
          </div>
          <div className={styles.footerLinks}>
            <a href="#" className={styles.footerLink}>Gizlilik Politikası</a>
            <a href="#" className={styles.footerLink}>KVKK Aydınlatma Metni</a>
            <a href="#" className={styles.footerLink}>Kullanım Koşulları</a>
            <a href="mailto:destek@ayaz.app" className={styles.footerLink}>Destek</a>
          </div>
          <div className={styles.footerCopy}>
            &copy; {new Date().getFullYear()} AYAZ. Tüm hakları saklıdır.
          </div>
        </div>
      </footer>
    </div>
  );
}
