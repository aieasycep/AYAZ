'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import {
  listRoles,
  getRoleView,
  type RoleSummary,
  type RoleView,
  type AttentionSeverity,
} from '@/lib/role-views-api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './roles.module.css';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ROLE_STORAGE_KEY = 'ayaz_role';

// ---------------------------------------------------------------------------
// Icon map — inline SVGs keyed by icon_key
// ---------------------------------------------------------------------------

function RoleIcon({ iconKey, size = 20 }: { iconKey: string; size?: number }) {
  const strokeProps = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };

  switch (iconKey) {
    case 'trending':
      return (
        <svg {...strokeProps}>
          <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
          <polyline points="17 6 23 6 23 12" />
        </svg>
      );
    case 'palette':
      return (
        <svg {...strokeProps}>
          <circle cx="13.5" cy="6.5" r=".5" fill="currentColor" />
          <circle cx="17.5" cy="10.5" r=".5" fill="currentColor" />
          <circle cx="8.5" cy="7.5" r=".5" fill="currentColor" />
          <circle cx="6.5" cy="12.5" r=".5" fill="currentColor" />
          <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z" />
        </svg>
      );
    case 'chat':
      return (
        <svg {...strokeProps}>
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      );
    case 'calendar':
      return (
        <svg {...strokeProps}>
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      );
    case 'chart':
      return (
        <svg {...strokeProps}>
          <line x1="18" y1="20" x2="18" y2="10" />
          <line x1="12" y1="20" x2="12" y2="4" />
          <line x1="6" y1="20" x2="6" y2="14" />
        </svg>
      );
    default:
      // Generic grid icon as fallback
      return (
        <svg {...strokeProps}>
          <rect x="3" y="3" width="7" height="7" />
          <rect x="14" y="3" width="7" height="7" />
          <rect x="14" y="14" width="7" height="7" />
          <rect x="3" y="14" width="7" height="7" />
        </svg>
      );
  }
}

// ---------------------------------------------------------------------------
// Severity dot
// ---------------------------------------------------------------------------

function SeverityDot({ severity }: { severity: AttentionSeverity }) {
  const cls =
    severity === 'high'
      ? styles.severityHigh
      : severity === 'medium'
        ? styles.severityMedium
        : styles.severityLow;
  return <span className={`${styles.severityDot} ${cls}`} aria-hidden="true" />;
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function LoadingSkeletonRoles() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonRolePicker}`} />
      <div className={`${styles.skeleton} ${styles.skeletonMetrics}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

function LoadingSkeletonView() {
  return (
    <>
      <div className={`${styles.skeleton} ${styles.skeletonMetrics}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function RolesPage() {
  const [roles, setRoles] = useState<RoleSummary[]>([]);
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [view, setView] = useState<RoleView | null>(null);

  const [rolesLoading, setRolesLoading] = useState(true);
  const [rolesError, setRolesError] = useState<string | null>(null);

  const [viewLoading, setViewLoading] = useState(false);
  const [viewError, setViewError] = useState<string | null>(null);

  // Fetch the role view for a given key
  const fetchView = useCallback(async (roleKey: string) => {
    setViewLoading(true);
    setViewError(null);
    try {
      const result = await getRoleView(roleKey);
      setView(result);
    } catch (err: unknown) {
      setViewError(
        parseApiError(err),
      );
    } finally {
      setViewLoading(false);
    }
  }, []);

  // Select a role: persist + fetch view
  function selectRole(roleKey: string) {
    setSelectedRole(roleKey);
    if (typeof window !== 'undefined') {
      localStorage.setItem(ROLE_STORAGE_KEY, roleKey);
    }
    fetchView(roleKey);
  }

  // Fetch roles list on mount
  const fetchRoles = useCallback(async () => {
    setRolesLoading(true);
    setRolesError(null);
    try {
      const result = await listRoles();
      setRoles(result);

      // Determine initial role: stored → first from list
      const stored =
        typeof window !== 'undefined'
          ? localStorage.getItem(ROLE_STORAGE_KEY)
          : null;
      const initial =
        stored && result.find((r) => r.key === stored)
          ? stored
          : result[0]?.key ?? null;

      if (initial) {
        setSelectedRole(initial);
        fetchView(initial);
      }
    } catch (err: unknown) {
      setRolesError(
        parseApiError(err),
      );
    } finally {
      setRolesLoading(false);
    }
  }, [fetchView]);

  useEffect(() => {
    fetchRoles();
  }, [fetchRoles]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Rol Görünümü</h1>
          <p className={styles.pageSubtitle}>
            Ekibinizin rolünü seçin, size özel pazarlama kokpitini görün.
          </p>
        </div>

        {/* Roles loading / error / picker */}
        {rolesLoading ? (
          <LoadingSkeletonRoles />
        ) : rolesError ? (
          <div className={styles.errorBox}>
            <span className={styles.errorText}>{rolesError}</span>
            <button className={styles.retryBtn} onClick={fetchRoles}>
              Tekrar Dene
            </button>
          </div>
        ) : (
          <>
            {/* Role picker */}
            <SectionCard title="Rol Seçin">
              <div className={styles.rolePicker} role="listbox" aria-label="Rol seçici">
                {roles.map((role) => (
                  <button
                    key={role.key}
                    role="option"
                    aria-selected={selectedRole === role.key}
                    className={`${styles.roleCard} ${selectedRole === role.key ? styles.roleCardActive : ''}`}
                    onClick={() => selectRole(role.key)}
                    type="button"
                  >
                    <span className={styles.roleCardIcon}>
                      <RoleIcon iconKey={role.icon_key} size={18} />
                    </span>
                    <span className={styles.roleCardBody}>
                      <span className={styles.roleCardLabel}>{role.label}</span>
                      <span className={styles.roleCardDesc}>{role.description}</span>
                    </span>
                  </button>
                ))}
              </div>
            </SectionCard>

            {/* Role view */}
            {viewLoading ? (
              <LoadingSkeletonView />
            ) : viewError ? (
              <div className={styles.errorBox}>
                <span className={styles.errorText}>{viewError}</span>
                {selectedRole && (
                  <button
                    className={styles.retryBtn}
                    onClick={() => fetchView(selectedRole)}
                  >
                    Tekrar Dene
                  </button>
                )}
              </div>
            ) : view ? (
              <div className={styles.viewGrid}>

                {/* Metric tiles */}
                {view.metrics.length > 0 && (
                  <SectionCard title="Metrikler">
                    <div className={styles.metricsGrid}>
                      {view.metrics.map((metric, i) => (
                        <div key={i} className={styles.metricCard}>
                          <span className={styles.metricLabel}>{metric.label}</span>
                          <span className={styles.metricValue}>{metric.value}</span>
                          <span className={styles.metricHint}>{metric.hint}</span>
                        </div>
                      ))}
                    </div>
                  </SectionCard>
                )}

                {/* Dikkat gerektirenler */}
                <SectionCard title="Dikkat Gerektirenler">
                  {view.attention.length === 0 ? (
                    <div className={styles.emptyState}>
                      Şu an dikkat gerektiren bir şey yok.
                    </div>
                  ) : (
                    <div className={styles.attentionList}>
                      {view.attention.map((item, i) => (
                        <div key={i} className={styles.attentionItem}>
                          <SeverityDot severity={item.severity} />
                          <div className={styles.attentionBody}>
                            <div className={styles.attentionTitle}>{item.title}</div>
                            <div className={styles.attentionDetail}>{item.detail}</div>
                          </div>
                          <Link href={item.href} className={styles.attentionLink}>
                            Git &rarr;
                          </Link>
                        </div>
                      ))}
                    </div>
                  )}
                </SectionCard>

                {/* Öncelikli ekranlar */}
                {view.priority_screens.length > 0 && (
                  <SectionCard title="Öncelikli Ekranlar">
                    <div className={styles.priorityGrid}>
                      {view.priority_screens.map((screen, i) => (
                        <Link key={i} href={screen.href} className={styles.priorityCard}>
                          <span className={styles.priorityLabel}>{screen.label}</span>
                          <span className={styles.priorityWhy}>{screen.why}</span>
                        </Link>
                      ))}
                    </div>
                  </SectionCard>
                )}

                {/* Hızlı işlemler */}
                {view.quick_actions.length > 0 && (
                  <SectionCard title="Hızlı İşlemler">
                    <div className={styles.quickActionsRow}>
                      {view.quick_actions.map((action, i) => (
                        <Link key={i} href={action.href} className={styles.quickActionBtn}>
                          {action.label}
                        </Link>
                      ))}
                    </div>
                  </SectionCard>
                )}

              </div>
            ) : null}
          </>
        )}
      </main>
    </div>
  );
}
