import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { apiFetch } from "../api/client";
import { apiJson, type ApiResult } from "../api/json";
import type { EntityNode, EntitySettings, Group, SettingField, SettingValue, SlaPolicy } from "../api/types";
import { useCan } from "../auth/AuthContext";
import { AuditTable } from "../components/AuditTable";
import { Tabs } from "../components/Tabs";
import { MONO, PRIMARY_BUTTON, formatDateTime } from "../components/ui";
import { ProjectAccess } from "./ProjectAccess";

const FIELDS: SettingField[] = ["default_branch", "owner_group_id", "repo_url", "repo_type", "repo_path_prefix"];
const REPO_TYPES = ["gitlab", "github", "gitea", "bitbucket"];
const LABELS: Record<SettingField, string> = {
  default_branch: "settings.defaultBranch",
  owner_group_id: "settings.owner",
  repo_url: "settings.repoUrl",
  repo_type: "settings.repoType",
  repo_path_prefix: "settings.repoPrefix",
};
// Поля репозитория закрепляются и возвращаются к файлу вместе (ключ "repo")
const PIN_OF: Record<SettingField, string> = {
  default_branch: "default_branch",
  owner_group_id: "owner_group_id",
  repo_url: "repo",
  repo_type: "repo",
  repo_path_prefix: "repo",
};
const SHOW_REVERT: SettingField[] = ["default_branch", "owner_group_id", "repo_url"];
const SECTION = { marginBottom: 16 } as const;
const HINT = { fontSize: 11, color: "var(--text-muted)" } as const;
const TAG = {
  display: "inline-flex",
  alignItems: "center",
  fontSize: 12,
  padding: "2px 8px",
  borderRadius: 999,
  border: "1px solid var(--border)",
  background: "var(--bg-page)",
} as const;

type Draft = Record<SettingField, string>;
interface RuleDraft {
  pattern: string;
  group_id: string;
}

/** Собственное значение узла (не унаследованное) — то, что редактируется. */
function ownValue(v: SettingValue): string {
  return v.source === "manual" || v.source === "file" ? String(v.value ?? "") : "";
}

export function ProjectSettings() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const can = useCan();
  const [tab, setTab] = useState<"settings" | "access" | "audit">("settings");
  const [entity, setEntity] = useState<EntityNode | null>(null);
  // Права — на этом проекте (страница рисуется только после загрузки entity)
  const editable = can("entity:write", entity?.path);
  const canAssignSla = can("sla:assign", entity?.path);
  const canAudit = can("audit:read", entity?.path);
  const [settings, setSettings] = useState<EntitySettings | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [rules, setRules] = useState<RuleDraft[]>([]);
  const [slug, setSlug] = useState("");
  // "" — наследовать политику
  const [slaDraft, setSlaDraft] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [policies, setPolicies] = useState<SlaPolicy[]>([]);
  const [knownTags, setKnownTags] = useState<string[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const apply = useCallback((s: EntitySettings) => {
    setSettings(s);
    setDraft(Object.fromEntries(FIELDS.map((f) => [f, ownValue(s.fields[f])])) as Draft);
    setRules(s.ownership_rules.map((r) => ({ pattern: r.pattern, group_id: r.group_id })));
    setSlaDraft(s.sla.own ? (s.sla.policy_id ?? "") : "");
    setTags(s.tags);
    if (s.warnings.length > 0) setMessage(s.warnings.join("; "));
  }, []);

  const load = useCallback(async () => {
    const [e, s] = await Promise.all([
      apiJson<EntityNode>(`/api/v1/entities/${id}`),
      apiJson<EntitySettings>(`/api/v1/entities/${id}/settings`),
    ]);
    if (!e.ok || !e.data || !s.ok || !s.data) {
      setLoadError(e.status === 404 ? t("common.notFound") : t("common.error"));
      return;
    }
    setEntity(e.data);
    setSlug(e.data.slug);
    apply(s.data);
  }, [id, t, apply]);

  useEffect(() => {
    void load();
  }, [load]);

  const canSeeGroups = can("group:read");
  useEffect(() => {
    if (canSeeGroups) void apiJson<Group[]>("/api/v1/groups").then((r) => setGroups(r.data ?? []));
  }, [canSeeGroups]);

  const canSeeSla = can("sla:read");
  useEffect(() => {
    if (canSeeSla) void apiJson<SlaPolicy[]>("/api/v1/sla-policies").then((r) => setPolicies(r.data ?? []));
    void apiJson<string[]>("/api/v1/tags").then((r) => setKnownTags(r.data ?? []));
  }, [canSeeSla]);

  if (loadError) return <p style={{ color: "var(--text-muted)" }}>{loadError}</p>;
  if (!entity || !settings || !draft) return <p style={{ color: "var(--text-muted)" }}>{t("common.loading")}</p>;

  const base = `/api/v1/entities/${id}`;
  const report = (res: ApiResult<unknown>) =>
    setMessage(res.ok ? t("common.saved") : res.error ?? (res.status === 409 ? t("settings.repoConflict") : t("common.error")));
  const applyResult = (res: ApiResult<EntitySettings>) => {
    report(res);
    if (res.ok && res.data) apply(res.data);
  };

  const saveFields = async () => {
    const changed: Record<string, string | null> = {};
    for (const f of FIELDS) {
      if (draft[f] !== ownValue(settings.fields[f])) changed[f] = draft[f].trim() || null;
    }
    if (Object.keys(changed).length === 0) return;
    applyResult(await apiJson<EntitySettings>(`${base}/settings`, "PATCH", changed));
  };
  const saveSlug = async () => {
    const res = await apiJson<EntityNode>(base, "PATCH", { slug: slug.trim() });
    report(res);
    if (res.ok && res.data) {
      setEntity(res.data);
      await load();
    }
  };
  const saveRules = async () => {
    const body = rules
      .filter((r) => r.pattern.trim() && r.group_id)
      .map((r) => ({ pattern: r.pattern.trim(), group_id: r.group_id }));
    applyResult(await apiJson<EntitySettings>(`${base}/ownership-rules`, "PUT", body));
  };
  const revert = async (field: string) =>
    applyResult(await apiJson<EntitySettings>(`${base}/settings/unpin`, "POST", { field }));
  const reassign = async () => {
    const res = await apiJson<{ reassigned: number }>(`${base}/reassign`, "POST");
    setMessage(res.ok && res.data ? t("settings.reassigned", { count: res.data.reassigned }) : res.error ?? t("common.error"));
  };
  const download = async () => {
    const res = await apiFetch(`${base}/config.yml`);
    if (!res.ok) {
      setMessage(t("common.error"));
      return;
    }
    const url = URL.createObjectURL(await res.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = ".secretvuln.yml";
    link.click();
    URL.revokeObjectURL(url);
  };
  const saveSlaTags = async () => {
    // тег, набранный без Enter, тоже сохраняем
    const pending = tagInput.trim().toLowerCase();
    const nextTags = pending && !tags.includes(pending) ? [...tags, pending] : tags;
    const body: Record<string, unknown> = {};
    if (slaDraft !== (settings.sla.own ? (settings.sla.policy_id ?? "") : "")) body.sla_policy_id = slaDraft || null;
    if (nextTags.join(",") !== settings.tags.join(",")) body.tags = nextTags;
    if (Object.keys(body).length === 0) return;
    const res = await apiJson<EntitySettings>(`${base}/settings`, "PATCH", body);
    // при ошибке набранный тег остаётся в поле, чтобы его можно было поправить
    if (res.ok) setTagInput("");
    applyResult(res);
  };
  const addTag = () => {
    const tag = tagInput.trim().toLowerCase();
    if (tag && !tags.includes(tag)) setTags([...tags, tag]);
    setTagInput("");
  };
  const ownTags = new Set(tags);
  const inheritedTags = settings.effective_tags.filter((e) => e.inherited_from && !ownTags.has(e.tag));
  const slaSource = settings.sla.own
    ? t("settings.source.manual")
    : settings.sla.inherited_from
      ? t("settings.source.inherited", { from: settings.sla.inherited_from })
      : t("settings.slaDefault");
  const moveRule = (index: number, delta: number) =>
    setRules((prev) => {
      const target = index + delta;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  const updateRule = (index: number, patch: Partial<RuleDraft>) =>
    setRules((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  const groupName = (groupId: string | null) => groups.find((g) => g.id === groupId)?.name ?? groupId ?? "";
  const sourceLabel = (v: SettingValue) =>
    v.source === "inherited"
      ? t("settings.source.inherited", { from: v.inherited_from })
      : t(`settings.source.${v.source}`);
  const canRevert = (pin: string) => editable && settings.has_config_file && settings.pinned_fields.includes(pin);

  const renderInput = (f: SettingField, v: SettingValue) => {
    const inherited = v.source === "inherited" ? String(v.value ?? "") : "";
    const onChange = (value: string) => setDraft({ ...draft, [f]: value });
    if (f === "owner_group_id" || f === "repo_type") {
      const options = f === "owner_group_id" ? groups.map((g) => ({ value: g.id, label: g.name })) : REPO_TYPES.map((r) => ({ value: r, label: r }));
      const emptyLabel = inherited ? (f === "owner_group_id" ? groupName(inherited) : inherited) : t("settings.choose");
      return (
        <select id={`sv-${f}`} disabled={!editable} value={draft[f]} onChange={(e) => onChange(e.target.value)}>
          <option value="">{emptyLabel}</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        id={`sv-${f}`}
        disabled={!editable}
        value={draft[f]}
        placeholder={inherited}
        onChange={(e) => onChange(e.target.value)}
        style={{ minWidth: 280 }}
      />
    );
  };

  return (
    <div style={{ maxWidth: 900 }}>
      <Link to="/projects" style={{ fontSize: 12 }}>
        ← {t("settings.back")}
      </Link>
      <h1 style={{ marginBottom: 4 }}>{entity.name}</h1>
      <div style={{ ...MONO, color: "var(--text-secondary)", marginBottom: 16 }}>{entity.path}</div>
      {message && (
        <p role="status" style={{ fontSize: 13, color: "var(--accent)" }}>
          {message}
        </p>
      )}

      <Tabs
        label={t("settings.tabs")}
        tabs={[
          { id: "settings", label: t("settings.tabSettings") },
          { id: "access", label: t("access.tab") },
          ...(canAudit ? [{ id: "audit" as const, label: t("audit.tab") }] : []),
        ]}
        value={tab === "audit" && !canAudit ? "settings" : tab}
        onChange={setTab}
      />
      {tab === "audit" && canAudit ? (
        <AuditTable key={entity.id} query={{ entity_id: entity.id, subtree: true }} />
      ) : tab === "access" ? (
        <ProjectAccess key={entity.id} entity={entity} />
      ) : (
      <>
      <section className="card" style={SECTION}>
        <div className="section-label">{t("settings.configFile")}</div>
        <p style={{ fontSize: 13, marginTop: 0 }}>
          {settings.has_config_file && settings.config_applied_at
            ? t("settings.configApplied", {
                date: formatDateTime(settings.config_applied_at),
                commit: settings.config_commit_sha?.slice(0, 12) ?? t("common.none"),
              })
            : t("settings.noConfig")}
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button onClick={download}>{t("settings.downloadConfig")}</button>
          {editable && <button onClick={reassign}>{t("settings.reassign")}</button>}
        </div>
      </section>

      <section className="card" style={SECTION}>
        <div className="section-label">{t("settings.title")}</div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(160px, max-content) 1fr",
            gap: "10px 16px",
            alignItems: "center",
          }}
        >
          <label htmlFor="sv-slug" style={{ fontSize: 13 }}>
            {t("settings.slug")}
          </label>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              id="sv-slug"
              disabled={!editable}
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              style={{ ...MONO, minWidth: 200 }}
            />
            {editable && slug !== entity.slug && <button onClick={saveSlug}>{t("common.save")}</button>}
          </div>
          {FIELDS.map((f) => {
            const v = settings.fields[f];
            return (
              <div key={f} style={{ display: "contents" }}>
                <label htmlFor={`sv-${f}`} style={{ fontSize: 13 }}>
                  {t(LABELS[f])}
                </label>
                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  {renderInput(f, v)}
                  <span style={HINT}>{sourceLabel(v)}</span>
                  {SHOW_REVERT.includes(f) && canRevert(PIN_OF[f]) && (
                    <button style={{ fontSize: 11 }} onClick={() => void revert(PIN_OF[f])}>
                      {t("settings.revert")}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {editable && (
          <button style={{ ...PRIMARY_BUTTON, marginTop: 12 }} onClick={saveFields}>
            {t("common.save")}
          </button>
        )}
      </section>

      <section className="card" style={SECTION}>
        <div className="section-label">{t("settings.slaTitle")}</div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(160px, max-content) 1fr",
            gap: "10px 16px",
            alignItems: "center",
          }}
        >
          <label htmlFor="sv-sla" style={{ fontSize: 13 }}>
            {t("settings.slaPolicy")}
          </label>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <select
              id="sv-sla"
              disabled={!editable || !canSeeSla || !canAssignSla}
              value={slaDraft}
              onChange={(e) => setSlaDraft(e.target.value)}
            >
              <option value="">
                {settings.sla.own
                  ? t("settings.slaInheritPlain")
                  : t("settings.slaInherit", { name: settings.sla.policy_name ?? t("common.none") })}
              </option>
              {policies.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <span style={HINT}>{slaSource}</span>
          </div>
          <label htmlFor="sv-tag" style={{ fontSize: 13 }}>
            {t("settings.tags")}
          </label>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            {tags.map((tag) => (
              <span key={tag} style={TAG}>
                {tag}
                {editable && (
                  <button
                    aria-label={t("settings.removeTag", { tag })}
                    onClick={() => setTags(tags.filter((x) => x !== tag))}
                    style={{ border: "none", background: "none", padding: 0, marginLeft: 4, cursor: "pointer", color: "inherit" }}
                  >
                    ×
                  </button>
                )}
              </span>
            ))}
            {inheritedTags.map((e) => (
              <span key={e.tag} style={{ ...TAG, opacity: 0.6 }} title={t("settings.source.inherited", { from: e.inherited_from })}>
                {e.tag}
              </span>
            ))}
            {editable && (
              <>
                <input
                  id="sv-tag"
                  list="sv-known-tags"
                  value={tagInput}
                  placeholder={t("settings.addTag")}
                  onChange={(e) => setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addTag();
                    }
                  }}
                  style={{ width: 160 }}
                />
                <datalist id="sv-known-tags">
                  {knownTags.map((tag) => (
                    <option key={tag} value={tag} />
                  ))}
                </datalist>
              </>
            )}
            {tags.length === 0 && inheritedTags.length === 0 && !editable && <span style={HINT}>{t("common.none")}</span>}
          </div>
        </div>
        <p style={{ ...HINT, marginBottom: 0 }}>{t("settings.slaHint")}</p>
        {editable && (
          <button style={{ ...PRIMARY_BUTTON, marginTop: 12 }} onClick={saveSlaTags}>
            {t("common.save")}
          </button>
        )}
      </section>

      <section className="card" style={SECTION}>
        <div className="section-label">
          {t("settings.rules")} <span style={HINT}>({t(`settings.source.${settings.rules_source}`)})</span>
        </div>
        <p style={{ ...HINT, fontSize: 12, marginTop: 0 }}>{t("settings.rulesHint")}</p>
        {rules.map((rule, i) => (
          <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6, alignItems: "center" }}>
            <input
              aria-label={t("settings.pattern")}
              placeholder="app/payments/**"
              disabled={!editable}
              value={rule.pattern}
              onChange={(e) => updateRule(i, { pattern: e.target.value })}
              style={{ ...MONO, flex: 1 }}
            />
            <select
              aria-label={t("team.label")}
              disabled={!editable}
              value={rule.group_id}
              onChange={(e) => updateRule(i, { group_id: e.target.value })}
            >
              <option value="">{t("settings.choose")}</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
            {editable && (
              <>
                <button aria-label={t("settings.up")} onClick={() => moveRule(i, -1)}>
                  ↑
                </button>
                <button aria-label={t("settings.down")} onClick={() => moveRule(i, 1)}>
                  ↓
                </button>
                <button aria-label={t("settings.remove")} onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                  ✕
                </button>
              </>
            )}
          </div>
        ))}
        {editable && (
          <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            <button onClick={() => setRules([...rules, { pattern: "", group_id: "" }])}>+ {t("settings.addRule")}</button>
            <button style={PRIMARY_BUTTON} onClick={saveRules}>
              {t("settings.saveRules")}
            </button>
            {canRevert("ownership_rules") && (
              <button onClick={() => void revert("ownership_rules")}>{t("settings.revert")}</button>
            )}
          </div>
        )}
        {settings.inherited_rules.length > 0 && (
          <>
            <div className="section-label" style={{ marginTop: 16 }}>
              {t("settings.inheritedRules")}
            </div>
            <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
              <tbody>
                {settings.inherited_rules.map((r, i) => (
                  <tr key={i}>
                    <td style={{ ...MONO, padding: "4px 8px 4px 0" }}>{r.pattern}</td>
                    <td style={{ padding: "4px 8px" }}>{r.group_name}</td>
                    <td style={{ padding: "4px 0", color: "var(--text-muted)" }}>{r.entity_path}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
      </>
      )}
    </div>
  );
}
