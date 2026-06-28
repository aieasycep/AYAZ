'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { logout as logoutApi } from '@/lib/api';
import WorkspaceSwitcher from './WorkspaceSwitcher';
import NotificationBell from './NotificationBell';
import { useTheme } from './ThemeProvider';
import styles from './AppNav.module.css';
import CommandPalette from './CommandPalette';
import QuickAsk from './QuickAsk';

export const NAV_LINKS = [
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
  { href: '/content', label: 'İçerik' },
  { href: '/optimizer', label: 'Optimizasyon' },
  { href: '/goals', label: 'Hedefler' },
  { href: '/automation', label: 'Otomasyon' },
  { href: '/tracking', label: 'Ölçümleme' },
  { href: '/billing', label: 'Faturalama' },
  { href: '/workspaces', label: 'Çalışma Alanları' },
  { href: '/settings', label: 'Ayarlar' },
];

// Resolve what the toggle button should look like given the stored theme.
// Shows a sun when dark mode is active (click → go light), moon otherwise.
function useResolvedDark(): boolean {
  const { theme } = useTheme();
  const [osDark, setOsDark] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    setOsDark(mq.matches);
    const handler = (e: MediaQueryListEvent) => setOsDark(e.matches);
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  if (theme === 'dark') return true;
  if (theme === 'light') return false;
  return osDark; // system
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const isDark = useResolvedDark();

  function toggle() {
    // Cycle: light → dark → system
    if (theme === 'light') setTheme('dark');
    else if (theme === 'dark') setTheme('system');
    else setTheme('light');
  }

  const label = isDark ? 'Açık temaya geç' : 'Koyu temaya geç';

  return (
    <button
      className={styles.themeToggle}
      onClick={toggle}
      aria-label={label}
      title={label}
      type="button"
    >
      {isDark ? (
        /* Sun icon */
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="5"/>
          <line x1="12" y1="1" x2="12" y2="3"/>
          <line x1="12" y1="21" x2="12" y2="23"/>
          <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
          <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
          <line x1="1" y1="12" x2="3" y2="12"/>
          <line x1="21" y1="12" x2="23" y2="12"/>
          <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
          <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
        </svg>
      ) : (
        /* Moon icon */
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      )}
    </button>
  );
}

export default function AppNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [quickAskOpen, setQuickAskOpen] = useState(false);

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

          {/* Right: workspace switcher + veriye-sor + notification bell + theme toggle + logout (desktop) + hamburger (mobile) */}
          <div className={styles.right}>
            <div className={styles.desktopOnly}>
              <WorkspaceSwitcher />
            </div>
            {/* "Veriye Sor" — persistent quick-ask button */}
            <button
              className={`${styles.quickAskBtn} ${styles.desktopOnly}`}
              onClick={() => setQuickAskOpen(true)}
              aria-label="Veriye Sor — yapay zeka asistanına soru sor"
              title="Veriye Sor (yapay zeka)"
              type="button"
            >
              {/* Spark / bolt icon */}
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
              Veriye Sor
            </button>
            <NotificationBell />
            <ThemeToggle />
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

      {/* Command palette — global ⌘K / Ctrl+K quick nav */}
      <CommandPalette onOpenQuickAsk={() => setQuickAskOpen(true)} />

      {/* QuickAsk modal — rendered at root level, inside AppNav wrapper */}
      {quickAskOpen && (
        <QuickAsk onClose={() => setQuickAskOpen(false)} />
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
          <div className={styles.drawerFooterTop}>
            <NotificationBell />
            <ThemeToggle />
          </div>
          {/* "Veriye Sor" — mobile drawer entry */}
          <button
            className={styles.drawerQuickAskBtn}
            onClick={() => {
              setDrawerOpen(false);
              setQuickAskOpen(true);
            }}
            aria-label="Veriye Sor — yapay zeka asistanına soru sor"
            type="button"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
            </svg>
            Veriye Sor
          </button>
          <button className={styles.drawerLogoutBtn} onClick={handleLogout}>
            Oturumu Kapat
          </button>
        </div>
      </nav>
    </>
  );
}
