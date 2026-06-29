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
  { href: '/roles', label: 'Rol Görünümü' },
  { href: '/dashboard', label: 'Panel' },
  { href: '/executive', label: 'Yönetici' },
  { href: '/health-index', label: 'Sağlık Endeksi' },
  { href: '/audit', label: 'Denetim' },
  { href: '/benchmark', label: 'Kıyaslama' },
  { href: '/recommendations', label: 'Öneriler' },
  { href: '/assistant', label: 'Asistan' },
  { href: '/briefing', label: 'Brifing' },
  { href: '/insights', label: 'İçgörüler' },
  { href: '/connections', label: 'Bağlantılar' },
  { href: '/feeds', label: 'Feed Yönetimi' },
  { href: '/reports', label: 'Raporlar' },
  { href: '/report-builder', label: 'Rapor Oluşturucu' },
  { href: '/ads', label: 'Reklam' },
  { href: '/creatives', label: 'Kreatifler' },
  { href: '/creative-lens', label: 'Kreatif Lensi' },
  { href: '/ad-studio', label: 'Reklam Stüdyosu' },
  { href: '/content', label: 'İçerik' },
  { href: '/inbox', label: 'Gelen Kutusu' },
  { href: '/optimizer', label: 'Optimizasyon' },
  { href: '/goals', label: 'Hedefler' },
  { href: '/planning', label: 'Planlama' },
  { href: '/marketing-calendar', label: 'Fırsat Takvimi' },
  { href: '/budget-simulator', label: 'Bütçe Senaryosu' },
  { href: '/automation', label: 'Otomasyon' },
  { href: '/tracking', label: 'Ölçümleme' },
  { href: '/funnel', label: 'Huni' },
  { href: '/consent', label: 'Rıza Merkezi' },
  { href: '/billing', label: 'Faturalama' },
  { href: '/workspaces', label: 'Çalışma Alanları' },
  { href: '/onboarding', label: 'Kurulum' },
  { href: '/settings', label: 'Ayarlar' },
];

// ---------------------------------------------------------------------------
// Grouped nav — additional exported structure used by the desktop dropdown nav
// and the mobile grouped drawer. Every href from NAV_LINKS appears in exactly
// one group OR in ACCOUNT_LINKS; no routes are dropped or duplicated.
// ---------------------------------------------------------------------------

export interface NavGroupLink {
  href: string;
  label: string;
}

export interface NavGroup {
  label: string;
  links: NavGroupLink[];
}

/** 5 visible nav groups shown in the desktop topbar. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: 'Genel Bakış',
    links: [
      { href: '/command-center', label: 'Komuta Merkezi' },
      { href: '/dashboard', label: 'Panel' },
      { href: '/roles', label: 'Rol Görünümü' },
      { href: '/executive', label: 'Yönetici' },
      { href: '/health-index', label: 'Sağlık Endeksi' },
      { href: '/briefing', label: 'Brifing' },
    ],
  },
  {
    label: 'Analiz',
    links: [
      { href: '/insights', label: 'İçgörüler' },
      { href: '/audit', label: 'Denetim' },
      { href: '/benchmark', label: 'Kıyaslama' },
      { href: '/funnel', label: 'Huni' },
      { href: '/recommendations', label: 'Öneriler' },
      { href: '/assistant', label: 'Asistan' },
    ],
  },
  {
    label: 'Reklam & İçerik',
    links: [
      { href: '/ads', label: 'Reklam' },
      { href: '/creatives', label: 'Kreatifler' },
      { href: '/creative-lens', label: 'Kreatif Lensi' },
      { href: '/ad-studio', label: 'Reklam Stüdyosu' },
      { href: '/content', label: 'İçerik' },
      { href: '/inbox', label: 'Gelen Kutusu' },
    ],
  },
  {
    label: 'Planlama & Bütçe',
    links: [
      { href: '/goals', label: 'Hedefler' },
      { href: '/planning', label: 'Planlama' },
      { href: '/marketing-calendar', label: 'Fırsat Takvimi' },
      { href: '/budget-simulator', label: 'Bütçe Senaryosu' },
      { href: '/optimizer', label: 'Optimizasyon' },
      { href: '/automation', label: 'Otomasyon' },
    ],
  },
  {
    label: 'Veri & Raporlar',
    links: [
      { href: '/connections', label: 'Bağlantılar' },
      { href: '/feeds', label: 'Feed Yönetimi' },
      { href: '/tracking', label: 'Ölçümleme' },
      { href: '/consent', label: 'Rıza Merkezi' },
      { href: '/reports', label: 'Raporlar' },
      { href: '/report-builder', label: 'Rapor Oluşturucu' },
    ],
  },
];

/** Account-menu links — these 4 routes are NOT in NAV_GROUPS but remain in NAV_LINKS. */
export const ACCOUNT_LINKS: NavGroupLink[] = [
  { href: '/settings', label: 'Ayarlar' },
  { href: '/workspaces', label: 'Çalışma Alanları' },
  { href: '/billing', label: 'Faturalama' },
  { href: '/onboarding', label: 'Kurulum' },
];

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

// ---------------------------------------------------------------------------
// DropdownGroup — one group trigger + floating dropdown panel
// ---------------------------------------------------------------------------

interface DropdownGroupProps {
  group: NavGroup;
  pathname: string;
  isOpen: boolean;
  onOpen: () => void;
  onClose: () => void;
  /** Mutable ref so the parent can restore focus to this trigger on Escape. */
  triggerRef: { current: HTMLButtonElement | null };
}

function DropdownGroup({
  group,
  pathname,
  isOpen,
  onOpen,
  onClose,
  triggerRef,
}: DropdownGroupProps) {
  const isGroupActive = group.links.some((l) => l.href === pathname);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close on Escape — return focus to trigger
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        onClose();
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, triggerRef]);

  return (
    <div className={styles.navGroup}>
      <button
        ref={(el) => { triggerRef.current = el; }}
        type="button"
        className={`${styles.navGroupTrigger} ${isGroupActive ? styles.navGroupTriggerActive : ''}`}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        onClick={() => (isOpen ? onClose() : onOpen())}
      >
        {group.label}
        <svg
          className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ''}`}
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
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {isOpen && (
        <div
          ref={dropdownRef}
          className={styles.dropdown}
          role="menu"
          aria-label={group.label}
        >
          {group.links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              role="menuitem"
              className={`${styles.dropdownLink} ${pathname === link.href ? styles.dropdownLinkActive : ''}`}
              onClick={onClose}
            >
              {link.label}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AccountMenu — avatar button + Level-2 dropdown
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

  // Derive initials from the logged-in user's full_name
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
      .catch(() => {
        // Not fatal — fallback to generic icon
      });
  }, []);

  // Close on Escape — return focus to trigger
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

  // Close on outside click
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
          /* Generic user icon fallback */
          <svg
            width="16"
            height="16"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" />
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
// AppNav — main export
// ---------------------------------------------------------------------------

export default function AppNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [quickAskOpen, setQuickAskOpen] = useState(false);
  const [openGroupIndex, setOpenGroupIndex] = useState<number | null>(null);

  // One mutable ref object per group trigger, for restoring focus on Escape
  const triggerRefs = useRef<Array<{ current: HTMLButtonElement | null }>>(
    NAV_GROUPS.map(() => ({ current: null }))
  );

  const closeDropdown = useCallback(() => setOpenGroupIndex(null), []);

  // Close dropdown on route change
  useEffect(() => {
    setDrawerOpen(false);
    setOpenGroupIndex(null);
  }, [pathname]);

  // Close dropdown on outside click
  useEffect(() => {
    if (openGroupIndex === null) return;
    function handleClick(e: MouseEvent) {
      // If the click target is inside any navGroup element, let that handler deal with it
      const navGroupEls = Array.from(document.querySelectorAll(`.${styles.navGroup}`));
      for (const el of navGroupEls) {
        if (el.contains(e.target as Node)) return;
      }
      setOpenGroupIndex(null);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [openGroupIndex]);

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
    await logoutApi();
    router.push('/login');
  }

  return (
    <>
      <header className={styles.topbar}>
        <div className={styles.inner}>
          {/* Left: brand + desktop grouped nav */}
          <div className={styles.left}>
            <span className={styles.brand}>AYAZ</span>
            <nav className={styles.nav} aria-label="Ana menü">
              {NAV_GROUPS.map((group, idx) => (
                <DropdownGroup
                  key={group.label}
                  group={group}
                  pathname={pathname}
                  isOpen={openGroupIndex === idx}
                  onOpen={() => setOpenGroupIndex(idx)}
                  onClose={closeDropdown}
                  triggerRef={triggerRefs.current[idx]}
                />
              ))}
            </nav>
          </div>

          {/* Right: veriye-sor (icon-only) + notification bell + theme toggle + account menu + hamburger (mobile) */}
          <div className={styles.right}>
            {/* "Veriye Sor" — icon-only on desktop */}
            <button
              className={`${styles.quickAskBtn} ${styles.desktopOnly}`}
              onClick={() => setQuickAskOpen(true)}
              aria-label="Veriye Sor — yapay zeka asistanına soru sor"
              title="Veriye Sor (yapay zeka)"
              type="button"
            >
              {/* Spark / bolt icon */}
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
            </button>
            <NotificationBell />
            <ThemeToggle />

            {/* Account menu — desktop only */}
            <div className={styles.desktopOnly}>
              <AccountMenu pathname={pathname} onLogout={handleLogout} />
            </div>

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
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className={styles.drawerGroup}>
              <div className={styles.drawerGroupLabel}>{group.label}</div>
              {group.links.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`${styles.drawerLink} ${pathname === link.href ? styles.drawerLinkActive : ''}`}
                >
                  {link.label}
                </Link>
              ))}
            </div>
          ))}

          {/* Account section in the drawer */}
          <div className={styles.drawerGroup}>
            <div className={styles.drawerGroupLabel}>Hesap</div>
            {ACCOUNT_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`${styles.drawerLink} ${pathname === link.href ? styles.drawerLinkActive : ''}`}
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
          {/* "Veriye Sor" — mobile drawer entry (keeps full text label) */}
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
