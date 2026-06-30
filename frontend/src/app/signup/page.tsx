'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { signup, setToken, getToken } from '@/lib/api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './signup.module.css';

export default function SignupPage() {
  const router = useRouter();

  const [fullName, setFullName] = useState('');
  const [orgName, setOrgName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');

  // Per-field inline validation errors
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  // Top-level API / submission error
  const [error, setError] = useState<React.ReactNode>('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (getToken()) {
      router.replace('/dashboard');
    }
  }, [router]);

  function validate(): boolean {
    const errors: Record<string, string> = {};

    if (!orgName.trim()) {
      errors.orgName = 'Şirket / Organizasyon adı zorunludur.';
    }
    if (!email.trim()) {
      errors.email = 'E-posta adresi zorunludur.';
    }
    if (password.length < 8) {
      errors.password = 'Şifre en az 8 karakter olmalıdır.';
    }
    if (password !== passwordConfirm) {
      errors.passwordConfirm = 'Şifreler eşleşmiyor.';
    }

    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    if (!validate()) return;

    setLoading(true);
    try {
      const res = await signup({
        email: email.trim(),
        password,
        org_name: orgName.trim(),
        ...(fullName.trim() ? { full_name: fullName.trim() } : {}),
      });
      setToken(res.access_token);
      router.push('/onboarding');
    } catch (err: unknown) {
      const message = parseApiError(err);

      if (
        message.includes('zaten kullanımda') ||
        message.includes('Bu e-posta adresi zaten')
      ) {
        // 409 duplicate email — surface inline link to login
        setError(
          <>
            Bu e-posta zaten kayıtlı —{' '}
            <Link href="/login" className={styles.errorLink}>
              giriş yapın
            </Link>
            .
          </>,
        );
      } else {
        setError(message);
      }
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

        <h1 className={styles.title}>Ücretsiz Hesap Oluştur</h1>

        {error && <div className={styles.error}>{error}</div>}

        <form onSubmit={handleSubmit} className={styles.form}>
          <div className={styles.field}>
            <label htmlFor="fullName" className={styles.label}>
              Ad Soyad{' '}
              <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
                (isteğe bağlı)
              </span>
            </label>
            <input
              id="fullName"
              type="text"
              className={styles.input}
              placeholder="Ada Yılmaz"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              autoComplete="name"
              disabled={loading}
            />
          </div>

          <div className={styles.field}>
            <label htmlFor="orgName" className={styles.label}>
              Şirket / Organizasyon Adı
            </label>
            <input
              id="orgName"
              type="text"
              className={`${styles.input} ${fieldErrors.orgName ? styles.inputError : ''}`}
              placeholder="Örn. Dijital Ajans A.Ş."
              value={orgName}
              onChange={(e) => {
                setOrgName(e.target.value);
                if (fieldErrors.orgName) setFieldErrors((p) => ({ ...p, orgName: '' }));
              }}
              required
              autoComplete="organization"
              disabled={loading}
            />
            {fieldErrors.orgName && (
              <span className={styles.fieldError}>{fieldErrors.orgName}</span>
            )}
          </div>

          <div className={styles.field}>
            <label htmlFor="email" className={styles.label}>
              E-posta
            </label>
            <input
              id="email"
              type="email"
              className={`${styles.input} ${fieldErrors.email ? styles.inputError : ''}`}
              placeholder="ada@sirket.com"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                if (fieldErrors.email) setFieldErrors((p) => ({ ...p, email: '' }));
              }}
              required
              autoComplete="email"
              disabled={loading}
            />
            {fieldErrors.email && (
              <span className={styles.fieldError}>{fieldErrors.email}</span>
            )}
          </div>

          <div className={styles.field}>
            <label htmlFor="password" className={styles.label}>
              Şifre
            </label>
            <input
              id="password"
              type="password"
              className={`${styles.input} ${fieldErrors.password ? styles.inputError : ''}`}
              placeholder="En az 8 karakter"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                if (fieldErrors.password) setFieldErrors((p) => ({ ...p, password: '' }));
              }}
              required
              autoComplete="new-password"
              disabled={loading}
            />
            {fieldErrors.password && (
              <span className={styles.fieldError}>{fieldErrors.password}</span>
            )}
          </div>

          <div className={styles.field}>
            <label htmlFor="passwordConfirm" className={styles.label}>
              Şifre (tekrar)
            </label>
            <input
              id="passwordConfirm"
              type="password"
              className={`${styles.input} ${fieldErrors.passwordConfirm ? styles.inputError : ''}`}
              placeholder="Şifreyi tekrar girin"
              value={passwordConfirm}
              onChange={(e) => {
                setPasswordConfirm(e.target.value);
                if (fieldErrors.passwordConfirm)
                  setFieldErrors((p) => ({ ...p, passwordConfirm: '' }));
              }}
              required
              autoComplete="new-password"
              disabled={loading}
            />
            {fieldErrors.passwordConfirm && (
              <span className={styles.fieldError}>{fieldErrors.passwordConfirm}</span>
            )}
          </div>

          <button type="submit" className={styles.button} disabled={loading}>
            {loading ? 'Hesap oluşturuluyor...' : 'Hesap Oluştur'}
          </button>
        </form>

        <div className={styles.footer}>
          Zaten hesabın var mı?{' '}
          <Link href="/login" className={styles.footerLink}>
            Giriş yap
          </Link>
        </div>
      </div>
    </div>
  );
}
