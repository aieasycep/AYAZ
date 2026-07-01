import Link from 'next/link';
import styles from './DashboardEmptyState.module.css';

export default function DashboardEmptyState() {
  return (
    <div className={styles.wrapper}>
      <div className={styles.icon}>📡</div>
      <h2 className={styles.title}>Henüz bağlı hesap yok</h2>
      <p className={styles.desc}>
        Verilerinizi görmek için en az bir reklam veya analitik hesabı bağlayın.
        Bağlantı kurmak yalnızca birkaç dakika sürer.
      </p>
      <Link href="/integrations?tab=veri-kaynaklari" className={styles.cta}>
        Bağlantı Ekle
      </Link>
    </div>
  );
}
