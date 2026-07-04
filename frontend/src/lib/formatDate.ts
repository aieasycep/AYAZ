// Türkçe tarih biçimlendirme — kullanıcıya dönük tüm tarihler buradan.
// Ham ISO ("2026-07-01") arayüze render EDİLMEMELİ; TR "1 Tem 2026" gösterilir.

/** "2026-07-01" → "1 Tem 2026". Geçersiz girdiyi olduğu gibi döndürür. */
export function formatDateTR(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('tr-TR', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

/** "2026-07-01" — "2026-07-31" → "1 Tem 2026 – 31 Tem 2026". */
export function formatDateRangeTR(
  from: string | null | undefined,
  to: string | null | undefined,
): string {
  const a = formatDateTR(from);
  const b = formatDateTR(to);
  if (a && b) return `${a} – ${b}`;
  return a || b;
}
