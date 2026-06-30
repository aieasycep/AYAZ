'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getContentPosts,
  createContentPost,
  patchContentPost,
  deleteContentPost,
  submitPost,
  approvePost,
  rejectPost,
  schedulePost,
  publishPost,
  generateCaption,
  createFromCreative,
  CHANNEL_LABELS,
  ALL_CHANNELS,
  STATUS_LABELS,
  STATUS_ORDER,
  type ContentPost,
  type ContentStatus,
  type Channel,
  type CreateContentPostPayload,
  type PatchContentPostPayload,
  type PublishGatedResult,
} from '@/lib/content-api';
import {
  getCreativesPerformance,
  type AdPerformance,
} from '@/lib/creatives-api';
import AppNav from '@/components/AppNav';
import { parseApiError } from '@/lib/parseApiError';
import styles from './content.module.css';

// -----------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString('tr-TR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function isGated(
  result: ContentPost | PublishGatedResult,
): result is PublishGatedResult {
  return (result as PublishGatedResult).gated === true;
}

// -----------------------------------------------------------------------
// Composer modal (create / edit)
// -----------------------------------------------------------------------

interface ComposerProps {
  post?: ContentPost | null;
  onClose: () => void;
  onSaved: () => void;
}

function ComposerModal({ post, onClose, onSaved }: ComposerProps) {
  const isEdit = Boolean(post);

  const [title, setTitle] = useState(post?.title ?? '');
  const [body, setBody] = useState(post?.body ?? '');
  const [channels, setChannels] = useState<Channel[]>(post?.channels ?? []);
  const [scheduledAt, setScheduledAt] = useState(
    post?.scheduled_at ? post.scheduled_at.slice(0, 16) : '',
  );
  const [mediaUrl, setMediaUrl] = useState(post?.media_url ?? '');

  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // AI caption state
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [aiCaption, setAiCaption] = useState<string | null>(null);
  const [aiHashtags, setAiHashtags] = useState<string[]>([]);

  function toggleChannel(ch: Channel) {
    setChannels((prev) =>
      prev.includes(ch) ? prev.filter((c) => c !== ch) : [...prev, ch],
    );
  }

  async function handleAiCaption() {
    const brief = title.trim() || body.trim();
    if (!brief) {
      setAiError('Açıklama önerisi için lütfen önce bir başlık veya açıklama girin.');
      return;
    }
    setAiLoading(true);
    setAiError(null);
    setAiCaption(null);
    setAiHashtags([]);
    try {
      const result = await generateCaption({
        brief,
        channel: channels[0],
      });
      setAiCaption(result.caption);
      setAiHashtags(result.hashtags);
    } catch (err: unknown) {
      setAiError(
        parseApiError(err),
      );
    } finally {
      setAiLoading(false);
    }
  }

  function applyAiCaption() {
    if (aiCaption) {
      const hashtagStr =
        aiHashtags.length > 0 ? '\n\n' + aiHashtags.join(' ') : '';
      setBody(aiCaption + hashtagStr);
      setAiCaption(null);
      setAiHashtags([]);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) {
      setFormError('Başlık zorunludur.');
      return;
    }
    setFormError(null);
    setSubmitting(true);
    try {
      if (isEdit && post) {
        const payload: PatchContentPostPayload = {
          title: title.trim(),
          body: body.trim() || undefined,
          channels,
          scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null,
          media_url: mediaUrl.trim() || null,
        };
        await patchContentPost(post.id, payload);
      } else {
        const payload: CreateContentPostPayload = {
          title: title.trim(),
          body: body.trim() || undefined,
          channels,
          scheduled_at: scheduledAt ? new Date(scheduledAt).toISOString() : null,
          media_url: mediaUrl.trim() || null,
        };
        await createContentPost(payload);
      }
      onSaved();
      onClose();
    } catch (err: unknown) {
      setFormError(
        parseApiError(err),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={styles.composerModal}>
        <div className={styles.composerHeader}>
          <span className={styles.composerTitle}>
            {isEdit ? 'İçeriği Düzenle' : 'Yeni İçerik'}
          </span>
          <button
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Kapat"
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className={styles.composerBody}>
            {/* Başlık */}
            <div className={styles.field}>
              <label className={styles.label}>Başlık</label>
              <input
                className={styles.input}
                placeholder="İçerik başlığını girin"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
                disabled={submitting}
              />
            </div>

            {/* Açıklama */}
            <div className={styles.field}>
              <label className={styles.label}>Açıklama</label>
              <textarea
                className={styles.textarea}
                placeholder="İçerik metni veya açıklama..."
                value={body}
                onChange={(e) => setBody(e.target.value)}
                disabled={submitting}
              />
            </div>

            {/* AI caption button */}
            <div>
              <button
                type="button"
                className={styles.aiBtn}
                onClick={handleAiCaption}
                disabled={aiLoading || submitting}
              >
                {aiLoading ? 'Öneri hazırlanıyor...' : 'AI ile Açıklama Öner'}
              </button>
              {aiError && (
                <p className={styles.formError} style={{ marginTop: '0.375rem' }}>
                  {aiError}
                </p>
              )}
            </div>

            {/* AI suggestion box */}
            {aiCaption && (
              <div className={styles.aiSuggestBox}>
                <div className={styles.aiSuggestTitle}>AI Önerisi</div>
                <p className={styles.aiSuggestCaption}>{aiCaption}</p>
                {aiHashtags.length > 0 && (
                  <p className={styles.aiHashtags}>{aiHashtags.join(' ')}</p>
                )}
                <div className={styles.aiSuggestActions}>
                  <button
                    type="button"
                    className={styles.primaryBtn}
                    onClick={applyAiCaption}
                  >
                    Açıklamaya Uygula
                  </button>
                  <button
                    type="button"
                    className={styles.secondaryBtn}
                    onClick={() => { setAiCaption(null); setAiHashtags([]); }}
                  >
                    Kapat
                  </button>
                </div>
              </div>
            )}

            {/* Kanallar */}
            <div className={styles.field}>
              <label className={styles.label}>Kanallar</label>
              <div className={styles.channelToggleRow}>
                {ALL_CHANNELS.map((ch) => (
                  <button
                    key={ch}
                    type="button"
                    className={`${styles.channelToggle} ${
                      channels.includes(ch) ? styles.channelToggleActive : ''
                    }`}
                    onClick={() => toggleChannel(ch)}
                    disabled={submitting}
                  >
                    {CHANNEL_LABELS[ch]}
                  </button>
                ))}
              </div>
            </div>

            {/* Yayın Tarihi */}
            <div className={styles.field}>
              <label className={styles.label}>Yayın Tarihi (opsiyonel)</label>
              <input
                className={styles.input}
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
                disabled={submitting}
              />
            </div>

            {/* Görsel URL */}
            <div className={styles.field}>
              <label className={styles.label}>Görsel URL (opsiyonel)</label>
              <input
                className={styles.input}
                placeholder="https://..."
                value={mediaUrl}
                onChange={(e) => setMediaUrl(e.target.value)}
                disabled={submitting}
              />
            </div>

            {formError && (
              <span className={styles.formError} role="alert">
                {formError}
              </span>
            )}
          </div>

          <div className={styles.composerFooter}>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={onClose}
              disabled={submitting}
            >
              İptal
            </button>
            <button
              type="submit"
              className={styles.primaryBtn}
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

// -----------------------------------------------------------------------
// Schedule modal
// -----------------------------------------------------------------------

interface ScheduleModalProps {
  post: ContentPost;
  onClose: () => void;
  onScheduled: () => void;
}

function ScheduleModal({ post, onClose, onScheduled }: ScheduleModalProps) {
  const [scheduledAt, setScheduledAt] = useState(
    post.scheduled_at ? post.scheduled_at.slice(0, 16) : '',
  );
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!scheduledAt) {
      setFormError('Lütfen bir yayın tarihi seçin.');
      return;
    }
    setFormError(null);
    setSubmitting(true);
    try {
      await schedulePost(post.id, new Date(scheduledAt).toISOString());
      onScheduled();
      onClose();
    } catch (err: unknown) {
      setFormError(
        parseApiError(err),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={styles.scheduleModal}>
        <div className={styles.scheduleHeader}>
          <span className={styles.scheduleTitle}>Zamanla</span>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Kapat">
            &times;
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className={styles.scheduleBody}>
            <div className={styles.field}>
              <label className={styles.label}>Yayın Tarihi</label>
              <input
                className={styles.input}
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
                required
                disabled={submitting}
              />
            </div>
            {formError && (
              <span className={styles.formError} role="alert">
                {formError}
              </span>
            )}
          </div>
          <div className={styles.scheduleFooter}>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={onClose}
              disabled={submitting}
            >
              İptal
            </button>
            <button
              type="submit"
              className={styles.primaryBtn}
              disabled={submitting}
            >
              {submitting ? 'Zamanlanıyor...' : 'Zamanla'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// Reject modal
// -----------------------------------------------------------------------

interface RejectModalProps {
  post: ContentPost;
  onClose: () => void;
  onRejected: () => void;
}

function RejectModal({ post, onClose, onRejected }: RejectModalProps) {
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    setSubmitting(true);
    try {
      await rejectPost(post.id, note.trim() || undefined);
      onRejected();
      onClose();
    } catch (err: unknown) {
      setFormError(
        parseApiError(err),
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={styles.rejectModal}>
        <div className={styles.rejectHeader}>
          <span className={styles.rejectTitle}>Reddet</span>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Kapat">
            &times;
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className={styles.rejectBody}>
            <div className={styles.field}>
              <label className={styles.label}>Red Notu (opsiyonel)</label>
              <textarea
                className={styles.textarea}
                placeholder="Reddetme gerekçenizi yazın..."
                value={note}
                onChange={(e) => setNote(e.target.value)}
                disabled={submitting}
                style={{ minHeight: '80px' }}
              />
            </div>
            {formError && (
              <span className={styles.formError} role="alert">
                {formError}
              </span>
            )}
          </div>
          <div className={styles.rejectFooter}>
            <button
              type="button"
              className={styles.secondaryBtn}
              onClick={onClose}
              disabled={submitting}
            >
              İptal
            </button>
            <button
              type="submit"
              className={styles.dangerBtn}
              disabled={submitting}
            >
              {submitting ? 'Reddediliyor...' : 'Reddet'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// Post card
// -----------------------------------------------------------------------

interface PostCardProps {
  post: ContentPost;
  onEdit: (post: ContentPost) => void;
  onRefresh: () => void;
}

function PostCard({ post, onEdit, onRefresh }: PostCardProps) {
  const [busy, setBusy] = useState(false);
  const [showSchedule, setShowSchedule] = useState(false);
  const [showReject, setShowReject] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      onRefresh();
    } catch (err: unknown) {
      setActionError(parseApiError(err));
    } finally {
      setBusy(false);
    }
  }

  // publishPost is wired to the "Yayınla" button in the scheduled column;
  // it always returns gated on 501 rather than throwing.
  async function handlePublish() {
    setBusy(true);
    setActionError(null);
    try {
      const result = await publishPost(post.id);
      if (isGated(result)) {
        setActionError(result.message);
      } else {
        onRefresh();
      }
    } catch (err: unknown) {
      setActionError(parseApiError(err));
    } finally {
      setBusy(false);
    }
  }
  void handlePublish; // referenced below in scheduled status block

  const status: ContentStatus = post.status;

  return (
    <>
      <div className={styles.postCard}>
        <div className={styles.postCardTop}>
          <span className={styles.postTitle}>{post.title}</span>
          {post.ai_assisted && (
            <span className={styles.aiBadge} title="AI yardımıyla oluşturuldu">
              AI
            </span>
          )}
        </div>

        {post.body && (
          <p className={styles.postBody}>{post.body}</p>
        )}

        {post.channels.length > 0 && (
          <div className={styles.channelChips}>
            {post.channels.map((ch) => (
              <span key={ch} className={styles.channelChip}>
                {CHANNEL_LABELS[ch]}
              </span>
            ))}
          </div>
        )}

        {post.scheduled_at && (
          <div className={styles.scheduledAt}>
            <span>Yayın:</span>
            <span>{fmtDate(post.scheduled_at)}</span>
          </div>
        )}

        {actionError && (
          <p className={styles.formError} role="alert" style={{ marginTop: '0.25rem' }}>
            {actionError}
          </p>
        )}

        {/* Contextual actions by status */}
        <div className={styles.cardActions}>
          {status === 'draft' && (
            <>
              <button
                className={styles.cardBtn}
                onClick={() => onEdit(post)}
                disabled={busy}
              >
                Düzenle
              </button>
              <button
                className={`${styles.cardBtn} ${styles.cardBtnSuccess}`}
                onClick={() => run(() => submitPost(post.id).then(() => {}))}
                disabled={busy}
              >
                Gönder
              </button>
              <button
                className={`${styles.cardBtn} ${styles.cardBtnDanger}`}
                onClick={() =>
                  run(() => deleteContentPost(post.id).then(() => {}))
                }
                disabled={busy}
              >
                Sil
              </button>
            </>
          )}

          {status === 'pending_approval' && (
            <>
              <button
                className={`${styles.cardBtn} ${styles.cardBtnSuccess}`}
                onClick={() => run(() => approvePost(post.id).then(() => {}))}
                disabled={busy}
              >
                Onayla
              </button>
              <button
                className={`${styles.cardBtn} ${styles.cardBtnDanger}`}
                onClick={() => setShowReject(true)}
                disabled={busy}
              >
                Reddet
              </button>
            </>
          )}

          {status === 'approved' && (
            <button
              className={styles.cardBtn}
              onClick={() => setShowSchedule(true)}
              disabled={busy}
            >
              Zamanla
            </button>
          )}

          {status === 'scheduled' && (
            <>
              <button
                className={`${styles.cardBtn} ${styles.cardBtnGated}`}
                disabled
                title="Kanal kimliği gerekli — Ayarlar bölümünden kanalınızı bağlayın"
              >
                Yayınla
              </button>
              <button
                className={styles.cardBtn}
                onClick={() => onEdit(post)}
                disabled={busy}
              >
                Düzenle
              </button>
            </>
          )}

          {status === 'published' && (
            <button
              className={styles.cardBtn}
              onClick={() => onEdit(post)}
              disabled={busy}
            >
              Düzenle
            </button>
          )}
        </div>

        {status === 'scheduled' && (
          <p className={styles.gatedNote}>
            Canlı yayın için kanal bağlantısı (OAuth) gereklidir.
          </p>
        )}
      </div>

      {showSchedule && (
        <ScheduleModal
          post={post}
          onClose={() => setShowSchedule(false)}
          onScheduled={onRefresh}
        />
      )}

      {showReject && (
        <RejectModal
          post={post}
          onClose={() => setShowReject(false)}
          onRejected={onRefresh}
        />
      )}

    </>
  );
}

// -----------------------------------------------------------------------
// Kanban column
// -----------------------------------------------------------------------

interface KanbanColumnProps {
  status: ContentStatus;
  posts: ContentPost[];
  loading: boolean;
  onEdit: (post: ContentPost) => void;
  onRefresh: () => void;
}

function KanbanColumn({
  status,
  posts,
  loading,
  onEdit,
  onRefresh,
}: KanbanColumnProps) {
  return (
    <div className={styles.column}>
      <div className={styles.columnHeader}>
        <span className={styles.columnTitle}>{STATUS_LABELS[status]}</span>
        <span className={styles.columnCount}>{posts.length}</span>
      </div>

      <div className={styles.columnCards}>
        {loading ? (
          <div className={styles.columnEmpty}>
            <span className={styles.muted}>Yükleniyor...</span>
          </div>
        ) : posts.length === 0 ? (
          <div className={styles.columnEmpty}>
            <span className={styles.muted}>İçerik yok</span>
          </div>
        ) : (
          posts.map((post) => (
            <PostCard
              key={post.id}
              post={post}
              onEdit={onEdit}
              onRefresh={onRefresh}
            />
          ))
        )}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// Creative → content picker (Kreatif → İçerik köprüsü)
// -----------------------------------------------------------------------

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

interface CreativePickerProps {
  onClose: () => void;
  onCreated: () => void;
}

function CreativePickerModal({ onClose, onCreated }: CreativePickerProps) {
  const [creatives, setCreatives] = useState<AdPerformance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creatingId, setCreatingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await getCreativesPerformance({
          date_from: isoDaysAgo(30),
          date_to: isoDaysAgo(0),
          sort: 'roas',
        });
        if (!cancelled) {
          // Prefer the top picks; fall back to the first few ads
          const list = data.top.length > 0 ? data.top : data.ads.slice(0, 6);
          setCreatives(list);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(
            parseApiError(err),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleCreate(ad: AdPerformance) {
    setCreatingId(ad.ad_id);
    setError(null);
    try {
      await createFromCreative({
        ad_name: ad.ad_name,
        campaign_name: ad.campaign_name,
        channel: ad.channel,
        tone: 'samimi',
      });
      onCreated();
      onClose();
    } catch (err: unknown) {
      setError(parseApiError(err));
      setCreatingId(null);
    }
  }

  return (
    <div
      className={styles.overlay}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className={styles.composerModal}>
        <div className={styles.composerHeader}>
          <span className={styles.composerTitle}>Kreatiften İçerik Oluştur</span>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Kapat">
            &times;
          </button>
        </div>

        <div className={styles.pickerBody}>
        <p className={styles.pickerHint}>
          En iyi performans gösteren reklam kreatiflerinizi tek tıkla organik
          içerik taslağına çevirin. Başlık ve açıklama yapay zeka ile uyarlanır;
          taslağı düzenleyip onaya gönderebilirsiniz.
        </p>

        {error && <div className={styles.formError}>{error}</div>}

        {loading ? (
          <div className={styles.stateBoxSm}>
            <span className={styles.muted}>Kreatifler yükleniyor...</span>
          </div>
        ) : creatives.length === 0 ? (
          <div className={styles.stateBoxSm}>
            <span className={styles.muted}>
              Uygun reklam kreatifi bulunamadı.
            </span>
          </div>
        ) : (
          <div className={styles.creativeList}>
            {creatives.map((ad) => (
              <div key={ad.ad_id} className={styles.creativeRow}>
                <div className={styles.creativeInfo}>
                  <span className={styles.creativeName}>{ad.ad_name}</span>
                  <span className={styles.creativeMeta}>
                    {ad.channel} · ROAS {ad.roas.toFixed(2)}x
                  </span>
                </div>
                <button
                  className={styles.secondaryBtn}
                  disabled={creatingId !== null}
                  onClick={() => handleCreate(ad)}
                >
                  {creatingId === ad.ad_id ? 'Oluşturuluyor...' : 'Taslak Oluştur'}
                </button>
              </div>
            ))}
          </div>
        )}
        </div>
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// Calendar (month) view
// -----------------------------------------------------------------------

const TR_MONTHS = [
  'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
  'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık',
];
// Week starts Monday (TR convention)
const TR_WEEKDAYS = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];

// Status → calendar chip colour class
const CAL_STATUS_CLASS: Record<ContentStatus, string> = {
  draft: styles.calChipDraft,
  pending_approval: styles.calChipPending,
  approved: styles.calChipApproved,
  scheduled: styles.calChipScheduled,
  published: styles.calChipPublished,
  archived: styles.calChipArchived,
};

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

interface CalendarViewProps {
  posts: ContentPost[];
  onEdit: (post: ContentPost) => void;
}

function CalendarView({ posts, onEdit }: CalendarViewProps) {
  // Default to the month of the most recent scheduled post, else current month.
  const initial = (() => {
    const scheduled = posts
      .filter((p) => p.scheduled_at)
      .map((p) => p.scheduled_at as string)
      .sort()
      .reverse();
    const anchor = scheduled.length > 0 ? new Date(scheduled[0]) : new Date();
    return { year: anchor.getFullYear(), month: anchor.getMonth() };
  })();

  const [year, setYear] = useState(initial.year);
  const [month, setMonth] = useState(initial.month);

  // Map posts to their scheduled date key (YYYY-MM-DD)
  const byDate: Record<string, ContentPost[]> = {};
  for (const p of posts) {
    if (!p.scheduled_at) continue;
    const key = p.scheduled_at.slice(0, 10);
    (byDate[key] ||= []).push(p);
  }

  // Build the day grid. JS getDay(): 0=Sun..6=Sat → convert to Mon=0..Sun=6.
  const firstWeekdayRaw = new Date(year, month, 1).getDay();
  const leadingBlanks = (firstWeekdayRaw + 6) % 7;
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (string | null)[] = [];
  for (let i = 0; i < leadingBlanks; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push(`${year}-${pad2(month + 1)}-${pad2(d)}`);
  }
  while (cells.length % 7 !== 0) cells.push(null);

  const todayKey = (() => {
    const t = new Date();
    return `${t.getFullYear()}-${pad2(t.getMonth() + 1)}-${pad2(t.getDate())}`;
  })();

  function prevMonth() {
    if (month === 0) {
      setYear(year - 1);
      setMonth(11);
    } else {
      setMonth(month - 1);
    }
  }
  function nextMonth() {
    if (month === 11) {
      setYear(year + 1);
      setMonth(0);
    } else {
      setMonth(month + 1);
    }
  }

  const scheduledCount = Object.values(byDate).reduce(
    (acc, arr) => acc + arr.length,
    0,
  );

  return (
    <div className={styles.calendar}>
      <div className={styles.calHeader}>
        <button className={styles.calNavBtn} onClick={prevMonth} aria-label="Önceki ay">
          ‹
        </button>
        <span className={styles.calMonthLabel}>
          {TR_MONTHS[month]} {year}
        </span>
        <button className={styles.calNavBtn} onClick={nextMonth} aria-label="Sonraki ay">
          ›
        </button>
        <span className={styles.calHint}>
          {scheduledCount > 0
            ? `${scheduledCount} planlı içerik`
            : 'Bu içerikler yayın tarihine göre yerleştirildi'}
        </span>
      </div>

      <div className={styles.calWeekdays}>
        {TR_WEEKDAYS.map((w) => (
          <div key={w} className={styles.calWeekday}>
            {w}
          </div>
        ))}
      </div>

      <div className={styles.calGrid}>
        {cells.map((key, i) => {
          if (key === null) {
            return <div key={`b-${i}`} className={styles.calCellEmpty} />;
          }
          const dayNum = Number(key.slice(8, 10));
          const dayPosts = byDate[key] || [];
          return (
            <div
              key={key}
              className={`${styles.calCell} ${key === todayKey ? styles.calCellToday : ''}`}
            >
              <div className={styles.calDayNum}>{dayNum}</div>
              <div className={styles.calDayPosts}>
                {dayPosts.map((p) => (
                  <button
                    key={p.id}
                    className={`${styles.calChip} ${CAL_STATUS_CLASS[p.status] || ''}`}
                    title={`${p.title} — ${STATUS_LABELS[p.status]}`}
                    onClick={() => onEdit(p)}
                  >
                    {p.title}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// -----------------------------------------------------------------------
// Main page
// -----------------------------------------------------------------------

export default function ContentPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  const [posts, setPosts] = useState<ContentPost[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showComposer, setShowComposer] = useState(false);
  const [editingPost, setEditingPost] = useState<ContentPost | null>(null);
  const [showCreativePicker, setShowCreativePicker] = useState(false);
  const [viewMode, setViewMode] = useState<'board' | 'calendar'>('board');

  const fetchPosts = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getContentPosts();
      setPosts(data);
    } catch (err: unknown) {
      setError(parseApiError(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchPosts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleEdit(post: ContentPost) {
    setEditingPost(post);
    setShowComposer(true);
  }

  function handleCloseComposer() {
    setShowComposer(false);
    setEditingPost(null);
  }

  // Group posts by status for the board columns
  const postsByStatus: Record<ContentStatus, ContentPost[]> = {
    draft: [],
    pending_approval: [],
    approved: [],
    scheduled: [],
    published: [],
    archived: [],
  };
  for (const p of posts) {
    if (p.status in postsByStatus) {
      postsByStatus[p.status].push(p);
    }
  }

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div className={styles.pageHeader}>
          <div className={styles.pageHeaderText}>
            <h1 className={styles.pageTitle}>İçerik Planlayıcı</h1>
            <p className={styles.pageSubtitle}>
              Sosyal içeriklerinizi planlayın, taslak oluşturun, onaydan geçirin
              ve yayına hazırlayın.
            </p>
          </div>
          <div className={styles.pageHeaderActions}>
            <button
              className={styles.secondaryBtn}
              onClick={() => setShowCreativePicker(true)}
            >
              ✨ Kreatiften Oluştur
            </button>
            <button
              className={styles.primaryBtn}
              onClick={() => {
                setEditingPost(null);
                setShowComposer(true);
              }}
            >
              + Yeni İçerik
            </button>
          </div>
        </div>

        {/* Credential gate banner */}
        <div className={styles.gateBanner}>
          <span className={styles.gateBannerIcon}>&#9888;</span>
          <p className={styles.gateBannerText}>
            <strong>Canlı yayın kimlik bilgisi gerektirir.</strong> Instagram,
            Facebook, X, LinkedIn, TikTok ve YouTube kanallarını Ayarlar
            bölümünden OAuth ile bağladıktan sonra &quot;Yayınla&quot; butonu
            aktif hale gelir. Kanal bağlantısı kurulmadan yayınlama
            yapılamaz (KVKK/OAuth).
          </p>
        </div>

        {/* View toggle: Pano (kanban) / Takvim (calendar) */}
        {(loading || posts.length > 0) && (
          <div className={styles.viewToggle}>
            <button
              className={`${styles.viewToggleBtn} ${viewMode === 'board' ? styles.viewToggleBtnActive : ''}`}
              onClick={() => setViewMode('board')}
            >
              Pano
            </button>
            <button
              className={`${styles.viewToggleBtn} ${viewMode === 'calendar' ? styles.viewToggleBtnActive : ''}`}
              onClick={() => setViewMode('calendar')}
            >
              Takvim
            </button>
          </div>
        )}

        {/* Error state */}
        {error && (
          <div className={styles.stateBoxSm}>
            <span className={styles.errorText}>{error}</span>
            <br />
            <button
              className={styles.secondaryBtn}
              style={{ marginTop: '0.75rem' }}
              onClick={fetchPosts}
            >
              Tekrar Dene
            </button>
          </div>
        )}

        {/* Empty state (not loading, no error, no posts) */}
        {!loading && !error && posts.length === 0 && (
          <div className={styles.stateBox}>
            <p className={styles.muted}>Henüz içerik eklenmedi.</p>
            <button
              className={styles.primaryBtn}
              style={{ marginTop: '1rem' }}
              onClick={() => {
                setEditingPost(null);
                setShowComposer(true);
              }}
            >
              + İlk İçeriği Oluştur
            </button>
          </div>
        )}

        {/* Kanban board */}
        {(loading || posts.length > 0) && viewMode === 'board' && (
          <div className={styles.board}>
            {STATUS_ORDER.map((status) => (
              <KanbanColumn
                key={status}
                status={status}
                posts={postsByStatus[status]}
                loading={loading}
                onEdit={handleEdit}
                onRefresh={fetchPosts}
              />
            ))}
          </div>
        )}

        {/* Calendar (month) view */}
        {!loading && posts.length > 0 && viewMode === 'calendar' && (
          <CalendarView posts={posts} onEdit={handleEdit} />
        )}
      </main>

      {/* Composer modal */}
      {showComposer && (
        <ComposerModal
          post={editingPost}
          onClose={handleCloseComposer}
          onSaved={fetchPosts}
        />
      )}

      {/* Kreatif → İçerik picker */}
      {showCreativePicker && (
        <CreativePickerModal
          onClose={() => setShowCreativePicker(false)}
          onCreated={fetchPosts}
        />
      )}
    </div>
  );
}
