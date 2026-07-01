'use client';

import { useEffect } from 'react';

/**
 * Registers the service worker for offline shell + static caching.
 * This must be a Client Component so it can run browser-side code.
 * Rendered inside RootLayout with no visual output.
 */
export default function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (typeof window === 'undefined' || !('serviceWorker' in navigator)) return;

    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .catch((err) => {
        // Non-fatal — app works without SW, just no offline support
        console.warn('[SW] Registration failed:', err);
      });
  }, []);

  return null;
}
