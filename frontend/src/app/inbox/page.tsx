'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getInboxMessages,
  getInboxMessage,
  replyToMessage,
  assignMessage,
  setMessageStatus,
  setMessageTags,
  suggestReply,
  getInboxStats,
  CHANNEL_LABELS,
  KIND_LABELS,
  STATUS_LABELS,
  SENTIMENT_LABELS,
  ALL_CHANNELS,
  ALL_STATUSES,
  type SocialMessage,
  type MessageWithThread,
  type SocialReply,
  type Channel,
  type MessageKind,
  type MessageStatus,
  type Sentiment,
  type InboxStats,
  type GetInboxMessagesOptions,
} from '@/lib/inbox-api';
import AppNav from '@/components/AppNav';
import EmptyState from '@/components/EmptyState';
import styles from './inbox.module.css';

// --- Helpers ---

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

function fmtRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'az önce';
  if (mins < 60) return `${mins} dk önce`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} sa önce`;
  const days = Math.floor(hours / 24);
  return `${days} gün önce`;
}

// --- Sentiment dot ---

function SentimentDot({ sentiment, size = 'sm' }: { sentiment: Sentiment; size?: 'sm' | 'md' }) {
  const cls =
    sentiment === 'positive'
      ? styles.sentimentPositive
      : sentiment === 'negative'
      ? styles.sentimentNegative
      : styles.sentimentNeutral;
  return <span className={`${size === 'sm' ? styles.sentimentDotSm : styles.sentimentDot} ${cls}`} title={SENTIMENT_LABELS[sentiment]} />;
}

// --- Status badge ---

function StatusBadge({ status }: { status: MessageStatus }) {
  const cls: Record<MessageStatus, string> = {
    open: styles.statusOpen,
    pending: styles.statusPending,
    resolved: styles.statusResolved,
    snoozed: styles.statusSnoozed,
  };
  return (
    <span className={`${styles.statusBadge} ${cls[status] ?? ''}`}>
      {STATUS_LABELS[status]}
    </span>
  );
}

// --- Stats strip ---

function StatsStrip({
  stats,
  loading,
}: {
  stats: InboxStats | null;
  loading: boolean;
}) {
  if (loading || !stats) {
    return (
      <div className={styles.statsStrip}>
        <span className={styles.muted} style={{ fontSize: '0.8rem', padding: '0.5rem 0' }}>
          İstatistikler yükleniyor...
        </span>
      </div>
    );
  }

  return (
    <div className={styles.statsStrip}>
      <div className={`${styles.statPill} ${styles.statPillOpen}`}>
        <span className={styles.statPillValue}>{(stats.open ?? 0).toLocaleString('tr-TR')}</span>
        <span className={styles.statPillLabel}>Açık</span>
      </div>
      <div className={`${styles.statPill} ${styles.statPillPending}`}>
        <span className={styles.statPillValue}>{(stats.pending ?? 0).toLocaleString('tr-TR')}</span>
        <span className={styles.statPillLabel}>Beklemede</span>
      </div>
      <div className={`${styles.statPill} ${styles.statPillResolved}`}>
        <span className={styles.statPillValue}>{(stats.resolved ?? 0).toLocaleString('tr-TR')}</span>
        <span className={styles.statPillLabel}>Çözüldü</span>
      </div>

      <div className={styles.sentimentRow}>
        {(['positive', 'neutral', 'negative'] as Sentiment[]).map((s) => (
          <div
            key={s}
            className={`${styles.sentimentCounter} ${
              s === 'positive' ? styles.sentimentCounterPositive
              : s === 'negative' ? styles.sentimentCounterNegative
              : styles.sentimentCounterNeutral
            }`}
          >
            <span
              className={`${styles.sentimentDot} ${
                s === 'positive' ? styles.sentimentPositive
                : s === 'negative' ? styles.sentimentNegative
                : styles.sentimentNeutral
              }`}
            />
            <span className={styles.sentimentCounterValue}>
              {((stats.by_sentiment?.[s]) ?? 0).toLocaleString('tr-TR')}
            </span>
            <span className={styles.sentimentCounterLabel}>{SENTIMENT_LABELS[s]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Message list item ---

function MessageListItem({
  msg,
  active,
  onClick,
}: {
  msg: SocialMessage;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <div
      className={`${styles.messageRow} ${active ? styles.messageRowActive : ''}`}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === 'Enter' && onClick()}
      aria-selected={active}
    >
      <div className={styles.messageRowTop}>
        <span className={styles.channelBadge}>{CHANNEL_LABELS[msg.channel]}</span>
        <span className={styles.kindBadge}>{KIND_LABELS[msg.kind]}</span>
        <SentimentDot sentiment={msg.sentiment} size="sm" />
        <span className={styles.authorHandle}>@{msg.author_handle.replace(/^@+/, '')}</span>
        <span className={styles.msgTime}>{fmtRelative(msg.received_at)}</span>
      </div>
      <div className={styles.msgExcerpt}>{msg.text}</div>
      <div className={styles.messageRowMeta}>
        <StatusBadge status={msg.status} />
        {msg.assignee && (
          <span className={styles.assigneeChip}>{msg.assignee}</span>
        )}
      </div>
    </div>
  );
}

// --- Left pane ---

function MessageListPane({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (msg: SocialMessage) => void;
}) {
  const [filters, setFilters] = useState<GetInboxMessagesOptions>({});
  const [messages, setMessages] = useState<SocialMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMessages = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getInboxMessages(filters);
      setMessages(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Mesajlar yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    fetchMessages();
  }, [fetchMessages]);

  function setFilter<K extends keyof GetInboxMessagesOptions>(
    key: K,
    value: GetInboxMessagesOptions[K],
  ) {
    setFilters((prev) => {
      const next = { ...prev };
      if (value === '' || value === undefined) {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
  }

  return (
    <div className={styles.card}>
      {/* Filters */}
      <div className={styles.filtersBar}>
        <div className={styles.filterRow}>
          <select
            className={styles.selectSm}
            value={filters.channel ?? ''}
            onChange={(e) => setFilter('channel', e.target.value as Channel || undefined)}
            aria-label="Kanal filtresi"
          >
            <option value="">Tüm Kanallar</option>
            {ALL_CHANNELS.map((c) => (
              <option key={c} value={c}>{CHANNEL_LABELS[c]}</option>
            ))}
          </select>

          <select
            className={styles.selectSm}
            value={filters.kind ?? ''}
            onChange={(e) => setFilter('kind', e.target.value as MessageKind || undefined)}
            aria-label="Tür filtresi"
          >
            <option value="">Tüm Türler</option>
            {(['dm', 'comment', 'mention'] as MessageKind[]).map((k) => (
              <option key={k} value={k}>{KIND_LABELS[k]}</option>
            ))}
          </select>
        </div>
        <div className={styles.filterRow}>
          <select
            className={styles.selectSm}
            value={filters.status ?? ''}
            onChange={(e) => setFilter('status', e.target.value as MessageStatus || undefined)}
            aria-label="Durum filtresi"
          >
            <option value="">Tüm Durumlar</option>
            {ALL_STATUSES.map((s) => (
              <option key={s} value={s}>{STATUS_LABELS[s]}</option>
            ))}
          </select>

          <select
            className={styles.selectSm}
            value={filters.sentiment ?? ''}
            onChange={(e) => setFilter('sentiment', e.target.value as Sentiment || undefined)}
            aria-label="Duygu filtresi"
          >
            <option value="">Tüm Duygular</option>
            {(['positive', 'neutral', 'negative'] as Sentiment[]).map((s) => (
              <option key={s} value={s}>{SENTIMENT_LABELS[s]}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Message list */}
      {loading ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.muted}>Mesajlar yükleniyor...</span>
        </div>
      ) : error ? (
        <div className={styles.stateBoxSm}>
          <span className={styles.errorText}>{error}</span>
          <br />
          <button className={styles.secondaryBtn} style={{ marginTop: '0.5rem' }} onClick={fetchMessages}>
            Tekrar Dene
          </button>
        </div>
      ) : messages.length === 0 ? (
        <div className={styles.stateBox}>
          <span className={styles.muted}>Bu filtrelerle eşleşen mesaj bulunamadı.</span>
        </div>
      ) : (
        <div className={styles.messageList} role="listbox" aria-label="Mesaj listesi">
          {messages.map((msg) => (
            <MessageListItem
              key={msg.id}
              msg={msg}
              active={selectedId === msg.id}
              onClick={() => onSelect(msg)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// --- Reply bubble ---

function ReplyBubble({ reply }: { reply: SocialReply }) {
  return (
    <div className={styles.replyBubble}>
      <div className={styles.replyMeta}>
        <span className={styles.replyAuthor}>{reply.author}</span>
        <span className={styles.replyTime}>{fmtDate(reply.created_at)}</span>
        {reply.ai_assisted && (
          <span className={styles.replyAiBadge}>YZ destekli</span>
        )}
      </div>
      <div className={styles.replyBody}>{reply.body}</div>
      {!reply.delivered && (
        <span className={styles.replyDeliveryNote}>
          AYAZ&apos;da kayıtlı — canlı gönderim OAuth kimliği bekliyor
        </span>
      )}
    </div>
  );
}

// --- Tag input ---

function TagInput({
  tags,
  onChange,
  disabled,
}: {
  tags: string[];
  onChange: (tags: string[]) => void;
  disabled?: boolean;
}) {
  const [inputVal, setInputVal] = useState('');

  function addTag() {
    const trimmed = inputVal.trim();
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed]);
    }
    setInputVal('');
  }

  function removeTag(tag: string) {
    onChange(tags.filter((t) => t !== tag));
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
      <div style={{ display: 'flex', gap: '0.35rem' }}>
        <input
          className={styles.input}
          placeholder="Etiket ekle..."
          value={inputVal}
          onChange={(e) => setInputVal(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              addTag();
            }
          }}
          disabled={disabled}
          aria-label="Etiket girişi"
          style={{ flex: 1 }}
        />
        <button
          type="button"
          className={styles.secondaryBtn}
          onClick={addTag}
          disabled={disabled || !inputVal.trim()}
        >
          Ekle
        </button>
      </div>
      {tags.length > 0 && (
        <div className={styles.tagsWrap}>
          {tags.map((tag) => (
            <span key={tag} className={styles.tagChip}>
              {tag}
              <button
                className={styles.tagRemoveBtn}
                onClick={() => removeTag(tag)}
                disabled={disabled}
                aria-label={`${tag} etiketini kaldır`}
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// --- Conversation pane ---

function ConversationPane({
  messageId,
  onUpdated,
}: {
  messageId: string;
  onUpdated?: () => void;
}) {
  const [thread, setThread] = useState<MessageWithThread | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Reply composer
  const [replyBody, setReplyBody] = useState('');
  const [replying, setReplying] = useState(false);
  const [replyError, setReplyError] = useState<string | null>(null);
  const [suggestLoading, setSuggestLoading] = useState(false);

  // Action bar
  const [assignee, setAssignee] = useState('');
  const [assigning, setAssigning] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);
  const [assignSuccess, setAssignSuccess] = useState(false);

  const [newStatus, setNewStatus] = useState<MessageStatus | ''>('');
  const [settingStatus, setSettingStatus] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [tags, setTags] = useState<string[]>([]);
  const [savingTags, setSavingTags] = useState(false);
  const [tagsError, setTagsError] = useState<string | null>(null);
  const [tagsSuccess, setTagsSuccess] = useState(false);

  const prevIdRef = useRef<string | null>(null);

  const fetchThread = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getInboxMessage(messageId);
      setThread(data);
      // Initialise action bar state from loaded data
      setAssignee(data.assignee ?? '');
      setNewStatus(data.status);
      setTags(data.tags ?? []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Konuşma yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, [messageId]);

  // Reset composer when switching messages
  useEffect(() => {
    if (prevIdRef.current !== messageId) {
      prevIdRef.current = messageId;
      setReplyBody('');
      setReplyError(null);
      setAssignError(null);
      setAssignSuccess(false);
      setStatusError(null);
      setTagsError(null);
      setTagsSuccess(false);
    }
    fetchThread();
  }, [messageId, fetchThread]);

  async function handleSuggestReply() {
    if (!thread) return;
    setSuggestLoading(true);
    try {
      const result = await suggestReply({
        text: thread.text,
        channel: thread.channel,
      });
      setReplyBody(result.reply);
    } catch (err: unknown) {
      setReplyError(err instanceof Error ? err.message : 'Öneri alınamadı');
    } finally {
      setSuggestLoading(false);
    }
  }

  async function handleReply() {
    if (!replyBody.trim()) return;
    setReplying(true);
    setReplyError(null);
    try {
      const newReply: SocialReply = await replyToMessage(messageId, replyBody.trim());
      setThread((prev) =>
        prev ? { ...prev, replies: [...(prev.replies ?? []), newReply] } : prev,
      );
      setReplyBody('');
      onUpdated?.();
    } catch (err: unknown) {
      setReplyError(err instanceof Error ? err.message : 'Yanıt gönderilemedi');
    } finally {
      setReplying(false);
    }
  }

  async function handleAssign() {
    if (!assignee.trim()) return;
    setAssigning(true);
    setAssignError(null);
    setAssignSuccess(false);
    try {
      const updated = await assignMessage(messageId, assignee.trim());
      setThread((prev) => (prev ? { ...prev, ...updated } : prev));
      setAssignSuccess(true);
      setTimeout(() => setAssignSuccess(false), 2500);
      onUpdated?.();
    } catch (err: unknown) {
      setAssignError(err instanceof Error ? err.message : 'Atama yapılamadı');
    } finally {
      setAssigning(false);
    }
  }

  async function handleSetStatus() {
    if (!newStatus) return;
    setSettingStatus(true);
    setStatusError(null);
    try {
      const updated = await setMessageStatus(messageId, newStatus as MessageStatus);
      setThread((prev) => (prev ? { ...prev, ...updated } : prev));
      onUpdated?.();
    } catch (err: unknown) {
      setStatusError(err instanceof Error ? err.message : 'Durum güncellenemedi');
    } finally {
      setSettingStatus(false);
    }
  }

  async function handleSaveTags() {
    setSavingTags(true);
    setTagsError(null);
    setTagsSuccess(false);
    try {
      const updated = await setMessageTags(messageId, tags);
      setThread((prev) => (prev ? { ...prev, ...updated } : prev));
      setTagsSuccess(true);
      setTimeout(() => setTagsSuccess(false), 2500);
      onUpdated?.();
    } catch (err: unknown) {
      setTagsError(err instanceof Error ? err.message : 'Etiketler kaydedilemedi');
    } finally {
      setSavingTags(false);
    }
  }

  if (loading) {
    return (
      <div className={styles.card}>
        <div className={styles.stateBox}>
          <span className={styles.muted}>Konuşma yükleniyor...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.card}>
        <div className={styles.stateBox}>
          <span className={styles.errorText}>{error}</span>
          <br />
          <button className={styles.secondaryBtn} style={{ marginTop: '0.75rem' }} onClick={fetchThread}>
            Tekrar Dene
          </button>
        </div>
      </div>
    );
  }

  if (!thread) return null;

  const replies: SocialReply[] = thread.replies ?? [];

  return (
    <div className={`${styles.card} ${styles.conversationPane}`}>
      {/* Original message */}
      <div className={styles.conversationHeader}>
        <div className={styles.convAuthorRow}>
          <span className={styles.convAuthorName}>{thread.author_name}</span>
          <span className={styles.convAuthorHandle}>@{thread.author_handle.replace(/^@+/, '')}</span>
          <div className={styles.convBadges}>
            <span className={styles.channelBadge}>{CHANNEL_LABELS[thread.channel]}</span>
            <span className={styles.kindBadge}>{KIND_LABELS[thread.kind]}</span>
            <SentimentDot sentiment={thread.sentiment} size="sm" />
            <StatusBadge status={thread.status} />
          </div>
        </div>

        <div className={styles.convText}>{thread.text}</div>

        {thread.permalink && (
          <a
            href={thread.permalink}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.convPermalink}
          >
            Orijinal gönderiye git &rarr;
          </a>
        )}

        <span className={styles.muted} style={{ fontSize: '0.75rem' }}>
          {fmtDate(thread.received_at)}
        </span>
      </div>

      {/* Replies thread */}
      {replies.length > 0 && (
        <div className={styles.repliesThread}>
          {replies.map((reply) => (
            <ReplyBubble key={reply.id} reply={reply} />
          ))}
        </div>
      )}

      {/* Composer */}
      <div className={styles.composerSection}>
        <span className={styles.composerLabel}>Yanıt Yaz</span>
        <textarea
          className={styles.composerTextarea}
          placeholder="Yanıtınızı buraya yazın..."
          value={replyBody}
          onChange={(e) => setReplyBody(e.target.value)}
          disabled={replying || suggestLoading}
          aria-label="Yanıt metni"
        />
        <div className={styles.composerActions}>
          <button
            className={styles.aiBtn}
            onClick={handleSuggestReply}
            disabled={suggestLoading || replying}
            title="Yapay zeka ile yanıt önerisi al"
          >
            {suggestLoading ? 'Öneriliyor...' : 'YZ Yanıt Öner'}
          </button>
          <button
            className={styles.primaryBtn}
            onClick={handleReply}
            disabled={replying || !replyBody.trim()}
          >
            {replying ? 'Gönderiliyor...' : 'Yanıtla'}
          </button>
        </div>
        {replyError && (
          <span className={styles.formError} role="alert">
            {replyError}
          </span>
        )}
      </div>

      {/* Action bar */}
      <div className={styles.actionBar}>
        <div className={styles.actionBarLabel}>İşlemler</div>
        <div className={styles.actionRow}>
          {/* Assign */}
          <div className={styles.actionField}>
            <label className={styles.actionFieldLabel}>Ata</label>
            <div style={{ display: 'flex', gap: '0.35rem' }}>
              <input
                className={styles.input}
                placeholder="Kullanıcı adı"
                value={assignee}
                onChange={(e) => setAssignee(e.target.value)}
                disabled={assigning}
                onKeyDown={(e) => e.key === 'Enter' && handleAssign()}
                aria-label="Atanacak kullanıcı"
              />
              <button
                className={styles.secondaryBtn}
                onClick={handleAssign}
                disabled={assigning || !assignee.trim()}
              >
                {assigning ? '...' : 'Ata'}
              </button>
            </div>
            {assignError && <span className={styles.formError}>{assignError}</span>}
            {assignSuccess && <span className={styles.formSuccess}>Atandı.</span>}
          </div>

          {/* Status */}
          <div className={styles.actionField}>
            <label className={styles.actionFieldLabel}>Durum</label>
            <div style={{ display: 'flex', gap: '0.35rem' }}>
              <select
                className={styles.select}
                value={newStatus}
                onChange={(e) => setNewStatus(e.target.value as MessageStatus)}
                disabled={settingStatus}
                aria-label="Mesaj durumu"
              >
                {ALL_STATUSES.map((s) => (
                  <option key={s} value={s}>{STATUS_LABELS[s]}</option>
                ))}
              </select>
              <button
                className={styles.secondaryBtn}
                onClick={handleSetStatus}
                disabled={settingStatus || newStatus === thread.status}
              >
                {settingStatus ? '...' : 'Uygula'}
              </button>
            </div>
            {statusError && <span className={styles.formError}>{statusError}</span>}
          </div>
        </div>

        {/* Tags */}
        <div>
          <div className={styles.actionFieldLabel} style={{ marginBottom: '0.35rem' }}>Etiketler</div>
          <TagInput tags={tags} onChange={setTags} disabled={savingTags} />
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem' }}>
            <button
              className={styles.secondaryBtn}
              onClick={handleSaveTags}
              disabled={savingTags}
            >
              {savingTags ? 'Kaydediliyor...' : 'Etiketleri Kaydet'}
            </button>
            {tagsSuccess && <span className={styles.formSuccess}>Kaydedildi.</span>}
            {tagsError && <span className={styles.formError}>{tagsError}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

// --- Main page ---

export default function InboxPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  const [stats, setStats] = useState<InboxStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(true);
  const [selectedMessage, setSelectedMessage] = useState<SocialMessage | null>(null);
  // Increment to trigger re-fetches in child components
  const [listRefetchKey, setListRefetchKey] = useState(0);

  useEffect(() => {
    if (!getToken()) return;
    let cancelled = false;
    setStatsLoading(true);
    getInboxStats()
      .then((data) => {
        if (!cancelled) {
          setStats(data);
          setStatsLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setStatsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [listRefetchKey]);

  function handleMessageSelect(msg: SocialMessage) {
    setSelectedMessage(msg);
  }

  function handleActionDone() {
    setListRefetchKey((k) => k + 1);
  }

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Sosyal Gelen Kutusu</h1>
          <p className={styles.pageSubtitle}>
            Tüm sosyal kanallardan gelen mesaj, yorum ve bahsetmeleri tek yerden yanıtlayın.
          </p>
        </div>

        {/* Gate banner */}
        <div className={styles.gateBanner} role="note">
          <span className={styles.gateBannerIcon}>i</span>
          <span>
            Canlı senkron ve gönderim için kanal kimliği (OAuth) gerekir. Bu sürümde iş akışı
            (atama, durum değiştirme, etiket, yanıt taslağı) tam çalışır; canlı platform
            gönderimi OAuth bağlantısı tamamlandığında aktif olur.
          </span>
        </div>

        {/* Stats strip */}
        <StatsStrip stats={stats} loading={statsLoading} />

        {/* Two-pane inbox */}
        <div className={styles.inboxLayout}>
          {/* Left: message list */}
          <MessageListPane
            key={listRefetchKey}
            selectedId={selectedMessage?.id ?? null}
            onSelect={handleMessageSelect}
          />

          {/* Right: conversation */}
          {selectedMessage ? (
            <ConversationPane
              messageId={selectedMessage.id}
              onUpdated={handleActionDone}
            />
          ) : (
            <div className={styles.card}>
              <div className={styles.emptyConversationWrap}>
                <EmptyState
                  title="Bir mesaj seçin"
                  subtitle="Sol taraftan bir mesaj seçerek konuşmayı ve yanıt seçeneklerini görün."
                />
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
