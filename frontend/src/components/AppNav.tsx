'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { logout as logoutApi } from '@/lib/api';
import { getMe } from '@/lib/settings-api';
import NotificationBell from './NotificationBell';
import { useTheme } from './ThemeProvider';
import styles from './AppNav.module.css';
import CommandPalette from './CommandPalette';
import QuickAsk from './QuickAsk';
import WorkspaceSwitcher from './WorkspaceSwitcher';

// ---------------------------------------------------------------------------
// Flat nav links — KEEP as-is; CommandPalette imports this.
// ---------------------------------------------------------------------------

export const NAV_LINKS = [
  { href: '/command-center', label: 'Komuta Merkezi' },
  { href: '/dashboard', label: 'Panel' },
  { href: '/executive', label: 'Yönetici' },
  { href: '/briefing', label: 'Günlük Brifing' },
  { href: '/health-index', label: 'Sağlık Endeksi' },
  { href: '/content', label: 'İçerik & Takvim' },
  { href: '/inbox', label: 'Gelen Kutusu' },
  { href: '/marketing-calendar', label: 'Fırsat Takvimi' },
  { href: '/ads', label: 'Reklam Yönetimi' },
  { href: '/optimizer', label: 'Bütçe Optimizasyonu' },
  { href: '/budget-simulator', label: 'Bütçe Senaryosu' },
  { href: '/recommendations', label: 'Öneriler' },
  { href: '/ad-studio', label: 'Reklam Metni Stüdyosu' },
  { href: '/creatives', label: 'Kreatifler' },
  { href: '/creative-lens', label: 'Kreatif Lensi' },
  { href: '/insights', label: 'İçgörüler' },
  { href: '/funnel', label: 'Dönüşüm Hunisi' },
  { href: '/benchmark', label: 'Sektör Kıyaslama' },
  { href: '/audit', label: 'Hesap Taraması' },
  { href: '/reports', label: 'Raporlar' },
  { href: '/report-builder', label: 'Rapor Oluşturucu' },
  { href: '/goals', label: 'Hedefler' },
  { href: '/planning', label: 'Bütçe Planlayıcı' },
  { href: '/automation', label: 'Otomasyon' },
  { href: '/integrations', label: 'Entegrasyonlar' },
  { href: '/connections', label: 'Bağlantılar' },
  { href: '/feeds', label: 'Feed Yönetimi' },
  { href: '/tracking', label: 'Ölçümleme' },
  { href: '/consent', label: 'KVKK Rıza Merkezi' },
  { href: '/assistant', label: 'AI Asistanı' },
  { href: '/settings', label: 'Ayarlar' },
  { href: '/workspaces', label: 'Çalışma Alanları' },
  { href: '/billing', label: 'Faturalama' },
  { href: '/onboarding', label: 'Kurulum' },
  { href: '/roles', label: 'Rol Görünümü' },
  { href: '/notifications', label: 'Bildirimler' },
];

// ---------------------------------------------------------------------------
// Grouped nav — sidebar sections. Every href from NAV_LINKS appears in exactly
// one NAV_GROUPS entry OR in ACCOUNT_LINKS; no routes are dropped or duplicated.
// ---------------------------------------------------------------------------

export interface NavGroupLink {
  href: string;
  label: string;
}

export interface NavGroup {
  label: string;
  links: NavGroupLink[];
}

/** 9 sidebar section groups. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Genel Bakış',
    links: [
      { href: '/command-center', label: 'Komuta Merkezi' },
      { href: '/dashboard', label: 'Panel' },
      { href: '/executive', label: 'Yönetici' },
      { href: '/briefing', label: 'Günlük Brifing' },
      { href: '/health-index', label: 'Sağlık Endeksi' },
    ],
  },
  {
    label: 'Sosyal Medya',
    links: [
      { href: '/content', label: 'İçerik & Takvim' },
      { href: '/inbox', label: 'Gelen Kutusu' },
      { href: '/marketing-calendar', label: 'Fırsat Takvimi' },
    ],
  },
  {
    label: 'Reklam',
    links: [
      { href: '/ads', label: 'Reklam Yönetimi' },
      { href: '/optimizer', label: 'Bütçe Optimizasyonu' },
      { href: '/budget-simulator', label: 'Bütçe Senaryosu' },
      { href: '/recommendations', label: 'Öneriler' },
    ],
  },
  {
    label: 'Kreatif',
    links: [
      { href: '/ad-studio', label: 'Reklam Metni Stüdyosu' },
      { href: '/creatives', label: 'Kreatifler' },
      { href: '/creative-lens', label: 'Kreatif Lensi' },
    ],
  },
  {
    label: 'Analiz',
    links: [
      { href: '/insights', label: 'İçgörüler' },
      { href: '/funnel', label: 'Dönüşüm Hunisi' },
      { href: '/benchmark', label: 'Sektör Kıyaslama' },
      { href: '/audit', label: 'Hesap Taraması' },
    ],
  },
  {
    label: 'Raporlar',
    links: [
      { href: '/reports', label: 'Raporlar' },
      { href: '/report-builder', label: 'Rapor Oluşturucu' },
    ],
  },
  {
    label: 'Planlama',
    links: [
      { href: '/goals', label: 'Hedefler' },
      { href: '/planning', label: 'Bütçe Planlayıcı' },
      { href: '/automation', label: 'Otomasyon' },
    ],
  },
  {
    label: 'Veri & Entegrasyon',
    links: [
      { href: '/integrations', label: 'Entegrasyonlar' },
      { href: '/connections', label: 'Bağlantılar' },
      { href: '/feeds', label: 'Feed Yönetimi' },
      { href: '/tracking', label: 'Ölçümleme' },
      { href: '/consent', label: 'KVKK Rıza Merkezi' },
    ],
  },
  {
    label: 'AI Asistanı',
    links: [
      { href: '/assistant', label: 'AI Asistanı' },
    ],
  },
];

/**
 * Account / utility links — rendered in the account dropdown in the top strip
 * and in the mobile drawer. These routes are NOT in NAV_GROUPS.
 */
export const ACCOUNT_LINKS: NavGroupLink[] = [
  { href: '/settings', label: 'Ayarlar' },
  { href: '/workspaces', label: 'Çalışma Alanları' },
  { href: '/billing', label: 'Faturalama' },
  { href: '/onboarding', label: 'Kurulum' },
  { href: '/roles', label: 'Rol Görünümü' },
  { href: '/notifications', label: 'Bildirimler' },
];

// ---------------------------------------------------------------------------
// Inline SVG icons — 18×18 stroke style, keyed by group label
// ---------------------------------------------------------------------------

function IconGenel() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="3" width="7" height="7" rx="1"/>
      <rect x="14" y="3" width="7" height="7" rx="1"/>
      <rect x="3" y="14" width="7" height="7" rx="1"/>
      <rect x="14" y="14" width="7" height="7" rx="1"/>
    </svg>
  );
}

function IconSosyal() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M17 2H7a5 5 0 0 0-5 5v10a5 5 0 0 0 5 5h10a5 5 0 0 0 5-5V7a5 5 0 0 0-5-5z"/>
      <circle cx="12" cy="12" r="3"/>
      <circle cx="17.5" cy="6.5" r="1"/>
    </svg>
  );
}

function IconReklam() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
    </svg>
  );
}

function IconKreatif() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 20h9"/>
      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>
    </svg>
  );
}

function IconAnaliz() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="18" y1="20" x2="18" y2="10"/>
      <line x1="12" y1="20" x2="12" y2="4"/>
      <line x1="6" y1="20" x2="6" y2="14"/>
    </svg>
  );
}

function IconRaporlar() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
      <polyline points="14 2 14 8 20 8"/>
      <line x1="16" y1="13" x2="8" y2="13"/>
      <line x1="16" y1="17" x2="8" y2="17"/>
      <polyline points="10 9 9 9 8 9"/>
    </svg>
  );
}

function IconPlanlama() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
      <line x1="16" y1="2" x2="16" y2="6"/>
      <line x1="8" y1="2" x2="8" y2="6"/>
      <line x1="3" y1="10" x2="21" y2="10"/>
    </svg>
  );
}

function IconVeri() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <ellipse cx="12" cy="5" rx="9" ry="3"/>
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
    </svg>
  );
}

function IconAI() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
    </svg>
  );
}

const GROUP_ICONS: Record<string, () => JSX.Element> = {
  'Genel Bakış': IconGenel,
  'Sosyal Medya': IconSosyal,
  'Reklam': IconReklam,
  'Kreatif': IconKreatif,
  'Analiz': IconAnaliz,
  'Raporlar': IconRaporlar,
  'Planlama': IconPlanlama,
  'Veri & Entegrasyon': IconVeri,
  'AI Asistanı': IconAI,
};

// ---------------------------------------------------------------------------
// ThemeToggle
// ---------------------------------------------------------------------------

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
  return osDark;
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const isDark = useResolvedDark();

  function toggle() {
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
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
        </svg>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// AccountMenu — avatar + dropdown for account/utility links + logout
// ---------------------------------------------------------------------------

interface AccountMenuProps {
  pathname: string;
  onLogout: () => void;
}

function AccountMenu({ pathname, onLogout }: AccountMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [initials, setInitials] = useState('');
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    getMe()
      .then((profile) => {
        const name = profile.full_name?.trim();
        if (!name) return;
        const parts = name.split(/\s+/);
        const derived =
          parts.length >= 2
            ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
            : parts[0].slice(0, 2).toUpperCase();
        setInitials(derived);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    function handleClick(e: MouseEvent) {
      if (
        menuRef.current?.contains(e.target as Node) ||
        triggerRef.current?.contains(e.target as Node)
      ) {
        return;
      }
      setIsOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isOpen]);

  const isAccountActive = ACCOUNT_LINKS.some((l) => l.href === pathname);

  return (
    <div className={styles.accountMenuWrapper}>
      <button
        ref={triggerRef}
        type="button"
        className={`${styles.avatarBtn} ${isAccountActive ? styles.avatarBtnActive : ''}`}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-label="Hesap menüsü"
        title="Hesap menüsü"
        onClick={() => setIsOpen((prev) => !prev)}
      >
        {initials ? (
          <span className={styles.avatarInitials} aria-hidden="true">
            {initials}
          </span>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="8" r="4"/>
            <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
          </svg>
        )}
      </button>

      {isOpen && (
        <div
          ref={menuRef}
          className={styles.accountDropdown}
          role="menu"
          aria-label="Hesap menüsü"
        >
          {ACCOUNT_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              role="menuitem"
              className={`${styles.dropdownLink} ${pathname === link.href ? styles.dropdownLinkActive : ''}`}
              onClick={() => setIsOpen(false)}
            >
              {link.label}
            </Link>
          ))}
          <div className={styles.accountDivider} role="separator" />
          <button
            type="button"
            role="menuitem"
            className={styles.accountLogoutItem}
            onClick={() => {
              setIsOpen(false);
              onLogout();
            }}
          >
            Oturumu Kapat
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SidebarSection — one collapsible group in the sidebar
// ---------------------------------------------------------------------------

interface SidebarSectionProps {
  group: NavGroup;
  pathname: string;
}

function SidebarSection({ group, pathname }: SidebarSectionProps) {
  const isGroupActive = group.links.some((l) => l.href === pathname);
  // Start expanded if any link in the group is active
  const [expanded, setExpanded] = useState(isGroupActive);
  const Icon = GROUP_ICONS[group.label] ?? IconGenel;

  // Auto-expand when navigating into a group
  useEffect(() => {
    if (isGroupActive) setExpanded(true);
  }, [isGroupActive]);

  return (
    <div className={styles.sidebarSection}>
      <button
        type="button"
        className={`${styles.sectionToggle} ${isGroupActive ? styles.sectionToggleActive : ''}`}
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
      >
        <span className={styles.sectionToggleIcon}>
          <Icon />
        </span>
        <span className={styles.sectionToggleLabel}>{group.label}</span>
        <svg
          className={`${styles.sectionChevron} ${expanded ? styles.sectionChevronOpen : ''}`}
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="6 9 12 15 18 9"/>
        </svg>
      </button>

      {expanded && (
        <div className={styles.sectionLinks}>
          {group.links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={`${styles.sidebarLink} ${pathname === link.href ? styles.sidebarLinkActive : ''}`}
              aria-current={pathname === link.href ? 'page' : undefined}
            >
              {pathname === link.href && (
                <span className={styles.activeBar} aria-hidden="true" />
              )}
              {link.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AppNav — main export
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// GlobalSearch — desktop-only search input in the top strip that opens
// CommandPalette (same as ⌘K). Wires into the same openPalette mechanism
// by dispatching a synthetic ⌘K keyboard event the CommandPalette listens to.
// ---------------------------------------------------------------------------

function GlobalSearch() {
  function handleFocus() {
    // Trigger ⌘K open by dispatching the exact event CommandPalette listens for
    const event = new KeyboardEvent('keydown', {
      key: 'k',
      metaKey: true,
      bubbles: true,
      cancelable: true,
    });
    document.dispatchEvent(event);
  }

  return (
    <div className={styles.globalSearch} aria-hidden="false">
      <svg
        className={styles.globalSearchIcon}
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
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
      <input
        type="text"
        className={styles.globalSearchInput}
        placeholder="Ara veya git…"
        aria-label="Ara veya git (⌘K)"
        readOnly
        onFocus={handleFocus}
        onClick={handleFocus}
      />
      <kbd className={styles.globalSearchKbd}>⌘K</kbd>
    </div>
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

  // Close drawer on Escape key
  useEffect(() => {
    if (!drawerOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setDrawerOpen(false);
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [drawerOpen]);

  // Prevent body scroll when mobile drawer is open
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

  const handleLogout = useCallback(async () => {
    await logoutApi();
    router.push('/login');
  }, [router]);

  return (
    <>
      {/* ============================================================
          DESKTOP: Fixed left sidebar
          ============================================================ */}
      <nav
        className={styles.sidebar}
        aria-label="Ana menü"
        data-app-sidebar
      >
        {/* Brand */}
        <div className={styles.sidebarBrand}>
          <span className={styles.brandText}>AYAZ</span>
        </div>

        {/* Scrollable nav sections */}
        <div className={styles.sidebarNav}>
          {NAV_GROUPS.map((group) => (
            <SidebarSection
              key={group.label}
              group={group}
              pathname={pathname}
            />
          ))}
        </div>
      </nav>

      {/* ============================================================
          SLIM TOP STRIP (visible on desktop, to the right of sidebar;
          also shown on mobile as the only top bar with hamburger)
          ============================================================ */}
      <header className={styles.topStrip} aria-label="Üst araç çubuğu">
        {/* Left: workspace switcher (desktop) + hamburger (mobile) */}
        <div className={styles.stripLeft}>
          {/* Hamburger — mobile only */}
          <button
            className={styles.hamburger}
            onClick={() => setDrawerOpen((prev) => !prev)}
            aria-label={drawerOpen ? 'Menüyü kapat' : 'Menüyü aç'}
            aria-expanded={drawerOpen}
            aria-controls="mobile-drawer"
            type="button"
          >
            <span className={`${styles.hamburgerLine} ${drawerOpen ? styles.hamburgerLineTopOpen : ''}`} />
            <span className={`${styles.hamburgerLine} ${drawerOpen ? styles.hamburgerLineMidOpen : ''}`} />
            <span className={`${styles.hamburgerLine} ${drawerOpen ? styles.hamburgerLineBotOpen : ''}`} />
          </button>

          {/* Brand — mobile only (sidebar brand hidden on mobile) */}
          <span className={styles.mobileBrand}>AYAZ</span>

          {/* WorkspaceSwitcher — desktop only */}
          <div className={styles.desktopOnly}>
            <WorkspaceSwitcher />
          </div>
        </div>

        {/* Center: global search — desktop only */}
        <GlobalSearch />

        {/* Right: utility icons + account */}
        <div className={styles.stripRight}>
          {/* Veriye Sor */}
          <button
            className={styles.quickAskBtn}
            onClick={() => setQuickAskOpen(true)}
            aria-label="Veriye Sor — yapay zeka asistanına soru sor"
            title="Veriye Sor"
            type="button"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
            </svg>
          </button>

          <NotificationBell />
          <ThemeToggle />
          <AccountMenu pathname={pathname} onLogout={handleLogout} />
        </div>
      </header>

      {/* ============================================================
          MOBILE: off-canvas drawer
          ============================================================ */}

      {/* Overlay */}
      {drawerOpen && (
        <div
          className={styles.overlay}
          onClick={() => setDrawerOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Drawer panel */}
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
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className={styles.drawerGroup}>
              <div className={styles.drawerGroupLabel}>{group.label}</div>
              {group.links.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`${styles.drawerLink} ${pathname === link.href ? styles.drawerLinkActive : ''}`}
                  aria-current={pathname === link.href ? 'page' : undefined}
                  onClick={() => setDrawerOpen(false)}
                >
                  {link.label}
                </Link>
              ))}
            </div>
          ))}

          {/* Account section in mobile drawer */}
          <div className={styles.drawerGroup}>
            <div className={styles.drawerGroupLabel}>Hesap</div>
            {ACCOUNT_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`${styles.drawerLink} ${pathname === link.href ? styles.drawerLinkActive : ''}`}
                aria-current={pathname === link.href ? 'page' : undefined}
                onClick={() => setDrawerOpen(false)}
              >
                {link.label}
              </Link>
            ))}
          </div>
        </div>

        <div className={styles.drawerFooter}>
          <div className={styles.drawerFooterTop}>
            <NotificationBell />
            <ThemeToggle />
          </div>
          <button
            className={styles.drawerQuickAskBtn}
            onClick={() => {
              setDrawerOpen(false);
              setQuickAskOpen(true);
            }}
            aria-label="Veriye Sor — yapay zeka asistanına soru sor"
            type="button"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
            </svg>
            Veriye Sor
          </button>
          <button className={styles.drawerLogoutBtn} onClick={handleLogout} type="button">
            Oturumu Kapat
          </button>
        </div>
      </nav>

      {/* ============================================================
          Global: CommandPalette + QuickAsk modal
          ============================================================ */}
      <CommandPalette onOpenQuickAsk={() => setQuickAskOpen(true)} />
      {quickAskOpen && <QuickAsk onClose={() => setQuickAskOpen(false)} />}
    </>
  );
}
