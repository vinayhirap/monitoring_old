"use client";

import { useState, useEffect } from "react";
import useSWR from "swr";
import { authedFetch, authedFetcher, getUser } from "@/lib/auth";
import { Panel, Stat } from "@/components/Panel";
import { ErrorState, EmptyState, InfoBanner, LoadingSkeleton } from "@/components/States";
import {
  Users as UsersIcon, ShieldCheck, ShieldOff, UserPlus, Search, Trash2, Key,
  CheckCircle2, XCircle, ChevronRight, X, Filter, Crown, Activity, AlertTriangle, RefreshCw,
} from "lucide-react";
import clsx from "clsx";


type UserRow = {
  id: number;
  email: string;
  full_name: string | null;
  role: "OWNER" | "ADMIN" | "ANALYST" | "USER";
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  last_login_at: string | null;
  last_seen_at: string | null;
  last_login_ip: string | null;
  subscription: {
    tier: string;
    is_active: boolean;
    valid_until: string | null;
    telegram_username: string | null;
  };
};


type Tab = "users" | "subscriptions" | "audit" | "settings";


export default function AdminUsersPage() {
  const me = getUser();
  const [tab, setTab] = useState<Tab>("users");

  if (me && !me.is_superuser) {
    return (
      <ErrorState
        title="Admin only"
        message="You need an admin role to view this page."
      />
    );
  }

  return (
    <div className="space-y-4">
      {/* Header + tabs */}
      <div className="bg-bg-surface border border-bg-line rounded-lg overflow-hidden">
        <div className="px-5 py-4 border-b border-bg-line">
          <h1 className="text-xl font-bold text-text-primary flex items-center gap-2">
            <UsersIcon className="w-5 h-5 text-accent-amber" />
            User Management
          </h1>
          <p className="text-[11px] text-text-muted mt-1">
            Manage users, subscriptions, and audit history. OptScale-style RBAC with OWNER / ADMIN / ANALYST / USER roles.
          </p>
        </div>
        <nav className="flex border-b border-bg-line bg-bg-panel2/30">
          {(["users", "subscriptions", "audit", "settings"] as Tab[]).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={clsx(
                "px-5 py-2.5 text-[12px] font-semibold capitalize border-b-2 transition-colors",
                tab === t
                  ? "border-accent-amber text-accent-amber"
                  : "border-transparent text-text-muted hover:text-text-primary"
              )}>
              {t === "audit" ? "Audit Log" : t}
            </button>
          ))}
        </nav>
      </div>

      {tab === "users"         && <UsersTab />}
      {tab === "subscriptions" && <SubscriptionsTab />}
      {tab === "audit"         && <AuditTab />}
      {tab === "settings"      && <SettingsTab />}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// TAB 1 — Users
// ═══════════════════════════════════════════════════════════════════════════

function UsersTab() {
  const me = getUser();
  const [q, setQ] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("");
  const [activeFilter, setActiveFilter] = useState<string>("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [drawerUserId, setDrawerUserId] = useState<number | null>(null);
  const [showInvite, setShowInvite] = useState(false);

  const PAGE_SIZE = 25;
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE),
  });
  if (q)            params.set("q", q);
  if (roleFilter)   params.set("role", roleFilter);
  if (activeFilter) params.set("active", activeFilter);

  const { data, error, mutate, isLoading } = useSWR<any>(
    `/api/admin/users?${params}`, authedFetcher,
    { refreshInterval: 60_000, revalidateOnFocus: false }
  );

  function toggleSel(id: number) {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  }

  async function bulkAction(action: string, role?: string) {
    if (selected.size === 0) return;
    const confirm_msg = action === "delete"
      ? `Delete ${selected.size} user(s)? This cannot be undone.`
      : `${action} ${selected.size} user(s)?`;
    if (!window.confirm(confirm_msg)) return;
    try {
      const res = await authedFetch("/api/admin/users/bulk", {
        method: "POST",
        body: JSON.stringify({ user_ids: Array.from(selected), action, role }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail);
      }
      setSelected(new Set());
      mutate();
    } catch (e: any) {
      alert("Bulk action failed: " + e.message);
    }
  }

  return (
    <>
      {/* Toolbar */}
      <div className="bg-bg-surface border border-bg-line rounded-lg p-3 flex flex-wrap items-center gap-3">
        <div className="flex-1 min-w-[200px] relative">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-text-muted" />
          <input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }}
            placeholder="Search email or name…"
            className="w-full pl-7 pr-3 py-1.5 text-[12px] rounded border border-bg-line bg-bg-base focus:border-accent-amber" />
        </div>
        <select value={roleFilter} onChange={(e) => { setRoleFilter(e.target.value); setPage(0); }}
          className="text-[11px] px-2 py-1.5 rounded border border-bg-line bg-bg-base">
          <option value="">All roles</option>
          <option value="OWNER">OWNER</option>
          <option value="ADMIN">ADMIN</option>
          <option value="ANALYST">ANALYST</option>
          <option value="USER">USER</option>
        </select>
        <select value={activeFilter} onChange={(e) => { setActiveFilter(e.target.value); setPage(0); }}
          className="text-[11px] px-2 py-1.5 rounded border border-bg-line bg-bg-base">
          <option value="">All status</option>
          <option value="true">Active</option>
          <option value="false">Disabled</option>
        </select>
        <button onClick={() => mutate()}
          className="text-[11px] px-2 py-1.5 rounded border border-bg-line hover:border-accent-amber flex items-center gap-1">
          <RefreshCw className={clsx("w-3 h-3", isLoading && "animate-spin")} />
          Refresh
        </button>
        <button onClick={() => setShowInvite(true)}
          className="text-[11px] px-3 py-1.5 rounded bg-accent-amber text-white font-bold hover:opacity-90 flex items-center gap-1">
          <UserPlus className="w-3 h-3" />
          Invite user
        </button>
      </div>

      {/* Bulk action bar (sticky when selection > 0) */}
      {selected.size > 0 && (
        <div className="bg-accent-amber/10 border border-accent-amber/40 rounded-lg p-3 flex items-center gap-3">
          <span className="text-[12px] font-bold text-accent-amber">
            {selected.size} selected
          </span>
          <button onClick={() => bulkAction("activate")}
            className="text-[11px] px-2 py-1 rounded border border-accent-green/40 text-accent-green hover:bg-accent-green/10">
            Activate
          </button>
          <button onClick={() => bulkAction("deactivate")}
            className="text-[11px] px-2 py-1 rounded border border-accent-amber/40 text-accent-amber hover:bg-accent-amber/10">
            Deactivate
          </button>
          <select onChange={(e) => e.target.value && bulkAction("set_role", e.target.value)}
            className="text-[11px] px-2 py-1 rounded border border-bg-line bg-bg-base">
            <option value="">Change role…</option>
            <option value="USER">USER</option>
            <option value="ANALYST">ANALYST</option>
            <option value="ADMIN">ADMIN</option>
          </select>
          <button onClick={() => bulkAction("delete")}
            className="text-[11px] px-2 py-1 rounded border border-accent-red/40 text-accent-red hover:bg-accent-red/10">
            <Trash2 className="w-3 h-3 inline mr-1" />Delete
          </button>
          <button onClick={() => setSelected(new Set())}
            className="ml-auto text-[11px] text-text-muted hover:text-text-primary">Clear</button>
        </div>
      )}

      {error && <ErrorState message={String(error.message)} onRetry={() => mutate()} />}
      {isLoading && !data && <LoadingSkeleton lines={6} />}

      {/* Users table */}
      {data && (
        <div className="bg-bg-surface border border-bg-line rounded-lg overflow-hidden">
          <table className="w-full text-[11px]">
            <thead className="bg-bg-panel2/50">
              <tr>
                <th className="w-8 px-3 py-2 text-left">
                  <input type="checkbox"
                    checked={selected.size > 0 && data.users.every((u: UserRow) => selected.has(u.id))}
                    onChange={(e) => setSelected(e.target.checked
                      ? new Set(data.users.map((u: UserRow) => u.id))
                      : new Set())} />
                </th>
                <th className="text-left py-2">Email / Name</th>
                <th className="text-left">Role</th>
                <th className="text-left">Tier</th>
                <th className="text-left">Status</th>
                <th className="text-left">Last login</th>
                <th className="text-right pr-3">Created</th>
                <th className="w-8"></th>
              </tr>
            </thead>
            <tbody>
              {data.users.map((u: UserRow) => (
                <tr key={u.id} className={clsx(
                  "border-t border-bg-line hover:bg-bg-panel2/50 cursor-pointer",
                  selected.has(u.id) && "bg-accent-amber/5"
                )}>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={selected.has(u.id)}
                      onChange={() => toggleSel(u.id)} />
                  </td>
                  <td className="py-2" onClick={() => setDrawerUserId(u.id)}>
                    <div className="font-semibold text-text-primary">{u.full_name || "—"}</div>
                    <div className="text-text-muted text-[10px]">{u.email}</div>
                  </td>
                  <td onClick={() => setDrawerUserId(u.id)}>
                    <RoleBadge role={u.role} />
                  </td>
                  <td onClick={() => setDrawerUserId(u.id)}>
                    <TierBadge tier={u.subscription.tier} />
                  </td>
                  <td onClick={() => setDrawerUserId(u.id)}>
                    {u.is_active
                      ? <span className="text-accent-green">● Active</span>
                      : <span className="text-accent-red">● Disabled</span>}
                  </td>
                  <td className="text-text-muted" onClick={() => setDrawerUserId(u.id)}>
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never"}
                  </td>
                  <td className="text-right pr-3 text-text-muted" onClick={() => setDrawerUserId(u.id)}>
                    {new Date(u.created_at).toLocaleDateString()}
                  </td>
                  <td><ChevronRight className="w-3.5 h-3.5 text-text-muted" /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.users.length === 0 && (
            <div className="text-center py-8 text-text-muted text-sm">No users match the filters.</div>
          )}
        </div>
      )}

      {/* Pagination */}
      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-[11px] text-text-muted">
          <span>Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, data.total)} of {data.total}</span>
          <div className="flex gap-1">
            <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page === 0}
              className="px-2 py-1 rounded border border-bg-line disabled:opacity-30">Previous</button>
            <button onClick={() => setPage(page + 1)}
              disabled={(page + 1) * PAGE_SIZE >= data.total}
              className="px-2 py-1 rounded border border-bg-line disabled:opacity-30">Next</button>
          </div>
        </div>
      )}

      {drawerUserId && (
        <UserDrawer userId={drawerUserId} onClose={() => setDrawerUserId(null)}
          onAction={() => mutate()} actorRole={me?.is_superuser ? "OWNER" : "USER"} />
      )}
      {showInvite && (
        <InviteModal onClose={() => setShowInvite(false)} onCreated={() => { setShowInvite(false); mutate(); }} />
      )}
    </>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// User drawer (slide-in detail)
// ═══════════════════════════════════════════════════════════════════════════

function UserDrawer({ userId, onClose, onAction, actorRole }:
                    { userId: number; onClose: () => void; onAction: () => void; actorRole: string }) {
  const { data, mutate } = useSWR<any>(`/api/admin/users/${userId}`, authedFetcher);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [newPw, setNewPw] = useState("");

  async function patch(payload: any) {
    setBusy(true); setErr(null);
    try {
      const res = await authedFetch(`/api/admin/users/${userId}`, {
        method: "PATCH", body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const e = await res.json(); throw new Error(e.detail);
      }
      mutate(); onAction();
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function setSubscription(tier: string) {
    setBusy(true); setErr(null);
    try {
      const res = await authedFetch(`/api/admin/subscriptions/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ tier, duration_days: 30 }),
      });
      if (!res.ok) {
        const e = await res.json(); throw new Error(e.detail);
      }
      mutate(); onAction();
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function resetPassword() {
    if (!newPw || newPw.length < 6) { setErr("min 6 chars"); return; }
    if (!window.confirm(`Reset password for ${data?.email}?`)) return;
    setBusy(true); setErr(null);
    try {
      const res = await authedFetch(`/api/admin/users/${userId}/reset-password`, {
        method: "POST",
        body: JSON.stringify({ new_password: newPw }),
      });
      if (!res.ok) {
        const e = await res.json(); throw new Error(e.detail);
      }
      const result = await res.json();
      alert(result.message);
      setNewPw("");
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function deleteUser() {
    if (!window.confirm(`PERMANENTLY DELETE ${data?.email}? This cannot be undone.`)) return;
    setBusy(true); setErr(null);
    try {
      const res = await authedFetch(`/api/admin/users/${userId}`, { method: "DELETE" });
      if (!res.ok) {
        const e = await res.json(); throw new Error(e.detail);
      }
      onAction(); onClose();
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/40" onClick={onClose} />
      <div className="w-full max-w-md bg-bg-surface shadow-2xl overflow-y-auto">
        <div className="sticky top-0 bg-bg-surface border-b border-bg-line px-5 py-3 flex items-center justify-between z-10">
          <h2 className="font-bold text-text-primary">User details</h2>
          <button onClick={onClose}><X className="w-4 h-4 text-text-muted" /></button>
        </div>

        {!data ? <div className="p-5"><LoadingSkeleton /></div> : (
          <div className="p-5 space-y-4">
            {err && <ErrorState message={err} />}

            {/* Identity */}
            <div>
              <div className="text-lg font-bold text-text-primary">{data.full_name || data.email}</div>
              <div className="text-[11px] text-text-muted">{data.email}</div>
              <div className="flex items-center gap-2 mt-2">
                <RoleBadge role={data.role} />
                <TierBadge tier={data.subscription?.tier || "FREE"} />
                {data.is_active
                  ? <span className="text-[10px] text-accent-green">● Active</span>
                  : <span className="text-[10px] text-accent-red">● Disabled</span>}
              </div>
            </div>

            {/* Activity */}
            <div className="grid grid-cols-2 gap-3 text-[11px]">
              <Stat label="Created" value={new Date(data.created_at).toLocaleDateString()} />
              <Stat label="Last login"
                value={data.last_login_at ? new Date(data.last_login_at).toLocaleString() : "never"} />
              <Stat label="Last IP" value={data.last_login_ip || "—"} />
              <Stat label="Subscription expires"
                value={data.subscription?.valid_until ? new Date(data.subscription.valid_until).toLocaleDateString() : "no expiry"} />
            </div>

            {/* Actions */}
            <div className="border-t border-bg-line pt-4 space-y-2">
              <div className="text-[10px] uppercase text-text-muted font-bold">Quick actions</div>
              <div className="grid grid-cols-2 gap-2">
                <button onClick={() => patch({ is_active: !data.is_active })} disabled={busy}
                  className="text-[11px] py-1.5 rounded border border-bg-line hover:border-accent-amber">
                  {data.is_active ? "Disable" : "Enable"}
                </button>
                <button onClick={deleteUser} disabled={busy || data.role === "OWNER"}
                  className="text-[11px] py-1.5 rounded border border-accent-red/40 text-accent-red hover:bg-accent-red/10 disabled:opacity-30">
                  <Trash2 className="w-3 h-3 inline mr-1" />Delete
                </button>
              </div>
            </div>

            {/* Role change */}
            <div className="border-t border-bg-line pt-4 space-y-2">
              <div className="text-[10px] uppercase text-text-muted font-bold">Role</div>
              <select value={data.role} onChange={(e) => patch({ role: e.target.value })} disabled={busy}
                className="w-full text-[12px] px-2 py-1.5 rounded border border-bg-line bg-bg-base">
                <option value="USER">USER</option>
                <option value="ANALYST">ANALYST</option>
                <option value="ADMIN">ADMIN</option>
                <option value="OWNER" disabled={actorRole !== "OWNER"}>OWNER {actorRole !== "OWNER" && "(OWNER only)"}</option>
              </select>
            </div>

            {/* Subscription tier */}
            <div className="border-t border-bg-line pt-4 space-y-2">
              <div className="text-[10px] uppercase text-text-muted font-bold">Subscription tier</div>
              <div className="grid grid-cols-2 gap-2">
                {["FREE", "BASIC", "INTERMEDIATE", "ADVANCED"].map((t) => (
                  <button key={t} onClick={() => setSubscription(t)} disabled={busy}
                    className={clsx("text-[11px] py-1.5 rounded border",
                      data.subscription?.tier === t
                        ? "border-accent-amber bg-accent-amber/10 text-accent-amber font-bold"
                        : "border-bg-line hover:border-accent-amber")}>
                    {t}
                  </button>
                ))}
              </div>
            </div>

            {/* Password reset */}
            <div className="border-t border-bg-line pt-4 space-y-2">
              <div className="text-[10px] uppercase text-text-muted font-bold">Reset password</div>
              <div className="flex gap-2">
                <input value={newPw} onChange={(e) => setNewPw(e.target.value)} type="password"
                  placeholder="New password (min 6)"
                  className="flex-1 text-[12px] px-2 py-1.5 rounded border border-bg-line bg-bg-base" />
                <button onClick={resetPassword} disabled={busy || !newPw}
                  className="text-[11px] px-3 py-1.5 rounded border border-accent-amber text-accent-amber font-bold hover:bg-accent-amber/10 disabled:opacity-30">
                  <Key className="w-3 h-3 inline mr-1" />Reset
                </button>
              </div>
            </div>

            {/* Audit history */}
            <div className="border-t border-bg-line pt-4">
              <div className="text-[10px] uppercase text-text-muted font-bold mb-2">Recent activity</div>
              <ul className="space-y-1.5">
                {data.audit_history?.slice(0, 10).map((h: any) => (
                  <li key={h.id} className="text-[10px] text-text-secondary border-l-2 border-bg-line pl-2">
                    <div className="font-semibold">{h.action.replace(/\./g, " · ")}</div>
                    <div className="text-text-muted">{h.summary}</div>
                    <div className="text-text-muted">{new Date(h.occurred_at).toLocaleString()}</div>
                  </li>
                ))}
                {(!data.audit_history || data.audit_history.length === 0) && (
                  <li className="text-[10px] text-text-muted">No audit history yet.</li>
                )}
              </ul>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// Invite modal
// ═══════════════════════════════════════════════════════════════════════════

function InviteModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("USER");
  const [tier, setTier] = useState("FREE");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [created, setCreated] = useState<any>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const res = await authedFetch("/api/admin/users/invite", {
        method: "POST",
        body: JSON.stringify({
          email, full_name: name || null, role, tier,
          initial_password: password,
        }),
      });
      if (!res.ok) {
        const e = await res.json(); throw new Error(e.detail);
      }
      const data = await res.json();
      setCreated(data);
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4">
      <div className="bg-bg-surface rounded-lg shadow-2xl w-full max-w-md">
        <div className="px-5 py-3 border-b border-bg-line flex items-center justify-between">
          <h2 className="font-bold text-text-primary">Invite user</h2>
          <button onClick={onClose}><X className="w-4 h-4 text-text-muted" /></button>
        </div>
        {created ? (
          <div className="p-5 space-y-3">
            <div className="text-accent-green text-[12px] flex items-start gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <div className="font-bold">Account created</div>
                <div className="text-text-secondary mt-1">{created.message}</div>
              </div>
            </div>
            <button onClick={() => { onCreated(); }}
              className="w-full bg-accent-amber text-white py-2 rounded font-bold">Done</button>
          </div>
        ) : (
          <form onSubmit={submit} className="p-5 space-y-3 text-[12px]">
            <div>
              <label className="text-[10px] uppercase text-text-muted block mb-1">Email *</label>
              <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required
                className="w-full px-3 py-1.5 rounded border border-bg-line bg-bg-base" />
            </div>
            <div>
              <label className="text-[10px] uppercase text-text-muted block mb-1">Full name (optional)</label>
              <input value={name} onChange={(e) => setName(e.target.value)}
                className="w-full px-3 py-1.5 rounded border border-bg-line bg-bg-base" />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] uppercase text-text-muted block mb-1">Role</label>
                <select value={role} onChange={(e) => setRole(e.target.value)}
                  className="w-full px-3 py-1.5 rounded border border-bg-line bg-bg-base">
                  <option>USER</option><option>ANALYST</option><option>ADMIN</option>
                </select>
              </div>
              <div>
                <label className="text-[10px] uppercase text-text-muted block mb-1">Tier</label>
                <select value={tier} onChange={(e) => setTier(e.target.value)}
                  className="w-full px-3 py-1.5 rounded border border-bg-line bg-bg-base">
                  <option>FREE</option><option>BASIC</option>
                  <option>INTERMEDIATE</option><option>ADVANCED</option>
                </select>
              </div>
            </div>
            <div>
              <label className="text-[10px] uppercase text-text-muted block mb-1">Initial password (min 6) *</label>
              <input value={password} onChange={(e) => setPassword(e.target.value)} type="text"
                minLength={6} required
                className="w-full px-3 py-1.5 rounded border border-bg-line bg-bg-base" />
              <div className="text-[10px] text-text-muted mt-1">Share with the user via a secure channel. They can change it after first login.</div>
            </div>
            {err && <div className="text-[11px] text-accent-red">{err}</div>}
            <button type="submit" disabled={busy}
              className="w-full bg-accent-amber text-white py-2 rounded font-bold disabled:opacity-50">
              {busy ? "Creating…" : "Create user"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// TAB 2 — Subscriptions
// ═══════════════════════════════════════════════════════════════════════════

function SubscriptionsTab() {
  const { data: summary } = useSWR<any>("/api/admin/subscription-summary", authedFetcher,
    { refreshInterval: 60_000 });
  const { data: subs }    = useSWR<any>("/api/admin/subscriptions", authedFetcher);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label="Total active" value={summary?.total_active ?? "—"} color="text-accent-amber" />
        <Stat label="FREE"         value={summary?.active_by_tier?.FREE ?? "—"} />
        <Stat label="BASIC"        value={summary?.active_by_tier?.BASIC ?? "—"} color="text-accent-blue" />
        <Stat label="INTERMEDIATE" value={summary?.active_by_tier?.INTERMEDIATE ?? "—"} color="text-accent-violet" />
        <Stat label="ADVANCED"     value={summary?.active_by_tier?.ADVANCED ?? "—"} color="text-accent-amber" />
      </div>

      {summary?.expiring_in_7d > 0 && (
        <InfoBanner type="warning">
          <strong>{summary.expiring_in_7d}</strong> subscription{summary.expiring_in_7d === 1 ? "" : "s"} expiring in the next 7 days.
        </InfoBanner>
      )}

      <Panel title="Active subscriptions">
        {!subs ? <LoadingSkeleton /> : (
          <table className="w-full text-[11px]">
            <thead className="text-text-muted">
              <tr>
                <th className="text-left py-1.5">Email</th>
                <th className="text-left">Tier</th>
                <th className="text-left">Telegram</th>
                <th className="text-left">Valid until</th>
                <th className="text-left">Notes</th>
              </tr>
            </thead>
            <tbody>
              {subs.subscriptions?.map((s: any) => (
                <tr key={s.user_id} className="border-t border-bg-line">
                  <td className="py-1.5 font-semibold">{s.email}</td>
                  <td><TierBadge tier={s.tier} /></td>
                  <td className="text-text-muted">{s.telegram_username ? `@${s.telegram_username}` : "—"}</td>
                  <td className="text-text-muted">{s.valid_until ? new Date(s.valid_until).toLocaleDateString() : "no expiry"}</td>
                  <td className="text-text-muted text-[10px]">{s.notes || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// TAB 3 — Audit log
// ═══════════════════════════════════════════════════════════════════════════

function AuditTab() {
  const [actionFilter, setActionFilter] = useState("");
  const { data, mutate } = useSWR<any>(
    `/api/admin/audit-log?limit=200${actionFilter ? `&action=${actionFilter}` : ""}`,
    authedFetcher, { refreshInterval: 30_000 });

  return (
    <Panel title="Audit Log" right={
      <select value={actionFilter} onChange={(e) => { setActionFilter(e.target.value); mutate(); }}
        className="text-[10px] px-2 py-1 rounded border border-bg-line bg-bg-base">
        <option value="">All actions</option>
        <option value="auth">auth.* (logins)</option>
        <option value="user">user.* (admin changes)</option>
      </select>
    }>
      {!data ? <LoadingSkeleton /> : (
        <table className="w-full text-[11px]">
          <thead className="text-text-muted">
            <tr>
              <th className="text-left py-1.5">When</th>
              <th className="text-left">Actor</th>
              <th className="text-left">Action</th>
              <th className="text-left">Target</th>
              <th className="text-left">Summary</th>
            </tr>
          </thead>
          <tbody>
            {data.entries?.map((e: any) => (
              <tr key={e.id} className="border-t border-bg-line">
                <td className="py-1.5 text-text-muted">{new Date(e.occurred_at).toLocaleString()}</td>
                <td>
                  <div className="font-semibold">{e.actor?.email}</div>
                  <div className="text-text-muted text-[10px]">{e.actor?.role}</div>
                </td>
                <td className="font-mono text-accent-amber text-[10px]">{e.action}</td>
                <td>{e.target?.email || "—"}</td>
                <td className="text-text-secondary">{e.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// TAB 4 — Settings
// ═══════════════════════════════════════════════════════════════════════════

function SettingsTab() {
  return (
    <Panel title="Organization settings">
      <div className="space-y-3 text-[12px]">
        <InfoBanner>
          Settings UI coming next iteration. Currently configurable via .env:
          <ul className="mt-2 ml-4 list-disc">
            <li><code>SECRET_KEY</code> — JWT signing key</li>
            <li><code>LIVE_ONLY</code> — strict-live-data mode</li>
            <li>Telegram channels — set in <code>app/models/subscription.py</code> <code>TIER_FEATURES</code></li>
          </ul>
        </InfoBanner>
        <p className="text-text-muted">
          Future: default tier for new signups, signup toggle, password policy, 2FA enforcement,
          API rate limits per tier, Telegram bot token + channel ID configuration.
        </p>
      </div>
    </Panel>
  );
}


// ═══════════════════════════════════════════════════════════════════════════
// Shared badges
// ═══════════════════════════════════════════════════════════════════════════

function RoleBadge({ role }: { role: string }) {
  const cfg: any = {
    OWNER:   { color: "bg-accent-amber/15 text-accent-amber border-accent-amber/40",   icon: Crown },
    ADMIN:   { color: "bg-accent-violet/15 text-accent-violet border-accent-violet/40", icon: ShieldCheck },
    ANALYST: { color: "bg-accent-blue/15 text-accent-blue border-accent-blue/40",      icon: Activity },
    USER:    { color: "bg-text-muted/15 text-text-secondary border-bg-line",            icon: UsersIcon },
  }[role] || { color: "bg-text-muted/15 text-text-muted", icon: UsersIcon };
  const Icon = cfg.icon;
  return (
    <span className={clsx("inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider", cfg.color)}>
      <Icon className="w-2.5 h-2.5" /> {role}
    </span>
  );
}


function TierBadge({ tier }: { tier: string }) {
  const cls = tier === "ADVANCED"     ? "bg-accent-amber/15 text-accent-amber"
             : tier === "INTERMEDIATE" ? "bg-accent-violet/15 text-accent-violet"
             : tier === "BASIC"        ? "bg-accent-blue/15 text-accent-blue"
             : "bg-text-muted/15 text-text-muted";
  return (
    <span className={clsx("inline-block px-1.5 py-0.5 rounded text-[10px] font-bold uppercase", cls)}>
      {tier}
    </span>
  );
}
