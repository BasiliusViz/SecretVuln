import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiJson } from "../api/json";
import type { Binding, EntityBindings, EntityNode, Group } from "../api/types";
import { useCan } from "../auth/AuthContext";
import { PRIMARY_BUTTON, formatDate } from "../components/ui";

const SECTION = { marginBottom: 16 } as const;
const HINT = { fontSize: 11, color: "var(--text-muted)" } as const;
const CELL = { padding: "6px 8px", borderTop: "1px solid var(--border)" } as const;

/** Вкладка проекта «Доступ»: какие группы с какими ролями работают с проектом. */
export function ProjectAccess({ entity }: { entity: EntityNode }) {
  const { t } = useTranslation();
  const can = useCan();
  const [data, setData] = useState<EntityBindings | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupId, setGroupId] = useState("");
  const [roleId, setRoleId] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [loadError, setLoadError] = useState(false);

  const base = `/api/v1/entities/${entity.id}/bindings`;
  const load = useCallback(async () => {
    const res = await apiJson<EntityBindings>(base);
    if (res.ok && res.data) setData(res.data);
    else setLoadError(true);
  }, [base]);

  useEffect(() => {
    void load();
  }, [load]);

  // roles приходит, только если у вызывающего есть access:manage на проекте
  const canManage = !!data?.roles;
  const canSeeGroups = can("group:read");
  useEffect(() => {
    if (canManage && canSeeGroups) void apiJson<Group[]>("/api/v1/groups").then((r) => setGroups(r.data ?? []));
  }, [canManage, canSeeGroups]);

  if (loadError) return <p style={{ color: "var(--text-muted)" }}>{t("common.error")}</p>;
  if (!data) return <p style={{ color: "var(--text-muted)" }}>{t("common.loading")}</p>;

  const roles = data.roles ?? [];
  const grantable = roles.filter((r) => r.grantable);
  const locked = roles.filter((r) => !r.grantable);
  const permLabel = (perm: string) => {
    const [res, action] = perm.split(":");
    return `${t(`perm.resource.${res}`)}: ${t(`perm.action.${action}`).toLowerCase()}`;
  };

  const add = async () => {
    if (!groupId || !roleId) return;
    setMessage(null);
    const res = await apiJson(base, "POST", { group_id: groupId, role_id: roleId });
    if (!res.ok) {
      setMessage(res.status === 409 ? t("access.duplicate") : res.error ?? t("common.error"));
      return;
    }
    setGroupId("");
    setRoleId("");
    await load();
  };
  const remove = async (b: Binding) => {
    if (!window.confirm(t("access.removeConfirm", { group: b.group_name, role: b.role_name }))) return;
    setMessage(null);
    const res = await apiJson(`/api/v1/bindings/${b.id}`, "DELETE");
    if (!res.ok) setMessage(res.error ?? t("common.error"));
    await load();
  };
  // Снять привязку можно по тому же правилу «не сильнее своих», что и выдать
  const canRemove = (b: Binding) => canManage && roles.some((r) => r.id === b.role_id && r.grantable);

  const table = (rows: Binding[], own: boolean) => (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr style={{ textAlign: "left", color: "var(--text-secondary)", fontSize: 12 }}>
          <th style={{ padding: "4px 8px", fontWeight: 500 }}>{t("access.group")}</th>
          <th style={{ padding: "4px 8px", fontWeight: 500 }}>{t("access.role")}</th>
          <th style={{ padding: "4px 8px", fontWeight: 500 }}>{own ? t("access.since") : t("access.source")}</th>
          {own && canManage && <th />}
        </tr>
      </thead>
      <tbody>
        {rows.map((b) => (
          <tr key={b.id}>
            <td style={CELL}>{b.group_name}</td>
            <td style={CELL}>{b.role_name}</td>
            <td style={{ ...CELL, color: "var(--text-muted)" }}>
              {own
                ? formatDate(b.created_at)
                : b.entity_path === null
                  ? t("access.wholeTree")
                  : t("access.from", { path: b.entity_path })}
            </td>
            {own && canManage && (
              <td style={{ ...CELL, textAlign: "right" }}>
                {canRemove(b) ? (
                  <button style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => void remove(b)}>
                    {t("access.remove")}
                  </button>
                ) : (
                  <span style={HINT} title={t("access.cannotRemoveHint")}>
                    {t("access.cannotRemove")}
                  </span>
                )}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );

  return (
    <>
      {message && (
        <p role="status" style={{ fontSize: 13, color: "var(--accent)" }}>
          {message}
        </p>
      )}

      <section className="card" style={SECTION}>
        <div className="section-label">{t("access.ownTitle")}</div>
        {data.own.length === 0 ? <p style={HINT}>{t("access.ownEmpty")}</p> : table(data.own, true)}

        {canManage && (
          <div style={{ marginTop: 12 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <select value={groupId} onChange={(e) => setGroupId(e.target.value)} aria-label={t("access.group")}>
                <option value="">{t("access.pickGroup")}</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
              </select>
              <select value={roleId} onChange={(e) => setRoleId(e.target.value)} aria-label={t("access.role")}>
                <option value="">{t("access.pickRole")}</option>
                {grantable.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
                {locked.map((r) => (
                  <option key={r.id} value={r.id} disabled>
                    {r.name} — {t("access.locked")}
                  </option>
                ))}
              </select>
              <button style={PRIMARY_BUTTON} disabled={!groupId || !roleId} onClick={() => void add()}>
                {t("access.add")}
              </button>
            </div>
            {locked.length > 0 && (
              <div style={{ ...HINT, marginTop: 8 }}>
                <div>{t("access.lockedHint")}</div>
                <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                  {locked.map((r) => (
                    <li key={r.id}>
                      {r.name}: {r.missing.map(permLabel).join(", ")}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>

      <section className="card" style={SECTION}>
        <div className="section-label">{t("access.inheritedTitle")}</div>
        <p style={{ ...HINT, marginTop: 0 }}>{t("access.inheritedHint")}</p>
        {data.inherited.length === 0 ? <p style={HINT}>{t("access.inheritedEmpty")}</p> : table(data.inherited, false)}
      </section>
    </>
  );
}
