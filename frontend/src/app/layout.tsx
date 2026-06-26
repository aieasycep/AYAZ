import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AYAZ - Dijital Pazarlama Paneli',
  description: 'Tüm dijital pazarlama araçlarınız tek bir panelde.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="tr">
      <body>{children}</body>
    </html>
  );
}
