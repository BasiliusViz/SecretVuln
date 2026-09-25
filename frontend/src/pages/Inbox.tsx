import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";

import { apiJson } from "../api/json";
import type { BulkResult, EntityNode, Finding, Group } from "../api/types";
import { DecisionDialog, type DecisionBody } from "../components/DecisionDialog";
import { SeverityBadge } from "../components/SeverityBadge";
import { Tabs } from "../components/Tabs";
import { MONO } from "../components/ui";

type Tab = "new" | "requests" | "questions" | "unassigned";
const TABS: Tab[] = ["new", "requests", "questions", "unassigned"];
const OPEN = "status=new&status=triaged&status=confirmed&status=in_progress";
const QUERIES: Record<Tab, string> = {
  new: "status=new&order=number",
  requests: "pending_decision=true&order=number",
  questions: `help_requested=true&${OPEN}&order=number`,
  unassigned: `unassigned=true&${OPEN}&order=severity`,
};
const CELL = { padding: "8px 12px" } as const;

export function Inbox() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("new");
  const [items, setItems] = useState<Finding[] | null>(null);
  const [cursor, setCursor] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [groups, setGroups] = useState<Group[]>([]);
  const [paths, setPaths] = useState<Record<string, string>>({});
  const [team, setTeam] = useState("");
  const [fpOpen, setFpOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const teamRef = useRef<HTMLSelectElement>(null);

  const load = useCallback(async () => {
    const res = await apiJson<Finding[]>(`/api/v1/findings?${QUERIES[tab]}&limit=200`);
    setItems(res.data ?? []);
    setCursor(0);
    setSelected(new Set());
  }, [tab]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void apiJson<Group[]>("/api/v1/groups").then((r) => setGroups(r.data ?? []));
    void apiJson<EntityNode[]>("/api/v1/entities").then((r) =>
      setPaths(Object.fromEntries((r.data ?? []).map((e) => [e.id, e.path]))),
    );
  }, []);

  // Действие применяется к отмеченным, а если ничего не отмечено — к строке под курсором
  const targets = useMemo(() => {
    if (selected.size > 0) return [...selected];
    const current = items?.[cursor];
    return current ? [current.id] : [];
  }, [selected, items, cursor]);

  const bulk = useCallback(
    async (body: Record<string, unknown>): Promise<string | null> => {
      if (targets.length === 0) return null;
      const res = await apiJson<BulkResult>("/api/v1/findings/bulk", "POST", { ids: targets, ...body });
      if (!res.ok || !res.data) return res.error ?? t("common.error");
      setMessage(t("inbox.result", { applied: res.data.applied, skipped: res.data.skipped.length }));
      await load();
      return null;
    },
    [targets, load, t],
  );

  const confirm = useCallback(async () => {
    const err = await bulk({ action: "confirm" });
    if (err) setMessage(err);
  }, [bulk]);

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (fpOpen || ["INPUT", "TEXTAREA", "SELECT"].includes(tag) || e.ctrlKey || e.metaKey || e.altKey) return;
      const list = items ?? [];
      const key = e.key.toLowerCase();
      if (key === "j") setCursor((c) => Math.min(c + 1, Math.max(list.length - 1, 0)));
      else if (key === "k") setCursor((c) => Math.max(c - 1, 0));
      else if (key === "x" && list[cursor]) toggle(list[cursor].id);
      else if (key === "c") void confirm();
      else if (key === "f") setFpOpen(true);
      else if (key === "a") teamRef.current?.focus();
      else if (e.key === "Enter" && list[cursor]) navigate(`/f/SV-${list[cursor].number}`);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, cursor, fpOpen, confirm, toggle, navigate]);

  const assign = async () => {
    if (!team) return;
    const err = await bulk({ action: "assign", group_id: team });
    if (err) setMessage(err);
    setTeam("");
  };
  const submitFp = (body: DecisionBody) =>
    bulk({ action: "false_positive", reason_tag: body.reason_tag, reason: body.reason });

  return (
    <div>
      <h1>{t("inbox.title")}</h1>
      <Tabs
        label={t("inbox.title")}
        tabs={TABS.map((id) => ({ id, label: t(`inbox.tabs.${id}`) }))}
        value={tab}
        onChange={setTab}
      />

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {t("inbox.selected", { count: targets.length })}
        </span>
        <button onClick={() => void confirm()} disabled={targets.length === 0}>
          {t("inbox.confirm")}
        </button>
        <button onClick={() => setFpOpen(true)} disabled={targets.length === 0}>
          {t("inbox.falsePositive")}
        </button>
        <select ref={teamRef} value={team} onChange={(e) => setTeam(e.target.value)} aria-label={t("inbox.pickTeam")}>
          <option value="">{t("inbox.pickTeam")}</option>
          {groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        <button onClick={assign} disabled={!team || targets.length === 0}>
          {t("inbox.assign")}
        </button>
        {message && (
          <span role="status" style={{ fontSize: 12, color: "var(--accent)" }}>
            {message}
          </span>
        )}
      </div>
      <p style={{ fontSize: 11, color: "var(--text-muted)", margin: "0 0 8px" }}>{t("inbox.hotkeys")}</p>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {items === null ? (
          <p style={{ padding: 16, margin: 0, color: "var(--text-muted)" }}>{t("common.loading")}</p>
        ) : items.length === 0 ? (
          <p style={{ padding: 16, margin: 0, color: "var(--text-muted)" }}>{t("inbox.empty")}</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <tbody>
              {items.map((f, i) => (
                <tr
                  key={f.id}
                  onClick={() => setCursor(i)}
                  aria-current={i === cursor}
                  style={{
                    borderBottom: "1px solid var(--border)",
                    background: i === cursor ? "var(--accent-bg)" : undefined,
                  }}
                >
                  <td style={{ ...CELL, width: 24 }}>
                    <input
                      type="checkbox"
                      checked={selected.has(f.id)}
                      onChange={() => toggle(f.id)}
                      aria-label={`SV-${f.number}`}
                    />
                  </td>
                  <td style={CELL}>
                    <SeverityBadge severity={f.severity} />
                  </td>
                  <td style={{ ...CELL, ...MONO, whiteSpace: "nowrap" }}>
                    <Link to={`/f/SV-${f.number}`}>SV-{f.number}</Link>
                  </td>
                  <td style={CELL}>
                    <div style={{ fontWeight: 500 }}>{f.title.slice(0, 120)}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                      {f.scanner} · {paths[f.entity_id] ?? "…"} · {f.assignee_group?.name ?? t("team.none")}
                    </div>
                  </td>
                  <td style={{ ...CELL, fontSize: 12 }}>{t(`status.${f.status}`)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {fpOpen && <DecisionDialog mode="false_positive" onSubmit={submitFp} onClose={() => setFpOpen(false)} />}
    </div>
  );
}
