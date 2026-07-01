'use client';

// Shared "Yazdır / PDF" button. Triggers the browser's print dialog, from which
// the user can Save-as-PDF. Zero dependencies: the branded output is produced by
// the global `@media print` rules (see globals.css) that strip app chrome.
//
// The button carries the global `print-hide` class so it never appears in the
// printed output itself. Pass a `className` to match the host page's button
// styling.

interface PrintButtonProps {
  className?: string;
  label?: string;
}

export default function PrintButton({
  className = '',
  label = 'Yazdır / PDF',
}: PrintButtonProps) {
  function handlePrint() {
    if (typeof window !== 'undefined') window.print();
  }
  return (
    <button
      type="button"
      className={`${className} print-hide`.trim()}
      onClick={handlePrint}
      aria-label="Raporu yazdır veya PDF olarak kaydet"
    >
      {label}
    </button>
  );
}
