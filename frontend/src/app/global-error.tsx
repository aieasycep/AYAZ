'use client';

interface GlobalErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function GlobalError({ error, reset }: GlobalErrorProps) {
  return (
    <html lang="tr">
      <body
        style={{
          minHeight: '100vh',
          background: '#f5f6fa',
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '2rem',
          margin: 0,
        }}
      >
        <div
          style={{
            background: '#ffffff',
            border: '1px solid #e2e5ef',
            borderRadius: '10px',
            boxShadow: '0 4px 16px rgba(0,0,0,0.10)',
            padding: '2.5rem 2rem',
            maxWidth: '460px',
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '1rem',
            textAlign: 'center',
          }}
        >
          <div
            aria-hidden="true"
            style={{
              width: '3rem',
              height: '3rem',
              borderRadius: '50%',
              background: 'rgba(239,68,68,0.1)',
              color: '#ef4444',
              fontSize: '1.5rem',
              fontWeight: 700,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            !
          </div>
          <h1
            style={{
              fontSize: '1.25rem',
              fontWeight: 700,
              color: '#1a1d2e',
              margin: 0,
            }}
          >
            Uygulama başlatılamadı
          </h1>
          <p
            style={{
              fontSize: '0.9375rem',
              color: '#6b7280',
              lineHeight: 1.6,
              maxWidth: '360px',
              margin: 0,
            }}
          >
            Beklenmedik bir hata nedeniyle uygulama yüklenemedi. Lütfen sayfayı
            yenileyerek tekrar deneyin.
          </p>
          {error.digest && (
            <p
              style={{
                fontSize: '0.75rem',
                color: '#6b7280',
                fontFamily: 'monospace',
                margin: 0,
              }}
            >
              Hata kodu: {error.digest}
            </p>
          )}
          <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', justifyContent: 'center', marginTop: '0.5rem' }}>
            <button
              onClick={reset}
              style={{
                background: '#3b5bdb',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                padding: '0.625rem 1.375rem',
                fontSize: '0.9375rem',
                fontWeight: 600,
                cursor: 'pointer',
                fontFamily: 'inherit',
              }}
            >
              Tekrar dene
            </button>
            <a
              href="/"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                border: '1.5px solid #e2e5ef',
                borderRadius: '8px',
                padding: '0.625rem 1.375rem',
                fontSize: '0.9375rem',
                fontWeight: 600,
                color: '#1a1d2e',
                textDecoration: 'none',
              }}
            >
              Ana sayfaya dön
            </a>
          </div>
        </div>
      </body>
    </html>
  );
}
