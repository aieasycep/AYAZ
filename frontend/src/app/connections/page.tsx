'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getConnectedAccounts,
  getOAuthAuthorizeUrl,
  type ConnectedAccount,
  type Platform,
  type SyncStatus,
} from '@/lib/connectors-api';
import AppNav from '@/components/AppNav';
import styles from './connections.module.css';

// --- Platform metadata ---

interface PlatformMeta {
  id: Platform;
  name: string;
  label: string;
  icon: string;
  iconBg: string;
}

const PLATFORMS: PlatformMeta[] = [
  { id: 'google_ads', name: 'Google Ads', label: 'Arama ve Görüntülü Reklamlar', icon: 'G', iconBg: '#4285F4' },
  { id: 'meta_ads', name: 'Meta Ads', label: 'Facebook ve Instagram Reklamları', icon: 'M', iconBg: '#1877F2' },
  { id: 'ga4', name: 'Google Analytics 4', label: 'Web Analitik', icon: 'A', iconBg: '#E37400' },
  { id: 'search_console', name: 'Search Console', label: 'SEO ve Organik Arama', icon: 'S', iconBg: '#34A853' },
  { id: 'tiktok_ads', name: 'TikTok Ads', label: 'TikTok Reklamları', icon: 'T', iconBg: '#010101' },
  { id: 'linkedin_ads', name: 'LinkedIn Ads', label: 'LinkedIn Reklam Kampanyaları', icon: 'Li', iconBg: '#0A66C2' },
  { id: 'microsoft_ads', name: 'Microsoft Ads', label: 'Bing Arama ve Görüntülü Reklamlar', icon: 'Ms', iconBg: '#00A4EF' },
  { id: 'criteo', name: 'Criteo', label: 'Yeniden Hedefleme Reklamları', icon: 'Cr', iconBg: '#F05A22' },
  { id: 'pinterest_ads', name: 'Pinterest Ads', label: 'Pinterest Reklam Kampanyaları', icon: 'Pi', iconBg: '#E60023' },
];

// --- Status helpers ---

function statusLabel(status: SyncStatus): string {
  switch (status) {
    case 'connected': return 'Bağlı';
    case 'syncing': return 'Senkronize ediliyor';
    case 'error': return 'Hata';
    case 'pending': return 'Bekliyor';
  }
}

function statusClass(status: SyncStatus): string {
  switch (status) {
    case 'connected': return styles.badgeConnected;
    case 'syncing': return styles.badgeSyncing;
    case 'error': return styles.badgeError;
    case 'pending': return styles.badgePending;
  }
}

function cardClass(status: SyncStatus): string {
  switch (status) {
    case 'error': return styles.platformCardError;
    case 'connected':
    case 'syncing': return styles.platformCardConnected;
    default: return '';
  }
}

function fmtDate(iso: string | null): string {
  if (!iso) return 'Hiç senkronize edilmedi';
  const d = new Date(iso);
  return d.toLocaleString('tr-TR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// --- Component ---

export default function ConnectionsPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  const [accounts, setAccounts] = useState<ConnectedAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Per-platform connecting state
  const [connecting, setConnecting] = useState<Partial<Record<Platform, boolean>>>({});

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getConnectedAccounts();
      setAccounts(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Hesaplar yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchAccounts();
  }, [fetchAccounts]);

  async function handleConnect(platform: Platform) {
    setConnecting((prev) => ({ ...prev, [platform]: true }));
    try {
      const { authorize_url } = await getOAuthAuthorizeUrl(platform);
      window.location.href = authorize_url;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Yetkilendirme başlatılamadı';
      alert(msg);
      setConnecting((prev) => ({ ...prev, [platform]: false }));
    }
  }

  // Build a map of platform → connected accounts
  const accountsByPlatform: Partial<Record<Platform, ConnectedAccount[]>> = {};
  for (const acc of accounts) {
    if (!accountsByPlatform[acc.platform]) {
      accountsByPlatform[acc.platform] = [];
    }
    accountsByPlatform[acc.platform]!.push(acc);
  }

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        <div>
          <h1 className={styles.pageTitle}>Bağlantılar</h1>
          <p className={styles.pageSubtitle}>
            Reklam ve analitik hesaplarınızı AYAZ&apos;a bağlayın.
          </p>
        </div>

        {/* Connected accounts section */}
        {!loading && !error && accounts.length > 0 && (
          <section className={styles.section}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>
                Bağlı Hesaplar ({accounts.length})
              </h2>
            </div>
            <div className={styles.accountsList}>
              {accounts.map((acc) => {
                const meta = PLATFORMS.find((p) => p.id === acc.platform);
                return (
                  <div key={acc.id} className={styles.accountRow}>
                    <div
                      className={styles.platformIcon}
                      style={{ background: meta?.iconBg ?? '#6b7280', color: '#fff' }}
                    >
                      {meta?.icon ?? '?'}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className={styles.accountName}>{acc.display_name}</div>
                      <div className={styles.accountPlatform}>{meta?.name ?? acc.platform}</div>
                    </div>
                    <span className={`${styles.badge} ${statusClass(acc.sync_status)}`}>
                      <span className={styles.badgeDot} />
                      {statusLabel(acc.sync_status)}
                    </span>
                    <span className={styles.watermarkText}>
                      {fmtDate(acc.watermark)}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* Platform connection grid */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>Desteklenen Platformlar</h2>
          </div>

          {loading ? (
            <div className={styles.stateBox}>
              <span className={styles.muted}>Hesaplar yükleniyor...</span>
            </div>
          ) : error ? (
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button
                className={styles.resyncBtn}
                style={{ marginTop: '1rem' }}
                onClick={fetchAccounts}
              >
                Tekrar Dene
              </button>
            </div>
          ) : (
            <div className={styles.platformGrid}>
              {PLATFORMS.map((meta) => {
                const connectedList = accountsByPlatform[meta.id] ?? [];
                const isConnected = connectedList.length > 0;
                const isConnecting = connecting[meta.id] ?? false;

                return (
                  <div
                    key={meta.id}
                    className={`${styles.platformCard} ${isConnected ? cardClass(connectedList[0].sync_status) : ''}`}
                  >
                    <div className={styles.platformTop}>
                      <div
                        className={styles.platformIcon}
                        style={{ background: meta.iconBg, color: '#fff' }}
                      >
                        {meta.icon}
                      </div>
                      <div className={styles.platformInfo}>
                        <div className={styles.platformName}>{meta.name}</div>
                        <div className={styles.platformLabel}>{meta.label}</div>
                      </div>
                    </div>

                    {isConnected ? (
                      <>
                        {connectedList.map((acc) => (
                          <div key={acc.id}>
                            <div className={styles.watermarkRow}>
                              <span className={`${styles.badge} ${statusClass(acc.sync_status)}`}>
                                <span className={styles.badgeDot} />
                                {statusLabel(acc.sync_status)}
                              </span>
                              <span className={styles.watermarkText}>
                                {fmtDate(acc.watermark)}
                              </span>
                            </div>
                            <div
                              className={styles.watermarkText}
                              style={{ marginTop: '0.25rem' }}
                            >
                              {acc.display_name}
                            </div>
                          </div>
                        ))}
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                          <button
                            className={styles.resyncBtn}
                            onClick={() => handleConnect(meta.id)}
                            disabled={isConnecting}
                          >
                            {isConnecting ? 'Yönlendiriliyor...' : 'Yeniden Bağla'}
                          </button>
                          <button
                            className={styles.resyncBtn}
                            onClick={fetchAccounts}
                          >
                            Yenile
                          </button>
                        </div>
                      </>
                    ) : (
                      <button
                        className={styles.connectBtn}
                        onClick={() => handleConnect(meta.id)}
                        disabled={isConnecting}
                      >
                        {isConnecting ? 'Yönlendiriliyor...' : 'Bağla'}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
