import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { apiFetch } from "../api/client";
import { apiJson } from "../api/json";
import type {
  MetricPeriod,
  MetricQuery,
  MetricResult,
  MetricRow,
} from "../api/types";
import { SEVERITY_ORDER, useSeverityColors } from "../theme/severity";

const PERIODS: MetricPeriod[] = ["30d", "90d", "365d"];

// Виджеты — JSON-запросы к POST /metrics/aggregate; период подставляется из переключателя
type Tile = {
  id: string;
  query: MetricQuery;
  format: "count" | "percent" | "days";
  alert?: boolean;
};
const TILES: Tile[] = [
  { id: "open", query: { metric: "count" }, format: "count" },
  { id: "overdue", query: { metric: "overdue" }, format: "count", alert: true },
  { id: "slaRatio", query: { metric: "sla_ratio" }, format: "percent" },
  { id: "mttr", query: { metric: "mttr_days" }, format: "days" },
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
): Promise<MetricRow[] | null> {
  const res = await apiJson<MetricResult>("/api/v1/metrics/aggregate", "POST", {
    ...query,
    period,
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

function MetricTile({
  tile,
  value,
  period,
}: {
  tile: Tile;
  value: number | null | undefined;
  period: MetricPeriod;
}) {
  const { t } = useTranslation();
  const text =
    value === undefined
      ? "…"
      : value === null
        ? "—"
        : tile.format === "percent"
          ? `${Math.round(value * 100)}%`
          : tile.format === "days"
            ? value.toFixed(1)
            : String(value);
  const alarm = tile.alert && !!value;
  return (
    <div className="card" style={{ padding: "10px 14px" }}>
      <div className="section-label">{t(`dashboard.tiles.${tile.id}`)}</div>
      <div
        className="metric"
        style={{ color: alarm ? "var(--sev-critical-text)" : undefined }}
      >
        {alarm && "⚠ "}
        {text}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
        {t(`dashboard.tileHints.${tile.id}`, {
          period: t(`dashboard.periods.${period}`),
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
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [stats, setStats] = useState<Stats | null>(null);
  const severityColors = useSeverityColors();
  const [period, setPeriod] = useState<MetricPeriod>("90d");
  const [tileValues, setTileValues] = useState<Record<string, number | null>>(
    {},
  );
  const [weekly, setWeekly] = useState<
    { week: string; opened: number; resolved: number }[] | null
  >(null);
  const [overdueTeams, setOverdueTeams] = useState<MetricRow[] | null>(null);

  useEffect(() => {
    let alive = true;
    setTileValues({});
    void Promise.all(TILES.map((tile) => aggregate(tile.query, period))).then(
      (results) => {
        if (!alive) return;
        setTileValues(
          Object.fromEntries(
            TILES.map((tile, i) => [tile.id, results[i]?.[0]?.value ?? null]),
          ),
        );
      },
    );
    void Promise.all(WEEKLY.map((w) => aggregate(w.query, period))).then(
      ([opened, resolved]) => {
        if (!alive) return;
        const by = (rows: MetricRow[] | null) =>
          new Map((rows ?? []).map((r) => [r.key, r.value ?? 0]));
        const o = by(opened);
        const r = by(resolved);
        setWeekly(
          weeksOf(period).map((week) => ({
            week,
            opened: o.get(week) ?? 0,
            resolved: r.get(week) ?? 0,
          })),
        );
      },
    );
    void aggregate(OVERDUE_BY_TEAM, period).then((rows) => {
      if (alive)
        setOverdueTeams(
          (rows ?? [])
            .filter((r) => r.value)
            .sort((a, b) => (b.value ?? 0) - (a.value ?? 0)),
        );
    });
    return () => {
      alive = false;
    };
  }, [period]);

  useEffect(() => {
    apiFetch("/api/v1/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealthError(true));
    apiFetch("/api/v1/findings/stats")
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {});
  }, []);

  return (
    <div>
      <h1>{t("dashboard.title")}</h1>
      <p style={{ color: "var(--text-muted)", fontSize: 12, marginTop: -8 }}>
        {healthError
          ? t("common.apiDown")
          : health
            ? `${t("common.apiUp")} · ${health.database === "up" ? t("common.dbUp") : t("common.dbDown")}`
            : t("common.loading")}
      </p>
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          marginBottom: 10,
        }}
      >
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
          {t("dashboard.period")}
        </span>
        {PERIODS.map((p) => (
          <button
            key={p}
            onClick={() => setPeriod(p)}
            aria-pressed={p === period}
            style={
              p === period
                ? { borderColor: "var(--accent)", color: "var(--accent)" }
                : undefined
            }
          >
            {t(`dashboard.periods.${p}`)}
          </button>
        ))}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))",
          gap: 10,
          marginBottom: 10,
        }}
      >
        {TILES.map((tile) => (
          <MetricTile
            key={tile.id}
            tile={tile}
            value={tileValues[tile.id]}
            period={period}
          />
        ))}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: 10,
          marginBottom: 18,
        }}
      >
        {SEVERITY_ORDER.map((sev) => (
          <div
            key={sev}
            className="card"
            style={{
              padding: "10px 14px",
              borderTop: `3px solid ${severityColors[sev]}`,
              borderTopLeftRadius: 0,
              borderTopRightRadius: 0,
            }}
          >
            <div className="section-label">{t(`severityPlural.${sev}`)}</div>
            <div className="metric" style={{ color: severityColors[sev] }}>
              {stats ? (stats.by_severity[sev] ?? 0) : "—"}
            </div>
          </div>
        ))}
      </div>

      {stats && stats.total > 0 && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div style={{ fontWeight: 500, marginBottom: 10 }}>
            {t("dashboard.byStatus")}
          </div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {Object.entries(stats.by_status).map(([st, cnt]) => (
              <div key={st} style={{ fontSize: 13 }}>
                <span style={{ color: "var(--text-muted)" }}>
                  {t(`status.${st}`)}
                </span>{" "}
                <span style={{ fontWeight: 600 }}>{cnt}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 18 }}>
        <div style={{ fontWeight: 500, marginBottom: 8 }}>
          {t("dashboard.weekly")}
        </div>
        {weekly === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("common.loading")}
          </p>
        ) : (
          <div style={{ width: "100%", height: 240 }}>
            <ResponsiveContainer>
              <BarChart
                data={weekly}
                barGap={2}
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
                  cursor={{ fill: "var(--accent-bg)" }}
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
                <Legend
                  wrapperStyle={{
                    fontSize: 12,
                    color: "var(--text-secondary)",
                  }}
                />
                {WEEKLY.map((w) => (
                  <Bar
                    key={w.id}
                    dataKey={w.id}
                    name={t(`dashboard.series.${w.id}`)}
                    fill={w.color}
                    radius={[4, 4, 0, 0]}
                    maxBarSize={14}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="card">
        <div style={{ fontWeight: 500, marginBottom: 8 }}>
          {t("dashboard.overdueByTeam")}
        </div>
        {overdueTeams === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("common.loading")}
          </p>
        ) : overdueTeams.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0 }}>
            {t("dashboard.noOverdue")}
          </p>
        ) : (
          <table
            style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
          >
            <tbody>
              {overdueTeams.map((r) => {
                const max = overdueTeams[0].value ?? 1;
                return (
                  <tr key={r.key ?? "none"}>
                    <td
                      style={{
                        padding: "4px 12px 4px 0",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {r.label ?? t("team.none")}
                    </td>
                    <td style={{ width: "100%", padding: "4px 0" }}>
                      <div
                        style={{
                          height: 8,
                          width: `${((r.value ?? 0) / max) * 100}%`,
                          minWidth: 4,
                          background: "var(--sev-critical)",
                          borderRadius: "0 4px 4px 0",
                        }}
                      />
                    </td>
                    <td
                      style={{
                        padding: "4px 0 4px 12px",
                        textAlign: "right",
                        fontWeight: 600,
                      }}
                    >
                      {r.value}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
