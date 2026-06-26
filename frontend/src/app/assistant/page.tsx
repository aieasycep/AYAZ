'use client';

import {
  useState,
  useEffect,
  useRef,
  useCallback,
  KeyboardEvent,
} from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  listConversations,
  createConversation,
  getMessages,
  sendMessage,
  type Conversation,
  type Message,
  type ToolUsed,
} from '@/lib/assistant-api';
import AppNav from '@/components/AppNav';
import styles from './assistant.module.css';

// ---- Suggested prompts ----

const SUGGESTED_PROMPTS = [
  'Bu hafta neyi optimize etmeliyim?',
  'ROAS\'ım neden düştü?',
  'Kampanyalarımı özetle',
  'En kötü performanslı kampanya hangisi?',
  'ROAS %20 düşerse beni uyaracak bir kural oluştur',
  'Bu ay için 5x ROAS hedefi koy',
];

// ---- Action tool names (these trigger a green "aksiyon" chip) ----

const ACTION_TOOLS = new Set([
  'create_automation_rule',
  'create_goal',
  'create_alert_rule',
  'apply_fix',
  'set_goal',
  'set_budget',
]);

// ---- Tool chip icon mapping ----

function toolIcon(name: string): string {
  const n = name.toLowerCase();
  if (n.includes('rule') || n.includes('kural') || n.includes('automation')) return '⚡';
  if (n.includes('goal') || n.includes('hedef')) return '🎯';
  if (n.includes('performans') || n.includes('performance')) return '📊';
  if (n.includes('kampanya') || n.includes('campaign')) return '📣';
  if (n.includes('içgörü') || n.includes('insight')) return '💡';
  if (n.includes('roas') || n.includes('spend') || n.includes('budget')) return '💰';
  if (n.includes('rapor') || n.includes('report')) return '📋';
  return '🔧';
}

function isActionTool(name: string): boolean {
  return ACTION_TOOLS.has(name.toLowerCase());
}

function actionToolLabel(name: string, summary: string): string {
  const n = name.toLowerCase();
  if (n.includes('rule') || n.includes('kural') || n.includes('automation')) {
    return summary || 'kural oluşturuldu';
  }
  if (n.includes('goal') || n.includes('hedef')) {
    return summary || 'hedef oluşturuldu';
  }
  return summary || 'aksiyon alındı';
}

// ---- Date formatter ----

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('tr-TR', {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function fmtConvDate(iso: string): string {
  return new Date(iso).toLocaleDateString('tr-TR', {
    day: '2-digit',
    month: '2-digit',
  });
}

// ---- UI message type (combines stored + optimistic) ----

interface UiMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  tools_used?: ToolUsed[];
  created_at: string;
}

// ---- Component ----

export default function AssistantPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  // --- Conversations ---
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [convsLoading, setConvsLoading] = useState(true);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [creatingConv, setCreatingConv] = useState(false);

  // --- Messages ---
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [msgsLoading, setMsgsLoading] = useState(false);
  const [msgsError, setMsgsError] = useState<string | null>(null);

  // --- Sending ---
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [lastFailedContent, setLastFailedContent] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, sending]);

  // --- Load conversations ---

  const fetchConversations = useCallback(async () => {
    setConvsLoading(true);
    try {
      const data = await listConversations();
      // Sort newest first by updated_at
      data.sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );
      setConversations(data);
    } catch {
      // Non-fatal: show empty list
      setConversations([]);
    } finally {
      setConvsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) return;
    fetchConversations();
  }, [fetchConversations]);

  // --- Load messages for a conversation ---

  const fetchMessages = useCallback(async (convId: string) => {
    setMsgsLoading(true);
    setMsgsError(null);
    setMessages([]);
    try {
      const data = await getMessages(convId);
      const ui: UiMessage[] = data.map((m: Message) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        created_at: m.created_at,
      }));
      setMessages(ui);
    } catch (err: unknown) {
      setMsgsError(
        err instanceof Error ? err.message : 'Mesajlar yüklenemedi',
      );
    } finally {
      setMsgsLoading(false);
    }
  }, []);

  function selectConversation(id: string) {
    if (id === activeConvId) return;
    setActiveConvId(id);
    setSendError(null);
    setLastFailedContent(null);
    fetchMessages(id);
  }

  // --- Create new conversation ---

  async function handleNewChat() {
    setCreatingConv(true);
    try {
      const conv = await createConversation();
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      setMessages([]);
      setMsgsError(null);
      setSendError(null);
      setLastFailedContent(null);
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Sohbet başlatılamadı');
    } finally {
      setCreatingConv(false);
    }
  }

  // --- Send a message ---

  async function doSend(content: string) {
    if (!content.trim() || !activeConvId || sending) return;

    const trimmed = content.trim();
    setSendError(null);
    setLastFailedContent(null);
    setInput('');

    // Optimistic user message
    const optimisticId = `opt-${Date.now()}`;
    const userMsg: UiMessage = {
      id: optimisticId,
      role: 'user',
      content: trimmed,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setSending(true);

    try {
      const res = await sendMessage(activeConvId, trimmed);
      const assistantMsg: UiMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: res.assistant_message.content,
        tools_used: res.tools_used,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Refresh conversation list to update title/timestamp
      fetchConversations();
    } catch (err: unknown) {
      setSendError(
        err instanceof Error ? err.message : 'Mesaj gönderilemedi',
      );
      setLastFailedContent(trimmed);
      // Remove optimistic message on failure
      setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
    } finally {
      setSending(false);
    }
  }

  function handleSend() {
    doSend(input);
  }

  function handleRetry() {
    if (lastFailedContent) {
      doSend(lastFailedContent);
    }
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleSuggest(prompt: string) {
    if (sending) return;
    doSend(prompt);
  }

  const isEmpty = messages.length === 0 && !msgsLoading && !msgsError;
  const isInputDisabled = !activeConvId || sending;

  return (
    <div className={styles.shell}>
      <AppNav />

      <div className={styles.body}>
        {/* ---- Sidebar ---- */}
        <aside className={styles.sidebar}>
          <div className={styles.sidebarHeader}>
            <div className={styles.sidebarTitle}>Sohbetler</div>
            <button
              className={styles.newChatBtn}
              onClick={handleNewChat}
              disabled={creatingConv}
            >
              + Yeni sohbet
            </button>
          </div>

          <div className={styles.convList}>
            {convsLoading ? (
              <div className={styles.sidebarLoading}>Yükleniyor...</div>
            ) : conversations.length === 0 ? (
              <div className={styles.sidebarEmpty}>
                Henüz sohbet yok. Yeni bir sohbet başlatın.
              </div>
            ) : (
              conversations.map((conv) => (
                <button
                  key={conv.id}
                  className={`${styles.convItem} ${activeConvId === conv.id ? styles.convItemActive : ''}`}
                  onClick={() => selectConversation(conv.id)}
                  title={`${conv.title} — ${fmtConvDate(conv.updated_at)}`}
                >
                  {conv.title || 'Yeni sohbet'}
                </button>
              ))
            )}
          </div>
        </aside>

        {/* ---- Chat area ---- */}
        <div className={styles.chat}>
          {!activeConvId ? (
            /* No conversation selected */
            <div className={styles.noConvPlaceholder}>
              Bir sohbet seçin veya yeni sohbet başlatın.
            </div>
          ) : msgsLoading ? (
            /* Loading messages */
            <div className={styles.noConvPlaceholder}>
              Mesajlar yükleniyor...
            </div>
          ) : msgsError ? (
            /* Error loading messages */
            <div className={styles.noConvPlaceholder}>
              <span style={{ color: 'var(--color-danger)', fontSize: '0.9rem' }}>
                {msgsError}
              </span>
            </div>
          ) : isEmpty ? (
            /* Empty conversation — intro + suggested prompts */
            <>
              <div className={styles.intro}>
                <div className={styles.introIcon}>🤖</div>
                <div className={styles.introTitle}>AYAZ Asistan</div>
                <p className={styles.introSubtitle}>
                  Verilerinize dayalı Türkçe pazarlama asistanı. Reklam
                  performansınız, ROAS&apos;ınız, kampanyalarınız veya bütçeniz
                  hakkında soru sorabilirsiniz.
                </p>
                <div className={styles.suggestGrid}>
                  {SUGGESTED_PROMPTS.map((prompt) => (
                    <button
                      key={prompt}
                      className={styles.suggestChip}
                      onClick={() => handleSuggest(prompt)}
                      disabled={sending}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>

              {/* Error + retry for this state */}
              {sendError && (
                <div className={styles.errorBanner}>
                  <span>{sendError}</span>
                  {lastFailedContent && (
                    <button className={styles.retryBtn} onClick={handleRetry}>
                      Tekrar dene
                    </button>
                  )}
                </div>
              )}

              {/* Input bar is still shown */}
              <div className={styles.inputBar}>
                <div className={styles.inputRow}>
                  <textarea
                    ref={textareaRef}
                    className={styles.textarea}
                    rows={1}
                    placeholder="Bir şey sorun..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={isInputDisabled}
                  />
                  <button
                    className={styles.sendBtn}
                    onClick={handleSend}
                    disabled={isInputDisabled || !input.trim()}
                  >
                    Gönder
                  </button>
                </div>
                <div className={styles.inputHint}>
                  Enter ile gönder, Shift+Enter ile satır ekle
                </div>
              </div>
            </>
          ) : (
            /* Messages view */
            <>
              <div className={styles.messages}>
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`${styles.msgRow} ${msg.role === 'user' ? styles.msgRowUser : ''}`}
                  >
                    <div
                      className={`${styles.avatar} ${msg.role === 'assistant' ? styles.avatarAssistant : styles.avatarUser}`}
                      title={msg.role === 'assistant' ? `AYAZ — ${fmtTime(msg.created_at)}` : `Siz — ${fmtTime(msg.created_at)}`}
                    >
                      {msg.role === 'assistant' ? 'A' : 'S'}
                    </div>

                    <div>
                      <div
                        className={`${styles.bubble} ${msg.role === 'assistant' ? styles.bubbleAssistant : styles.bubbleUser}`}
                      >
                        {msg.content}
                      </div>

                      {/* Tool chips for assistant messages */}
                      {msg.role === 'assistant' &&
                        msg.tools_used &&
                        msg.tools_used.length > 0 && (
                          <div className={styles.toolChips}>
                            {msg.tools_used.map((tool, i) => {
                              const action = isActionTool(tool.name);
                              return (
                                <span
                                  key={i}
                                  className={`${styles.toolChip} ${action ? styles.toolChipAction : ''}`}
                                  title={tool.summary}
                                >
                                  {action
                                    ? `✅ ${actionToolLabel(tool.name, tool.summary)}`
                                    : `${toolIcon(tool.name)} ${tool.summary || tool.name}`}
                                </span>
                              );
                            })}
                          </div>
                        )}
                    </div>
                  </div>
                ))}

                {/* Typing indicator while waiting */}
                {sending && (
                  <div className={styles.typingRow}>
                    <div className={`${styles.avatar} ${styles.avatarAssistant}`}>
                      A
                    </div>
                    <div className={styles.typingBubble}>
                      <span className={styles.typingDot} />
                      <span className={styles.typingDot} />
                      <span className={styles.typingDot} />
                    </div>
                  </div>
                )}

                <div ref={messagesEndRef} />
              </div>

              {/* Error + retry banner */}
              {sendError && (
                <div className={styles.errorBanner}>
                  <span>{sendError}</span>
                  {lastFailedContent && (
                    <button className={styles.retryBtn} onClick={handleRetry}>
                      Tekrar dene
                    </button>
                  )}
                </div>
              )}

              {/* Input bar */}
              <div className={styles.inputBar}>
                <div className={styles.inputRow}>
                  <textarea
                    ref={textareaRef}
                    className={styles.textarea}
                    rows={1}
                    placeholder="Bir şey sorun..."
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    disabled={isInputDisabled}
                  />
                  <button
                    className={styles.sendBtn}
                    onClick={handleSend}
                    disabled={isInputDisabled || !input.trim()}
                  >
                    Gönder
                  </button>
                </div>
                <div className={styles.inputHint}>
                  Enter ile gönder, Shift+Enter ile satır ekle
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
