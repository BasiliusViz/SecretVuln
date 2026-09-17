import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "../api/client";

interface Permission {
  resource: string;
  action: string;
}

interface Role {
  id: string;
  name: string;
  description: string | null;
  is_builtin: boolean;
  permissions: Permission[];
}

interface Catalog {
  catalog: Record<string, string[]>;
  actions: string[];
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

function permKey(resource: string, action: string) {
  return `${resource}:${action}`;
}

function PermissionMatrix({
  catalog,
  selected,
  onToggle,
  readOnly,
}: {
  catalog: Catalog;
  selected: Set<string>;
  onToggle: (resource: string, action: string) => void;
  readOnly: boolean;
}) {
  const { t } = useTranslation();
  const resources = Object.keys(catalog.catalog);
  return (
    <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr>
          <th style={{ textAlign: "left", padding: "4px 12px 4px 0", fontWeight: 500 }} />
          {catalog.actions.map((a) => (
            <th key={a} style={{ padding: "4px 10px", fontWeight: 500, fontSize: 12 }}>
              {t(`perm.action.${a}`)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {resources.map((res) => (
          <tr key={res} style={{ borderTop: "1px solid var(--border)" }}>
            <td style={{ padding: "6px 12px 6px 0", fontWeight: 500 }}>
              {t(`perm.resource.${res}`)}
            </td>
            {catalog.actions.map((a) => {
              const valid = catalog.catalog[res].includes(a);
              const on = selected.has(permKey(res, a));
              return (
                <td key={a} style={{ padding: "6px 10px", textAlign: "center" }}>
                  {valid ? (
                    <input
                      type="checkbox"
                      checked={on}
                      disabled={readOnly}
                      onChange={() => onToggle(res, a)}
                    />
                  ) : (
                    <span style={{ color: "var(--border)" }}>—</span>
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RoleCard({
  role,
  catalog,
  onChanged,
}: {
  role: Role;
  catalog: Catalog;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(role.permissions.map((p) => permKey(p.resource, p.action))),
  );
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const dirty = useMemo(() => {
    const orig = new Set(role.permissions.map((p) => permKey(p.resource, p.action)));
    if (orig.size !== selected.size) return true;
    for (const k of selected) if (!orig.has(k)) return true;
    return false;
  }, [role.permissions, selected]);

  const toggle = (resource: string, action: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      const k = permKey(resource, action);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  const save = async () => {
    setSaving(true);
    setMsg(null);
    const permissions = [...selected].map((k) => {
      const [resource, action] = k.split(":");
      return { resource, action };
    });
    const res = await apiFetch(`/api/v1/roles/${role.id}/permissions`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ permissions }),
    }).catch(() => null);
    setSaving(false);
    if (res?.ok) {
      setMsg(t("roles.saved"));
      onChanged();
    } else {
      setMsg(t("roles.saveError"));
    }
  };

  const del = async () => {
    if (!window.confirm(t("roles.deleteConfirm", { name: role.name }))) return;
    await apiFetch(`/api/v1/roles/${role.id}`, { method: "DELETE" });
    onChanged();
  };

  return (
    <div style={{ borderTop: "1px solid var(--border)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px" }}>
        <button
          onClick={() => setExpanded((v) => !v)}
          style={{ border: "none", background: "none", padding: 0, color: "var(--text-muted)", width: 14 }}
          aria-label={t("groups.toggle")}
        >
          {expanded ? "▾" : "▸"}
        </button>
        <span style={{ fontWeight: 500 }}>{role.name}</span>
        {role.is_builtin && (
          <span
            style={{
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: 99,
              background: "var(--sev-info-bg)",
              color: "var(--sev-info-text)",
            }}
          >
            {t("roles.builtin")}
          </span>
        )}
        {role.description && (
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{role.description}</span>
        )}
        <span style={{ fontSize: 12, color: "var(--text-muted)", marginLeft: "auto" }}>
          {t("roles.permCount", { count: role.permissions.length })}
        </span>
        {!role.is_builtin && (
          <button
            style={{ fontSize: 12, padding: "2px 10px", color: "var(--text-muted)" }}
            onClick={del}
          >
            ✕
          </button>
        )}
      </div>
      {expanded && (
        <div style={{ padding: "4px 14px 16px 38px" }}>
          <PermissionMatrix catalog={catalog} selected={selected} onToggle={toggle} readOnly={false} />
          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12 }}>
            <button onClick={save} disabled={!dirty || saving}>
              {saving ? t("common.loading") : t("roles.save")}
            </button>
            {msg && <span style={{ fontSize: 12, color: "var(--accent)" }}>{msg}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

function CreateRoleForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    const res = await apiFetch("/api/v1/roles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
    }).catch(() => null);
    setBusy(false);
    if (res?.status === 201) onDone();
    else if (res?.status === 409) setError(t("roles.duplicate"));
    else setError(t("roles.saveError"));
  };

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ fontWeight: 500, marginBottom: 10 }}>{t("roles.createTitle")}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
        <input
          style={{ ...inputStyle, flex: "1 1 180px" }}
          placeholder={t("roles.name")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <input
          style={{ ...inputStyle, flex: "2 1 240px" }}
          placeholder={t("roles.description")}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 10 }}>
        {t("roles.createHint")}
      </div>
      {error && <div style={{ color: "var(--sev-critical-text)", fontSize: 12, marginBottom: 8 }}>{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={submit} disabled={busy || !name.trim()}>
          {t("roles.create")}
        </button>
        <button onClick={onCancel}>{t("roles.cancel")}</button>
      </div>
    </div>
  );
}

export function Roles() {
  const { t } = useTranslation();
  const [roles, setRoles] = useState<Role[] | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [forbidden, setForbidden] = useState(false);

  const reload = useCallback(() => {
    apiFetch("/api/v1/roles")
      .then((r) => {
        if (r.status === 403) {
          setForbidden(true);
          return [];
        }
        return r.json();
      })
      .then(setRoles)
      .catch(() => setRoles([]));
    apiFetch("/api/v1/permissions/catalog")
      .then((r) => (r.ok ? r.json() : null))
      .then(setCatalog)
      .catch(() => {});
  }, []);

  useEffect(reload, [reload]);

  if (forbidden) {
    return (
      <div>
        <h1>{t("roles.title")}</h1>
        <div className="card">
          <p style={{ color: "var(--text-muted)", margin: 0 }}>{t("roles.forbidden")}</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1>{t("roles.title")}</h1>
        <button onClick={() => setFormOpen(true)}>+ {t("roles.createTitle")}</button>
      </div>
      <p style={{ color: "var(--text-muted)", fontSize: 13, marginTop: -8, maxWidth: 640 }}>
        {t("roles.intro")}
      </p>

      {formOpen && (
        <CreateRoleForm
          onDone={() => {
            setFormOpen(false);
            reload();
          }}
          onCancel={() => setFormOpen(false)}
        />
      )}

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {roles === null || catalog === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("common.loading")}</p>
        ) : roles.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("roles.empty")}</p>
        ) : (
          <div style={{ marginTop: -1 }}>
            {roles.map((r) => (
              <RoleCard key={r.id} role={r} catalog={catalog} onChanged={reload} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
