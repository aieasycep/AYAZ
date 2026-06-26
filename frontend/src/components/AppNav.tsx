'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { clearToken } from '@/lib/api';
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

  function handleLogout() {
    clearToken();
    router.push('/login');
  }

  return (
    <header className={styles.topbar}>
      <div className={styles.inner}>
        <div className={styles.left}>
          <span className={styles.brand}>AYAZ</span>
          <nav className={styles.nav}>
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
        <div className={styles.right}>
          <WorkspaceSwitcher />
          <button className={styles.logoutBtn} onClick={handleLogout}>
            Oturumu Kapat
          </button>
        </div>
      </div>
    </header>
  );
}
