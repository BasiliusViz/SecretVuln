import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "../api/client";

interface RoleBrief {
  id: string;
  name: string;
}

interface Member {
  id: string;
  email: string;
  full_name: string | null;
  auth_source: string;
}

interface Group {
  id: string;
  name: string;
  description: string | null;
  source: "manual" | "ldap";
  ldap_group: string | null;
  last_synced_at: string | null;
  member_count: number;
  roles: RoleBrief[];
}

interface GroupDetail extends Group {
  members: Member[];
}

const inputStyle = {
  fontFamily: "inherit",
  fontSize: 13,
  color: "var(--text-primary)",
  background: "var(--bg-page)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  padding: "6px 10px",
} as const;

function SourceBadge({ source }: { source: "manual" | "ldap" }) {
  const { t } = useTranslation();
  const ldap = source === "ldap";
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 500,
        padding: "2px 8px",
        borderRadius: 99,
        background: ldap ? "var(--accent-bg)" : "var(--sev-info-bg)",
        color: ldap ? "var(--accent)" : "var(--sev-info-text)",
      }}
    >
      {ldap ? "LDAP" : t("groups.manual")}
    </span>
  );
}

function CreateGroupForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [source, setSource] = useState<"manual" | "ldap">("ldap");
  const [ldapGroup, setLdapGroup] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    const res = await apiFetch("/api/v1/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name.trim(),
        source,
        ldap_group: source === "ldap" ? ldapGroup.trim() || name.trim() : null,
      }),
    }).catch(() => null);
    setBusy(false);
    if (res?.status === 201) onDone();
    else if (res?.status === 409) setError(t("groups.duplicate"));
    else setError(t("groups.saveError"));
  };

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ fontWeight: 500, marginBottom: 10 }}>{t("groups.createTitle")}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
        <input
          style={{ ...inputStyle, flex: "1 1 200px" }}
          placeholder={t("groups.name")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <select
          style={{ ...inputStyle, flex: "0 0 auto" }}
          value={source}
          onChange={(e) => setSource(e.target.value as "manual" | "ldap")}
        >
          <option value="ldap">{t("groups.sourceLdap")}</option>
          <option value="manual">{t("groups.sourceManual")}</option>
        </select>
        {source === "ldap" && (
          <input
            style={{ ...inputStyle, flex: "1 1 200px" }}
            placeholder={t("groups.ldapGroupPlaceholder")}
            value={ldapGroup}
            onChange={(e) => setLdapGroup(e.target.value)}
          />
        )}
      </div>
      {source === "ldap" && (
        <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 10 }}>
          {t("groups.ldapHint")}
        </div>
      )}
      {error && <div style={{ color: "var(--sev-critical-text)", fontSize: 12, marginBottom: 8 }}>{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={submit} disabled={busy || !name.trim()}>
          {t("groups.create")}
        </button>
        <button onClick={onCancel}>{t("groups.cancel")}</button>
      </div>
    </div>
  );
}

function MemberManager({ group, onChanged }: { group: GroupDetail; onChanged: () => void }) {
  const { t } = useTranslation();
  const [allUsers, setAllUsers] = useState<Member[]>([]);
  const [selected, setSelected] = useState("");

  useEffect(() => {
    if (group.source === "manual") {
      apiFetch("/api/v1/users").then((r) => r.json()).then(setAllUsers).catch(() => {});
    }
  }, [group.source]);

  const memberIds = useMemo(() => new Set(group.members.map((m) => m.id)), [group.members]);
  const candidates = allUsers.filter((u) => !memberIds.has(u.id));

  const addMember = async () => {
    if (!selected) return;
    await apiFetch(`/api/v1/groups/${group.id}/members/${selected}`, { method: "POST" });
    setSelected("");
    onChanged();
  };

  const removeMember = async (userId: string) => {
    await apiFetch(`/api/v1/groups/${group.id}/members/${userId}`, { method: "DELETE" });
    onChanged();
  };

  return (
    <div style={{ padding: "4px 0" }}>
      {group.members.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--text-muted)", padding: "6px 0" }}>
          {t("groups.noMembers")}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {group.members.map((m) => (
            <div
              key={m.id}
              style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}
            >
              <span style={{ fontWeight: 500 }}>{m.full_name || m.email}</span>
              <span style={{ color: "var(--text-muted)", fontSize: 12 }}>{m.email}</span>
              {group.source === "manual" && (
                <button
                  style={{ fontSize: 11, padding: "1px 8px", marginLeft: "auto" }}
                  onClick={() => removeMember(m.id)}
                >
                  {t("groups.remove")}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {group.source === "manual" && (
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <select
            style={{ ...inputStyle, flex: "1 1 auto" }}
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="">{t("groups.pickUser")}</option>
            {candidates.map((u) => (
              <option key={u.id} value={u.id}>
                {u.full_name ? `${u.full_name} (${u.email})` : u.email}
              </option>
            ))}
          </select>
          <button onClick={addMember} disabled={!selected}>
            {t("groups.addMember")}
          </button>
        </div>
      )}
    </div>
  );
}

function GroupRow({
  group,
  allRoles,
  onChanged,
}: {
  group: Group;
  allRoles: RoleBrief[];
  onChanged: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [roleToAdd, setRoleToAdd] = useState("");

  const addRole = async () => {
    if (!roleToAdd) return;
    await apiFetch(`/api/v1/groups/${group.id}/roles/${roleToAdd}`, { method: "POST" });
    setRoleToAdd("");
    onChanged();
  };

  const removeRole = async (roleId: string) => {
    await apiFetch(`/api/v1/groups/${group.id}/roles/${roleId}`, { method: "DELETE" });
    onChanged();
  };

  const loadDetail = useCallback(async () => {
    const d = await apiFetch(`/api/v1/groups/${group.id}`).then((r) => r.json());
    setDetail(d);
  }, [group.id]);

  const toggle = async () => {
    if (!expanded && !detail) await loadDetail();
    setExpanded((v) => !v);
  };

  const sync = async () => {
    setSyncing(true);
    setSyncMsg(null);
    const res = await apiFetch(`/api/v1/groups/${group.id}/sync`, { method: "POST" }).catch(() => null);
    setSyncing(false);
    if (res?.ok) {
      const r = await res.json();
      setSyncMsg(t("groups.syncResult", { added: r.added, removed: r.removed, provisioned: r.provisioned }));
      await loadDetail();
      onChanged();
    } else {
      const detail = res ? (await res.json().catch(() => ({}))).detail : null;
      setSyncMsg(detail || t("groups.syncError"));
    }
  };

  const del = async () => {
    if (!window.confirm(t("groups.deleteConfirm", { name: group.name }))) return;
    await apiFetch(`/api/v1/groups/${group.id}`, { method: "DELETE" });
    onChanged();
  };

  const synced = group.last_synced_at
    ? new Date(group.last_synced_at).toLocaleString(i18n.language === "ru" ? "ru-RU" : undefined)
    : t("groups.neverSynced");

  return (
    <div style={{ borderTop: "1px solid var(--border)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px" }}>
        <button
          onClick={toggle}
          style={{ border: "none", background: "none", padding: 0, color: "var(--text-muted)", width: 14 }}
          aria-label={t("groups.toggle")}
        >
          {expanded ? "▾" : "▸"}
        </button>
        <span style={{ fontWeight: 500 }}>{group.name}</span>
        <SourceBadge source={group.source} />
        {group.source === "ldap" && group.ldap_group && (
          <span style={{ fontSize: 12, color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
            ← {group.ldap_group}
          </span>
        )}
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {t("groups.memberCount", { count: group.member_count })}
        </span>
        {group.roles.map((r) => (
          <span
            key={r.id}
            style={{
              fontSize: 11,
              fontWeight: 500,
              padding: "2px 8px",
              borderRadius: 99,
              background: "var(--sev-low-bg)",
              color: "var(--sev-low-text)",
            }}
          >
            {r.name}
          </span>
        ))}
        <span style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          {group.source === "ldap" && (
            <button style={{ fontSize: 12, padding: "2px 10px" }} onClick={sync} disabled={syncing}>
              {syncing ? t("groups.syncing") : t("groups.sync")}
            </button>
          )}
          <button
            style={{ fontSize: 12, padding: "2px 10px", color: "var(--text-muted)" }}
            onClick={del}
          >
            ✕
          </button>
        </span>
      </div>
      {group.source === "ldap" && (
        <div style={{ padding: "0 14px 6px 38px", fontSize: 11, color: "var(--text-muted)" }}>
          {t("groups.lastSynced")}: {synced}
          {syncMsg && <span style={{ marginLeft: 10, color: "var(--accent)" }}>{syncMsg}</span>}
        </div>
      )}
      {expanded && detail && (
        <div style={{ padding: "6px 14px 14px 38px" }}>
          <MemberManager group={detail} onChanged={() => { loadDetail(); onChanged(); }} />
          <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 8 }}>{t("groups.rolesTitle")}</div>
            {group.roles.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 8 }}>
                {t("groups.noRoles")}
              </div>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
                {group.roles.map((r) => (
                  <span
                    key={r.id}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      fontSize: 12,
                      padding: "2px 6px 2px 10px",
                      borderRadius: 99,
                      background: "var(--sev-low-bg)",
                      color: "var(--sev-low-text)",
                    }}
                  >
                    {r.name}
                    <button
                      onClick={() => removeRole(r.id)}
                      style={{
                        border: "none", background: "none", cursor: "pointer",
                        color: "inherit", padding: 0, fontSize: 13, lineHeight: 1,
                      }}
                      aria-label={t("groups.remove")}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div style={{ display: "flex", gap: 8 }}>
              <select
                style={{ ...inputStyle, flex: "1 1 auto" }}
                value={roleToAdd}
                onChange={(e) => setRoleToAdd(e.target.value)}
              >
                <option value="">{t("groups.pickRole")}</option>
                {allRoles
                  .filter((r) => !group.roles.some((gr) => gr.id === r.id))
                  .map((r) => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
              </select>
              <button onClick={addRole} disabled={!roleToAdd}>
                {t("groups.addRole")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function Groups() {
  const { t } = useTranslation();
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [allRoles, setAllRoles] = useState<RoleBrief[]>([]);
  const [formOpen, setFormOpen] = useState(false);

  const reload = useCallback(() => {
    apiFetch("/api/v1/groups")
      .then((r) => r.json())
      .then(setGroups)
      .catch(() => setGroups([]));
    apiFetch("/api/v1/roles")
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: RoleBrief[]) => setAllRoles(rows))
      .catch(() => setAllRoles([]));
  }, []);

  useEffect(reload, [reload]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1>{t("groups.title")}</h1>
        <button onClick={() => setFormOpen(true)}>+ {t("groups.createTitle")}</button>
      </div>
      <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: -8, maxWidth: 640 }}>
        {t("groups.intro")}
      </p>

      {formOpen && (
        <CreateGroupForm
          onDone={() => {
            setFormOpen(false);
            reload();
          }}
          onCancel={() => setFormOpen(false)}
        />
      )}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {groups === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("common.loading")}</p>
        ) : groups.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("groups.empty")}</p>
        ) : (
          <div style={{ marginTop: -1 }}>
            {groups.map((g) => (
              <GroupRow key={g.id} group={g} allRoles={allRoles} onChanged={reload} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
