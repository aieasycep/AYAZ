import Link from 'next/link';
import styles from './not-found.module.css';

export default function NotFound() {
  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div className={styles.code} aria-hidden="true">404</div>
        <h1 className={styles.title}>Sayfa bulunamadı</h1>
        <p className={styles.desc}>
          Aradığınız sayfa taşınmış, silinmiş ya da hiç var olmamış olabilir.
        </p>
        <div className={styles.actions}>
          <Link href="/dashboard" className={styles.primaryLink}>
            Panele dön
          </Link>
          <Link href="/" className={styles.secondaryLink}>
            Ana sayfaya git
          </Link>
        </div>
      </div>
    </div>
  );
}
