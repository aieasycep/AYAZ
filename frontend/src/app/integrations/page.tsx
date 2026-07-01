'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import { parseApiError } from '@/lib/parseApiError';
import EmptyState from '@/components/EmptyState';
import AppNav from '@/components/AppNav';
import DataSourcesPanel from '@/components/DataSourcesPanel';
import {
  getCatalog,
  getConnections,
  connectIntegration,
  connectApiKey,
  disconnectIntegration,
  requestIntegration,
  statusLabel,
  type CatalogEntry,
  type Connection,
  type IntegrationStatus,
  type IntegrationCategory,
  type ConnectApiKeyPayload,
} from '@/lib/integrations-api';
import styles from './integrations.module.css';

// ---------------------------------------------------------------------------
// Catalogue metadata — static display data (category labels, search aliases)
// ---------------------------------------------------------------------------

const CATEGORY_LABELS: Record<string, string> = {
  all: 'Tümü',
  ads: 'Reklam',
  analytics: 'Analitik',
  social: 'Sosyal',
  messaging: 'Mesajlaşma',
  ecommerce: 'E-ticaret',
  productivity: 'Üretkenlik',
  other: 'Diğer',
};

const STATUS_FILTERS = [
  { value: 'all', label: 'Tümü' },
  { value: 'connected', label: 'Bağlı' },
  { value: 'available', label: 'Bağlanabilir' },
] as const;

// Starter set recommended in the wizard
const RECOMMENDED_KEYS = ['google_workspace', 'google_ads', 'meta_ads', 'slack'];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusBadgeClass(status: IntegrationStatus): string {
  switch (status) {
    case 'connected': return styles.badgeConnected;
    case 'connecting': return styles.badgeConnecting;
    case 'syncing': return styles.badgeSyncing;
    case 'needs_reconnect': return styles.badgeNeedsReconnect;
    case 'error': return styles.badgeError;
    default: return '';
  }
}

function cardBorderClass(entry: CatalogEntry): string {
  if (entry.coming_soon) return styles.integrationCardComingSoon;
  if (!entry.connected) return '';
  switch (entry.connection_status) {
    case 'connected': return styles.integrationCardConnected;
    case 'needs_reconnect': return styles.integrationCardNeedsReconnect;
    case 'error': return styles.integrationCardError;
    default: return styles.integrationCardConnected;
  }
}

function encouragingLine(connected: number, total: number): string {
  if (connected === 0) return 'İlk entegrasyonunuzu bağlayın ve verilerinizi görün.';
  if (connected === 1) return 'Harika başlangıç! Bir tane daha bağlayarak daha fazla içgörü elde edin.';
  if (connected >= total) return 'Tebrikler — tüm entegrasyonlar bağlı!';
  const remaining = total - connected;
  return `${remaining} entegrasyon daha bağlanmayı bekliyor.`;
}

// Open OAuth popup and return a promise that resolves when postMessage arrives
function openOAuthPopup(
  authorizeUrl: string,
  expectedOrigin: string,
): Promise<{ key: string; status: string }> {
  const features = [
    'width=600',
    'height=720',
    'scrollbars=yes',
    'resizable=yes',
    'noopener=no',
  ].join(',');

  const popup = window.open(authorizeUrl, 'ayaz_oauth', features);

  return new Promise((resolve, reject) => {
    if (!popup) {
      reject(new Error('Açılır pencere engelleyici aktif. Lütfen açılır pencerelere izin verin.'));
      return;
    }

    function handler(event: MessageEvent) {
      // Accept same origin or explicitly matching origin
      if (expectedOrigin && event.origin !== expectedOrigin && expectedOrigin !== '*') return;
      const data = event.data as { type?: string; key?: string; status?: string };
      if (data?.type === 'ayaz-oauth') {
        window.removeEventListener('message', handler);
        resolve({ key: data.key ?? '', status: data.status ?? '' });
      }
    }

    window.addEventListener('message', handler);

    // Cleanup if popup is closed without message
    const poll = setInterval(() => {
      if (popup.closed) {
        clearInterval(poll);
        window.removeEventListener('message', handler);
        reject(new Error('Bağlantı penceresi kapatıldı.'));
      }
    }, 500);
  });
}

// ---------------------------------------------------------------------------
// ApiKeyModal
// ---------------------------------------------------------------------------

interface ApiKeyModalProps {
  entry: CatalogEntry;
  onClose: () => void;
  onConnected: () => void;
}

function ApiKeyModal({ entry, onClose, onConnected }: ApiKeyModalProps) {
  const [apiKey, setApiKey] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!apiKey.trim()) {
      setFormError('API anahtarı boş bırakılamaz.');
      return;
    }
    setFormError(null);
    setSubmitting(true);
    try {
      const payload: ConnectApiKeyPayload = { api_key: apiKey.trim() };
      await connectApiKey(entry.key, payload);
      onConnected();
    } catch (err: unknown) {
      setFormError(parseApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalBox} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>{entry.display_name} — API Anahtarı ile Bağlan</span>
          <button type="button" className={styles.modalClose} onClick={onClose} aria-label="Kapat">
            &times;
          </button>
        </div>
        <form onSubmit={handleSubmit} style={{ display: 'contents' }}>
          <div className={styles.modalBody}>
            <p className={styles.modalHint}>
              {entry.display_name} hesabınızdan API anahtarınızı alın ve aşağıya yapıştırın.{' '}
              {/* Setup guide link if metadata provides it */}
              <a
                href="#"
                className={styles.modalHintLink}
                target="_blank"
                rel="noreferrer"
                onClick={(e) => e.preventDefault()}
              >
                Nasıl alınır?
              </a>
            </p>
            <div className={styles.formField}>
              <label className={styles.formLabel} htmlFor="api-key-input">
                API Anahtarı
              </label>
              <input
                id="api-key-input"
                type="password"
                className={styles.formInput}
                placeholder="Anahtarınızı buraya yapıştırın"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                autoFocus
                autoComplete="off"
              />
            </div>
            {formError && <div className={styles.formError}>{formError}</div>}
          </div>
          <div className={styles.modalFooter}>
            <button type="button" className={styles.btnSecondary} onClick={onClose}>
              Vazgeç
            </button>
            <button type="submit" className={styles.btnPrimary} disabled={submitting}>
              {submitting ? 'Doğrulanıyor...' : 'Doğrula ve Bağla'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DisconnectConfirmModal
// ---------------------------------------------------------------------------

interface DisconnectConfirmModalProps {
  entryName: string;
  onCancel: () => void;
  onConfirm: () => void;
  loading: boolean;
}

function DisconnectConfirmModal({
  entryName,
  onCancel,
  onConfirm,
  loading,
}: DisconnectConfirmModalProps) {
  return (
    <div className={styles.modalOverlay} onClick={onCancel}>
      <div className={styles.modalBox} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>Bağlantıyı Kes</span>
          <button type="button" className={styles.modalClose} onClick={onCancel} aria-label="Kapat">
            &times;
          </button>
        </div>
        <div className={styles.modalBody}>
          <p className={styles.confirmText}>
            <strong>{entryName}</strong> bağlantısını kesmek istediğinizden emin misiniz?
            Veriler silinmez ancak yeni senkronizasyon durur.
          </p>
        </div>
        <div className={styles.modalFooter}>
          <button type="button" className={styles.btnSecondary} onClick={onCancel}>
            İptal
          </button>
          <button
            type="button"
            className={styles.btnDanger}
            onClick={onConfirm}
            disabled={loading}
          >
            {loading ? 'Kesiliyor...' : 'Evet, bağlantıyı kes'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// OperatorSetupModal
// ---------------------------------------------------------------------------

function OperatorSetupModal({ entryName, onClose }: { entryName: string; onClose: () => void }) {
  return (
    <div className={styles.modalOverlay} onClick={onClose}>
      <div className={styles.modalBox} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <span className={styles.modalTitle}>{entryName} — Yapılandırma Gerekli</span>
          <button type="button" className={styles.modalClose} onClick={onClose} aria-label="Kapat">
            &times;
          </button>
        </div>
        <div className={styles.modalBody}>
          <div className={styles.infoBox}>
            Yönetici bu sağlayıcıyı henüz yapılandırmadı. Lütfen AYAZ yöneticinizle iletişime
            geçin veya destek ekibimize yazın.
          </div>
        </div>
        <div className={styles.modalFooter}>
          <button type="button" className={styles.btnSecondary} onClick={onClose}>
            Tamam
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// IntegrationCard
// ---------------------------------------------------------------------------

interface IntegrationCardProps {
  entry: CatalogEntry;
  connecting: boolean;
  onConnect: (entry: CatalogEntry) => void;
  onRequest: (key: string) => void;
  onDisconnect: (entry: CatalogEntry) => void;
  onReconnect: (entry: CatalogEntry) => void;
}

function IntegrationCard({
  entry,
  connecting,
  onConnect,
  onRequest,
  onDisconnect,
  onReconnect,
}: IntegrationCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Close menu on outside click
  useEffect(() => {
    if (!menuOpen) return;
    function handleOutside(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, [menuOpen]);

  const isConnected = entry.connected && entry.connection_status !== 'disconnected';
  const needsReconnect = entry.connection_status === 'needs_reconnect';
  const hasError = entry.connection_status === 'error';

  function renderCTA() {
    if (entry.coming_soon) {
      return (
        <button
          type="button"
          className={styles.btnMuted}
          onClick={() => onRequest(entry.key)}
          title="Hazır olduğunda haber al"
        >
          Talep et
        </button>
      );
    }

    if (isConnected) {
      return (
        <div className={styles.menuWrap} ref={menuRef}>
          <button
            type="button"
            className={styles.menuBtn}
            onClick={() => setMenuOpen((p) => !p)}
            aria-label="Yönet"
            title="Yönet"
          >
            &#8942;
          </button>
          {menuOpen && (
            <div className={styles.menuDropdown} role="menu">
              {needsReconnect || hasError ? (
                <button
                  type="button"
                  className={styles.menuItem}
                  role="menuitem"
                  onClick={() => { setMenuOpen(false); onReconnect(entry); }}
                >
                  Yeniden Bağla
                </button>
              ) : null}
              <button
                type="button"
                className={`${styles.menuItem} ${styles.menuItemDanger}`}
                role="menuitem"
                onClick={() => { setMenuOpen(false); onDisconnect(entry); }}
              >
                Bağlantıyı Kes
              </button>
            </div>
          )}
        </div>
      );
    }

    return (
      <button
        type="button"
        className={styles.btnPrimary}
        onClick={() => onConnect(entry)}
        disabled={connecting}
      >
        {connecting ? 'Bağlanıyor...' : 'Bağla'}
      </button>
    );
  }

  function renderStatusBadge() {
    if (entry.coming_soon) {
      return (
        <span className={`${styles.statusBadge} ${styles.badgeComingSoon}`}>
          Yakında
        </span>
      );
    }
    if (!entry.connected) return null;
    const st = entry.connection_status ?? 'connected';
    return (
      <span className={`${styles.statusBadge} ${statusBadgeClass(st)}`}>
        <span className={styles.statusDot} />
        {statusLabel(st)}
      </span>
    );
  }

  return (
    <div className={`${styles.integrationCard} ${cardBorderClass(entry)}`}>
      {/* Top: icon + name + status badge */}
      <div className={styles.cardTop}>
        <div className={styles.cardLeft}>
          <div className={styles.cardIcon} style={{ background: entry.icon_bg }}>
            <span className={styles.cardIconText}>{entry.icon}</span>
          </div>
          <div>
            <div className={styles.cardName}>{entry.display_name}</div>
            {entry.category && (
              <span className={styles.categoryBadge}>
                {CATEGORY_LABELS[entry.category] ?? entry.category}
              </span>
            )}
          </div>
        </div>
        {renderStatusBadge()}
      </div>

      {/* Description */}
      <p className={styles.cardDesc}>{entry.description}</p>

      {/* Footer: reconnect amber hint + CTA */}
      <div className={styles.cardFooter}>
        {(needsReconnect || hasError) && (
          <button
            type="button"
            className={styles.btnPrimary}
            onClick={() => onReconnect(entry)}
            disabled={connecting}
          >
            {connecting ? 'Bağlanıyor...' : 'Yeniden Bağla'}
          </button>
        )}
        {!needsReconnect && !hasError && renderCTA()}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Wizard — onboarding panel (shown when < 2 integrations connected)
// ---------------------------------------------------------------------------

interface WizardPanelProps {
  catalog: CatalogEntry[];
  onConnect: (entry: CatalogEntry) => void;
  onDismiss: () => void;
}

function WizardPanel({ catalog, onConnect, onDismiss }: WizardPanelProps) {
  const recommended = catalog.filter(
    (e) => RECOMMENDED_KEYS.includes(e.key) && !e.coming_soon && !e.connected,
  );
  const connectedCount = catalog.filter((e) => e.connected).length;

  if (recommended.length === 0 && connectedCount > 0) return null;

  return (
    <div className={styles.wizardPanel}>
      <div className={styles.wizardHeader}>
        <div>
          <div className={styles.wizardTitle}>Hızlı Kurulum Sihirbazı</div>
          <div className={styles.wizardSubtitle}>
            İlk verilerinize ulaşmak için birkaç dakikanızı ayırın.
          </div>
        </div>
        <button type="button" className={styles.wizardDismiss} onClick={onDismiss}>
          Kapat
        </button>
      </div>
      <div className={styles.wizardBody}>
        <div className={styles.wizardStep}>
          <div className={`${styles.wizardStepNum} ${connectedCount >= 1 ? styles.wizardStepNumDone : ''}`}>
            {connectedCount >= 1 ? '✓' : '1'}
          </div>
          <div className={styles.wizardStepContent}>
            <div className={styles.wizardStepLabel}>Reklam veya analitik hesabını bağla</div>
            <div className={styles.wizardStepDesc}>
              Google veya Meta ile başlamak en hızlı yoldur — tek OAuth, anında veri.
            </div>
            {recommended.length > 0 && (
              <div className={styles.wizardQuickBtns}>
                {recommended.map((entry) => (
                  <button
                    key={entry.key}
                    type="button"
                    className={styles.recommendedCard}
                    onClick={() => onConnect(entry)}
                  >
                    <span
                      className={styles.recommendedCardIcon}
                      style={{ background: entry.icon_bg }}
                    >
                      {entry.icon}
                    </span>
                    {entry.display_name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className={`${styles.wizardStep} ${connectedCount < 1 ? styles.wizardStepInactive : ''}`}>
          <div className={`${styles.wizardStepNum} ${connectedCount >= 2 ? styles.wizardStepNumDone : ''}`}>
            {connectedCount >= 2 ? '✓' : '2'}
          </div>
          <div className={styles.wizardStepContent}>
            <div className={styles.wizardStepLabel}>Bir bildirim kanalı ekle (opsiyonel)</div>
            <div className={styles.wizardStepDesc}>
              Slack bağlıysa Copilot sizi otomatik uyarabilir — &quot;ROAS düşerse haber ver&quot;.
            </div>
          </div>
        </div>

        <div className={`${styles.wizardStep} ${connectedCount < 2 ? styles.wizardStepInactive : ''}`}>
          <div className={`${styles.wizardStepNum} ${connectedCount >= 3 ? styles.wizardStepNumDone : ''}`}>
            {connectedCount >= 3 ? '✓' : '3'}
          </div>
          <div className={styles.wizardStepContent}>
            <div className={styles.wizardStepLabel}>Panele git ve ilk içgörünüzü görün</div>
            <div className={styles.wizardStepDesc}>
              En az bir bağlantı yapıldıktan sonra verileriniz 5 dakika içinde hazır olur.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type StatusFilter = 'all' | 'connected' | 'available';
type CategoryFilter = IntegrationCategory | 'all';

export default function IntegrationsPage() {
  const router = useRouter();

  // Auth guard
  useEffect(() => {
    if (!getToken()) router.replace('/login');
  }, [router]);

  // Data state
  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // UI filter state
  const [searchQ, setSearchQ] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all');
  const [showWizard, setShowWizard] = useState(true);

  // Primary tab: data sources (feed the dashboards) vs apps & actions.
  // Default to "veri-kaynaklari" (connecting data is the foundational first step);
  // a ?tab=uygulamalar query opens the apps/actions catalog directly.
  const [mainTab, setMainTab] = useState<'veri-kaynaklari' | 'uygulamalar'>('veri-kaynaklari');

  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('tab');
    if (t === 'uygulamalar') setMainTab('uygulamalar');
  }, []);

  const selectMainTab = useCallback((t: 'veri-kaynaklari' | 'uygulamalar') => {
    setMainTab(t);
    const url = t === 'uygulamalar' ? '/integrations?tab=uygulamalar' : '/integrations';
    window.history.replaceState(null, '', url);
  }, []);

  // Per-key action state
  const [connectingKeys, setConnectingKeys] = useState<Set<string>>(new Set());
  const [disconnectingKeys, setDisconnectingKeys] = useState<Set<string>>(new Set());

  // Modals
  const [apiKeyModal, setApiKeyModal] = useState<CatalogEntry | null>(null);
  const [operatorModal, setOperatorModal] = useState<CatalogEntry | null>(null);
  const [disconnectModal, setDisconnectModal] = useState<CatalogEntry | null>(null);

  // Load data
  const loadData = useCallback(async () => {
    if (!getToken()) return;
    setLoading(true);
    setError(null);
    try {
      const [cat, conns] = await Promise.all([getCatalog(), getConnections()]);
      setCatalog(cat);
      setConnections(conns);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Derived: categories that actually have entries
  const categories = ['all', ...Array.from(new Set(catalog.map((e) => e.category)))];

  // Filter catalog
  const filtered = catalog.filter((entry) => {
    // Category
    if (categoryFilter !== 'all' && entry.category !== categoryFilter) return false;

    // Status
    if (statusFilter === 'connected' && !entry.connected) return false;
    if (statusFilter === 'available' && (entry.connected || entry.coming_soon)) return false;

    // Search
    if (searchQ.trim()) {
      const q = searchQ.toLowerCase();
      const haystack = [
        entry.display_name,
        entry.description,
        entry.category,
        ...(entry.aliases ?? []),
      ]
        .join(' ')
        .toLowerCase();
      if (!haystack.includes(q)) return false;
    }

    return true;
  });

  // Group: recommended first (only when no filters active), then by category
  const recommended = filtered.filter((e) => RECOMMENDED_KEYS.includes(e.key) && !e.connected && !e.coming_soon);
  const rest = filtered.filter((e) => !RECOMMENDED_KEYS.includes(e.key) || e.connected || e.coming_soon);

  const showRecommended =
    recommended.length > 0 && !searchQ && statusFilter === 'all' && categoryFilter === 'all';

  // Connect handler — popup OAuth or api_key modal
  const handleConnect = useCallback(
    async (entry: CatalogEntry) => {
      setConnectingKeys((prev) => new Set(prev).add(entry.key));
      try {
        const response = await connectIntegration(entry.key);

        if (response.mode === 'operator_setup_required') {
          setOperatorModal(entry);
          return;
        }

        if (response.mode === 'api_key') {
          setApiKeyModal(entry);
          return;
        }

        // mode === 'popup'
        if (response.authorize_url) {
          const origin = window.location.origin;
          try {
            await openOAuthPopup(response.authorize_url, origin);
            // Popup closed with success — refresh data without full page reload
            await loadData();
          } catch {
            // Popup closed or blocked — remove connecting state; user may retry
          }
        }
      } catch (err: unknown) {
        alert(parseApiError(err));
      } finally {
        setConnectingKeys((prev) => {
          const next = new Set(prev);
          next.delete(entry.key);
          return next;
        });
      }
    },
    [loadData],
  );

  const handleRequest = useCallback(async (key: string) => {
    try {
      await requestIntegration(key);
      alert('Talebiniz alındı. Hazır olduğunda size haber vereceğiz.');
    } catch {
      // Silently ignore — coming_soon demand signal is best-effort
    }
  }, []);

  const handleDisconnect = useCallback(
    async (entry: CatalogEntry) => {
      if (!entry.connection_id) return;
      setDisconnectingKeys((prev) => new Set(prev).add(entry.key));
      try {
        await disconnectIntegration(entry.key, entry.connection_id);
        await loadData();
      } catch (err: unknown) {
        alert(parseApiError(err));
      } finally {
        setDisconnectingKeys((prev) => {
          const next = new Set(prev);
          next.delete(entry.key);
          return next;
        });
        setDisconnectModal(null);
      }
    },
    [loadData],
  );

  // Progress stats
  const connectedCount = catalog.filter((e) => e.connected).length;
  const totalCount = catalog.filter((e) => !e.coming_soon).length;
  const pct = totalCount > 0 ? Math.round((connectedCount / totalCount) * 100) : 0;

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Entegrasyon Merkezi</h1>
            <p className={styles.pageSubtitle}>
              Tüm reklam, analitik ve aksiyon araçlarınızı tek yerden bağlayın.
            </p>
          </div>
        </div>

        {/* Primary tabs — single front door, split by purpose */}
        <div className={styles.mainTabs} role="tablist" aria-label="Entegrasyon bölümleri">
          <button
            type="button"
            role="tab"
            aria-selected={mainTab === 'veri-kaynaklari'}
            className={`${styles.mainTab} ${mainTab === 'veri-kaynaklari' ? styles.mainTabActive : ''}`}
            onClick={() => selectMainTab('veri-kaynaklari')}
          >
            Veri Kaynakları
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mainTab === 'uygulamalar'}
            className={`${styles.mainTab} ${mainTab === 'uygulamalar' ? styles.mainTabActive : ''}`}
            onClick={() => selectMainTab('uygulamalar')}
          >
            Uygulamalar &amp; Aksiyonlar
            {connectedCount > 0 && <span className={styles.mainTabCount}>{connectedCount}</span>}
          </button>
        </div>

        {/* ── Tab: Veri Kaynakları (data sources that feed the dashboards) ── */}
        {mainTab === 'veri-kaynaklari' && <DataSourcesPanel />}

        {/* ── Tab: Uygulamalar & Aksiyonlar (apps + automated actions) ── */}
        {mainTab === 'uygulamalar' && (
          <>
        {/* Error banner */}
        {error && !loading && (
          <div className={styles.errorBanner}>
            <span>{error}</span>
            <button type="button" className={styles.btnSecondary} onClick={loadData}>
              Tekrar Dene
            </button>
          </div>
        )}

        {/* Progress hero */}
        {!loading && catalog.length > 0 && (
          <div className={styles.progressHero}>
            <div className={styles.progressRow}>
              <span className={styles.progressLabel}>
                Bağlı Uygulama &amp; Aksiyon{' '}
                <span className={styles.progressCount}>
                  {connectedCount}/{totalCount}
                </span>
              </span>
              <span className={styles.progressCount}>{pct}%</span>
            </div>
            <div className={styles.progressTrack}>
              <div className={styles.progressFill} style={{ width: `${pct}%` }} />
            </div>
            <p className={styles.progressTagline}>
              <span className={styles.progressTaglineHighlight}>
                {encouragingLine(connectedCount, totalCount)}
              </span>
            </p>
          </div>
        )}

        {/* Wizard — shown until user dismisses or has 3+ connections */}
        {!loading && showWizard && connectedCount < 3 && catalog.length > 0 && (
          <WizardPanel
            catalog={catalog}
            onConnect={handleConnect}
            onDismiss={() => setShowWizard(false)}
          />
        )}

        {/* Search + status filter */}
        <div className={styles.filterBar}>
          <div className={styles.searchWrap}>
            <svg
              className={styles.searchIcon}
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="search"
              className={styles.searchInput}
              placeholder='Ara: "google", "slack", "analitik"...'
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              aria-label="Entegrasyon ara"
            />
          </div>

          <div className={styles.statusFilter}>
            <span className={styles.statusFilterLabel}>Durum:</span>
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                className={`${styles.statusFilterBtn} ${statusFilter === f.value ? styles.statusFilterBtnActive : ''}`}
                onClick={() => setStatusFilter(f.value)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* Category tabs */}
        <div className={styles.categoryTabs} role="tablist" aria-label="Kategori filtresi">
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              role="tab"
              aria-selected={categoryFilter === cat}
              className={`${styles.categoryTab} ${categoryFilter === cat ? styles.categoryTabActive : ''}`}
              onClick={() => setCategoryFilter(cat as CategoryFilter)}
            >
              {CATEGORY_LABELS[cat] ?? cat}
            </button>
          ))}
        </div>

        {/* Loading state */}
        {loading && (
          <div className={styles.stateBox}>
            <span className={styles.loadingText}>Entegrasyonlar yükleniyor...</span>
          </div>
        )}

        {/* Empty state */}
        {!loading && filtered.length === 0 && !error && (
          <EmptyState
            title="Eşleşen entegrasyon bulunamadı"
            subtitle="Arama teriminizi veya filtreleri değiştirin."
            action={{ label: 'Tüm entegrasyonları göster', onClick: () => { setSearchQ(''); setStatusFilter('all'); setCategoryFilter('all'); } }}
          />
        )}

        {/* Catalog */}
        {!loading && filtered.length > 0 && (
          <div className={styles.catalogSection}>
            {/* Recommended strip */}
            {showRecommended && (
              <div>
                <div className={styles.sectionLabel}>Önerilen Başlangıç</div>
                <div className={styles.cardGrid} style={{ marginTop: '12px' }}>
                  {recommended.map((entry) => (
                    <IntegrationCard
                      key={entry.key}
                      entry={entry}
                      connecting={connectingKeys.has(entry.key)}
                      onConnect={handleConnect}
                      onRequest={handleRequest}
                      onDisconnect={(e) => setDisconnectModal(e)}
                      onReconnect={handleConnect}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* All / remaining cards */}
            {(rest.length > 0 || !showRecommended) && (
              <div>
                {showRecommended && rest.length > 0 && (
                  <div className={styles.sectionLabel}>Tümü</div>
                )}
                <div className={styles.cardGrid} style={{ marginTop: showRecommended && rest.length > 0 ? '12px' : undefined }}>
                  {(showRecommended ? rest : filtered).map((entry) => (
                    <IntegrationCard
                      key={entry.key}
                      entry={entry}
                      connecting={connectingKeys.has(entry.key)}
                      onConnect={handleConnect}
                      onRequest={handleRequest}
                      onDisconnect={(e) => setDisconnectModal(e)}
                      onReconnect={handleConnect}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
          </>
        )}
      </main>

      {/* Modals */}
      {apiKeyModal && (
        <ApiKeyModal
          entry={apiKeyModal}
          onClose={() => setApiKeyModal(null)}
          onConnected={() => {
            setApiKeyModal(null);
            loadData();
          }}
        />
      )}

      {operatorModal && (
        <OperatorSetupModal
          entryName={operatorModal.display_name}
          onClose={() => setOperatorModal(null)}
        />
      )}

      {disconnectModal && (
        <DisconnectConfirmModal
          entryName={disconnectModal.display_name}
          loading={disconnectingKeys.has(disconnectModal.key)}
          onCancel={() => setDisconnectModal(null)}
          onConfirm={() => handleDisconnect(disconnectModal)}
        />
      )}
    </div>
  );
}
