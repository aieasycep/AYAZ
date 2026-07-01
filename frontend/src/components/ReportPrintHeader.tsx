// Branded header shown ONLY in the printed / PDF output (hidden on screen via the
// global `.print-only` utility). Uses inline styles so it renders identically in
// print without depending on any CSS-module class. Reusable across any report
// surface that wants a branded PDF.

interface ReportPrintHeaderProps {
  title: string;
  subtitle?: string;
}

export default function ReportPrintHeader({ title, subtitle }: ReportPrintHeaderProps) {
  return (
    <div
      className="print-only"
      style={{
        marginBottom: '16px',
        paddingBottom: '10px',
        borderBottom: '2px solid #111827',
      }}
    >
      <div
        style={{
          fontSize: '20px',
          fontWeight: 700,
          letterSpacing: '0.5px',
          color: '#111827',
        }}
      >
        AYAZ
      </div>
      <div style={{ fontSize: '16px', fontWeight: 600, marginTop: '4px', color: '#111827' }}>
        {title}
      </div>
      {subtitle && (
        <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '2px' }}>{subtitle}</div>
      )}
    </div>
  );
}
