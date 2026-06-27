import styles from './loading.module.css';

export default function Loading() {
  return (
    <div className={styles.shell}>
      <div
        className={styles.spinner}
        role="status"
        aria-label="Sayfa yükleniyor"
      >
        <span className={styles.spinnerRing} />
      </div>
    </div>
  );
}
