'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { getToken } from '@/lib/api';
import {
  getWorkspaces,
  getCurrentWorkspace,
  patchCurrentWorkspace,
  getMembers,
  inviteMember,
  removeMember,
  patchMember,
  switchWorkspace,
  createWorkspace,
  setToken,
  type Workspace,
  type WorkspaceMember,
  type WorkspaceRole,
} from '@/lib/workspaces-api';
import AppNav from '@/components/AppNav';
import styles from './workspaces.module.css';

// ─── Role helpers ─────────────────────────────────────────────────────────────

function roleLabel(role: WorkspaceRole): string {
  switch (role) {
    case 'owner': return 'Sahibi';
    case 'admin': return 'Yönetici';
    case 'member': return 'Üye';
  }
}

function roleBadgeClass(role: WorkspaceRole): string {
  switch (role) {
    case 'owner': return styles.roleOwner;
    case 'admin': return styles.roleAdmin;
    case 'member': return styles.roleMember;
  }
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function WorkspacesPage() {
  const router = useRouter();

  useEffect(() => {
    if (!getToken()) {
      router.replace('/login');
    }
  }, [router]);

  return (
    <div className={styles.shell}>
      <AppNav />
      <main className={styles.main}>
        <div className={styles.pageHeader}>
          <div>
            <h1 className={styles.pageTitle}>Çalışma Alanları</h1>
            <p className={styles.pageSubtitle}>
              Marka ayarları, ekip üyeleri ve çalışma alanı yönetimi
            </p>
          </div>
        </div>

        <BrandSection />
        <MembersSection />
        <WorkspacesSection />
      </main>
    </div>
  );
}

// ─── Marka (White-label) Section ──────────────────────────────────────────────

function BrandSection() {
  const [current, setCurrent] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Form state
  const [brandName, setBrandName] = useState('');
  const [logoUrl, setLogoUrl] = useState('');
  const [primaryColor, setPrimaryColor] = useState('#3b5bdb');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [saveSuccess, setSaveSuccess] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const ws = await getCurrentWorkspace();
      setCurrent(ws);
      setBrandName(ws.brand_name ?? '');
      setLogoUrl(ws.logo_url ?? '');
      setPrimaryColor(ws.primary_color ?? '#3b5bdb');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError('');
    setSaveSuccess(false);
    try {
      const updated = await patchCurrentWorkspace({
        brand_name: brandName || null,
        logo_url: logoUrl || null,
        primary_color: primaryColor || null,
      });
      setCurrent(updated);
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : 'Kayıt başarısız');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <div className={styles.sectionTitle}>Marka (White-label) Ayarları</div>
          <div className={styles.sectionSubtitle}>
            Çalışma alanınızın görünümünü özelleştirin
          </div>
        </div>
      </div>

      {loading ? (
        <div className={styles.stateBox}>
          <p className={styles.muted}>Yükleniyor...</p>
        </div>
      ) : error ? (
        <div className={styles.stateBox}>
          <p className={styles.errorText}>{error}</p>
          <button className={styles.retryBtn} onClick={load}>Tekrar Dene</button>
        </div>
      ) : (
        <>
          <form onSubmit={handleSave} className={styles.brandForm}>
            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Marka Adı</label>
              <input
                type="text"
                className={styles.fieldInput}
                placeholder={current?.name ?? 'Marka adı'}
                value={brandName}
                onChange={(e) => setBrandName(e.target.value)}
                disabled={saving}
              />
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Logo URL</label>
              <input
                type="url"
                className={styles.fieldInput}
                placeholder="https://cdn.example.com/logo.png"
                value={logoUrl}
                onChange={(e) => setLogoUrl(e.target.value)}
                disabled={saving}
              />
            </div>

            <div className={styles.fieldGroup}>
              <label className={styles.fieldLabel}>Ana Renk</label>
              <div className={styles.colorRow}>
                <input
                  type="color"
                  className={styles.colorSwatch}
                  value={primaryColor}
                  onChange={(e) => setPrimaryColor(e.target.value)}
                  disabled={saving}
                  aria-label="Renk seç"
                />
                <input
                  type="text"
                  className={styles.colorInput}
                  value={primaryColor}
                  onChange={(e) => setPrimaryColor(e.target.value)}
                  disabled={saving}
                  placeholder="#3b5bdb"
                  maxLength={7}
                />
              </div>
            </div>

            <button type="submit" className={styles.saveBtn} disabled={saving}>
              {saving ? 'Kaydediliyor...' : 'Kaydet'}
            </button>
          </form>

          {saveSuccess && (
            <p className={styles.formSuccess}>Marka ayarları kaydedildi.</p>
          )}
          {saveError && (
            <p className={styles.formError}>{saveError}</p>
          )}

          {/* Live preview */}
          <div className={styles.brandPreview}>
            <div className={styles.brandPreviewLabel}>Ön İzleme</div>
            <span
              className={styles.brandChip}
              style={{ background: primaryColor || '#3b5bdb' }}
            >
              {logoUrl && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={logoUrl}
                  alt="logo"
                  className={styles.brandChipLogo}
                  onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                />
              )}
              {brandName || current?.name || 'Marka Adı'}
            </span>
          </div>
        </>
      )}
    </div>
  );
}

// ─── Members Section ───────────────────────────────────────────────────────────

function MembersSection() {
  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Invite form
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState<WorkspaceRole>('member');
  const [inviting, setInviting] = useState(false);
  const [inviteError, setInviteError] = useState('');
  const [inviteSuccess, setInviteSuccess] = useState(false);

  // Per-row busy state
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const list = await getMembers();
      setMembers(list);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleRoleChange(member: WorkspaceMember, newRole: WorkspaceRole) {
    // Guard: can't demote the last owner
    if (member.role === 'owner' && newRole !== 'owner') {
      const ownerCount = members.filter((m) => m.role === 'owner').length;
      if (ownerCount <= 1) {
        alert('En az bir sahip olmalıdır. Rol değiştirilemez.');
        return;
      }
    }
    setBusyId(member.membership_id);
    try {
      const updated = await patchMember(member.membership_id, newRole);
      // Backend returns {membership_id, user_id, tenant_id, role} without `email`;
      // merge to preserve existing fields (email, etc.) for display.
      setMembers((prev) =>
        prev.map((m) =>
          m.membership_id === updated.membership_id
            ? { ...m, role: updated.role }
            : m,
        )
      );
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Rol değiştirilemedi');
    } finally {
      setBusyId(null);
    }
  }

  async function handleRemove(member: WorkspaceMember) {
    // Guard: can't remove last owner
    if (member.role === 'owner') {
      const ownerCount = members.filter((m) => m.role === 'owner').length;
      if (ownerCount <= 1) {
        alert('En az bir sahip olmalıdır. Üye kaldırılamaz.');
        return;
      }
    }
    if (!confirm(`${member.email} adlı üyeyi kaldırmak istiyor musunuz?`)) return;
    setBusyId(member.membership_id);
    try {
      await removeMember(member.membership_id);
      setMembers((prev) => prev.filter((m) => m.membership_id !== member.membership_id));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Üye kaldırılamadı');
    } finally {
      setBusyId(null);
    }
  }

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    setInviting(true);
    setInviteError('');
    setInviteSuccess(false);
    try {
      await inviteMember(inviteEmail, inviteRole);
      setInviteSuccess(true);
      setInviteEmail('');
      setInviteRole('member');
      setTimeout(() => setInviteSuccess(false), 4000);
    } catch (err: unknown) {
      setInviteError(err instanceof Error ? err.message : 'Davet gönderilemedi');
    } finally {
      setInviting(false);
    }
  }

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <div className={styles.sectionTitle}>Ekip Üyeleri</div>
          <div className={styles.sectionSubtitle}>
            Çalışma alanına erişimi yönetin
          </div>
        </div>
      </div>

      {loading ? (
        <div className={styles.stateBox}>
          <p className={styles.muted}>Yükleniyor...</p>
        </div>
      ) : error ? (
        <div className={styles.stateBox}>
          <p className={styles.errorText}>{error}</p>
          <button className={styles.retryBtn} onClick={load}>Tekrar Dene</button>
        </div>
      ) : (
        <>
          {members.length === 0 ? (
            <div className={styles.stateBox}>
              <p className={styles.muted}>Henüz üye yok.</p>
            </div>
          ) : (
            <div className={styles.membersList}>
              {members.map((member) => {
                const busy = busyId === member.membership_id;
                return (
                  <div key={member.membership_id} className={styles.memberRow}>
                    <span className={styles.memberEmail}>{member.email}</span>
                    <span className={`${styles.roleBadge} ${roleBadgeClass(member.role)}`}>
                      {roleLabel(member.role)}
                    </span>
                    <select
                      className={styles.roleSelect}
                      value={member.role}
                      onChange={(e) => handleRoleChange(member, e.target.value as WorkspaceRole)}
                      disabled={busy}
                      aria-label={`${member.email} rolü`}
                    >
                      <option value="owner">Sahibi</option>
                      <option value="admin">Yönetici</option>
                      <option value="member">Üye</option>
                    </select>
                    <button
                      className={styles.removeBtn}
                      onClick={() => handleRemove(member)}
                      disabled={busy}
                    >
                      Kaldır
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          <div className={styles.inviteFormWrapper}>
            <div className={styles.inviteFormTitle}>Üye Davet Et</div>
            <form onSubmit={handleInvite} className={styles.inviteForm}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>E-posta</label>
                <input
                  type="email"
                  className={styles.fieldInput}
                  placeholder="ornek@sirket.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  required
                  disabled={inviting}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Rol</label>
                <select
                  className={styles.fieldSelect}
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as WorkspaceRole)}
                  disabled={inviting}
                >
                  <option value="admin">Yönetici</option>
                  <option value="member">Üye</option>
                </select>
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>&nbsp;</label>
                <button type="submit" className={styles.saveBtn} disabled={inviting}>
                  {inviting ? 'Gönderiliyor...' : 'Davet Gönder'}
                </button>
              </div>
            </form>
            {inviteSuccess && (
              <p className={styles.inviteSuccess}>Davet gönderildi.</p>
            )}
            {inviteError && (
              <p className={styles.formError}>{inviteError}</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Workspaces List Section ───────────────────────────────────────────────────

function WorkspacesSection() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [switchingId, setSwitchingId] = useState<string | null>(null);

  // Create form
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const list = await getWorkspaces();
      setWorkspaces(list);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Yüklenemedi');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleSwitch(ws: Workspace) {
    setSwitchingId(ws.id);
    try {
      const res = await switchWorkspace(ws.id);
      setToken(res.access_token);
      window.location.href = '/dashboard';
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Geçiş başarısız');
      setSwitchingId(null);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    setCreateError('');
    try {
      const ws = await createWorkspace(newName.trim());
      setWorkspaces((prev) => [...prev, ws]);
      setNewName('');
    } catch (err: unknown) {
      setCreateError(err instanceof Error ? err.message : 'Oluşturulamadı');
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <div>
          <div className={styles.sectionTitle}>Çalışma Alanlarım</div>
          <div className={styles.sectionSubtitle}>
            Tüm çalışma alanlarınız ve rolleriniz
          </div>
        </div>
      </div>

      {loading ? (
        <div className={styles.stateBox}>
          <p className={styles.muted}>Yükleniyor...</p>
        </div>
      ) : error ? (
        <div className={styles.stateBox}>
          <p className={styles.errorText}>{error}</p>
          <button className={styles.retryBtn} onClick={load}>Tekrar Dene</button>
        </div>
      ) : (
        <>
          {workspaces.length === 0 ? (
            <div className={styles.stateBox}>
              <p className={styles.muted}>Henüz çalışma alanı yok.</p>
            </div>
          ) : (
            <div className={styles.workspacesList}>
              {workspaces.map((ws) => {
                const busy = switchingId === ws.id;
                return (
                  <div key={ws.id} className={styles.workspaceRow}>
                    <span className={styles.workspaceName}>{ws.name}</span>
                    <span className={`${styles.roleBadge} ${roleBadgeClass(ws.role)}`}>
                      {roleLabel(ws.role)}
                    </span>
                    <button
                      className={styles.switchBtn}
                      onClick={() => handleSwitch(ws)}
                      disabled={busy || switchingId !== null}
                    >
                      {busy ? 'Geçiş yapılıyor...' : 'Geç'}
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          <div className={styles.createFormWrapper}>
            <div className={styles.createFormTitle}>Yeni Çalışma Alanı</div>
            <form onSubmit={handleCreate} className={styles.createForm}>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>Çalışma Alanı Adı</label>
                <input
                  type="text"
                  className={styles.fieldInput}
                  placeholder="Ajans Adı"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  required
                  disabled={creating}
                />
              </div>
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>&nbsp;</label>
                <button type="submit" className={styles.saveBtn} disabled={creating || !newName.trim()}>
                  {creating ? 'Oluşturuluyor...' : 'Oluştur'}
                </button>
              </div>
            </form>
            {createError && (
              <p className={styles.formError}>{createError}</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}
