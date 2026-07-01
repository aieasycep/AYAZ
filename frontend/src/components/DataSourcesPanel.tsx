'use client';

import { useState, useEffect, useCallback } from 'react';
import { getToken } from '@/lib/api';
import { parseApiError } from '@/lib/parseApiError';
import {
  getConnectedAccounts,
  getOAuthAuthorizeUrl,
  syncAccount,
  type ConnectedAccount,
  type Platform,
  type SyncStatus,
} from '@/lib/connectors-api';
import EmptyState from '@/components/EmptyState';
import styles from '@/app/connections/connections.module.css';

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

/**
 * DataSourcesPanel — the "Veri Kaynakları" tab inside the Integration Center.
 *
 * Lists ad/analytics data-source connections (ConnectedAccount) that feed the
 * dashboards, with sync status, plus the supported-platform grid for connecting
 * new sources. Extracted from the former /connections page so the Integration
 * Center can be the single front door for connecting everything. Renders no
 * AppNav / page shell — the host page provides those.
 */
export default function DataSourcesPanel() {
  const [accounts, setAccounts] = useState<ConnectedAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Per-platform connecting state
  const [connecting, setConnecting] = useState<Partial<Record<Platform, boolean>>>({});
  // Per-account manual-sync state + last result message
  const [syncing, setSyncing] = useState<Record<string, boolean>>({});
  const [syncMsg, setSyncMsg] = useState<{ id: string; text: string; ok: boolean } | null>(null);

  const fetchAccounts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getConnectedAccounts();
      setAccounts(data);
    } catch (err: unknown) {
      setError(parseApiError(err));
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
      alert(parseApiError(err));
      setConnecting((prev) => ({ ...prev, [platform]: false }));
    }
  }

  async function handleSync(accountId: string) {
    setSyncing((prev) => ({ ...prev, [accountId]: true }));
    setSyncMsg(null);
    try {
      const r = await syncAccount(accountId);
      setSyncMsg({
        id: accountId,
        text: `Senkronize edildi — ${r.records_processed.toLocaleString('tr-TR')} kayıt işlendi (${r.inserted.toLocaleString('tr-TR')} yeni).`,
        ok: true,
      });
      await fetchAccounts();
    } catch (err: unknown) {
      setSyncMsg({ id: accountId, text: parseApiError(err), ok: false });
    } finally {
      setSyncing((prev) => ({ ...prev, [accountId]: false }));
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
    <>
      <p className={styles.pageSubtitle}>
        Reklam ve analitik hesaplarınızı bağlayın — panellerinizi besleyen veriler buradan akar.
      </p>

      {/* Connected accounts — clean list with status badges */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>
            Bağlı Hesaplar{accounts.length > 0 ? ` (${accounts.length})` : ''}
          </h2>
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
        ) : accounts.length === 0 ? (
          <EmptyState
            title="Henüz bağlı hesap yok"
            subtitle="Aşağıdan bir platform seçerek bağlantı kurabilirsiniz."
          />
        ) : (
          <div className={styles.accountsList}>
            {accounts.map((acc) => {
              const meta = PLATFORMS.find((p) => p.id === acc.platform);
              const isSyncing = syncing[acc.id] ?? false;
              return (
                <div key={acc.id}>
                  <div className={styles.accountRow}>
                    <div
                      className={styles.platformIcon}
                      style={{ background: meta?.iconBg ?? '#6b7280', color: '#fff' }}
                    >
                      {meta?.icon ?? '?'}
                    </div>
                    <div className={styles.accountInfo}>
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
                    <button
                      className={styles.resyncBtn}
                      onClick={() => handleSync(acc.id)}
                      disabled={isSyncing}
                      title="Bu hesabın son 30 günlük verisini şimdi çek"
                    >
                      {isSyncing ? 'Senkronize ediliyor...' : 'Senkronize et'}
                    </button>
                  </div>
                  {syncMsg?.id === acc.id && (
                    <div
                      className={styles.watermarkText}
                      style={{
                        margin: '0.25rem 0 0.5rem 3.25rem',
                        color: syncMsg.ok ? 'var(--color-success-text)' : 'var(--color-critical-text)',
                      }}
                      role="status"
                    >
                      {syncMsg.text}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Platform grid — reflects connected status */}
      <section className={styles.section}>
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle}>Desteklenen Platformlar</h2>
        </div>

        {loading ? null : error ? null : (
          <div className={styles.platformGrid}>
            {PLATFORMS.map((meta) => {
              const connectedList = accountsByPlatform[meta.id] ?? [];
              const isConnected = connectedList.length > 0;
              const isConnecting = connecting[meta.id] ?? false;
              const primaryAcc = connectedList[0];

              return (
                <div
                  key={meta.id}
                  className={`${styles.platformCard} ${isConnected ? cardClass(primaryAcc.sync_status) : ''}`}
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
                    {/* Connected status badge in top-right */}
                    {isConnected && (
                      <span className={`${styles.badge} ${statusClass(primaryAcc.sync_status)}`}>
                        <span className={styles.badgeDot} />
                        {statusLabel(primaryAcc.sync_status)}
                      </span>
                    )}
                  </div>

                  {isConnected ? (
                    <>
                      {connectedList.map((acc) => (
                        <div key={acc.id} className={styles.connectedAccRow}>
                          <span className={styles.watermarkText}>{acc.display_name}</span>
                          <span className={styles.watermarkText}>{fmtDate(acc.watermark)}</span>
                        </div>
                      ))}
                      <div className={styles.cardActions}>
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
    </>
  );
}
