import type { Metadata, Viewport } from 'next';
import './globals.css';
import ServiceWorkerRegistrar from '@/components/ServiceWorkerRegistrar';
import InstallPrompt from '@/components/InstallPrompt';
import ThemeProvider from '@/components/ThemeProvider';

export const metadata: Metadata = {
  title: 'AYAZ - Dijital Pazarlama Paneli',
  description: 'Tüm dijital pazarlama araçlarınız tek bir panelde — reklam, analiz, içgörü ve daha fazlası.',
  manifest: '/manifest.json',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'AYAZ',
  },
  icons: {
    icon: [
      { url: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
      { url: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
    ],
    apple: [
      { url: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
    ],
  },
  formatDetection: {
    telephone: false,
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  minimumScale: 1,
  viewportFit: 'cover',
  themeColor: '#1a1d2e',
};

/**
 * Inline script injected into <head> BEFORE any CSS or React hydration.
 * Reads localStorage and sets data-theme on <html> immediately, preventing
 * a flash-of-wrong-theme (FOUC) on page load.
 */
const THEME_SCRIPT = `(function(){
  try{
    var t=localStorage.getItem('ayaz_theme');
    if(t==='light'||t==='dark'||t==='system'){
      document.documentElement.dataset.theme=t;
    } else {
      document.documentElement.dataset.theme='system';
    }
  }catch(e){}
})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="tr" suppressHydrationWarning>
      {/* suppressHydrationWarning: THEME_SCRIPT <html>'e data-theme'i hydration'dan
          önce ekler (FOUC önleme); sunucu/istemci attribute farkı beklenir ve React
          uyarısı bastırılır — yalnız bu <html> öğesini kapsar. */}
      <head>
        {/* FOUC prevention: set data-theme before first paint */}
        {/* eslint-disable-next-line react/no-danger */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          {children}
        </ThemeProvider>
        <ServiceWorkerRegistrar />
        <InstallPrompt />
      </body>
    </html>
  );
}
