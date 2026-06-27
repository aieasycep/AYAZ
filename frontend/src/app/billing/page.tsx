'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import AppNav from '@/components/AppNav';
import {
  getPlans,
  getSubscription,
  postCheckout,
  postCancel,
  type Plan,
  type Subscription,
  type SubscriptionStatus,
} from '@/lib/billing-api';
import styles from './billing.module.css';

// ---- helpers ----

const TOKEN_KEY = 'ayaz_token';
function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

function formatDate(iso: string | null): string {
  if (!iso) return '-';
  return new Intl.DateTimeFormat('tr-TR', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date(iso));
}

function formatTry(amount: number): string {
  return new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency: 'TRY',
    maximumFractionDigits: 0,
  }).format(amount);
}

const STATUS_LABELS: Record<SubscriptionStatus, string> = {
  trialing: 'Deneme',
  active: 'Aktif',
  past_due: 'Gecikmiş',
  canceled: 'İptal',
  unknown: 'Bilinmiyor',
};

const STATUS_CSS: Record<SubscriptionStatus, string> = {
  trialing: styles.statusTrialing,
  active: styles.statusActive,
  past_due: styles.statusPastDue,
  canceled: styles.statusCanceled,
  unknown: styles.statusCanceled,
};

// Plans in intended display order; Growth is "recommended"
const PLAN_ORDER = ['free', 'starter', 'growth', 'agency'];
const RECOMMENDED_PLAN = 'growth';

// ---- Cancel confirm dialog ----

interface CancelDialogProps {
  onConfirm: () => void;
  onDismiss: () => void;
  loading: boolean;
  error: string | null;
}

function CancelDialog({ onConfirm, onDismiss, loading, error }: CancelDialogProps) {
  return (
    <div className={styles.overlay}>
      <div className={styles.dialog}>
        <div className={styles.dialogTitle}>Aboneliği iptal et</div>
        <div className={styles.dialogBody}>
          Aboneliğinizi iptal etmek istediğinizden emin misiniz? Mevcut dönem
          sonunda planınız ücretsiz plana geçecektir.
        </div>
        {error && <div className={styles.errorText} style={{ marginBottom: '0.75rem' }}>{error}</div>}
        <div className={styles.dialogActions}>
          <button className={styles.dialogCancelBtn} onClick={onDismiss} disabled={loading}>
            Vazgeç
          </button>
          <button className={styles.dialogConfirmBtn} onClick={onConfirm} disabled={loading}>
            {loading ? 'İptal ediliyor...' : 'Evet, iptal et'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---- Usage bar ----

interface UsageBarProps {
  used: number;
  limit: number | null;
}

function UsageBar({ used, limit }: UsageBarProps) {
  const pct = limit == null ? 0 : Math.min(100, (used / limit) * 100);
  const fillClass =
    pct >= 90
      ? styles.usageBarFillDanger
      : pct >= 70
      ? styles.usageBarFillWarning
      : styles.usageBarFill;

  return (
    <div className={styles.usageBox}>
      <div className={styles.usageLabel}>Veri kaynağı kullanımı</div>
      <div className={styles.usageBarTrack}>
        <div
          className={`${styles.usageBarFill} ${fillClass}`}
          style={{ width: limit == null ? '0%' : `${pct}%` }}
        />
      </div>
      <div className={styles.usageText}>
        {limit == null ? `${used} / Sınırsız` : `${used} / ${limit}`}
      </div>
    </div>
  );
}

// ---- Plan card ----

interface PlanCardProps {
  plan: Plan;
  isCurrent: boolean;
  isRecommended: boolean;
  onUpgrade: (code: string) => void;
  upgrading: string | null;
  testModeCode: string | null;
}

function PlanCard({
  plan,
  isCurrent,
  isRecommended,
  onUpgrade,
  upgrading,
  testModeCode,
}: PlanCardProps) {
  const cardClass = [
    styles.planCard,
    isCurrent ? styles.planCardCurrent : '',
    isRecommended && !isCurrent ? styles.planCardRecommended : '',
  ]
    .filter(Boolean)
    .join(' ');

  const dataSourceLimit = plan.limits?.data_sources ?? null;

  return (
    <div className={cardClass}>
      {isCurrent && <span className={styles.currentBadge}>Mevcut plan</span>}
      {isRecommended && !isCurrent && (
        <span className={styles.recommendedBadge}>Önerilen</span>
      )}

      <div className={styles.planName}>{plan.name}</div>

      <div className={styles.planPrice}>
        <span className={styles.planPriceTry}>
          {plan.price_try === 0 ? 'Ücretsiz' : formatTry(plan.price_try)}
        </span>
        {plan.price_try > 0 && plan.price_usd > 0 && (
          <span className={styles.planPriceUsd}>/ ay · ${plan.price_usd}</span>
        )}
        {plan.price_try === 0 && <span className={styles.planPriceUsd}>/ ay</span>}
      </div>

      <ul className={styles.planFeaturesList}>
        {dataSourceLimit !== null && (
          <li className={styles.planFeatureItem}>
            <svg className={styles.featureCheck} viewBox="0 0 16 16" fill="none">
              <path
                d="M3 8l3.5 3.5L13 4.5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {dataSourceLimit} veri kaynağı
          </li>
        )}
        {dataSourceLimit === null && (
          <li className={styles.planFeatureItem}>
            <svg className={styles.featureCheck} viewBox="0 0 16 16" fill="none">
              <path
                d="M3 8l3.5 3.5L13 4.5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            Sınırsız veri kaynağı
          </li>
        )}
        {plan.features.map((f) => (
          <li key={f} className={styles.planFeatureItem}>
            <svg className={styles.featureCheck} viewBox="0 0 16 16" fill="none">
              <path
                d="M3 8l3.5 3.5L13 4.5"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {f}
          </li>
        ))}
      </ul>

      {isCurrent ? (
        <div className={styles.currentPlanBtn}>Bu plandasınız</div>
      ) : (
        <button
          className={`${styles.upgradeBtn} ${isRecommended ? styles.upgradeBtnRecommended : ''}`}
          onClick={() => onUpgrade(plan.code)}
          disabled={upgrading !== null}
        >
          {upgrading === plan.code
            ? 'Yönlendiriliyor...'
            : plan.price_try === 0
            ? 'Bu plana geç'
            : 'Yükselt'}
        </button>
      )}

      {testModeCode === plan.code && (
        <div className={styles.testModeNote}>
          Test modu — gerçek ödeme alınmaz
        </div>
      )}
    </div>
  );
}

// ---- Main page ----

export default function BillingPage() {
  const router = useRouter();

  const [plans, setPlans] = useState<Plan[]>([]);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [plansLoading, setPlansLoading] = useState(true);
  const [subLoading, setSubLoading] = useState(true);
  const [plansError, setPlansError] = useState<string | null>(null);
  const [subError, setSubError] = useState<string | null>(null);

  const [upgrading, setUpgrading] = useState<string | null>(null);
  const [upgradeError, setUpgradeError] = useState<string | null>(null);
  const [testModeCode, setTestModeCode] = useState<string | null>(null);

  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [canceling, setCanceling] = useState(false);
  const [cancelError, setCancelError] = useState<string | null>(null);

  // Auth guard
  useEffect(() => {
    if (!getToken()) {
      router.push('/login');
    }
  }, [router]);

  const loadPlans = useCallback(async () => {
    setPlansLoading(true);
    setPlansError(null);
    try {
      const data = await getPlans();
      // Sort by defined order
      const sorted = [...data].sort((a, b) => {
        const ai = PLAN_ORDER.indexOf(a.code);
        const bi = PLAN_ORDER.indexOf(b.code);
        return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
      });
      setPlans(sorted);
    } catch (e) {
      setPlansError(e instanceof Error ? e.message : 'Planlar yüklenemedi');
    } finally {
      setPlansLoading(false);
    }
  }, []);

  const loadSubscription = useCallback(async () => {
    setSubLoading(true);
    setSubError(null);
    try {
      const data = await getSubscription();
      setSubscription(data);
    } catch (e) {
      setSubError(
        e instanceof Error ? e.message : 'Abonelik bilgisi yüklenemedi',
      );
    } finally {
      setSubLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPlans();
    loadSubscription();
  }, [loadPlans, loadSubscription]);

  async function handleUpgrade(planCode: string) {
    setUpgrading(planCode);
    setUpgradeError(null);
    setTestModeCode(null);
    try {
      const { checkout_url } = await postCheckout(planCode);
      const isTest =
        checkout_url.includes('test') ||
        checkout_url.includes('localhost') ||
        checkout_url.includes('sandbox');
      if (isTest) {
        setTestModeCode(planCode);
      }
      window.open(checkout_url, '_blank', 'noopener,noreferrer');
    } catch (e) {
      setUpgradeError(
        e instanceof Error ? e.message : 'Ödeme sayfası açılamadı',
      );
    } finally {
      setUpgrading(null);
    }
  }

  async function handleCancelConfirm() {
    setCanceling(true);
    setCancelError(null);
    try {
      await postCancel();
      setShowCancelDialog(false);
      await loadSubscription();
    } catch (e) {
      setCancelError(
        e instanceof Error ? e.message : 'İptal işlemi gerçekleştirilemedi',
      );
    } finally {
      setCanceling(false);
    }
  }

  // Derive current plan from plans list
  const currentPlan =
    subscription != null
      ? plans.find((p) => p.code === subscription.plan_code) ?? null
      : null;

  const canCancel =
    subscription != null &&
    subscription.status !== 'canceled' &&
    subscription.plan_code !== 'free';

  const periodLabel =
    subscription?.status === 'trialing' && subscription.trial_end
      ? `Deneme süresi bitiş: ${formatDate(subscription.trial_end)}`
      : subscription?.current_period_end
      ? `Dönem bitiş: ${formatDate(subscription.current_period_end)}`
      : null;

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Faturalama</h1>
            <p className={styles.pageSubtitle}>
              Aboneliğinizi ve planınızı yönetin
            </p>
          </div>
        </div>

        {/* Current subscription section */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <span className={styles.sectionTitle}>Mevcut Plan</span>
          </div>
          <div className={styles.sectionBody}>
            {subLoading ? (
              <div className={styles.stateBox}>
                <div className={styles.muted}>Yükleniyor...</div>
              </div>
            ) : subError ? (
              <div className={styles.stateBox}>
                <div className={styles.errorText}>{subError}</div>
                <button className={styles.retryBtn} onClick={loadSubscription}>
                  Tekrar dene
                </button>
              </div>
            ) : subscription == null ? (
              <div className={styles.stateBox}>
                <div className={styles.muted}>Abonelik bilgisi bulunamadı.</div>
              </div>
            ) : (
              <div className={styles.currentPlanCard}>
                <div className={styles.currentPlanInfo}>
                  <div className={styles.currentPlanName}>
                    {currentPlan?.name ?? subscription.plan_code}
                  </div>
                  <span
                    className={`${styles.statusBadge} ${STATUS_CSS[subscription.status] ?? styles.statusCanceled}`}
                  >
                    {STATUS_LABELS[subscription.status] ?? subscription.status}
                  </span>
                  {periodLabel && (
                    <div className={styles.periodText}>{periodLabel}</div>
                  )}
                </div>

                <UsageBar
                  used={subscription.usage.data_sources_used}
                  limit={currentPlan?.limits?.data_sources ?? null}
                />

                {canCancel && (
                  <div className={styles.cancelArea}>
                    <button
                      className={styles.cancelBtn}
                      onClick={() => setShowCancelDialog(true)}
                    >
                      Aboneliği iptal et
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        {/* Plan comparison section */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <span className={styles.sectionTitle}>Plan Karşılaştırma</span>
          </div>

          {upgradeError && (
            <div
              style={{ padding: '0.75rem 1.5rem' }}
              className={styles.errorText}
            >
              {upgradeError}
            </div>
          )}

          {plansLoading ? (
            <div className={styles.stateBox}>
              <div className={styles.muted}>Planlar yükleniyor...</div>
            </div>
          ) : plansError ? (
            <div className={styles.stateBox}>
              <div className={styles.errorText}>{plansError}</div>
              <button className={styles.retryBtn} onClick={loadPlans}>
                Tekrar dene
              </button>
            </div>
          ) : plans.length === 0 ? (
            <div className={styles.stateBox}>
              <div className={styles.muted}>Plan bilgisi bulunamadı.</div>
            </div>
          ) : (
            <div className={styles.plansGrid}>
              {plans.map((plan) => (
                <PlanCard
                  key={plan.code}
                  plan={plan}
                  isCurrent={subscription?.plan_code === plan.code}
                  isRecommended={plan.code === RECOMMENDED_PLAN}
                  onUpgrade={handleUpgrade}
                  upgrading={upgrading}
                  testModeCode={testModeCode}
                />
              ))}
            </div>
          )}
        </section>
      </main>

      {showCancelDialog && (
        <CancelDialog
          onConfirm={handleCancelConfirm}
          onDismiss={() => {
            setShowCancelDialog(false);
            setCancelError(null);
          }}
          loading={canceling}
          error={cancelError}
        />
      )}
    </div>
  );
}
