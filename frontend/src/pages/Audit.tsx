import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiJson } from "../api/json";
import { AUDIT_ACTION_GROUPS, type AuditQuery, type EntityNode } from "../api/types";
import { AuditTable } from "../components/AuditTable";

const inputStyle = {
  fontFamily: "inherit",
  fontSize: 13,
  color: "var(--text-primary)",
  background: "var(--bg-page)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  padding: "6px 10px",
};

export function Audit() {
  const { t } = useTranslation();
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [actorInput, setActorInput] = useState("");
  const [actor, setActor] = useState("");
  const [group, setGroup] = useState("");
  const [entityId, setEntityId] = useState("");

  useEffect(() => {
    void apiJson<EntityNode[]>("/api/v1/entities").then((r) => {
      if (r.ok && r.data) setEntities(r.data.filter((e) => !e.stub));
    });
  }, []);

  // Поиск по автору — после паузы в наборе, чтобы не дёргать API на каждую букву
  useEffect(() => {
    const id = setTimeout(() => setActor(actorInput), 300);
    return () => clearTimeout(id);
  }, [actorInput]);

  const query = useMemo<AuditQuery>(
    () => ({
      entity_id: entityId || undefined,
      actor: actor || undefined,
      action: group ? AUDIT_ACTION_GROUPS[group] : undefined,
      // даты из полей — локальные сутки целиком
      date_from: dateFrom ? new Date(`${dateFrom}T00:00:00`).toISOString() : undefined,
      date_to: dateTo ? new Date(`${dateTo}T23:59:59.999`).toISOString() : undefined,
    }),
    [entityId, actor, group, dateFrom, dateTo],
  );

  return (
    <div>
      <h1>{t("audit.title")}</h1>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginBottom: 12 }}>
        <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
          {t("audit.dateFrom")}
          <input type="date" style={inputStyle} value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </label>
        <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
          {t("audit.dateTo")}
          <input type="date" style={inputStyle} value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </label>
        <input
          style={{ ...inputStyle, minWidth: 180 }}
          value={actorInput}
          onChange={(e) => setActorInput(e.target.value)}
          placeholder={t("audit.actorPlaceholder")}
          aria-label={t("audit.actor")}
        />
        <select
          style={{ ...inputStyle, minWidth: 160 }}
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          aria-label={t("audit.action.label")}
        >
          <option value="">{t("audit.allActions")}</option>
          {Object.keys(AUDIT_ACTION_GROUPS).map((g) => (
            <option key={g} value={g}>
              {t(`audit.group.${g}`)}
            </option>
          ))}
        </select>
        <select
          style={{ ...inputStyle, minWidth: 200 }}
          value={entityId}
          onChange={(e) => setEntityId(e.target.value)}
          aria-label={t("audit.project")}
        >
          <option value="">{t("audit.allProjects")}</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>
              {e.path}
            </option>
          ))}
        </select>
      </div>

      <AuditTable query={query} />
    </div>
  );
}
