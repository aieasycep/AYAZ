'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { channelLabel } from '@/lib/channels';
import { getToken } from '@/lib/api';
import {
  getReports,
  createReport,
  deleteReport,
  previewReport,
  shareReport,
  getSchedules,
  createSchedule,
  type ReportDefinition,
  type ReportPreview,
  type ShareResponse,
  type ReportSchedule,
  type ReportCadence,
  type ReportConfig,
} from '@/lib/reports-api';
import KpiCard from '@/components/KpiCard';
import ChannelTable from '@/components/ChannelTable';
import AppNav from '@/components/AppNav';
import EmptyState from '@/components/EmptyState';
import SectionCard from '@/components/SectionCard';
import SuggestionsStrip from '@/components/SuggestionsStrip';
import { parseApiError } from '@/lib/parseApiError';
import styles from './reports.module.css';

// --- Date helpers ---

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function getDefaultDates() {
  const to = new Date();
  const from = new Date();
  from.setDate(from.getDate() - 29);
  return { from: toISODate(from), to: toISODate(to) };
}

function fmtDateDisplay(iso: string): string {
  return new Date(iso).toLocaleDateString('tr-TR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });
}

// --- Formatters ---

function fmtCurrency(n: number, decimals = 0): string {
  return new Intl.NumberFormat('tr-TR', {
    style: 'currency',
    currency: 'TRY',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n);
}

function fmtNum(n: number): string {
  return new Intl.NumberFormat('tr-TR').format(Math.round(n));
}

function fmtPct(n: number): string {
  return (
    '%' +
    (n * 100).toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  );
}

function fmtRoas(n: number): string {
  return (
    n.toLocaleString('tr-TR', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }) + 'x'
  );
}

// --- Cadence helpers ---

function cadenceLabel(c: ReportCadence): string {
  switch (c) {
    case 'daily': return 'Günlük';
    case 'weekly': return 'Haftalık';
    case 'monthly': return 'Aylık';
  }
}

function weekdayLabel(n: number | null | undefined): string {
  if (n == null) return '';
  const days = ['Pts', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
  return days[n] ?? '';
}

// --- New report form state ---

interface ReportFormState {
  name: string;
  metricsRaw: string;
  channelsRaw: string;
  brandName: string;
  logoUrl: string;
  color: string;
}

const EMPTY_REPORT_FORM: ReportFormState = {
  name: '',
  metricsRaw: '',
  channelsRaw: '',
  brandName: '',
  logoUrl: '',
  color: '',
};

// --- Schedule form state ---

interface ScheduleFormState {
  cadence: ReportCadence;
  weekday: string;
  hour: string;
  recipientsRaw: string;
}

const EMPTY_SCHEDULE_FORM: ScheduleFormState = {
  cadence: 'weekly',
  weekday: '0',
  hour: '9',
  recipientsRaw: '',
};

// --- Component ---

export default function ReportsPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) router.replace('/login');
  }, [router]);

  // --- Reports list ---
  const [reports, setReports] = useState<ReportDefinition[]>([]);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [reportsError, setReportsError] = useState<string | null>(null);

  const fetchReports = useCallback(async () => {
    setReportsLoading(true);
    setReportsError(null);
    try {
      const data = await getReports();
      setReports(data);
    } catch (err: unknown) {
      setReportsError(parseApiError(err));
    } finally {
      setReportsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchReports();
  }, [fetchReports]);

  // --- Selected report ---
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedReport = reports.find((r) => r.id === selectedId) ?? null;

  // --- Preview ---
  const defaults = getDefaultDates();
  const [dateFrom, setDateFrom] = useState(defaults.from);
  const [dateTo, setDateTo] = useState(defaults.to);
  const [appliedFrom, setAppliedFrom] = useState(defaults.from);
  const [appliedTo, setAppliedTo] = useState(defaults.to);

  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const fetchPreview = useCallback(async (id: string, from: string, to: string) => {
    setPreviewLoading(true);
    setPreviewError(null);
    setPreview(null);
    try {
      const data = await previewReport(id, from, to);
      setPreview(data);
    } catch (err: unknown) {
      setPreviewError(parseApiError(err));
    } finally {
      setPreviewLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) {
      fetchPreview(selectedId, appliedFrom, appliedTo);
    } else {
      setPreview(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  function applyPreviewDates() {
    setAppliedFrom(dateFrom);
    setAppliedTo(dateTo);
    if (selectedId) fetchPreview(selectedId, dateFrom, dateTo);
  }

  // --- Share ---
  const [shareResult, setShareResult] = useState<ShareResponse | null>(null);
  const [sharing, setSharing] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);

  async function handleShare() {
    if (!selectedId) return;
    setSharing(true);
    try {
      const result = await shareReport(selectedId);
      setShareResult(result);
      setCopySuccess(false);
    } catch (err: unknown) {
      alert(parseApiError(err));
    } finally {
      setSharing(false);
    }
  }

  function handleCopyUrl() {
    if (!shareResult) return;
    navigator.clipboard.writeText(shareResult.public_url).then(() => {
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2500);
    });
  }

  // Clear share result when switching reports
  useEffect(() => {
    setShareResult(null);
    setCopySuccess(false);
  }, [selectedId]);

  // --- Schedules ---
  const [schedules, setSchedules] = useState<ReportSchedule[]>([]);
  const [schedulesLoading, setSchedulesLoading] = useState(false);
  const [schedulesError, setSchedulesError] = useState<string | null>(null);

  const fetchSchedules = useCallback(async (id: string) => {
    setSchedulesLoading(true);
    setSchedulesError(null);
    try {
      const data = await getSchedules(id);
      setSchedules(data);
    } catch (err: unknown) {
      setSchedulesError(parseApiError(err));
    } finally {
      setSchedulesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) {
      fetchSchedules(selectedId);
    } else {
      setSchedules([]);
    }
  }, [selectedId, fetchSchedules]);

  // --- Schedule form ---
  const [scheduleForm, setScheduleForm] = useState<ScheduleFormState>(EMPTY_SCHEDULE_FORM);
  const [scheduleSubmitting, setScheduleSubmitting] = useState(false);
  const [scheduleFormError, setScheduleFormError] = useState<string | null>(null);

  async function handleScheduleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedId) return;
    setScheduleFormError(null);

    const recipients = scheduleForm.recipientsRaw
      .split(/[,\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    if (recipients.length === 0) {
      setScheduleFormError('En az bir alıcı e-posta adresi giriniz.');
      return;
    }

    const hour = parseInt(scheduleForm.hour, 10);
    if (isNaN(hour) || hour < 0 || hour > 23) {
      setScheduleFormError('Saat 0-23 arasında olmalıdır.');
      return;
    }

    setScheduleSubmitting(true);
    try {
      const created = await createSchedule(selectedId, {
        cadence: scheduleForm.cadence,
        weekday:
          scheduleForm.cadence === 'weekly'
            ? parseInt(scheduleForm.weekday, 10)
            : null,
        hour,
        recipients,
      });
      setSchedules((prev) => [...prev, created]);
      setScheduleForm(EMPTY_SCHEDULE_FORM);
    } catch (err: unknown) {
      setScheduleFormError(parseApiError(err));
    } finally {
      setScheduleSubmitting(false);
    }
  }

  // --- New report form ---
  const [showNewForm, setShowNewForm] = useState(false);
  const [reportForm, setReportForm] = useState<ReportFormState>(EMPTY_REPORT_FORM);
  const [reportSubmitting, setReportSubmitting] = useState(false);
  const [reportFormError, setReportFormError] = useState<string | null>(null);

  async function handleReportSubmit(e: React.FormEvent) {
    e.preventDefault();
    setReportFormError(null);

    if (!reportForm.name.trim()) {
      setReportFormError('Rapor adı zorunludur.');
      return;
    }

    const metrics = reportForm.metricsRaw
      .split(/[,\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    const channels = reportForm.channelsRaw
      .split(/[,\n]+/)
      .map((s) => s.trim())
      .filter(Boolean);

    const config: ReportConfig = {
      metrics: metrics.length > 0 ? metrics : undefined,
      channels: channels.length > 0 ? channels : undefined,
      white_label:
        reportForm.brandName || reportForm.logoUrl || reportForm.color
          ? {
              brand_name: reportForm.brandName || undefined,
              logo_url: reportForm.logoUrl || undefined,
              color: reportForm.color || undefined,
            }
          : undefined,
    };

    setReportSubmitting(true);
    try {
      const created = await createReport({ name: reportForm.name.trim(), config });
      setReports((prev) => [created, ...prev]);
      setReportForm(EMPTY_REPORT_FORM);
      setShowNewForm(false);
      setSelectedId(created.id);
    } catch (err: unknown) {
      setReportFormError(parseApiError(err));
    } finally {
      setReportSubmitting(false);
    }
  }

  // --- Delete report ---
  const [deleteBusy, setDeleteBusy] = useState<Record<string, boolean>>({});

  async function handleDelete(id: string) {
    if (!confirm('Bu raporu silmek istediğinizden emin misiniz?')) return;
    setDeleteBusy((prev) => ({ ...prev, [id]: true }));
    try {
      await deleteReport(id);
      setReports((prev) => prev.filter((r) => r.id !== id));
      if (selectedId === id) setSelectedId(null);
    } catch (err: unknown) {
      alert(parseApiError(err));
    } finally {
      setDeleteBusy((prev) => ({ ...prev, [id]: false }));
    }
  }

  // Build ChannelTable-compatible rows from preview
  const channelRows = (preview?.by_channel ?? []).map((r) => ({
    channel: r.channel,
    spend: r.spend ?? 0,
    impressions: r.impressions ?? 0,
    clicks: r.clicks ?? 0,
    conversions: r.conversions ?? 0,
    conversion_value: r.conversion_value ?? 0,
    ctr: r.ctr ?? 0,
    cpc: r.cpc ?? 0,
    cpa: r.cpa ?? 0,
    roas: r.roas ?? 0,
  }));

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Raporlar</h1>
            <p className={styles.pageSubtitle}>
              Performans raporları oluşturun, paylaşın ve zamanlayın.
            </p>
          </div>
        </div>

        {/* New report form */}
        {showNewForm && (
          <section className={styles.section}>
            <div className={styles.sectionHeader}>
              <h2 className={styles.sectionTitle}>Yeni Rapor Oluştur</h2>
            </div>
            <div className={styles.formWrapper}>
              <form onSubmit={handleReportSubmit}>
                <div className={styles.formGrid}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Rapor Adı</label>
                    <input
                      className={styles.fieldInput}
                      type="text"
                      placeholder="ör. Aylık Performans Raporu"
                      value={reportForm.name}
                      onChange={(e) =>
                        setReportForm((f) => ({ ...f, name: e.target.value }))
                      }
                    />
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Metrikler</label>
                    <input
                      className={styles.fieldInput}
                      type="text"
                      placeholder="spend, roas, cpc, ctr"
                      value={reportForm.metricsRaw}
                      onChange={(e) =>
                        setReportForm((f) => ({ ...f, metricsRaw: e.target.value }))
                      }
                    />
                    <span className={styles.fieldHint}>Virgülle ayırın</span>
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Kanallar</label>
                    <input
                      className={styles.fieldInput}
                      type="text"
                      placeholder="google_ads, meta, tiktok"
                      value={reportForm.channelsRaw}
                      onChange={(e) =>
                        setReportForm((f) => ({ ...f, channelsRaw: e.target.value }))
                      }
                    />
                    <span className={styles.fieldHint}>Virgülle ayırın (boş = hepsi)</span>
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Marka Adı (Beyaz Etiket)</label>
                    <input
                      className={styles.fieldInput}
                      type="text"
                      placeholder="ör. Acme Dijital"
                      value={reportForm.brandName}
                      onChange={(e) =>
                        setReportForm((f) => ({ ...f, brandName: e.target.value }))
                      }
                    />
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Logo URL</label>
                    <input
                      className={styles.fieldInput}
                      type="url"
                      placeholder="https://..."
                      value={reportForm.logoUrl}
                      onChange={(e) =>
                        setReportForm((f) => ({ ...f, logoUrl: e.target.value }))
                      }
                    />
                  </div>

                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Renk (hex)</label>
                    <input
                      className={styles.fieldInput}
                      type="text"
                      placeholder="#3b5bdb"
                      value={reportForm.color}
                      onChange={(e) =>
                        setReportForm((f) => ({ ...f, color: e.target.value }))
                      }
                    />
                  </div>

                  <button
                    type="submit"
                    className={styles.submitBtn}
                    disabled={reportSubmitting}
                  >
                    {reportSubmitting ? 'Oluşturuluyor...' : 'Oluştur'}
                  </button>
                </div>
                {reportFormError && (
                  <div className={styles.formError}>{reportFormError}</div>
                )}
              </form>
            </div>
          </section>
        )}

        {/* Reports list */}
        <SectionCard
          title={`Rapor Listesi${reports.length > 0 ? ` (${reports.length})` : ''}`}
          right={
            <button
              className={styles.primaryCtaBtn}
              onClick={() => {
                setShowNewForm((v) => !v);
                setReportFormError(null);
              }}
            >
              {showNewForm ? 'İptal' : '+ Yeni Rapor Oluştur'}
            </button>
          }
        >
          {reportsLoading ? (
            <div className={styles.stateBox}>
              <span className={styles.muted}>Raporlar yükleniyor...</span>
            </div>
          ) : reportsError ? (
            <div className={styles.stateBox}>
              <span className={styles.errorText}>{reportsError}</span>
              <br />
              <button className={styles.retryBtn} onClick={fetchReports}>
                Tekrar Dene
              </button>
            </div>
          ) : reports.length === 0 ? (
            <EmptyState
              icon={
                <svg
                  width="48"
                  height="48"
                  viewBox="0 0 48 48"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  aria-hidden="true"
                >
                  <rect x="8" y="6" width="32" height="36" rx="4" stroke="currentColor" strokeWidth="2" fill="none" />
                  <path d="M16 16h16M16 22h16M16 28h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  <circle cx="36" cy="36" r="6" fill="var(--color-primary)" />
                  <path d="M36 33v3l2 2" stroke="var(--color-on-primary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              }
              title="Henüz rapor oluşturulmadı"
              subtitle="Kanal bazlı performans raporları oluşturun, paylaşın ve zamanlayın."
              action={{
                label: '+ Yeni Rapor Oluştur',
                onClick: () => {
                  setShowNewForm(true);
                  setReportFormError(null);
                },
              }}
            />
          ) : (
            <div className={styles.reportCardGrid}>
              {reports.map((report) => (
                <div
                  key={report.id}
                  className={`${styles.reportCard} ${selectedId === report.id ? styles.reportCardActive : ''}`}
                  onClick={() =>
                    setSelectedId(selectedId === report.id ? null : report.id)
                  }
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      setSelectedId(selectedId === report.id ? null : report.id);
                    }
                  }}
                  aria-pressed={selectedId === report.id}
                >
                  <div className={styles.reportCardTop}>
                    <div className={styles.reportCardIcon} aria-hidden="true">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M9 17H7a2 2 0 01-2-2V5a2 2 0 012-2h10a2 2 0 012 2v10a2 2 0 01-2 2h-2" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" />
                        <rect x="9" y="13" width="6" height="8" rx="1" stroke="currentColor" strokeWidth="1.75" />
                      </svg>
                    </div>
                    <div className={styles.reportCardActions}>
                      <button
                        className={styles.outlineBtn}
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedId(selectedId === report.id ? null : report.id);
                        }}
                      >
                        {selectedId === report.id ? 'Kapat' : 'Görüntüle'}
                      </button>
                      <button
                        className={styles.dangerBtn}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDelete(report.id);
                        }}
                        disabled={deleteBusy[report.id]}
                      >
                        Sil
                      </button>
                    </div>
                  </div>

                  <div className={styles.reportCardName}>{report.name}</div>
                  <div className={styles.reportCardDate}>
                    {fmtDateDisplay(report.created_at)}
                  </div>

                  {report.config.channels && report.config.channels.length > 0 && (
                    <div className={styles.reportCardPills}>
                      {report.config.channels.map((ch) => (
                        <span key={ch} className={styles.channelPill}>{channelLabel(ch)}</span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </SectionCard>

        {/* Report detail panel */}
        {selectedReport && (
          <section className={styles.detailPanel}>
            <div className={styles.detailHeader}>
              <h2 className={styles.detailTitle}>{selectedReport.name}</h2>
              <div className={styles.detailActions}>
                <button
                  className={styles.primaryBtn}
                  onClick={handleShare}
                  disabled={sharing}
                >
                  {sharing ? 'Paylaşılıyor...' : 'Paylaş'}
                </button>
              </div>
            </div>

            <div className={styles.detailBody}>
              {/* Date range */}
              <div className={styles.dateBar}>
                <div className={styles.dateGroup}>
                  <label className={styles.dateLabel} htmlFor="rpt-from">
                    Başlangıç
                  </label>
                  <input
                    id="rpt-from"
                    type="date"
                    className={styles.dateInput}
                    value={dateFrom}
                    max={dateTo}
                    onChange={(e) => setDateFrom(e.target.value)}
                  />
                </div>
                <div className={styles.dateGroup}>
                  <label className={styles.dateLabel} htmlFor="rpt-to">
                    Bitiş
                  </label>
                  <input
                    id="rpt-to"
                    type="date"
                    className={styles.dateInput}
                    value={dateTo}
                    min={dateFrom}
                    onChange={(e) => setDateTo(e.target.value)}
                  />
                </div>
                <button className={styles.applyBtn} onClick={applyPreviewDates}>
                  Uygula
                </button>
              </div>

              {/* KPI preview */}
              {previewLoading ? (
                <div className={styles.kpiPlaceholder}>
                  <span className={styles.muted}>Önizleme yükleniyor...</span>
                </div>
              ) : previewError ? (
                <div className={styles.kpiPlaceholder}>
                  <span className={styles.errorText}>{previewError}</span>
                </div>
              ) : preview ? (
                <>
                  <div className={styles.kpiGrid}>
                    {preview.totals.spend !== undefined && (
                      <KpiCard label="Harcama" value={fmtCurrency(preview.totals.spend)} />
                    )}
                    {preview.totals.impressions !== undefined && (
                      <KpiCard label="Gösterim" value={fmtNum(preview.totals.impressions)} />
                    )}
                    {preview.totals.clicks !== undefined && (
                      <KpiCard label="Tıklama" value={fmtNum(preview.totals.clicks)} />
                    )}
                    {preview.totals.conversions !== undefined && (
                      <KpiCard label="Dönüşüm" value={fmtNum(preview.totals.conversions)} />
                    )}
                    {preview.totals.roas !== undefined && (
                      <KpiCard label="ROAS" value={fmtRoas(preview.totals.roas)} />
                    )}
                    {preview.totals.cpc !== undefined && (
                      <KpiCard label="CPC" value={fmtCurrency(preview.totals.cpc, 2)} />
                    )}
                    {preview.totals.cpa !== undefined && (
                      <KpiCard label="CPA" value={fmtCurrency(preview.totals.cpa, 2)} />
                    )}
                    {preview.totals.ctr !== undefined && (
                      <KpiCard label="CTR" value={fmtPct(preview.totals.ctr)} />
                    )}
                  </div>

                  <ChannelTable
                    rows={channelRows}
                    loading={false}
                    error={null}
                  />
                </>
              ) : null}

              {/* Share box */}
              {shareResult && (
                <div className={styles.shareBox}>
                  <div className={styles.shareBoxTitle}>Paylaşım Bağlantısı</div>
                  <div className={styles.shareUrlRow}>
                    <span className={styles.shareUrlText}>
                      {shareResult.public_url}
                    </span>
                    <button
                      className={styles.outlineBtn}
                      onClick={handleCopyUrl}
                    >
                      {copySuccess ? 'Kopyalandı!' : 'Kopyala'}
                    </button>
                    <button
                      className={styles.outlineBtn}
                      onClick={() => window.open(shareResult.public_url, '_blank')}
                    >
                      Aç
                    </button>
                  </div>
                  {copySuccess && (
                    <span className={styles.copySuccess}>Bağlantı panoya kopyalandı.</span>
                  )}
                </div>
              )}

              {/* Schedule form */}
              <div className={styles.scheduleFormWrapper}>
                <div className={styles.scheduleFormTitle}>Zamanla</div>

                {/* Existing schedules */}
                {schedulesLoading ? (
                  <span className={styles.muted}>Zamanlamalar yükleniyor...</span>
                ) : schedulesError ? (
                  <span className={styles.errorText}>{schedulesError}</span>
                ) : schedules.length > 0 ? (
                  <div className={styles.scheduleList}>
                    {schedules.map((s) => (
                      <div key={s.id} className={styles.scheduleRow}>
                        <span className={styles.scheduleRowName}>
                          {cadenceLabel(s.cadence)}
                          {s.cadence === 'weekly' && s.weekday != null
                            ? ` · ${weekdayLabel(s.weekday)}`
                            : ''}
                          {` · ${String(s.hour).padStart(2, '0')}:00`}
                        </span>
                        <span>{s.recipients.join(', ')}</span>
                      </div>
                    ))}
                  </div>
                ) : null}

                <form onSubmit={handleScheduleSubmit} style={{ marginTop: '1rem' }}>
                  <div className={styles.scheduleGrid}>
                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Sıklık</label>
                      <select
                        className={styles.fieldSelect}
                        value={scheduleForm.cadence}
                        onChange={(e) =>
                          setScheduleForm((f) => ({
                            ...f,
                            cadence: e.target.value as ReportCadence,
                          }))
                        }
                      >
                        <option value="daily">Günlük</option>
                        <option value="weekly">Haftalık</option>
                        <option value="monthly">Aylık</option>
                      </select>
                    </div>

                    {scheduleForm.cadence === 'weekly' && (
                      <div className={styles.fieldGroup}>
                        <label className={styles.fieldLabel}>Gün</label>
                        <select
                          className={styles.fieldSelect}
                          value={scheduleForm.weekday}
                          onChange={(e) =>
                            setScheduleForm((f) => ({ ...f, weekday: e.target.value }))
                          }
                        >
                          <option value="0">Pazartesi</option>
                          <option value="1">Salı</option>
                          <option value="2">Çarşamba</option>
                          <option value="3">Perşembe</option>
                          <option value="4">Cuma</option>
                          <option value="5">Cumartesi</option>
                          <option value="6">Pazar</option>
                        </select>
                      </div>
                    )}

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Saat (0-23)</label>
                      <input
                        className={styles.fieldInput}
                        type="number"
                        min="0"
                        max="23"
                        value={scheduleForm.hour}
                        onChange={(e) =>
                          setScheduleForm((f) => ({ ...f, hour: e.target.value }))
                        }
                      />
                    </div>

                    <div className={styles.fieldGroup}>
                      <label className={styles.fieldLabel}>Alıcı E-postalar</label>
                      <input
                        className={styles.fieldInput}
                        type="text"
                        placeholder="a@b.com, c@d.com"
                        value={scheduleForm.recipientsRaw}
                        onChange={(e) =>
                          setScheduleForm((f) => ({ ...f, recipientsRaw: e.target.value }))
                        }
                      />
                      <span className={styles.fieldHint}>Virgülle ayırın</span>
                    </div>

                    <button
                      type="submit"
                      className={styles.submitBtn}
                      disabled={scheduleSubmitting}
                    >
                      {scheduleSubmitting ? 'Kaydediliyor...' : 'Zamanla'}
                    </button>
                  </div>
                  {scheduleFormError && (
                    <div className={styles.formError}>{scheduleFormError}</div>
                  )}
                </form>
              </div>
            </div>
          </section>
        )}

        <SuggestionsStrip
          title="Başlamak için"
          suggestions={[
            { label: 'Rapor Oluşturucu ile sorgu yaz', href: '/report-builder' },
            { label: 'Kampanya performansını gör', href: '/ads' },
            { label: 'Panel özeti', href: '/dashboard' },
          ]}
        />
      </main>
    </div>
  );
}
