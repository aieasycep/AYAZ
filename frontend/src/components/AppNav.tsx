'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { clearToken } from '@/lib/api';
import styles from './AppNav.module.css';

const NAV_LINKS = [
  { href: '/dashboard', label: 'Panel' },
  { href: '/insights', label: 'İçgörüler' },
  { href: '/connections', label: 'Bağlantılar' },
  { href: '/feeds', label: 'Feed Yönetimi' },
  { href: '/reports', label: 'Raporlar' },
  { href: '/ads', label: 'Reklam' },
  { href: '/automation', label: 'Otomasyon' },
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
        <button className={styles.logoutBtn} onClick={handleLogout}>
          Oturumu Kapat
        </button>
      </div>
    </header>
  );
}
