import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiJson } from "../api/json";
import {
  MEMORIES_CHANGED,
  MEMORY_STATUSES,
  REASON_TAGS,
  type EntityNode,
  type Memory,
  type MemoryDecision,
  type MemoryStatus,
  type ReasonTag,
} from "../api/types";
import { useCan } from "../auth/AuthContext";
import { Modal } from "../components/Modal";
import { Tabs } from "../components/Tabs";
import { MONO, PRIMARY_BUTTON } from "../components/ui";

const inputStyle = {
  fontFamily: "inherit",
  fontSize: 13,
  color: "var(--text-primary)",
  background: "var(--bg-page)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  padding: "6px 10px",
} as const;

const cell = { padding: "8px 12px", verticalAlign: "top" } as const;
const head = { padding: "8px 12px", fontWeight: 500 } as const;
const fieldLabel = { display: "grid", gap: 4, fontSize: 13 } as const;

const CONDITIONS = [
  { field: "scanner", label: "memory.scanner" },
  { field: "rule_id", label: "memory.ruleId" },
  { field: "cwe", label: "memory.cwe" },
  { field: "path_glob", label: "memory.pathGlob" },
] as const;
type ConditionField = (typeof CONDITIONS)[number]["field"];

type Draft = Record<ConditionField, string> & {
  entity_id: string;
  decision: MemoryDecision;
  reason_tag: ReasonTag;
  reason: string;
};

function toDraft(m: Memory | null, defaultEntity: string): Draft {
  return {
    entity_id: m?.entity_id ?? defaultEntity,
    scanner: m?.scanner ?? "",
    rule_id: m?.rule_id ?? "",
    cwe: m?.cwe ?? "",
    path_glob: m?.path_glob ?? "",
    decision: m?.decision ?? "false_positive",
    reason_tag: m?.reason_tag ?? "test_code",
    reason: m?.reason ?? "",
  };
}

function MemoryForm({
  memory,
  entities,
  defaultEntity,
  onClose,
  onSaved,
}: {
  memory: Memory | null;
  entities: EntityNode[];
  defaultEntity: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<Draft>(() => toDraft(memory, defaultEntity));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isFp = draft.decision === "false_positive";
  const reasonRequired = !isFp || draft.reason_tag === "other";
  const hasCondition = CONDITIONS.some(({ field }) => draft[field].trim());
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const save = async () => {
    if (!hasCondition) {
      setError(t("memory.conditionRequired"));
      return;
    }
    const body: Record<string, unknown> = {
      entity_id: draft.entity_id,
      decision: draft.decision,
      reason_tag: isFp ? draft.reason_tag : null,
      reason: draft.reason.trim() || null,
    };
    for (const { field } of CONDITIONS) body[field] = draft[field].trim() || null;
    setSaving(true);
    setError(null);
    const res = memory
      ? await apiJson<Memory>(`/api/v1/memories/${memory.id}`, "PATCH", body)
      : await apiJson<Memory>("/api/v1/memories", "POST", body);
    setSaving(false);
    if (res.ok) {
      onSaved();
      onClose();
    } else if (res.status === 403) setError(t("common.forbidden"));
    else setError(res.error || t("memory.saveError"));
  };

  return (
    <Modal title={memory ? t("memory.editTitle") : t("memory.create")} onClose={onClose}>
      <div style={{ display: "grid", gap: 10, minWidth: 380 }}>
        <label style={fieldLabel}>
          {t("memory.scope")}
          <select style={inputStyle} value={draft.entity_id} onChange={(e) => set({ entity_id: e.target.value })}>
            {/* область правила, на которую у пользователя уже нет права, остаётся в списке — иначе правка её сбросит */}
            {memory && !entities.some((e) => e.id === memory.entity_id) && (
              <option value={memory.entity_id}>{memory.entity_path}</option>
            )}
            {entities.map((e) => (
              <option key={e.id} value={e.id}>
                {e.path}
              </option>
            ))}
          </select>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("memory.scopeHint")}</span>
        </label>

        <fieldset style={{ border: "none", padding: 0, margin: 0, display: "grid", gap: 8 }}>
          <legend style={{ fontSize: 13, padding: 0, marginBottom: 4 }}>{t("memory.condition")}</legend>
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("memory.conditionHint")}</div>
          {CONDITIONS.map(({ field, label }) => (
            <label key={field} style={fieldLabel}>
              {t(label)}
              <input
                style={{ ...inputStyle, ...MONO }}
                value={draft[field]}
                onChange={(e) => set({ [field]: e.target.value } as Partial<Draft>)}
              />
              {field === "path_glob" && (
                <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("memory.pathGlobHint")}</span>
              )}
            </label>
          ))}
        </fieldset>

        <label style={fieldLabel}>
          {t("memory.decision")}
          <select
            style={inputStyle}
            value={draft.decision}
            onChange={(e) => set({ decision: e.target.value as MemoryDecision })}
          >
            <option value="false_positive">{t("decision.type.false_positive")}</option>
            <option value="risk_accepted">{t("decision.type.risk_accepted")}</option>
          </select>
        </label>
        {isFp && (
          <label style={fieldLabel}>
            {t("memory.reasonTag")}
            <select
              style={inputStyle}
              value={draft.reason_tag}
              onChange={(e) => set({ reason_tag: e.target.value as ReasonTag })}
            >
              {REASON_TAGS.map((tag) => (
                <option key={tag} value={tag}>
                  {t(`decision.tags.${tag}`)}
                </option>
              ))}
            </select>
          </label>
        )}
        <label style={fieldLabel}>
          {t(reasonRequired ? "decision.reasonRequired" : "decision.reasonOptional")}
          <textarea
            rows={3}
            value={draft.reason}
            onChange={(e) => set({ reason: e.target.value })}
            style={{ ...inputStyle, resize: "vertical" }}
          />
        </label>

        {memory?.status === "approved" && (
          <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("memory.recomputeHint")}</div>
        )}
        {error && (
          <div role="alert" style={{ color: "var(--sev-critical-text)", fontSize: 12 }}>
            {error}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}>{t("common.cancel")}</button>
          <button
            style={PRIMARY_BUTTON}
            onClick={save}
            disabled={saving || !draft.entity_id || (reasonRequired && !draft.reason.trim())}
          >
            {saving ? t("common.loading") : t("common.save")}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export function Memories() {
  const { t } = useTranslation();
  const can = useCan();
  const [tab, setTab] = useState<MemoryStatus>("approved");
  const [entityFilter, setEntityFilter] = useState("");
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [entities, setEntities] = useState<EntityNode[]>([]);
  // undefined — окно закрыто, null — новое правило
  const [editing, setEditing] = useState<Memory | null | undefined>(undefined);
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ status: tab, limit: "200" });
    if (entityFilter) {
      params.set("entity_id", entityFilter);
      params.set("include_descendants", "true");
    }
    // вкладку и фильтр переключают быстрее, чем приходит ответ — берём только последний
    const id = ++requestId.current;
    const res = await apiJson<Memory[]>(`/api/v1/memories?${params}`);
    if (id !== requestId.current) return;
    if (res.ok) {
      setMemories(res.data ?? []);
      setLoadError(null);
    } else setLoadError(res.status === 403 ? t("common.forbidden") : t("common.error"));
  }, [tab, entityFilter, t]);

  useEffect(() => {
    setMemories(null);
    void load();
  }, [load]);

  useEffect(() => {
    void apiJson<EntityNode[]>("/api/v1/entities").then((r) =>
      setEntities((r.data ?? []).filter((e) => !e.stub).sort((a, b) => a.path.localeCompare(b.path))),
    );
  }, []);

  const manageable = entities.filter((e) => can("memory:manage", e.path));
  const canCreate = manageable.length > 0;

  const changed = () => {
    window.dispatchEvent(new Event(MEMORIES_CHANGED));
    void load();
  };

  const setStatus = async (m: Memory, status: "approved" | "disabled") => {
    setActionError(null);
    const res = await apiJson(`/api/v1/memories/${m.id}`, "PATCH", { status });
    if (!res.ok) setActionError(res.status === 403 ? t("common.forbidden") : res.error || t("memory.saveError"));
    changed();
  };

  const showActions = memories?.some((m) => m.can_manage) ?? false;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1>{t("memory.title")}</h1>
        {canCreate && (
          <button style={PRIMARY_BUTTON} onClick={() => setEditing(null)}>
            {t("memory.create")}
          </button>
        )}
      </div>
      <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 0, maxWidth: 760 }}>{t("memory.intro")}</p>

      <Tabs
        label={t("memory.tabsLabel")}
        tabs={MEMORY_STATUSES.map((id) => ({ id, label: t(`memory.tabs.${id}`) }))}
        value={tab}
        onChange={setTab}
      />

      <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center" }}>
        <select
          style={{ ...inputStyle, minWidth: 220 }}
          value={entityFilter}
          onChange={(e) => setEntityFilter(e.target.value)}
          aria-label={t("memory.scope")}
        >
          <option value="">{t("memory.allProjects")}</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>
              {e.path}
            </option>
          ))}
        </select>
      </div>

      {actionError && (
        <div role="alert" style={{ color: "var(--sev-critical-text)", fontSize: 12, marginBottom: 8 }}>
          {actionError}
        </div>
      )}

      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        {loadError ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{loadError}</p>
        ) : !memories ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("common.loading")}</p>
        ) : memories.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("memory.empty")}</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                <th style={head}>{t("memory.condition")}</th>
                <th style={head}>{t("memory.scope")}</th>
                <th style={{ ...head, minWidth: 220 }}>{t("memory.decision")}</th>
                <th style={head}>{t("memory.source")}</th>
                <th style={head}>{t("memory.openFindings")}</th>
                {showActions && <th style={head} />}
              </tr>
            </thead>
            <tbody>
              {memories.map((m) => (
                <tr key={m.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={cell}>
                    <dl style={{ display: "grid", gridTemplateColumns: "max-content 1fr", gap: "2px 8px", margin: 0 }}>
                      {CONDITIONS.filter(({ field }) => m[field]).map(({ field, label }) => (
                        <div key={field} style={{ display: "contents" }}>
                          <dt style={{ fontSize: 12, color: "var(--text-muted)" }}>{t(label)}</dt>
                          <dd style={{ margin: 0, ...MONO, wordBreak: "break-all" }}>{m[field]}</dd>
                        </div>
                      ))}
                    </dl>
                  </td>
                  <td style={{ ...cell, ...MONO }}>{m.entity_path}</td>
                  <td style={cell}>
                    <div style={{ fontWeight: 500 }}>
                      {t(`decision.type.${m.decision}`)}
                      {m.reason_tag && (
                        <span style={{ fontWeight: 400, color: "var(--text-secondary)" }}>
                          {" — "}
                          {t(`decision.tags.${m.reason_tag}`)}
                        </span>
                      )}
                    </div>
                    {m.reason && (
                      <div style={{ color: "var(--text-secondary)", whiteSpace: "pre-wrap", fontSize: 12 }}>
                        {m.reason}
                      </div>
                    )}
                  </td>
                  <td style={{ ...cell, fontSize: 12, color: "var(--text-secondary)" }}>
                    {t(`memory.sourceValue.${m.source}`)}
                  </td>
                  <td style={{ ...cell, ...MONO }}>{m.open_findings}</td>
                  {showActions && (
                    <td style={{ ...cell, whiteSpace: "nowrap", textAlign: "right" }}>
                      {m.can_manage && (
                        <>
                          <button onClick={() => setEditing(m)}>{t("memory.edit")}</button>{" "}
                          {m.status === "suggested" && (
                            <>
                              <button style={PRIMARY_BUTTON} onClick={() => void setStatus(m, "approved")}>
                                {t("memory.approve")}
                              </button>{" "}
                              <button onClick={() => void setStatus(m, "disabled")}>{t("memory.reject")}</button>
                            </>
                          )}
                          {m.status === "approved" && (
                            <button onClick={() => void setStatus(m, "disabled")}>{t("memory.disable")}</button>
                          )}
                          {m.status === "disabled" && (
                            <button onClick={() => void setStatus(m, "approved")}>{t("memory.enable")}</button>
                          )}
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
        <MemoryForm
          memory={editing}
          entities={manageable}
          defaultEntity={manageable.find((e) => e.id === entityFilter)?.id ?? manageable[0]?.id ?? ""}
          onClose={() => setEditing(undefined)}
          onSaved={changed}
        />
      )}
    </div>
  );
}
