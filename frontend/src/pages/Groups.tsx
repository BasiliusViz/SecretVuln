import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "../api/client";
import { apiJson } from "../api/json";
import type { Binding, EntityNode } from "../api/types";
import { useCan } from "../auth/AuthContext";

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

/** Привязки группы «роль → область» (проект с поддеревом или всё дерево). */
function BindingManager({
  group,
  bindings,
  allRoles,
  entities,
  canWrite,
  onChanged,
}: {
  group: Group;
  bindings: Binding[];
  allRoles: RoleBrief[];
  entities: EntityNode[];
  canWrite: boolean;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [roleId, setRoleId] = useState("");
  // "" — на всё дерево
  const [entityId, setEntityId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const add = async () => {
    if (!roleId) return;
    setError(null);
    const res = await apiJson(`/api/v1/groups/${group.id}/bindings`, "POST", {
      role_id: roleId,
      entity_id: entityId || null,
    });
    if (!res.ok) {
      setError(res.status === 409 ? t("groups.bindingDuplicate") : res.error ?? t("groups.saveError"));
      return;
    }
    setRoleId("");
    setEntityId("");
    onChanged();
  };
  const remove = async (b: Binding) => {
    await apiFetch(`/api/v1/groups/${group.id}/bindings/${b.id}`, { method: "DELETE" });
    onChanged();
  };

  return (
    <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 500, marginBottom: 8 }}>{t("groups.bindingsTitle")}</div>
      {bindings.length === 0 ? (
        <div style={{ fontSize: 13, color: "var(--text-muted)", marginBottom: 8 }}>{t("groups.noBindings")}</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 10 }}>
          {bindings.map((b) => (
            <div key={b.id} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
              <span style={{ fontWeight: 500 }}>{b.role_name}</span>
              <span style={{ color: "var(--text-muted)" }}>→</span>
              <span style={b.entity_path ? { fontFamily: "var(--font-mono)", fontSize: 12 } : undefined}>
                {b.entity_path ?? t("groups.wholeTree")}
              </span>
              {canWrite && (
                <button
                  onClick={() => void remove(b)}
                  style={{ fontSize: 12, padding: "0 8px", color: "var(--text-muted)" }}
                  aria-label={t("groups.remove")}
                >
                  ×
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {canWrite && (
        <>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <select
              style={{ ...inputStyle, flex: "1 1 160px" }}
              value={roleId}
              onChange={(e) => setRoleId(e.target.value)}
              aria-label={t("groups.pickRole")}
            >
              <option value="">{t("groups.pickRole")}</option>
              {allRoles.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
            <select
              style={{ ...inputStyle, flex: "2 1 220px" }}
              value={entityId}
              onChange={(e) => setEntityId(e.target.value)}
              aria-label={t("groups.scope")}
            >
              <option value="">{t("groups.wholeTree")}</option>
              {entities.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.path}
                </option>
              ))}
            </select>
            <button onClick={() => void add()} disabled={!roleId}>
              {t("groups.addRole")}
            </button>
          </div>
          {error && <div style={{ color: "var(--sev-critical-text)", fontSize: 12, marginTop: 6 }}>{error}</div>}
        </>
      )}
    </div>
  );
}

function GroupRow({
  group,
  allRoles,
  entities,
  canWrite,
  onChanged,
}: {
  group: Group;
  allRoles: RoleBrief[];
  entities: EntityNode[];
  canWrite: boolean;
  onChanged: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<GroupDetail | null>(null);
  const [bindings, setBindings] = useState<Binding[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const loadBindings = useCallback(async () => {
    const r = await apiJson<Binding[]>(`/api/v1/groups/${group.id}/bindings`);
    setBindings(r.data ?? []);
  }, [group.id]);

  const loadDetail = useCallback(async () => {
    const d = await apiFetch(`/api/v1/groups/${group.id}`).then((r) => r.json());
    setDetail(d);
    await loadBindings();
  }, [group.id, loadBindings]);

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
        <span style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          {group.source === "ldap" && (
            <button style={{ fontSize: 12, padding: "2px 10px" }} onClick={sync} disabled={syncing}>
              {syncing ? t("groups.syncing") : t("groups.sync")}
            </button>
          )}
          {canWrite && (
            <button
              style={{ fontSize: 12, padding: "2px 10px", color: "var(--text-muted)" }}
              onClick={del}
            >
              ✕
            </button>
          )}
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
          <BindingManager
            group={group}
            bindings={bindings}
            allRoles={allRoles}
            entities={entities}
            canWrite={canWrite}
            onChanged={() => void loadBindings()}
          />
        </div>
      )}
    </div>
  );
}

export function Groups() {
  const { t } = useTranslation();
  const [groups, setGroups] = useState<Group[] | null>(null);
  const [allRoles, setAllRoles] = useState<RoleBrief[]>([]);
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [formOpen, setFormOpen] = useState(false);
  const can = useCan();
  // состав групп и привязки правит только глобальный group:write
  const canWrite = can("group:write", "*");

  const reload = useCallback(() => {
    apiFetch("/api/v1/groups")
      .then((r) => r.json())
      .then(setGroups)
      .catch(() => setGroups([]));
    apiFetch("/api/v1/roles")
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: RoleBrief[]) => setAllRoles(rows))
      .catch(() => setAllRoles([]));
    // выдавать можно только на видимые проекты, заглушки предков в область не попадают
    void apiJson<EntityNode[]>("/api/v1/entities").then((r) =>
      setEntities((r.data ?? []).filter((e) => !e.stub).sort((a, b) => a.path.localeCompare(b.path))),
    );
  }, []);

  useEffect(reload, [reload]);

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1>{t("groups.title")}</h1>
        {canWrite && <button onClick={() => setFormOpen(true)}>+ {t("groups.createTitle")}</button>}
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
              <GroupRow
                key={g.id}
                group={g}
                allRoles={allRoles}
                entities={entities}
                canWrite={canWrite}
                onChanged={reload}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
