'use client';

import { useEffect, useState } from 'react';
import styles from './InstallPrompt.module.css';

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

/**
 * Captures the browser's beforeinstallprompt event and shows a small,
 * dismissible "Ana ekrana ekle" banner at the bottom of the screen.
 * Only visible when the app is installable (not already installed as PWA).
 */
export default function InstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    // Don't show if already dismissed in this session
    if (sessionStorage.getItem('pwa-prompt-dismissed')) {
      return;
    }

    function handleBeforeInstall(e: Event) {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
      // Small delay so it doesn't flash immediately on load
      setTimeout(() => setVisible(true), 2000);
    }

    window.addEventListener('beforeinstallprompt', handleBeforeInstall);
    return () => window.removeEventListener('beforeinstallprompt', handleBeforeInstall);
  }, []);

  async function handleInstall() {
    if (!deferredPrompt) return;
    await deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      setDeferredPrompt(null);
      setVisible(false);
    }
  }

  function handleDismiss() {
    setDismissed(true);
    setVisible(false);
    sessionStorage.setItem('pwa-prompt-dismissed', '1');
  }

  if (!visible || dismissed || !deferredPrompt) return null;

  return (
    <div className={styles.banner} role="banner" aria-label="Uygulamayı yükle">
      <div className={styles.icon} aria-hidden="true">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="5" y="2" width="14" height="20" rx="2" ry="2"/>
          <circle cx="12" cy="17" r="1" fill="currentColor" stroke="none"/>
        </svg>
      </div>
      <div className={styles.text}>
        <strong>Uygulamayı Yükle</strong>
        <span>Ana ekrana ekle, çevrimdışı kullan</span>
      </div>
      <button className={styles.installBtn} onClick={handleInstall} aria-label="Ana ekrana ekle">
        Yükle
      </button>
      <button className={styles.dismissBtn} onClick={handleDismiss} aria-label="Kapat">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
          <line x1="18" y1="6" x2="6" y2="18"/>
          <line x1="6" y1="6" x2="18" y2="18"/>
        </svg>
      </button>
    </div>
  );
}
