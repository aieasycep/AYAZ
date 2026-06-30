'use client';

import { useState, useEffect, useCallback } from 'react';
import AppNav from '@/components/AppNav';
import SectionCard from '@/components/SectionCard';
import {
  generateAdCopy,
  saveDraft,
  listDrafts,
  updateDraftStatus,
  deleteDraft,
  PLATFORM_LABELS,
  TONE_LABELS,
  type AdPlatform,
  type AdTone,
  type AdField,
  type AdVariant,
  type AdGenerateResult,
  type AdCopyDraft,
  type DraftStatus,
} from '@/lib/ad-studio-api';
import { channelColor } from '@/lib/chartColors';
import styles from './ad-studio.module.css';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTRDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('tr-TR', {
      day: 'numeric',
      month: 'long',
      year: 'numeric',
    });
  } catch {
    return iso;
  }
}

const AD_PLATFORMS: AdPlatform[] = ['google_ads', 'meta_ads', 'tiktok_ads'];
const AD_TONES: AdTone[] = ['profesyonel', 'samimi', 'heyecanli', 'bilgilendirici'];

// ---------------------------------------------------------------------------
// FieldRow — single ad field with char counter + copy button
// ---------------------------------------------------------------------------

function FieldRow({ field }: { field: AdField }) {
  const [copied, setCopied] = useState(false);

  function handleCopy() {
    navigator.clipboard.writeText(field.value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }

  return (
    <div className={styles.adFieldRow}>
      <div className={styles.adFieldHeader}>
        <span className={styles.adFieldLabel}>{field.label}</span>
        <div className={styles.adFieldActions}>
          <span
            className={`${styles.charCounter} ${
              field.within_limit ? styles.charCounterOk : styles.charCounterOver
            }`}
          >
            {field.char_count} / {field.max_len}
          </span>
          <button
            type="button"
            className={`${styles.copyBtn} ${copied ? styles.copyBtnCopied : ''}`}
            onClick={handleCopy}
            aria-label={`${field.label} alanini kopyala`}
          >
            {copied ? 'Kopyalandı' : 'Kopyala'}
          </button>
        </div>
      </div>
      <div className={styles.adFieldValue}>{field.value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// VariantCard — one generated variant with save action
// ---------------------------------------------------------------------------

interface VariantCardProps {
  variant: AdVariant;
  product: string;
  result: AdGenerateResult;
  onSaved: () => void;
  onToast: (msg: string) => void;
}

function VariantCard({ variant, product, result, onSaved, onToast }: VariantCardProps) {
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    setSaving(true);
    try {
      await saveDraft({
        platform: result.platform,
        title: product || result.platform_label,
        brief: {
          platform: result.platform,
          product,
        },
        variants: [variant],
        source: result.source,
      });
      onSaved();
      onToast('Taslak kaydedildi');
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : 'Kaydetme hatası');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.variantCard}>
      <div className={styles.variantCardHeader}>
        <span className={styles.variantTitle}>Varyant {variant.index + 1}</span>
        <button
          type="button"
          className={styles.saveVariantBtn}
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? '...' : 'Kaydet'}
        </button>
      </div>
      <div className={styles.fieldsList}>
        {variant.fields.map((f) => (
          <FieldRow key={f.key} field={f} />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DraftRow — library entry
// ---------------------------------------------------------------------------

interface DraftRowProps {
  draft: AdCopyDraft;
  onRefresh: () => void;
  onToast: (msg: string) => void;
}

function DraftRow({ draft, onRefresh, onToast }: DraftRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [pending, setPending] = useState(false);

  const firstField: AdField | undefined = draft.variants[0]?.fields[0];

  async function handleToggleStatus() {
    const nextStatus: DraftStatus = draft.status === 'saved' ? 'archived' : 'saved';
    setPending(true);
    try {
      await updateDraftStatus(draft.id, nextStatus);
      onRefresh();
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : 'Durum güncellenemedi');
    } finally {
      setPending(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`"${draft.title}" taslagi silinsin mi?`)) return;
    setPending(true);
    try {
      await deleteDraft(draft.id);
      onRefresh();
      onToast('Taslak silindi');
    } catch (err: unknown) {
      onToast(err instanceof Error ? err.message : 'Silme hatası');
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={styles.draftCard}>
      <div className={styles.draftCardMain}>
        <div className={styles.draftCardMeta}>
          <div className={styles.draftCardBadges}>
            <span
              className={styles.platformBadge}
              style={{ background: channelColor(draft.platform), color: '#fff' }}
            >
              {draft.platform_label || PLATFORM_LABELS[draft.platform]}
            </span>
            {draft.source === 'ai' && (
              <span className={styles.sourceChipAiBadge}>AI</span>
            )}
            <span
              className={`${styles.sourceChip} ${
                draft.source === 'ai' ? styles.sourceChipAi : styles.sourceChipTemplate
              }`}
            >
              {draft.source === 'ai' ? 'Yapay zeka' : 'Otomatik'}
            </span>
          </div>
          <div className={styles.draftCardTitle}>{draft.title}</div>
          {firstField && (
            <div className={styles.draftCardPreview}>{firstField.value}</div>
          )}
          <div className={styles.draftCardDate}>{formatTRDate(draft.created_at)}</div>
        </div>

        <div className={styles.draftCardActions}>
          <button
            type="button"
            className={styles.draftActionBtn}
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? 'Kapat' : 'Görüntüle'}
          </button>
          <button
            type="button"
            className={styles.draftActionBtn}
            onClick={handleToggleStatus}
            disabled={pending}
          >
            {draft.status === 'saved' ? 'Arşivle' : 'Geri Yükle'}
          </button>
          <button
            type="button"
            className={`${styles.draftActionBtn} ${styles.draftActionBtnDanger}`}
            onClick={handleDelete}
            disabled={pending}
          >
            Sil
          </button>
        </div>
      </div>

      {expanded && (
        <div className={styles.draftExpanded}>
          <div className={styles.draftExpandedTitle}>
            {draft.variants.length} varyant
          </div>
          {draft.variants.map((v) => (
            <div key={v.index} className={styles.variantCard}>
              <div className={styles.variantCardHeader}>
                <span className={styles.variantTitle}>Varyant {v.index + 1}</span>
              </div>
              <div className={styles.fieldsList}>
                {v.fields.map((f) => (
                  <FieldRow key={f.key} field={f} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Library section
// ---------------------------------------------------------------------------

type LibraryFilter = 'all' | DraftStatus;

interface LibrarySectionProps {
  drafts: AdCopyDraft[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  onToast: (msg: string) => void;
}

function LibrarySection({ drafts, loading, error, onRefresh, onToast }: LibrarySectionProps) {
  const [filter, setFilter] = useState<LibraryFilter>('all');

  const filters: { key: LibraryFilter; label: string }[] = [
    { key: 'all', label: 'Tümü' },
    { key: 'saved', label: 'Kayıtlı' },
    { key: 'archived', label: 'Arşiv' },
  ];

  const visible = drafts.filter((d) => filter === 'all' || d.status === filter);

  const filterBar = (
    <div className={styles.filterBar}>
      {filters.map((f) => (
        <button
          key={f.key}
          type="button"
          className={`${styles.filterChip} ${filter === f.key ? styles.filterChipActive : ''}`}
          onClick={() => setFilter(f.key)}
        >
          {f.label}
        </button>
      ))}
    </div>
  );

  return (
    <SectionCard title="Taslak Kütüphanesi" right={filterBar}>
      {loading ? (
        <div className={styles.draftList}>
          {[0, 1, 2].map((i) => (
            <div key={i} className={`${styles.skeleton} ${styles.skeletonRow}`} />
          ))}
        </div>
      ) : error ? (
        <div className={styles.libraryEmpty}>
          <span className={styles.errorText}>{error}</span>
          <br />
          <button type="button" className={styles.retryBtn} onClick={onRefresh}>
            Tekrar Dene
          </button>
        </div>
      ) : visible.length === 0 ? (
        <div className={styles.libraryEmpty}>
          {drafts.length === 0
            ? 'Henüz kayıtlı taslak yok. Reklam metni ürettikten sonra "Kaydet" ile buraya ekleyebilirsiniz.'
            : 'Bu filtrede taslak bulunmuyor.'}
        </div>
      ) : (
        <div className={styles.draftList}>
          {visible.map((d) => (
            <DraftRow key={d.id} draft={d} onRefresh={onRefresh} onToast={onToast} />
          ))}
        </div>
      )}
    </SectionCard>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function AdStudioPage() {
  // Form state
  const [platform, setPlatform] = useState<AdPlatform>('meta_ads');
  const [product, setProduct] = useState('');
  const [valueProp, setValueProp] = useState('');
  const [tone, setTone] = useState<AdTone>('profesyonel');
  const [keywordsInput, setKeywordsInput] = useState('');
  const [audience, setAudience] = useState('');
  const [nVariants, setNVariants] = useState(3);

  // Generate state
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [result, setResult] = useState<AdGenerateResult | null>(null);

  // Library state
  const [drafts, setDrafts] = useState<AdCopyDraft[]>([]);
  const [draftsLoading, setDraftsLoading] = useState(true);
  const [draftsError, setDraftsError] = useState<string | null>(null);

  // Toast
  const [toast, setToast] = useState<string | null>(null);

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(null), 2800);
  }

  const fetchDrafts = useCallback(async () => {
    setDraftsLoading(true);
    setDraftsError(null);
    try {
      const data = await listDrafts();
      setDrafts(data);
    } catch (err: unknown) {
      setDraftsError(err instanceof Error ? err.message : 'Taslaklar yüklenemedi');
    } finally {
      setDraftsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDrafts();
  }, [fetchDrafts]);

  async function handleGenerate() {
    if (!product.trim()) return;
    setGenerating(true);
    setGenerateError(null);
    setResult(null);
    try {
      const keywords = keywordsInput
        .split(',')
        .map((k) => k.trim())
        .filter(Boolean);
      const res = await generateAdCopy({
        platform,
        product: product.trim(),
        value_prop: valueProp.trim() || undefined,
        tone,
        keywords: keywords.length > 0 ? keywords : undefined,
        audience: audience.trim() || undefined,
        n_variants: nVariants,
      });
      setResult(res);
    } catch (err: unknown) {
      setGenerateError(err instanceof Error ? err.message : 'Üretim başarisiz oldu');
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className={styles.shell}>
      <AppNav />

      <main className={styles.main}>
        {/* Page header */}
        <div>
          <h1 className={styles.pageTitle}>Reklam Metni Stüdyosu</h1>
          <p className={styles.pageSubtitle}>
            Marka diliyle Google, Meta ve TikTok reklam metinleri üretin; karakter
            sınırlarına uygunluğu anında görün ve taslak kütüphanenize kaydedin.
          </p>
        </div>

        {/* Workspace: form + results */}
        <div className={styles.workspace}>
          {/* Brief form */}
          <div className={styles.formCard}>
            <div className={styles.formCardTitle}>Brifing</div>

            {/* Platform selector */}
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Platform</label>
              <div className={styles.platformGroup}>
                {AD_PLATFORMS.map((p) => (
                  <button
                    key={p}
                    type="button"
                    className={`${styles.platformBtn} ${platform === p ? styles.platformBtnActive : ''}`}
                    onClick={() => setPlatform(p)}
                  >
                    {p === 'google_ads' ? 'Google' : p === 'meta_ads' ? 'Meta' : 'TikTok'}
                  </button>
                ))}
              </div>
            </div>

            {/* Product */}
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="adstudio-product">
                Ürün / Hizmet<span className={styles.fieldRequired}>*</span>
              </label>
              <input
                id="adstudio-product"
                type="text"
                className={styles.fieldInput}
                value={product}
                onChange={(e) => setProduct(e.target.value)}
                placeholder="örn. Kablosuz Kulaklık"
                autoComplete="off"
              />
            </div>

            {/* Value prop */}
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="adstudio-valueprop">
                Değer Önerisi
              </label>
              <textarea
                id="adstudio-valueprop"
                className={styles.fieldTextarea}
                value={valueProp}
                onChange={(e) => setValueProp(e.target.value)}
                placeholder="Ürününüzün en önemli avantajı nedir?"
                rows={2}
              />
            </div>

            {/* Tone */}
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="adstudio-tone">
                Ton
              </label>
              <select
                id="adstudio-tone"
                className={styles.fieldSelect}
                value={tone}
                onChange={(e) => setTone(e.target.value as AdTone)}
              >
                {AD_TONES.map((t) => (
                  <option key={t} value={t}>
                    {TONE_LABELS[t]}
                  </option>
                ))}
              </select>
            </div>

            {/* Keywords */}
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="adstudio-keywords">
                Anahtar Kelimeler
              </label>
              <input
                id="adstudio-keywords"
                type="text"
                className={styles.fieldInput}
                value={keywordsInput}
                onChange={(e) => setKeywordsInput(e.target.value)}
                placeholder="virgülle ayırın: indirim, kargo, fiyat"
              />
              <span className={styles.fieldHint}>Virgülle ayrılmış kelimeler</span>
            </div>

            {/* Audience */}
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel} htmlFor="adstudio-audience">
                Hedef Kitle
              </label>
              <input
                id="adstudio-audience"
                type="text"
                className={styles.fieldInput}
                value={audience}
                onChange={(e) => setAudience(e.target.value)}
                placeholder="örn. 25-40 yaş, teknoloji meraklısı"
              />
            </div>

            {/* n_variants */}
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Varyant Sayısı</label>
              <div className={styles.variantCountRow}>
                {[2, 3, 4].map((n) => (
                  <button
                    key={n}
                    type="button"
                    className={`${styles.variantCountBtn} ${nVariants === n ? styles.variantCountBtnActive : ''}`}
                    onClick={() => setNVariants(n)}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            {/* Error */}
            {generateError && (
              <div className={styles.formError}>{generateError}</div>
            )}

            {/* Submit */}
            <button
              type="button"
              className={styles.generateBtn}
              onClick={handleGenerate}
              disabled={generating || !product.trim()}
            >
              {generating ? 'Üretiliyor...' : 'Üret'}
            </button>
          </div>

          {/* Results */}
          <div className={styles.resultsPanel}>
            {generating ? (
              <div className={styles.loadingText}>Reklam metinleri üretiliyor...</div>
            ) : result ? (
              <>
                <div className={styles.resultsHeader}>
                  <span className={styles.resultsPlatformLabel}>
                    {result.platform_label || PLATFORM_LABELS[result.platform]}
                  </span>
                  <span
                    className={`${styles.sourceChip} ${
                      result.source === 'ai' ? styles.sourceChipAi : styles.sourceChipTemplate
                    }`}
                  >
                    {result.source === 'ai' ? 'Yapay zeka' : 'Otomatik'}
                  </span>
                  <span className={styles.sourceChip} style={{ background: 'transparent', color: 'var(--color-text-muted)' }}>
                    {result.tone_label || TONE_LABELS[result.tone]}
                  </span>
                </div>

                {result.variants.map((v) => (
                  <VariantCard
                    key={v.index}
                    variant={v}
                    product={product}
                    result={result}
                    onSaved={fetchDrafts}
                    onToast={showToast}
                  />
                ))}
              </>
            ) : (
              <div className={styles.resultsEmpty}>
                Brifing formunu doldurun ve "Üret" butonuna basın. Üretilen reklam
                metinleri burada görünecek.
              </div>
            )}
          </div>
        </div>

        {/* Draft library */}
        <LibrarySection
          drafts={drafts}
          loading={draftsLoading}
          error={draftsError}
          onRefresh={fetchDrafts}
          onToast={showToast}
        />
      </main>

      {/* Toast notification */}
      {toast && <div className={styles.toast}>{toast}</div>}
    </div>
  );
}
