'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { logout as logoutApi } from '@/lib/api';
import WorkspaceSwitcher from './WorkspaceSwitcher';
import styles from './AppNav.module.css';

const NAV_LINKS = [
  { href: '/dashboard', label: 'Panel' },
  { href: '/assistant', label: 'Asistan' },
  { href: '/briefing', label: 'Brifing' },
  { href: '/insights', label: 'İçgörüler' },
  { href: '/connections', label: 'Bağlantılar' },
  { href: '/feeds', label: 'Feed Yönetimi' },
  { href: '/reports', label: 'Raporlar' },
  { href: '/report-builder', label: 'Rapor Oluşturucu' },
  { href: '/ads', label: 'Reklam' },
  { href: '/creatives', label: 'Kreatifler' },
  { href: '/optimizer', label: 'Optimizasyon' },
  { href: '/goals', label: 'Hedefler' },
  { href: '/automation', label: 'Otomasyon' },
  { href: '/tracking', label: 'Ölçümleme' },
  { href: '/billing', label: 'Faturalama' },
  { href: '/workspaces', label: 'Çalışma Alanları' },
];

export default function AppNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Close drawer on route change
  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  // Prevent body scroll when drawer is open
  useEffect(() => {
    if (drawerOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [drawerOpen]);

  async function handleLogout() {
    await logoutApi(); // revoke server-side (best-effort) + clear local token
    router.push('/login');
  }

  return (
    <>
      <header className={styles.topbar}>
        <div className={styles.inner}>
          {/* Left: brand + desktop nav */}
          <div className={styles.left}>
            <span className={styles.brand}>AYAZ</span>
            <nav className={styles.nav} aria-label="Ana menü">
              {NAV_LINKS.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`${styles.navLink} ${pathname === link.href ? styles.navLinkActive : ''}`}
                >
                  {link.label}
                </Link>
              ))}
            </nav>
          </div>

          {/* Right: workspace switcher + logout (desktop) + hamburger (mobile) */}
          <div className={styles.right}>
            <div className={styles.desktopOnly}>
              <WorkspaceSwitcher />
            </div>
            <button className={`${styles.logoutBtn} ${styles.desktopOnly}`} onClick={handleLogout}>
              Oturumu Kapat
            </button>

            {/* Hamburger — mobile only */}
            <button
              className={styles.hamburger}
              onClick={() => setDrawerOpen((prev) => !prev)}
              aria-label={drawerOpen ? 'Menüyü kapat' : 'Menüyü aç'}
              aria-expanded={drawerOpen}
              aria-controls="mobile-drawer"
            >
              <span className={`${styles.hamburgerLine} ${drawerOpen ? styles.hamburgerLineTopOpen : ''}`} />
              <span className={`${styles.hamburgerLine} ${drawerOpen ? styles.hamburgerLineMidOpen : ''}`} />
              <span className={`${styles.hamburgerLine} ${drawerOpen ? styles.hamburgerLineBotOpen : ''}`} />
            </button>
          </div>
        </div>
      </header>

      {/* Mobile drawer overlay */}
      {drawerOpen && (
        <div
          className={styles.overlay}
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Mobile drawer */}
      <nav
        id="mobile-drawer"
        className={`${styles.drawer} ${drawerOpen ? styles.drawerOpen : ''}`}
        aria-label="Mobil menü"
      >
        <div className={styles.drawerHeader}>
          <span className={styles.drawerBrand}>AYAZ</span>
          <WorkspaceSwitcher />
        </div>

        <div className={styles.drawerLinks}>
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`${styles.drawerLink} ${pathname === link.href ? styles.drawerLinkActive : ''}`}
            >
              {link.label}
            </Link>
          ))}
        </div>

        <div className={styles.drawerFooter}>
          <button className={styles.drawerLogoutBtn} onClick={handleLogout}>
            Oturumu Kapat
          </button>
        </div>
      </nav>
    </>
  );
}
