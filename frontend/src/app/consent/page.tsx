'use client';

import { useState, useEffect, useCallback } from 'react';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import {
  getConsentCenter,
  GRADE_LABELS,
  type ConsentCenter,
  type ConsentSignal,
  type ConsentDestination,
  type ConsentSource,
  type ConsentCheck,
  type ConsentAuditEntry,
  type ConsentGrade,
  type ConsentCheckStatus,
} from '@/lib/consent-api';
import { parseApiError } from '@/lib/parseApiError';
import styles from './consent.module.css';

// ============================================================
// Helpers
// ============================================================

function gradeClass(grade: ConsentGrade): string {
  switch (grade) {
    case 'uyumlu':
      return styles.gradeUyumlu;
    case 'kismi':
      return styles.gradeKismi;
    case 'eksik':
      return styles.gradeEksik;
    default:
      return styles.gradeUyumlu;
  }
}

function ringFillClass(grade: ConsentGrade): string {
  switch (grade) {
    case 'uyumlu':
      return styles.scoreRingFillGreen;
    case 'kismi':
      return styles.scoreRingFillAmber;
    case 'eksik':
      return styles.scoreRingFillRed;
    default:
      return styles.scoreRingFillGreen;
  }
}

function progressFillClass(pct: number): string {
  if (pct >= 70) return styles.progressFill;
  if (pct >= 40) return `${styles.progressFill} ${styles.progressFillAmber}`;
  return `${styles.progressFill} ${styles.progressFillRed}`;
}

function postureClass(posture: string): string {
  const lower = posture.toLowerCase();
  if (lower.startsWith('katı')) return styles.postureKati;
  return styles.postureGevsek;
}

function statusBadgeClass(status: string): string {
  if (status === 'forwarded') return styles.statusBadgeForwarded;
  if (status === 'skipped' || status === 'skipped_no_consent')
    return styles.statusBadgeSkipped;
  return styles.statusBadgeDefault;
}

function formatEventTime(iso: string): string {
  try {
    return new Intl.DateTimeFormat('tr-TR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

// ============================================================
// SVG score ring — same idiom as audit page
// ============================================================

const RING_R = 46;
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_R;

interface ScoreRingProps {
  score: number;
  grade: ConsentGrade;
}

function ScoreRing({ score, grade }: ScoreRingProps) {
  const offset =
    RING_CIRCUMFERENCE * (1 - Math.min(Math.max(score, 0), 100) / 100);
  return (
    <div className={styles.scoreRing}>
      <svg
        className={styles.scoreRingCircle}
        viewBox="0 0 110 110"
        aria-hidden="true"
      >
        <circle
          className={styles.scoreRingTrack}
          cx="55"
          cy="55"
          r={RING_R}
        />
        <circle
          className={ringFillClass(grade)}
          cx="55"
          cy="55"
          r={RING_R}
          strokeDasharray={RING_CIRCUMFERENCE}
          strokeDashoffset={offset}
        />
      </svg>
      <div>
        <div className={styles.scoreNumber}>{score}</div>
        <div className={styles.scoreOutOf}>/100</div>
      </div>
    </div>
  );
}

// ============================================================
// Severity icon — mirrors audit page
// ============================================================

function SeverityIcon({ status }: { status: ConsentCheckStatus }) {
  const cls =
    status === 'pass'
      ? styles.severityPass
      : status === 'warn'
      ? styles.severityWarn
      : styles.severityFail;
  const symbol =
    status === 'pass' ? '✓' : status === 'warn' ? '⚠' : '✕';
  return (
    <span
      className={`${styles.severityIcon} ${cls}`}
      aria-label={status}
    >
      {symbol}
    </span>
  );
}

// ============================================================
// Consent signal card
// ============================================================

function SignalCard({ signal }: { signal: ConsentSignal }) {
  return (
    <div className={styles.signalCard}>
      <div className={styles.signalLabel}>{signal.label}</div>
      <div className={styles.signalRate}>%{signal.grant_rate_pct.toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}</div>
      <div className={styles.progressTrack}>
        <div
          className={progressFillClass(signal.grant_rate_pct)}
          style={{ width: `${Math.min(signal.grant_rate_pct, 100)}%` }}
        />
      </div>
      <div className={styles.signalCounts}>
        {signal.granted} onaylı · {signal.denied} reddedildi
      </div>
      {signal.description ? (
        <div className={styles.signalDesc}>{signal.description}</div>
      ) : null}
    </div>
  );
}

// ============================================================
// Destination row
// ============================================================

function DestinationTable({
  destinations,
}: {
  destinations: ConsentDestination[];
}) {
  if (destinations.length === 0) {
    return (
      <div className={styles.stateBox}>
        <span className={styles.errorText}>Hedef noktası bulunamadı.</span>
      </div>
    );
  }

  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Hedef</th>
            <th>Platform</th>
            <th>Duruş</th>
            <th>Zorunlu rızalar</th>
            <th className={styles.numCell}>İletildi</th>
            <th className={styles.numCell}>Atlandı</th>
          </tr>
        </thead>
        <tbody>
          {destinations.map((dest) => (
            <tr key={dest.name}>
              <td>{dest.name}</td>
              <td>{dest.platform}</td>
              <td>
                <span className={postureClass(dest.posture_label)}>
                  {dest.posture_label}
                </span>
              </td>
              <td>
                {dest.required_consent.length > 0 ? (
                  <div className={styles.chipList}>
                    {dest.required_consent.map((c) => (
                      <span key={c} className={styles.chip}>
                        {c}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span style={{ color: 'var(--color-text-muted)', fontSize: '0.75rem' }}>
                    —
                  </span>
                )}
              </td>
              <td className={styles.numCell}>{dest.forwarded}</td>
              <td className={styles.numCell}>{dest.skipped_no_consent}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p
        style={{
          marginTop: 'var(--space-2)',
          fontSize: '0.75rem',
          color: 'var(--color-text-muted)',
          lineHeight: 1.5,
        }}
      >
        Not: Hedef bazlı &ldquo;İletildi / Atlandı&rdquo; sayıları kaynak
        seviyesinde <strong>tahminidir</strong> — her olayın hangi hedefe
        iletildiği ayrı kaydedilmediğinden, aynı kaynağı paylaşan hedefler benzer
        değerler gösterebilir ve toplamla birebir örtüşmeyebilir. Kesin denetim
        kanıtı için olay-hedef eşleşme kaydı gerekir.
      </p>
    </div>
  );
}

// ============================================================
// Sources list
// ============================================================

function SourcesList({ sources }: { sources: ConsentSource[] }) {
  if (sources.length === 0) {
    return (
      <div className={styles.stateBox}>
        <span style={{ color: 'var(--color-text-muted)', fontSize: '0.875rem' }}>
          Kaynak bulunamadı.
        </span>
      </div>
    );
  }

  return (
    <div className={styles.sourceList}>
      {sources.map((src) => (
        <div key={src.name} className={styles.sourceRow}>
          <div className={styles.sourceName}>{src.name}</div>
          <code className={styles.sourceCookieVar}>
            {src.consent_cookie_var || 'yapılandırılmamış'}
          </code>
          <div className={styles.sourceEvents}>{src.events} olay</div>
          <span
            className={
              src.configured ? styles.configuredBadge : styles.unconfiguredBadge
            }
          >
            {src.configured ? 'Yapılandırıldı' : 'yapılandırılmamış'}
          </span>
        </div>
      ))}
    </div>
  );
}

// ============================================================
// Compliance check row
// ============================================================

function CheckRow({ check }: { check: ConsentCheck }) {
  const rowCls =
    check.status === 'warn'
      ? `${styles.checkRow} ${styles.checkRowWarn}`
      : check.status === 'fail'
      ? `${styles.checkRow} ${styles.checkRowFail}`
      : styles.checkRow;

  return (
    <div className={rowCls}>
      <SeverityIcon status={check.status} />
      <div className={styles.checkContent}>
        <div className={styles.checkTitle}>{check.label}</div>
        <div className={styles.checkFinding}>{check.finding}</div>
        {(check.status === 'warn' || check.status === 'fail') &&
          check.recommendation ? (
          <div className={styles.checkRecommendation}>
            <span className={styles.checkRecommendationLabel}>Öneri:</span>
            {check.recommendation}
          </div>
        ) : null}
      </div>
    </div>
  );
}

// ============================================================
// Audit trail table
// ============================================================

function AuditTrailTable({ entries }: { entries: ConsentAuditEntry[] }) {
  const [showAll, setShowAll] = useState(false);

  if (entries.length === 0) {
    return (
      <div className={styles.stateBox}>
        <span style={{ color: 'var(--color-text-muted)', fontSize: '0.875rem' }}>
          Denetim kaydı bulunamadı.
        </span>
      </div>
    );
  }

  const visibleEntries = showAll ? entries : entries.slice(0, 10);

  return (
    <>
      <div className={styles.tableWrap}>
        <table className={styles.auditTable}>
          <thead>
            <tr>
              <th>Zaman</th>
              <th>Olay</th>
              <th>Rıza</th>
              <th>Durum</th>
              <th>Sinyaller</th>
            </tr>
          </thead>
          <tbody>
            {visibleEntries.map((entry, idx) => (
              <tr key={`${entry.event_time}-${idx}`}>
                <td style={{ whiteSpace: 'nowrap' }}>
                  {formatEventTime(entry.event_time)}
                </td>
                <td>{entry.event_name}</td>
                <td>
                  <span
                    className={
                      entry.consent ? styles.consentYes : styles.consentNo
                    }
                  >
                    {entry.consent ? '✓' : '✕'}
                  </span>
                </td>
                <td>
                  <span className={statusBadgeClass(entry.status)}>
                    {entry.status_label}
                  </span>
                </td>
                <td className={styles.signalsSummaryCell}>
                  {entry.signals_summary}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {entries.length > 10 && (
        <button
          className={styles.auditToggleBtn}
          onClick={() => setShowAll((v) => !v)}
        >
          {showAll
            ? 'Daha Az Göster'
            : `Tümünü Gör (${entries.length} kayıt)`}
        </button>
      )}
    </>
  );
}

// ============================================================
// Checklist progress header
// ============================================================

function ChecklistProgress({ checks }: { checks: ConsentCheck[] }) {
  const passed = checks.filter((c) => c.status === 'pass').length;
  const total = checks.length;
  const pct = total > 0 ? Math.round((passed / total) * 100) : 0;
  const allPass = passed === total && total > 0;

  return (
    <SectionCard title="KVKK Uyum Kontrol Listesi">
      <div className={styles.checklistProgress}>
        <div className={styles.checklistProgressLeft}>
          <span className={styles.checklistProgressTitle}>Kontrol Listesi</span>
          <span className={`${styles.checklistProgressCount}${allPass ? ` ${styles.allPass}` : ''}`}>
            {passed}/{total} geçti
          </span>
        </div>
        <div className={styles.checklistProgressBar}>
          <div
            className={styles.checklistProgressFill}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className={styles.checkList}>
          {checks.map((check) => (
            <CheckRow key={check.id} check={check} />
          ))}
        </div>
      </div>
    </SectionCard>
  );
}

// ============================================================
// Loading skeleton
// ============================================================

function LoadingSkeleton() {
  return (
    <>
      <div className={styles.heroRow}>
        <div className={`${styles.skeleton} ${styles.skeletonHero}`} />
        <div className={`${styles.skeleton} ${styles.skeletonHero}`} />
      </div>
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
      <div className={`${styles.skeleton} ${styles.skeletonSection}`} />
    </>
  );
}

// ============================================================
// Main page
// ============================================================

export default function ConsentPage() {
  const [data, setData] = useState<ConsentCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getConsentCenter();
      setData(result);
    } catch (err: unknown) {
      setError(
        parseApiError(err),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>KVKK Rıza Yönetim Merkezi</h1>
          <p className={styles.pageSubtitle}>
            Tüm rıza ayarları, Consent Mode v2 sinyalleri ve KVKK uyumu tek
            yerde.
          </p>
        </div>

        {loading ? (
          <LoadingSkeleton />
        ) : error ? (
          <div className={styles.sectionCard}>
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{error}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchData}>
                Tekrar Dene
              </button>
            </div>
          </div>
        ) : data ? (
          <>
            {/* 1. Checklist progress header (HERO) */}
            <ChecklistProgress checks={data.compliance.checks} />

            {/* 2. Hero — two stat blocks */}
            <div className={styles.heroRow}>
              {/* (a) Rıza Oranı */}
              <div className={styles.heroCard}>
                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    flex: 1,
                    gap: '0.75rem',
                  }}
                >
                  <div className={styles.heroStatLabel}>Rıza Oranı</div>
                  <div className={styles.heroStatValue}>
                    %{data.summary.consent_rate_pct.toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}
                  </div>
                  <div className={styles.progressTrack}>
                    <div
                      className={progressFillClass(
                        data.summary.consent_rate_pct,
                      )}
                      style={{
                        width: `${Math.min(data.summary.consent_rate_pct, 100)}%`,
                      }}
                    />
                  </div>
                  <div className={styles.heroStatCaption}>
                    {data.summary.consented_events} onaylı /{' '}
                    {data.summary.total_events} toplam olay
                    {data.summary.skipped_no_consent > 0 && (
                      <> · {data.summary.skipped_no_consent} rıza olmadan atlandı</>
                    )}
                  </div>
                </div>
              </div>

              {/* (b) KVKK Uyum Skoru */}
              <div className={styles.heroCard}>
                <ScoreRing
                  score={data.compliance.score}
                  grade={data.compliance.grade}
                />
                <div className={styles.heroStatBlock}>
                  <div className={styles.heroStatLabel}>KVKK Uyum Skoru</div>
                  <span
                    className={`${styles.gradeBadge} ${gradeClass(data.compliance.grade)}`}
                  >
                    {GRADE_LABELS[data.compliance.grade]}
                  </span>
                  <div className={styles.countsRow}>
                    <span
                      className={`${styles.countItem} ${styles.countPass}`}
                    >
                      ✓ {data.compliance.counts.pass} geçti
                    </span>
                    <span
                      className={styles.countDivider}
                      aria-hidden="true"
                    >
                      ·
                    </span>
                    <span
                      className={`${styles.countItem} ${styles.countWarn}`}
                    >
                      ⚠ {data.compliance.counts.warn} uyarı
                    </span>
                    <span
                      className={styles.countDivider}
                      aria-hidden="true"
                    >
                      ·
                    </span>
                    <span
                      className={`${styles.countItem} ${styles.countFail}`}
                    >
                      ✕ {data.compliance.counts.fail} sorun
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* 3. Consent Mode v2 sinyalleri */}
            <SectionCard title="Consent Mode v2 Sinyalleri">
              {data.signals.length > 0 ? (
                <div className={styles.signalsGrid}>
                  {data.signals.map((signal) => (
                    <SignalCard key={signal.key} signal={signal} />
                  ))}
                </div>
              ) : (
                <div className={styles.stateBox}>
                  <span
                    style={{
                      color: 'var(--color-text-muted)',
                      fontSize: '0.875rem',
                    }}
                  >
                    Sinyal verisi bulunamadı.
                  </span>
                </div>
              )}
            </SectionCard>

            {/* 4. Hedef noktası rıza duruşu */}
            <SectionCard title="Hedef Noktası Rıza Duruşu">
              <DestinationTable destinations={data.destinations} />
            </SectionCard>

            {/* 5. Kaynaklar */}
            <SectionCard title="Kaynaklar">
              <SourcesList sources={data.sources} />
            </SectionCard>

            {/* 6. Rıza Denetim İzi */}
            <SectionCard title="Rıza Denetim İzi">
              <AuditTrailTable entries={data.audit_trail} />
            </SectionCard>
          </>
        ) : null}
      </main>
    </div>
  );
}
