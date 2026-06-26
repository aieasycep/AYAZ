'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getMe,
  updateProfile,
  changePassword,
  getPreferences,
  updatePreferences,
  type UserProfile,
  type UserPreferences,
} from '@/lib/settings-api';
import AppNav from '@/components/AppNav';
import styles from './settings.module.css';

// --- Helpers ---

function formatTurkishDate(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('tr-TR', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

// Timezone options shown in the select. If the stored value isn't in the list
// it will be appended as an extra option to avoid silently losing it.
const KNOWN_TIMEZONES = [
  { value: 'Europe/Istanbul', label: 'Europe/Istanbul (Türkiye)' },
  { value: 'Europe/London', label: 'Europe/London (Londra)' },
  { value: 'America/New_York', label: 'America/New_York (New York)' },
  { value: 'UTC', label: 'UTC' },
];

// --- Profile Card ---

function ProfileCard() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saveSuccess, setSaveSuccess] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const data = await getMe();
      setProfile(data);
      setFullName(data.full_name ?? '');
      setEmail(data.email ?? '');
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : 'Profil yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError('');
    setSaveSuccess(false);
    try {
      const updated = await updateProfile({
        full_name: fullName.trim(),
        email: email.trim(),
      });
      setProfile(updated);
      setFullName(updated.full_name ?? '');
      setEmail(updated.email ?? '');
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Profil kaydedilemedi');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <div className={styles.sectionTitle}>Profil</div>
          <div className={styles.sectionSubtitle}>Ad, soyad ve e-posta adresinizi güncelleyin</div>
        </div>
      </div>

      {loading ? (
        <div className={styles.stateBox}>
          <p className={styles.muted}>Yükleniyor...</p>
        </div>
      ) : loadError ? (
        <div className={styles.stateBox}>
          <p className={styles.errorText}>{loadError}</p>
          <button className={styles.retryBtn} onClick={load}>Tekrar Dene</button>
        </div>
      ) : (
        <form onSubmit={handleSave} className={styles.cardForm}>
          <div className={styles.formRow}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="profile-fullname">
                Ad Soyad
              </label>
              <input
                id="profile-fullname"
                type="text"
                className={styles.fieldInput}
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                disabled={saving}
                placeholder="Ad Soyad"
                autoComplete="name"
              />
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="profile-email">
                E-posta
              </label>
              <input
                id="profile-email"
                type="email"
                className={styles.fieldInput}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={saving}
                placeholder="ornek@sirket.com"
                autoComplete="email"
              />
            </div>
          </div>

          {profile?.created_at && (
            <div className={styles.fieldGroup}>
              <span className={styles.fieldLabel}>Uyelik Tarihi</span>
              <span className={styles.fieldStatic}>
                {formatTurkishDate(profile.created_at)}
              </span>
            </div>
          )}

          <div className={styles.formActions}>
            <button type="submit" className={styles.saveBtn} disabled={saving}>
              {saving ? 'Kaydediliyor...' : 'Kaydet'}
            </button>
            {saveSuccess && (
              <span className={styles.formSuccess}>Profil güncellendi.</span>
            )}
            {saveError && (
              <span className={styles.formError}>{saveError}</span>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

// --- Password Card ---

function PasswordCard() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('');

  const [saving, setSaving] = useState(false);
  const [clientError, setClientError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saveSuccess, setSaveSuccess] = useState(false);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setClientError('');
    setSaveError('');
    setSaveSuccess(false);

    // Client-side validation
    if (newPassword.length < 8) {
      setClientError('Yeni şifre en az 8 karakter olmalıdır.');
      return;
    }
    if (newPassword !== newPasswordConfirm) {
      setClientError('Yeni şifreler eşleşmiyor.');
      return;
    }

    setSaving(true);
    try {
      await changePassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword('');
      setNewPassword('');
      setNewPasswordConfirm('');
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      const e = err as Error & { status?: number };
      if (e.status === 429) {
        setSaveError('Çok fazla deneme, lütfen biraz sonra tekrar deneyin.');
      } else {
        setSaveError(e.message || 'Şifre değiştirilemedi');
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <div className={styles.sectionTitle}>Şifre Değiştir</div>
          <div className={styles.sectionSubtitle}>Hesap şifrenizi güncelleyin</div>
        </div>
      </div>

      <form onSubmit={handleSave} className={styles.cardForm}>
        <div className={styles.fieldGroup}>
          <label className={styles.fieldLabel} htmlFor="pw-current">
            Mevcut Şifre
          </label>
          <input
            id="pw-current"
            type="password"
            className={styles.fieldInput}
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            disabled={saving}
            autoComplete="current-password"
            required
          />
        </div>

        <div className={styles.formRow}>
          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel} htmlFor="pw-new">
              Yeni Şifre
            </label>
            <input
              id="pw-new"
              type="password"
              className={styles.fieldInput}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              disabled={saving}
              autoComplete="new-password"
              required
              minLength={8}
            />
          </div>

          <div className={styles.fieldGroup}>
            <label className={styles.fieldLabel} htmlFor="pw-confirm">
              Yeni Şifre (Tekrar)
            </label>
            <input
              id="pw-confirm"
              type="password"
              className={styles.fieldInput}
              value={newPasswordConfirm}
              onChange={(e) => setNewPasswordConfirm(e.target.value)}
              disabled={saving}
              autoComplete="new-password"
              required
            />
          </div>
        </div>

        {clientError && (
          <span className={styles.formError}>{clientError}</span>
        )}

        <div className={styles.formActions}>
          <button type="submit" className={styles.saveBtn} disabled={saving}>
            {saving ? 'Kaydediliyor...' : 'Şifreyi Güncelle'}
          </button>
          {saveSuccess && (
            <span className={styles.formSuccess}>Şifre güncellendi.</span>
          )}
          {saveError && (
            <span className={styles.formError}>{saveError}</span>
          )}
        </div>
      </form>
    </div>
  );
}

// --- Preferences Card ---

function PreferencesCard() {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  // Form state mirrors prefs fields
  const [locale, setLocale] = useState<'tr' | 'en'>('tr');
  const [timezone, setTimezone] = useState('Europe/Istanbul');
  const [emailAlerts, setEmailAlerts] = useState(true);
  const [emailBriefing, setEmailBriefing] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saveSuccess, setSaveSuccess] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const data = await getPreferences();
      setPrefs(data);
      setLocale(data.locale);
      setTimezone(data.timezone);
      setEmailAlerts(data.email_alerts);
      setEmailBriefing(data.email_briefing);
    } catch (err: unknown) {
      setLoadError(err instanceof Error ? err.message : 'Tercihler yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Build timezone option list, appending stored value if not in known list
  const timezoneOptions = [...KNOWN_TIMEZONES];
  if (prefs && !KNOWN_TIMEZONES.some((tz) => tz.value === prefs.timezone)) {
    timezoneOptions.push({ value: prefs.timezone, label: prefs.timezone });
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError('');
    setSaveSuccess(false);
    try {
      const updated = await updatePreferences({
        locale,
        timezone,
        email_alerts: emailAlerts,
        email_briefing: emailBriefing,
      });
      setPrefs(updated);
      setLocale(updated.locale);
      setTimezone(updated.timezone);
      setEmailAlerts(updated.email_alerts);
      setEmailBriefing(updated.email_briefing);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Tercihler kaydedilemedi');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <div className={styles.sectionTitle}>Tercihler</div>
          <div className={styles.sectionSubtitle}>Dil, saat dilimi ve bildirim ayarları</div>
        </div>
      </div>

      {loading ? (
        <div className={styles.stateBox}>
          <p className={styles.muted}>Yükleniyor...</p>
        </div>
      ) : loadError ? (
        <div className={styles.stateBox}>
          <p className={styles.errorText}>{loadError}</p>
          <button className={styles.retryBtn} onClick={load}>Tekrar Dene</button>
        </div>
      ) : (
        <form onSubmit={handleSave} className={styles.cardForm}>
          <div className={styles.formRow}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="pref-locale">
                Dil
              </label>
              <select
                id="pref-locale"
                className={styles.fieldSelect}
                value={locale}
                onChange={(e) => setLocale(e.target.value as 'tr' | 'en')}
                disabled={saving}
              >
                <option value="tr">Türkçe</option>
                <option value="en">English</option>
              </select>
              <span className={styles.fieldNote}>
                Dil tercihi kaydedilir; arayüz çevirisi yakında.
              </span>
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="pref-timezone">
                Saat Dilimi
              </label>
              <select
                id="pref-timezone"
                className={styles.fieldSelect}
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                disabled={saving}
              >
                {timezoneOptions.map((tz) => (
                  <option key={tz.value} value={tz.value}>
                    {tz.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className={styles.fieldGroup}>
            <span className={styles.fieldLabel}>Bildirimler</span>

            <label className={styles.toggleRow} htmlFor="pref-email-alerts">
              <input
                id="pref-email-alerts"
                type="checkbox"
                className={styles.toggleCheckbox}
                checked={emailAlerts}
                onChange={(e) => setEmailAlerts(e.target.checked)}
                disabled={saving}
              />
              <span className={styles.toggleLabel}>Uyarı e-postaları</span>
            </label>

            <label className={styles.toggleRow} htmlFor="pref-email-briefing">
              <input
                id="pref-email-briefing"
                type="checkbox"
                className={styles.toggleCheckbox}
                checked={emailBriefing}
                onChange={(e) => setEmailBriefing(e.target.checked)}
                disabled={saving}
              />
              <span className={styles.toggleLabel}>Günlük brifing e-postası</span>
            </label>
          </div>

          <div className={styles.formActions}>
            <button type="submit" className={styles.saveBtn} disabled={saving}>
              {saving ? 'Kaydediliyor...' : 'Kaydet'}
            </button>
            {saveSuccess && (
              <span className={styles.formSuccess}>Tercihler kaydedildi.</span>
            )}
            {saveError && (
              <span className={styles.formError}>{saveError}</span>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

// --- Page ---

export default function SettingsPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) router.replace('/login');
  }, [router]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Hesap &amp; Ayarlar</h1>
            <p className={styles.pageSubtitle}>
              Profil bilgilerinizi, şifrenizi ve uygulama tercihlerinizi yönetin.
            </p>
          </div>
        </div>

        <ProfileCard />
        <PasswordCard />
        <PreferencesCard />
      </main>
    </div>
  );
}
