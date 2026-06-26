'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getGoals,
  createGoal,
  deleteGoal,
  getGoalProgress,
  type Goal,
  type GoalProgress,
  type GoalMetric,
  type GoalStatus,
  type CreateGoalPayload,
} from '@/lib/goals-api';
import AppNav from '@/components/AppNav';
import styles from './goals.module.css';

// --- Formatters ---

function fmtCurrency(n: number, decimals = 0): string {
  return new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency: 'TRY',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

function fmtRoas(n: number): string {
  return (
    n.toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + 'x'
  );
}

function fmtNum(n: number): string {
  return new Intl.NumberFormat('tr-TR').format(Math.round(n));
}

function fmtMetricValue(metric: GoalMetric, value: number): string {
  switch (metric) {
    case 'spend':
    case 'conversion_value':
      return fmtCurrency(value);
    case 'roas':
      return fmtRoas(value);
    case 'conversions':
      return fmtNum(value);
  }
}

// --- Labels ---

function metricLabel(m: GoalMetric): string {
  switch (m) {
    case 'spend': return 'Harcama';
    case 'roas': return 'ROAS';
    case 'conversions': return 'Dönüşüm';
    case 'conversion_value': return 'Gelir';
  }
}

function statusLabel(s: GoalStatus): string {
  switch (s) {
    case 'on_track': return 'Yolunda';
    case 'at_risk': return 'Risk Altında';
    case 'off_track': return 'Geride';
  }
}

function statusBadgeClass(s: GoalStatus): string {
  switch (s) {
    case 'on_track': return styles.badgeOnTrack;
    case 'at_risk': return styles.badgeAtRisk;
    case 'off_track': return styles.badgeBehind;
  }
}

function progressFillClass(s: GoalStatus): string {
  switch (s) {
    case 'on_track': return styles.progressFillOnTrack;
    case 'at_risk': return styles.progressFillAtRisk;
    case 'off_track': return styles.progressFillBehind;
  }
}

// --- Date helpers ---

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getDefaultPeriodDates() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  const end = new Date(now.getFullYear(), now.getMonth() + 1, 0);
  return { start: toISODate(start), end: toISODate(end) };
}

// --- Goal card with lazy-loaded progress ---

interface GoalCardProps {
  goal: Goal;
  onDelete: (id: string) => void;
}

function GoalCard({ goal, onDelete }: GoalCardProps) {
  const [progress, setProgress] = useState<GoalProgress | null>(null);
  const [progressLoading, setProgressLoading] = useState(true);
  const [progressError, setProgressError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setProgressLoading(true);
    setProgressError(null);
    getGoalProgress(goal.id)
      .then((data) => {
        if (!cancelled) {
          setProgress(data);
          setProgressLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setProgressError(err instanceof Error ? err.message : 'Veriler alınamadı');
          setProgressLoading(false);
        }
      });
    return () => { cancelled = true; };
  }, [goal.id]);

  const pctCapped = progress
    ? Math.min(100, Math.max(0, progress.pct_to_target * 100))
    : 0;

  return (
    <div className={styles.goalCard}>
      {/* Top row: name + badge + delete */}
      <div className={styles.goalCardTop}>
        <div className={styles.goalMeta}>
          <div className={styles.goalName}>{goal.name}</div>
          <div className={styles.goalMetricRow}>
            <span className={styles.goalMetricTag}>{metricLabel(goal.metric)}</span>
            {goal.channel && (
              <span className={styles.goalChannel}>{goal.channel}</span>
            )}
            <span className={styles.goalPeriod}>
              {goal.period_start} – {goal.period_end}
            </span>
          </div>
        </div>
        <div className={styles.goalActions}>
          {progress && (
            <span className={`${styles.badge} ${statusBadgeClass(progress.status)}`}>
              {statusLabel(progress.status)}
            </span>
          )}
          <button
            className={styles.deleteBtn}
            onClick={() => onDelete(goal.id)}
          >
            Sil
          </button>
        </div>
      </div>

      {/* Progress */}
      {progressLoading && (
        <div className={styles.progressLoading}>Veriler yükleniyor...</div>
      )}
      {progressError && (
        <div className={styles.progressError}>{progressError}</div>
      )}
      {progress && !progressLoading && (
        <>
          <div className={styles.progressSection}>
            <div className={styles.progressLabels}>
              <span className={styles.progressCurrent}>
                {fmtMetricValue(goal.metric, progress.current_value)}
              </span>
              <span className={styles.progressTarget}>
                Hedef: {fmtMetricValue(goal.metric, progress.target_value)}
              </span>
            </div>
            <div className={styles.progressTrack}>
              <div
                className={`${styles.progressFill} ${progressFillClass(progress.status)}`}
                style={{ width: `${pctCapped}%` }}
              />
            </div>
          </div>

          {/* Forecast */}
          <div className={styles.forecastLine}>
            Tahmin: dönem sonu{' '}
            <span className={styles.forecastValue}>
              {fmtMetricValue(goal.metric, progress.forecast_value)}
            </span>
            {' '}— hedef{' '}
            <span className={styles.forecastValue}>
              {fmtMetricValue(goal.metric, progress.target_value)}
            </span>
            {' '}({progress.days_elapsed}/{progress.days_total} gün geçti)
          </div>

          {/* Recommendation */}
          {progress.recommendation && (
            <div className={styles.recommendation}>{progress.recommendation}</div>
          )}
        </>
      )}
    </div>
  );
}

// --- New goal form ---

interface NewGoalFormProps {
  onClose: () => void;
  onCreated: (goal: Goal) => void;
}

function NewGoalForm({ onClose, onCreated }: NewGoalFormProps) {
  const defaultPeriod = getDefaultPeriodDates();
  const [name, setName] = useState('');
  const [metric, setMetric] = useState<GoalMetric>('conversion_value');
  const [targetValue, setTargetValue] = useState('');
  const [period, setPeriod] = useState('ay');
  const [periodStart, setPeriodStart] = useState(defaultPeriod.start);
  const [periodEnd, setPeriodEnd] = useState(defaultPeriod.end);
  const [channel, setChannel] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      setFormError('Hedef adı zorunludur.');
      return;
    }
    const tv = parseFloat(targetValue);
    if (isNaN(tv) || tv <= 0) {
      setFormError('Geçerli bir hedef değeri girin.');
      return;
    }
    setFormError(null);
    setSubmitting(true);
    try {
      const payload: CreateGoalPayload = {
        name: name.trim(),
        metric,
        target_value: tv,
        period,
        period_start: periodStart,
        period_end: periodEnd,
        channel: channel.trim() || null,
      };
      const created = await createGoal(payload);
      onCreated(created);
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Hedef oluşturulamadı');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.formBox} onClick={(e) => e.stopPropagation()}>
        <div className={styles.formTitle}>Yeni Hedef</div>
        <form onSubmit={handleSubmit} style={{ display: 'contents' }}>
          <div className={styles.formField}>
            <label className={styles.formLabel} htmlFor="goal-name">
              Hedef Adı
            </label>
            <input
              id="goal-name"
              className={styles.formInput}
              type="text"
              placeholder="ör. Mart Gelir Hedefi"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          <div className={styles.formRow}>
            <div className={styles.formField}>
              <label className={styles.formLabel} htmlFor="goal-metric">
                Metrik
              </label>
              <select
                id="goal-metric"
                className={styles.formSelect}
                value={metric}
                onChange={(e) => setMetric(e.target.value as GoalMetric)}
              >
                <option value="conversion_value">Gelir</option>
                <option value="spend">Harcama</option>
                <option value="roas">ROAS</option>
                <option value="conversions">Dönüşüm</option>
              </select>
            </div>

            <div className={styles.formField}>
              <label className={styles.formLabel} htmlFor="goal-target">
                Hedef Değer
              </label>
              <input
                id="goal-target"
                className={styles.formInput}
                type="number"
                min="0"
                step="any"
                placeholder="ör. 500000"
                value={targetValue}
                onChange={(e) => setTargetValue(e.target.value)}
              />
            </div>
          </div>

          <div className={styles.formRow}>
            <div className={styles.formField}>
              <label className={styles.formLabel} htmlFor="goal-period-start">
                Dönem Başlangıç
              </label>
              <input
                id="goal-period-start"
                className={styles.formInput}
                type="date"
                value={periodStart}
                max={periodEnd}
                onChange={(e) => setPeriodStart(e.target.value)}
              />
            </div>
            <div className={styles.formField}>
              <label className={styles.formLabel} htmlFor="goal-period-end">
                Dönem Bitiş
              </label>
              <input
                id="goal-period-end"
                className={styles.formInput}
                type="date"
                value={periodEnd}
                min={periodStart}
                onChange={(e) => setPeriodEnd(e.target.value)}
              />
            </div>
          </div>

          <div className={styles.formField}>
            <label className={styles.formLabel} htmlFor="goal-channel">
              Kanal (opsiyonel)
            </label>
            <input
              id="goal-channel"
              className={styles.formInput}
              type="text"
              placeholder="ör. Google Ads"
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            />
          </div>

          {formError && (
            <div className={styles.formError}>{formError}</div>
          )}

          <div className={styles.formActions}>
            <button
              type="button"
              className={styles.formCancelBtn}
              onClick={onClose}
            >
              İptal
            </button>
            <button
              type="submit"
              className={styles.formSubmitBtn}
              disabled={submitting}
            >
              {submitting ? 'Kaydediliyor...' : 'Kaydet'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// --- Page ---

export default function GoalsPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) router.replace('/login');
  }, [router]);

  const [goals, setGoals] = useState<Goal[]>([]);
  const [goalsLoading, setGoalsLoading] = useState(true);
  const [goalsError, setGoalsError] = useState<string | null>(null);

  const fetchGoals = useCallback(async () => {
    setGoalsLoading(true);
    setGoalsError(null);
    try {
      const data = await getGoals();
      setGoals(data);
    } catch (err: unknown) {
      setGoalsError(err instanceof Error ? err.message : 'Hedefler yüklenemedi');
    } finally {
      setGoalsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchGoals();
  }, [fetchGoals]);

  const [showForm, setShowForm] = useState(false);

  function handleCreated(goal: Goal) {
    setGoals((prev) => [goal, ...prev]);
    setShowForm(false);
  }

  async function handleDelete(id: string) {
    try {
      await deleteGoal(id);
      setGoals((prev) => prev.filter((g) => g.id !== id));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Hedef silinemedi');
    }
  }

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Hedefler</h1>
            <p className={styles.pageSubtitle}>
              Pazarlama hedeflerinizi takip edin, ilerlemeyi ve tahminleri tek ekrandan görün.
            </p>
          </div>
          <button
            className={styles.newGoalBtn}
            onClick={() => setShowForm(true)}
          >
            + Yeni Hedef
          </button>
        </div>

        {/* Goals list */}
        <section className={styles.section}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>
              Aktif Hedefler
              {goals.length > 0 ? ` (${goals.length})` : ''}
            </h2>
          </div>

          {goalsLoading ? (
            <div className={styles.stateBox}>
              <span className={styles.muted}>Hedefler yükleniyor...</span>
            </div>
          ) : goalsError ? (
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{goalsError}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchGoals}>
                Tekrar Dene
              </button>
            </div>
          ) : goals.length === 0 ? (
            <div className={styles.stateBox}>
              <span className={styles.muted}>
                Henüz hedef oluşturulmamış. "Yeni Hedef" ile başlayın.
              </span>
            </div>
          ) : (
            <div className={styles.goalList}>
              {goals.map((goal) => (
                <GoalCard
                  key={goal.id}
                  goal={goal}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          )}
        </section>
      </main>

      {/* New goal form modal */}
      {showForm && (
        <NewGoalForm
          onClose={() => setShowForm(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  );
}
