import { Fragment, useEffect, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { fetchAudit } from "../api/audit";
import type { AuditEntry, AuditQuery } from "../api/types";
import { MONO, formatDateTime } from "./ui";

const PAGE_SIZE = 50;

// Ключи, у которых массив из двух элементов — это список, а не пара «было/стало»
const VALUE_KEYS = new Set(["added", "removed", "permissions"]);
// Значения, которые переводим по словарю, а не выводим как есть
const TRANSLATED = new Set(["reason", "source"]);

const CELL = { padding: "8px 12px" };
const TH = { ...CELL, fontWeight: 500 };

/** create/delete пишут снимок полей, остальные действия — пары `[было, стало]` */
function isSnapshot(action: string): boolean {
  return action.endsWith(".create") || action.endsWith(".delete");
}

function isDiff(action: string, key: string, value: unknown): value is [unknown, unknown] {
  return !isSnapshot(action) && Array.isArray(value) && value.length === 2 && !VALUE_KEYS.has(key);
}

/** Компактный вывод значения: списки примитивов — через запятую, объекты — JSON */
function formatValue(value: unknown, t: TFunction): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? t("audit.yes") : t("audit.no");
  if (typeof value === "number") return String(value);
  if (Array.isArray(value) && value.every((v) => v === null || typeof v !== "object")) {
    return value.length ? value.map((v) => formatValue(v, t)).join(", ") : "—";
  }
  return JSON.stringify(value);
}

function Changes({ action, changes }: { action: string; changes: Record<string, unknown> | null }) {
  const { t } = useTranslation();
  const entries = Object.entries(changes ?? {});
  const show = (key: string, v: unknown) =>
    TRANSLATED.has(key) && typeof v === "string" ? t(`audit.${key}.${v}`, { defaultValue: v }) : formatValue(v, t);
  if (entries.length === 0) {
    return <div style={{ color: "var(--text-muted)", fontSize: 12 }}>{t("audit.noChanges")}</div>;
  }
  return (
    <table style={{ borderCollapse: "collapse", fontSize: 12, width: "100%" }}>
      <thead>
        <tr style={{ textAlign: "left", color: "var(--text-muted)" }}>
          <th style={{ padding: "4px 8px", fontWeight: 500, width: "20%" }}>{t("audit.field")}</th>
          <th style={{ padding: "4px 8px", fontWeight: 500, width: "40%" }}>{t("audit.before")}</th>
          <th style={{ padding: "4px 8px", fontWeight: 500, width: "40%" }}>{t("audit.after")}</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, value]) => {
          const diff = isDiff(action, key, value);
          return (
            <tr key={key} style={{ borderTop: "1px solid var(--border)", verticalAlign: "top" }}>
              <td style={{ padding: "4px 8px" }}>{t(`audit.fieldName.${key}`, { defaultValue: key })}</td>
              <td style={{ padding: "4px 8px", ...MONO, wordBreak: "break-word", color: "var(--text-secondary)" }}>
                {diff ? show(key, value[0]) : "—"}
              </td>
              <td style={{ padding: "4px 8px", ...MONO, wordBreak: "break-word" }}>
                {show(key, diff ? value[1] : value)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * Таблица журнала аудита: строка раскрывается в таблицу изменений, пагинация по 50.
 * Фильтры приходят снаружи (`query` без limit/offset); при их смене — первая страница.
 */
export function AuditTable({ query, showProject = true }: { query: AuditQuery; showProject?: boolean }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const queryKey = JSON.stringify(query);
  useEffect(() => setOffset(0), [queryKey]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void fetchAudit({ ...query, limit: PAGE_SIZE, offset }).then((r) => {
      if (cancelled) return;
      setLoading(false);
      if (r.ok && r.data) {
        setItems(r.data.items);
        setTotal(r.data.total);
        setError(null);
      } else {
        setItems([]);
        setTotal(0);
        setError(
          r.status === 403 ? t("common.forbidden") : r.status === 404 ? t("common.notFound") : t("common.error"),
        );
      }
    });
    return () => {
      cancelled = true;
    };
    // query сравниваем по содержимому (queryKey), а не по ссылке
  }, [queryKey, offset, t]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const columns = showProject ? 6 : 5;

  return (
    <div>
      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        {error ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{error}</p>
        ) : items.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>
            {loading ? t("common.loading") : t("audit.empty")}
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                <th style={TH}>{t("audit.time")}</th>
                <th style={TH}>{t("audit.actor")}</th>
                <th style={TH}>{t("audit.action.label")}</th>
                <th style={TH}>{t("audit.target")}</th>
                {showProject && <th style={TH}>{t("audit.project")}</th>}
                <th style={TH}>{t("audit.ip")}</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => {
                const open = expanded.has(e.id);
                const deleted = e.entity_id === null && !!e.entity_path;
                return (
                  <Fragment key={e.id}>
                    <tr
                      onClick={() => toggle(e.id)}
                      aria-expanded={open}
                      style={{
                        borderBottom: "1px solid var(--border)",
                        cursor: "pointer",
                        background: open ? "var(--accent-bg)" : undefined,
                      }}
                    >
                      <td style={{ ...CELL, color: "var(--text-muted)", fontSize: 12, whiteSpace: "nowrap" }}>
                        <span style={{ display: "inline-block", width: 12 }}>{open ? "▾" : "▸"}</span>
                        {formatDateTime(e.created_at)}
                      </td>
                      <td style={CELL}>
                        {e.actor_type === "system" ? (
                          <span style={{ color: "var(--text-secondary)" }}>{t("audit.system")}</span>
                        ) : (
                          e.actor_label || "—"
                        )}
                      </td>
                      <td style={CELL}>{t(`audit.action.${e.action}`, { defaultValue: e.action })}</td>
                      <td style={CELL}>
                        <div>{e.target_label || "—"}</div>
                        {e.target_type && (
                          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                            {t(`audit.targetType.${e.target_type}`, { defaultValue: e.target_type })}
                          </div>
                        )}
                      </td>
                      {showProject && (
                        <td style={{ ...CELL, ...MONO, color: "var(--text-secondary)" }}>
                          {e.entity_path || "—"}
                          {deleted && (
                            <span style={{ color: "var(--text-muted)", marginLeft: 6 }}>{t("audit.deleted")}</span>
                          )}
                        </td>
                      )}
                      <td style={{ ...CELL, ...MONO, color: "var(--text-muted)" }}>{e.ip || "—"}</td>
                    </tr>
                    {open && (
                      <tr style={{ borderBottom: "1px solid var(--border)" }}>
                        <td colSpan={columns} style={{ padding: "8px 12px 12px 36px", background: "var(--bg-page)" }}>
                          <Changes action={e.action} changes={e.changes} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {!error && total > 0 && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, fontSize: 12 }}>
          <span style={{ color: "var(--text-muted)" }}>
            {t("audit.shown", { from: offset + 1, to: offset + items.length, total })}
          </span>
          <button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            {t("audit.prev")}
          </button>
          <button disabled={loading || offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
            {t("audit.next")}
          </button>
        </div>
      )}
    </div>
  );
}
