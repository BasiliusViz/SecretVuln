import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { apiFetch } from "../api/client";
import { apiJson } from "../api/json";
import { OPEN_STATUSES } from "../api/types";
import type {
  EntityNode,
  Finding,
  MetricPeriod,
  MetricQuery,
  MetricResult,
  MetricRow,
} from "../api/types";
import { SEVERITY_ICONS, SeverityBadge } from "../components/SeverityBadge";
import { MONO } from "../components/ui";
import { SEVERITY_ORDER, useSeverityColors } from "../theme/severity";

const PERIODS: MetricPeriod[] = ["30d", "90d", "365d"];
const RECENT_LIMIT = 8;
const RECENT_STATUSES = OPEN_STATUSES.map((s) => `status=${s}`).join("&");
const STATUS_ORDER = [
  "new",
  "triaged",
  "confirmed",
  "in_progress",
  "false_positive",
  "risk_accepted",
  "fixed",
];

// Виджеты — JSON-запросы к POST /metrics/aggregate; период и проект подставляются из шапки
type Tile = {
  id: string;
  query: MetricQuery;
  // percent — доля 0–1, points — уже проценты 0–100 (ai_agreement)
  format: "count" | "percent" | "points" | "days";
  alert?: boolean;
};
const TILES: Tile[] = [
  { id: "open", query: { metric: "count" }, format: "count" },
  { id: "overdue", query: { metric: "overdue" }, format: "count", alert: true },
  { id: "slaRatio", query: { metric: "sla_ratio" }, format: "percent" },
  { id: "mttr", query: { metric: "mttr_days" }, format: "days" },
  { id: "aiAgreement", query: { metric: "ai_agreement" }, format: "points" },
];
const WEEKLY: {
  id: "opened" | "resolved";
  query: MetricQuery;
  color: string;
}[] = [
  {
    id: "opened",
    query: { metric: "opened", group_by: "week" },
    color: "var(--accent)",
  },
  {
    id: "resolved",
    query: { metric: "resolved", group_by: "week" },
    color: "var(--text-muted)",
  },
];
const OVERDUE_BY_TEAM: MetricQuery = { metric: "overdue", group_by: "team" };

async function aggregate(
  query: MetricQuery,
  period: MetricPeriod,
  entityId: string,
): Promise<MetricRow[] | null> {
  const res = await apiJson<MetricResult>("/api/v1/metrics/aggregate", "POST", {
    ...query,
    period,
    // entity_id на бэкенде означает проект вместе с поддеревом
    filters: entityId
      ? { ...query.filters, entity_id: entityId }
      : query.filters,
  });
  return res.ok && res.data ? res.data.rows : null;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Понедельники (YYYY-MM-DD, UTC) за период — чтобы недели без событий не выпадали из графика. */
function weeksOf(period: MetricPeriod): string[] {
  const now = new Date();
  const today = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate(),
  );
  const monday = today - ((new Date(today).getUTCDay() + 6) % 7) * DAY_MS;
  const start = today - parseInt(period, 10) * DAY_MS;
  const weeks: string[] = [];
  for (let d = monday; d + 7 * DAY_MS > start; d -= 7 * DAY_MS)
    weeks.unshift(new Date(d).toISOString().slice(0, 10));
  return weeks;
}

function formatValue(tile: Tile, value: number | null | undefined): string {
  if (value === undefined) return "…";
  if (value === null) return "—";
  if (tile.format === "percent") return `${Math.round(value * 100)}%`;
  if (tile.format === "points") return `${Math.round(value)}%`;
  if (tile.format === "days") return value.toFixed(1);
  return String(value);
}

/** Ключ строки-вывода в `dashboard.insights` (или `noData`). */
function insightKey(
  tile: Tile,
  value: number | null,
  delta: number | null | undefined,
): string | null {
  if (value === null) return "dashboard.noData";
  switch (tile.id) {
    case "open":
      if (delta == null) return null;
      return `dashboard.insights.${delta > 0 ? "openUp" : delta < 0 ? "openDown" : "openFlat"}`;
    case "overdue":
      return `dashboard.insights.${value > 0 ? "overdueSome" : "overdueNone"}`;
    case "slaRatio":
      return `dashboard.insights.${value >= 1 ? "slaAll" : "slaSome"}`;
    default:
      return "dashboard.insights.period";
  }
}

function MetricTile({
  tile,
  row,
  period,
  delta,
}: {
  tile: Tile;
  row: MetricRow | null | undefined;
  period: MetricPeriod;
  // появилось минус закрыто за период; только у «Открыто»
  delta?: number | null;
}) {
  const { t } = useTranslation();
  const value = row === undefined ? undefined : (row?.value ?? null);
  const alarm = tile.alert && !!value;
  const periodText = t(`dashboard.periods.${period}`);
  const insight = value === undefined ? null : insightKey(tile, value, delta);
  return (
    <div className="dash-card">
      <div className="stat-top">
        <span className="stat-label">{t(`dashboard.tiles.${tile.id}`)}</span>
        {tile.id === "open" && delta != null && (
          <span
            className={`delta-badge ${delta > 0 ? "bad" : delta < 0 ? "good" : ""}`}
            title={t("dashboard.badges.delta", { period: periodText })}
          >
            <span aria-hidden="true">
              {delta > 0 ? "▲" : delta < 0 ? "▼" : "●"}
            </span>
            {delta > 0 ? `+${delta}` : delta < 0 ? `−${-delta}` : "0"}
          </span>
        )}
        {alarm && (
          <span className="delta-badge bad">
            <span aria-hidden="true">⚠</span>
            {t("dashboard.badges.overdue")}
          </span>
        )}
      </div>
      <div
        className="stat-value"
        style={{ color: alarm ? "var(--sev-critical)" : undefined }}
      >
        {formatValue(tile, value)}
      </div>
      {insight && (
        <div className="stat-insight">{t(insight, { period: periodText })}</div>
      )}
      <div className="stat-hint">
        {t(`dashboard.tileHints.${tile.id}`, {
          period: periodText,
          count: row?.count ?? 0,
        })}
      </div>
    </div>
  );
}

interface Health {
  status: string;
  database: string;
}

interface Stats {
  total: number;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
}

export function Dashboard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  // null — идёт загрузка, "error" — запрос упал (не путать с пустым результатом)
  const [stats, setStats] = useState<Stats | null | "error">(null);
  const severityColors = useSeverityColors();
  const [period, setPeriod] = useState<MetricPeriod>("90d");
  const [entityId, setEntityId] = useState("");
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [recent, setRecent] = useState<Finding[] | null | "error">(null);
  const [tileRows, setTileRows] = useState<Record<string, MetricRow | null>>(
    {},
  );
  const [weekly, setWeekly] = useState<
    { week: string; opened: number; resolved: number }[] | null | "error"
  >(null);
  const [overdueTeams, setOverdueTeams] = useState<
    MetricRow[] | null | "error"
  >(null);

  useEffect(() => {
    let alive = true;
    setTileRows({});
    setWeekly(null);
    setOverdueTeams(null);
    void Promise.all(
      TILES.map((tile) => aggregate(tile.query, period, entityId)),
    ).then((results) => {
      if (!alive) return;
      setTileRows(
        Object.fromEntries(
          TILES.map((tile, i) => [tile.id, results[i]?.[0] ?? null]),
        ),
      );
    });
    void Promise.all(
      WEEKLY.map((w) => aggregate(w.query, period, entityId)),
    ).then(([opened, resolved]) => {
      if (!alive) return;
      if (!opened || !resolved) {
        setWeekly("error");
        return;
      }
      const by = (rows: MetricRow[]) =>
        new Map(rows.map((r) => [r.key, r.value ?? 0]));
      const o = by(opened);
      const r = by(resolved);
      setWeekly(
        weeksOf(period).map((week) => ({
          week,
          opened: o.get(week) ?? 0,
          resolved: r.get(week) ?? 0,
        })),
      );
    });
    void aggregate(OVERDUE_BY_TEAM, period, entityId).then((rows) => {
      if (alive)
        setOverdueTeams(
          rows
            ? rows
                .filter((r) => r.value)
                .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
            : "error",
        );
    });
    return () => {
      alive = false;
    };
  }, [period, entityId]);

  // Блоки «сейчас»: не зависят от периода, только от проекта
  useEffect(() => {
    let alive = true;
    const scope = entityId
      ? `entity_id=${entityId}&include_descendants=true`
      : "";
    setStats(null);
    setRecent(null);
    void apiJson<Stats>(`/api/v1/findings/stats?${scope}`).then((r) => {
      if (alive) setStats(r.data ?? "error");
    });
    void apiJson<Finding[]>(
      // только открытые: закрытые и решённые в таблице без колонки статуса сбивают с толку
      `/api/v1/findings?order=number&limit=${RECENT_LIMIT}&${RECENT_STATUSES}&${scope}`,
    ).then((r) => {
      if (alive) setRecent(r.data ?? "error");
    });
    return () => {
      alive = false;
    };
  }, [entityId]);

  useEffect(() => {
    apiFetch("/api/v1/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealthError(true));
    // список уже ограничен доступными пользователю проектами; заглушки предков выбрать нельзя
    void apiJson<EntityNode[]>("/api/v1/entities").then((r) =>
      setEntities(
        (r.data ?? [])
          .filter((e) => !e.stub)
          .sort((a, b) => a.path.localeCompare(b.path)),
      ),
    );
  }, []);

  const entityPaths = useMemo(
    () => new Map(entities.map((e) => [e.id, e.path])),
    [entities],
  );
  const delta = Array.isArray(weekly)
    ? weekly.reduce((sum, w) => sum + w.opened - w.resolved, 0)
    : null;
  const statsData = stats === "error" ? null : stats;
  const sevMax = statsData
    ? Math.max(1, ...SEVERITY_ORDER.map((s) => statsData.by_severity[s] ?? 0))
    : 1;
  const statusRows = statsData
    ? [
        ...STATUS_ORDER.filter((st) => st in statsData.by_status),
        ...Object.keys(statsData.by_status).filter(
          (st) => !STATUS_ORDER.includes(st),
        ),
      ].map((st) => [st, statsData.by_status[st]] as const)
    : [];
  const statusMax = Math.max(1, ...statusRows.map(([, cnt]) => cnt));
  const loading = <p className="dash-muted">{t("common.loading")}</p>;
  const failed = <p className="dash-muted">{t("common.error")}</p>;

  return (
    <div>
      <div className="dash-head">
        <div>
          <h1>{t("dashboard.title")}</h1>
          <p className="dash-muted" style={{ fontSize: 12 }}>
            {healthError
              ? t("common.apiDown")
              : health
                ? `${t("common.apiUp")} · ${health.database === "up" ? t("common.dbUp") : t("common.dbDown")}`
                : t("common.loading")}
          </p>
        </div>
        <div className="dash-controls">
          <select
            aria-label={t("vulns.project")}
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
          >
            <option value="">{t("dashboard.allProducts")}</option>
            {entities.map((e) => (
              <option key={e.id} value={e.id}>
                {e.path}
              </option>
            ))}
          </select>
          <div className="seg" role="group" aria-label={t("dashboard.period")}>
            {PERIODS.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                aria-pressed={p === period}
              >
                {t(`dashboard.periods.${p}`)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="dash-grid">
        {TILES.map((tile) => (
          <MetricTile
            key={tile.id}
            tile={tile}
            row={tileRows[tile.id]}
            period={period}
            delta={tile.id === "open" ? delta : undefined}
          />
        ))}
        <div className="dash-card">
          <span className="stat-label">{t("dashboard.bySeverity")}</span>
          <div className="sev-list">
            {SEVERITY_ORDER.map((sev) => {
              const cnt = statsData ? (statsData.by_severity[sev] ?? 0) : null;
              return (
                <div key={sev} style={{ display: "contents" }}>
                  <span
                    aria-hidden="true"
                    style={{ color: severityColors[sev], fontSize: 10 }}
                  >
                    {SEVERITY_ICONS[sev]}
                  </span>
                  <div>
                    {t(`severityPlural.${sev}`)}
                    <div
                      style={{
                        height: 3,
                        marginTop: 2,
                        borderRadius: 2,
                        width: `${((cnt ?? 0) / sevMax) * 100}%`,
                        background: severityColors[sev],
                        transition: "width 0.3s ease",
                      }}
                    />
                  </div>
                  <span className="num" style={{ color: severityColors[sev] }}>
                    {cnt ?? "—"}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="dash-card" style={{ marginBottom: 12 }}>
        <div className="dash-card-head">
          <span className="dash-card-title">{t("dashboard.weekly")}</span>
          <span>
            {WEEKLY.map((w) => (
              <span key={w.id} className="legend-item">
                <i style={{ background: w.color }} />
                {t(`dashboard.series.${w.id}`)}
              </span>
            ))}
          </span>
        </div>
        {weekly === null ? (
          loading
        ) : weekly === "error" ? (
          failed
        ) : (
          <div style={{ width: "100%", height: 260 }}>
            <ResponsiveContainer>
              <AreaChart
                data={weekly}
                margin={{ top: 4, right: 8, left: -16, bottom: 0 }}
              >
                <CartesianGrid vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="week"
                  tickFormatter={(w: string) =>
                    w.slice(8, 10) + "." + w.slice(5, 7)
                  }
                  tick={{ fontSize: 11, fill: "var(--text-muted)" }}
                  axisLine={{ stroke: "var(--border)" }}
                  tickLine={false}
                  minTickGap={12}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 11, fill: "var(--text-muted)" }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  cursor={{ stroke: "var(--border)" }}
                  labelFormatter={(w) =>
                    t("dashboard.weekOf", {
                      date: String(w).split("-").reverse().join("."),
                    })
                  }
                  contentStyle={{
                    background: "var(--bg-card)",
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    fontSize: 12,
                    color: "var(--text-primary)",
                  }}
                />
                {WEEKLY.map((w) => (
                  <Area
                    key={w.id}
                    type="monotone"
                    dataKey={w.id}
                    name={t(`dashboard.series.${w.id}`)}
                    stroke={w.color}
                    strokeWidth={2}
                    fill={w.color}
                    fillOpacity={0.18}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="dash-two">
        <div className="dash-card">
          <div className="dash-card-head">
            <span className="dash-card-title">
              {t("dashboard.overdueByTeam")}
            </span>
          </div>
          {overdueTeams === null ? (
            loading
          ) : overdueTeams === "error" ? (
            failed
          ) : overdueTeams.length === 0 ? (
            <p className="dash-muted">{t("dashboard.noOverdue")}</p>
          ) : (
            <div className="hbars">
              {overdueTeams.map((r) => (
                <div key={r.key ?? "none"} style={{ display: "contents" }}>
                  <span>{r.label ?? t("team.none")}</span>
                  <div className="track">
                    <div
                      className="fill"
                      style={{
                        width: `${((r.value ?? 0) / (overdueTeams[0].value ?? 1)) * 100}%`,
                        background: "var(--sev-critical)",
                      }}
                    />
                  </div>
                  <span className="num">{r.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="dash-card">
          <div className="dash-card-head">
            <span className="dash-card-title">{t("dashboard.byStatus")}</span>
          </div>
          {stats === null ? (
            loading
          ) : stats === "error" ? (
            failed
          ) : statusRows.length === 0 ? (
            <p className="dash-muted">{t("dashboard.noData")}</p>
          ) : (
            <div className="hbars">
              {statusRows.map(([st, cnt]) => (
                <div key={st} style={{ display: "contents" }}>
                  <span style={{ color: "var(--text-secondary)" }}>
                    {t(`status.${st}`)}
                  </span>
                  <div className="track">
                    <div
                      className="fill"
                      style={{
                        width: `${(cnt / statusMax) * 100}%`,
                        background: "var(--accent)",
                      }}
                    />
                  </div>
                  <span className="num">{cnt}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="dash-card" style={{ padding: 0, overflow: "hidden" }}>
        <div className="dash-card-head" style={{ padding: "14px 16px 0" }}>
          <span className="dash-card-title">{t("dashboard.recent")}</span>
        </div>
        {recent === null ? (
          <div style={{ padding: "0 16px 14px" }}>{loading}</div>
        ) : recent === "error" ? (
          <div style={{ padding: "0 16px 14px" }}>{failed}</div>
        ) : recent.length === 0 ? (
          <p className="dash-muted" style={{ padding: "0 16px 14px" }}>
            {t("dashboard.recentEmpty")}
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="dash-table">
              <thead>
                <tr>
                  <th>{t("vulns.number")}</th>
                  <th>{t("vulns.name")}</th>
                  <th>{t("severity.label")}</th>
                  <th>{t("vulns.project")}</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((f) => (
                  <tr key={f.id} onClick={() => navigate(`/f/SV-${f.number}`)}>
                    <td style={{ ...MONO, whiteSpace: "nowrap" }}>
                      <Link
                        to={`/f/SV-${f.number}`}
                        onClick={(e) => e.stopPropagation()}
                      >
                        SV-{f.number}
                      </Link>
                    </td>
                    <td style={{ fontWeight: 500 }}>{f.title.slice(0, 100)}</td>
                    <td>
                      <SeverityBadge severity={f.severity} />
                    </td>
                    <td style={{ ...MONO, color: "var(--text-secondary)" }}>
                      {entityPaths.get(f.entity_id) ?? t("common.none")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
