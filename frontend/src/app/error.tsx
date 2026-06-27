'use client';

import Link from 'next/link';
import styles from './error.module.css';

interface ErrorPageProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function ErrorPage({ error, reset }: ErrorPageProps) {
  return (
    <div className={styles.shell}>
      <div className={styles.card}>
        <div className={styles.icon} aria-hidden="true">!</div>
        <h1 className={styles.title}>Bir şeyler ters gitti</h1>
        <p className={styles.desc}>
          Bu sayfayı yüklerken beklenmedik bir sorun oluştu. Lütfen tekrar
          deneyin ya da panele geri dönün.
        </p>
        {error.digest && (
          <p className={styles.digest}>Hata kodu: {error.digest}</p>
        )}
        <div className={styles.actions}>
          <button className={styles.primaryBtn} onClick={reset}>
            Tekrar dene
          </button>
          <Link href="/dashboard" className={styles.secondaryLink}>
            Panele dön
          </Link>
        </div>
      </div>
    </div>
  );
}
