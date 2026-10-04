import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiJson } from "../api/json";
import { SLA_DAY_FIELDS, type SlaDayField, type SlaPolicy } from "../api/types";
import { useCan } from "../auth/AuthContext";
import { Modal } from "../components/Modal";
import { SeverityBadge } from "../components/SeverityBadge";
import { PRIMARY_BUTTON } from "../components/ui";
import type { Severity } from "../theme/severity";

const inputStyle = {
  fontFamily: "inherit",
  fontSize: 13,
  color: "var(--text-primary)",
  background: "var(--bg-page)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  padding: "6px 10px",
} as const;

const cell = { padding: "8px 12px" } as const;

function fieldSeverity(f: SlaDayField): Severity {
  return f.replace("days_", "") as Severity;
}

type Draft = { name: string } & Record<SlaDayField, string>;

function toDraft(p: SlaPolicy | null): Draft {
  const d = { name: p?.name ?? "" } as Draft;
  for (const f of SLA_DAY_FIELDS) d[f] = p?.[f] != null ? String(p[f]) : "";
  return d;
}

function PolicyForm({
  policy,
  onClose,
  onSaved,
}: {
  policy: SlaPolicy | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Draft>(() => toDraft(policy));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    const body: Record<string, unknown> = { name: draft.name.trim() };
    for (const f of SLA_DAY_FIELDS) {
      const v = draft[f].trim();
      const n = Number(v);
      if (v && (!Number.isInteger(n) || n < 1 || n > 3650)) {
        setError(t("sla.daysInvalid"));
        return;
      }
      body[f] = v ? n : null;
    }
    setSaving(true);
    setError(null);
    const res = policy
      ? await apiJson<SlaPolicy>(`/api/v1/sla-policies/${policy.id}`, "PATCH", body)
      : await apiJson<SlaPolicy>("/api/v1/sla-policies", "POST", body);
    setSaving(false);
    if (res.ok) {
      onSaved();
      onClose();
    } else if (res.status === 409) setError(t("sla.nameTaken"));
    else if (res.status === 403) setError(t("common.forbidden"));
    else setError(t("sla.saveError"));
  };

  return (
    <Modal title={policy ? t("sla.edit") : t("sla.create")} onClose={onClose}>
      <div style={{ display: "grid", gap: 10, minWidth: 320 }}>
        <label style={{ display: "grid", gap: 4, fontSize: 13 }}>
          {t("sla.name")}
          <input
            style={inputStyle}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            autoFocus
          />
        </label>
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("sla.daysHint")}</div>
        {SLA_DAY_FIELDS.map((f) => (
          <label
            key={f}
            style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}
          >
            <SeverityBadge severity={fieldSeverity(f)} />
            <input
              style={{ ...inputStyle, width: 100 }}
              inputMode="numeric"
              placeholder={t("sla.noDeadline")}
              value={draft[f]}
              onChange={(e) => setDraft({ ...draft, [f]: e.target.value })}
            />
          </label>
        ))}
        {policy && (policy.is_default || policy.entities_count > 0) && (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("sla.recomputeHint")}</div>
        )}
        {error && <div style={{ color: "#A32D2D", fontSize: 12 }}>{error}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}>{t("common.cancel")}</button>
          <button style={PRIMARY_BUTTON} onClick={save} disabled={saving || !draft.name.trim()}>
            {saving ? t("common.loading") : t("common.save")}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function SlaPolicies() {
  const { t } = useTranslation();
  const can = useCan();
  const canManage = can("sla:manage");
  const [policies, setPolicies] = useState<SlaPolicy[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // undefined — окно закрыто, null — новая политика
  const [editing, setEditing] = useState<SlaPolicy | null | undefined>(undefined);

  const load = useCallback(async () => {
    const res = await apiJson<SlaPolicy[]>("/api/v1/sla-policies");
    if (res.ok) setPolicies(res.data);
    else setLoadError(res.status === 403 ? t("common.forbidden") : t("common.error"));
  }, [t]);

  useEffect(() => {
    load();
  }, [load]);

  const makeDefault = async (p: SlaPolicy) => {
    setActionError(null);
    const res = await apiJson(`/api/v1/sla-policies/${p.id}`, "PATCH", { is_default: true });
    if (!res.ok) setActionError(t("sla.saveError"));
    load();
  };

  const remove = async (p: SlaPolicy) => {
    if (!window.confirm(t("sla.deleteConfirm", { name: p.name }))) return;
    setActionError(null);
    const res = await apiJson(`/api/v1/sla-policies/${p.id}`, "DELETE");
    if (!res.ok) setActionError(res.status === 409 ? t("sla.deleteBlocked") : t("sla.saveError"));
    load();
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1>{t("sla.title")}</h1>
        {canManage && (
          <button style={PRIMARY_BUTTON} onClick={() => setEditing(null)}>
            {t("sla.create")}
          </button>
        )}
      </div>
      <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 0 }}>{t("sla.intro")}</p>

      {actionError && (
        <div style={{ color: "#A32D2D", fontSize: 12, marginBottom: 8 }}>{actionError}</div>
      )}

      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        {loadError ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{loadError}</p>
        ) : !policies ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("common.loading")}</p>
        ) : policies.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("sla.empty")}</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                <th style={{ ...cell, fontWeight: 500 }}>{t("sla.name")}</th>
                {SLA_DAY_FIELDS.map((f) => (
                  <th key={f} style={{ ...cell, fontWeight: 500 }}>
                    <SeverityBadge severity={fieldSeverity(f)} />
                  </th>
                ))}
                <th style={{ ...cell, fontWeight: 500 }}>{t("sla.projects")}</th>
                {canManage && <th style={cell} />}
              </tr>
            </thead>
            <tbody>
              {policies.map((p) => (
                <tr key={p.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={cell}>
                    {p.name}
                    {p.is_default && (
                      <span style={{ marginLeft: 8, fontSize: 11, color: "var(--accent)" }}>
                        {t("sla.default")}
                      </span>
                    )}
                  </td>
                  {SLA_DAY_FIELDS.map((f) => (
                    <td key={f} style={{ ...cell, fontFamily: "var(--font-mono)", fontSize: 12 }}>
                      {p[f] != null ? t("sla.days", { count: p[f] }) : "—"}
                    </td>
                  ))}
                  <td style={{ ...cell, color: "var(--text-secondary)" }}>{p.entities_count}</td>
                  {canManage && (
                    <td style={{ ...cell, whiteSpace: "nowrap", textAlign: "right" }}>
                      <button onClick={() => setEditing(p)}>{t("sla.edit")}</button>{" "}
                      {!p.is_default && (
                        <>
                          <button onClick={() => makeDefault(p)}>{t("sla.makeDefault")}</button>{" "}
                          <button onClick={() => remove(p)} disabled={p.entities_count > 0}>
                            {t("sla.delete")}
                          </button>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {editing !== undefined && (
        <PolicyForm policy={editing} onClose={() => setEditing(undefined)} onSaved={load} />
      )}
    </div>
  );
}
