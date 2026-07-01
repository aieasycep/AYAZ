'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { login, setToken, getToken } from '@/lib/api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './login.module.css';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (getToken()) {
      router.replace('/dashboard');
    }
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      const data = await login(email, password);
      setToken(data.access_token);
      router.push('/dashboard');
    } catch (err: unknown) {
      const message = parseApiError(err);
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <span className={styles.brandName}>AYAZ</span>
          <span className={styles.brandTagline}>Dijital Pazarlama Paneli</span>
        </div>

        <h1 className={styles.title}>Oturum Aç</h1>

        {error && <div className={styles.error}>{error}</div>}

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.field}>
            <label htmlFor="email" className={styles.label}>
              E-posta
            </label>
            <input
              id="email"
              type="email"
              className={styles.input}
              placeholder="demo@ayaz.app"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              disabled={loading}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="password" className={styles.label}>
              Parola
            </label>
            <input
              id="password"
              type="password"
              className={styles.input}
              placeholder="demo12345"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              disabled={loading}
            />
          </div>

          <button type="submit" className={styles.button} disabled={loading}>
            {loading ? 'Giriş yapılıyor...' : 'Giriş Yap'}
          </button>
        </form>

        <div className={styles.footer}>
          Hesabın yok mu?{' '}
          <Link href="/signup" className={styles.footerLink}>
            Ücretsiz kayıt ol
          </Link>
        </div>
      </div>
    </div>
  );
}
