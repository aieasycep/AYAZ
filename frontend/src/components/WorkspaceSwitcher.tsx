'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import {
  getWorkspaces,
  switchWorkspace,
  setToken,
  type Workspace,
} from '@/lib/workspaces-api';
import styles from './WorkspaceSwitcher.module.css';

export default function WorkspaceSwitcher() {
  const router = useRouter();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [current, setCurrent] = useState<Workspace | null>(null);
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getWorkspaces()
      .then((list) => {
        setWorkspaces(list);
        // The current workspace is the one whose role is owner, or first in list
        // Backend doesn't flag "current" in the list, so we store nothing here;
        // we rely on GET /workspaces/current from the page. For the switcher we
        // just show the list. Mark none as selected — nav link shows "Çalışma Alanları"
        if (list.length > 0) setCurrent(list[0]);
      })
      .catch(() => {
        // Silently ignore — switcher is non-critical
      });
  }, []);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  async function handleSwitch(ws: Workspace) {
    if (switching) return;
    setSwitching(true);
    setOpen(false);
    try {
      const res = await switchWorkspace(ws.id);
      setToken(res.access_token);
      // Reload to re-initialise all data under the new tenant context
      window.location.href = '/dashboard';
    } catch {
      setSwitching(false);
    }
  }

  function handleNewWorkspace() {
    setOpen(false);
    router.push('/workspaces');
  }

  if (workspaces.length === 0) return null;

  return (
    <div className={styles.wrapper} ref={dropdownRef}>
      <button
        className={styles.trigger}
        onClick={() => setOpen((v) => !v)}
        disabled={switching}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className={styles.triggerName}>
          {switching ? 'Geçiş yapılıyor...' : (current?.name ?? 'Çalışma Alanı')}
        </span>
        <svg
          className={`${styles.chevron} ${open ? styles.chevronOpen : ''}`}
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          aria-hidden="true"
        >
          <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className={styles.dropdown} role="listbox">
          <div className={styles.dropdownHeader}>Çalışma Alanları</div>
          {workspaces.map((ws) => (
            <button
              key={ws.id}
              className={`${styles.dropdownItem} ${ws.id === current?.id ? styles.dropdownItemCurrent : ''}`}
              onClick={() => handleSwitch(ws)}
              role="option"
              aria-selected={ws.id === current?.id}
            >
              <span className={styles.itemName}>{ws.name}</span>
              <span className={styles.itemRole}>{roleLabel(ws.role)}</span>
            </button>
          ))}
          <div className={styles.dropdownDivider} />
          <button className={styles.dropdownItemNew} onClick={handleNewWorkspace}>
            + Yeni çalışma alanı
          </button>
        </div>
      )}
    </div>
  );
}

function roleLabel(role: string): string {
  switch (role) {
    case 'owner': return 'Sahibi';
    case 'admin': return 'Yönetici';
    case 'member': return 'Üye';
    default: return role;
  }
}
