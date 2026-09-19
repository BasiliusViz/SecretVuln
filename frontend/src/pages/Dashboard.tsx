import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "../api/client";
import { SEVERITY_ORDER, useSeverityColors } from "../theme/severity";

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
          <div style={{ fontWeight: 500, marginBottom: 10 }}>{t("dashboard.byStatus")}</div>
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            {Object.entries(stats.by_status).map(([st, cnt]) => (
              <div key={st} style={{ fontSize: 13 }}>
                <span style={{ color: "var(--text-muted)" }}>{t(`status.${st}`)}</span>{" "}
                <span style={{ fontWeight: 600 }}>{cnt}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <div style={{ fontWeight: 500, marginBottom: 8 }}>{t("dashboard.newByWeek")}</div>
        <p style={{ color: "var(--text-muted)", margin: 0 }}>
          {stats && stats.total > 0
            ? `${t("vulns.count", { count: stats.total })}`
            : t("vulns.empty")}
        </p>
      </div>
    </div>
  );
}
