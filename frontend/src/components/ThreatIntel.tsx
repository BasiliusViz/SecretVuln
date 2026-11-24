import { useTranslation } from "react-i18next";

import type { FindingIntel, IntelKev } from "../api/types";
import { MONO, formatDate } from "./ui";

const MUTED = { color: "var(--text-muted)" } as const;

/** EPSS 0–1 → «12,3 %» */
export function formatPercent(value: number): string {
  return `${(value * 100).toLocaleString("ru-RU", { maximumFractionDigits: value < 0.001 ? 2 : 1 })} %`;
}

/** Плашка «Эксплуатируется (KEV)» — цвет критичности из темы, текст и значок */
export function KevBadge({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation();
  return (
    <span
      title={t("threat.kevHint")}
      aria-label={t("threat.kev")}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: compact ? "0 6px" : "1px 8px",
        borderRadius: 99,
        fontSize: 11,
        whiteSpace: "nowrap",
        background: "var(--sev-critical-bg)",
        color: "var(--sev-critical-text)",
        border: "1px solid var(--sev-critical)",
      }}
    >
      ⚡ {compact ? t("threat.kevShort") : t("threat.kev")}
    </span>
  );
}

function KevDetails({ kev }: { kev: IntelKev }) {
  const { t } = useTranslation();
  return (
    <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 4 }}>
      {kev.name && <div>{kev.name}</div>}
      <div>
        {kev.date_added && t("threat.kevAdded", { date: formatDate(kev.date_added) })}
        {kev.due_date && ` · ${t("threat.kevDue", { date: formatDate(kev.due_date) })}`}
        {kev.ransomware && (
          <span style={{ color: "var(--sev-critical-text)", marginLeft: 8 }}>🔒 {t("threat.ransomware")}</span>
        )}
      </div>
    </div>
  );
}

/**
 * Блок «Угрозы» в окне SV-N: CWE из справочника, по каждому CVE — EPSS, KEV, БДУ.
 * Данные справочников — внешние тексты, показываем как текст.
 */
export function ThreatIntel({ intel }: { intel: FindingIntel }) {
  const { t } = useTranslation();
  const cweNum = intel.cwe?.id.match(/^CWE-(\d+)$/)?.[1];
  const dates = (["epss", "kev", "bdu", "cwe"] as const)
    .filter((s) => intel.sources[s])
    .map((s) => `${t(`intel.source.${s}`)}: ${formatDate(intel.sources[s] as string)}`);

  return (
    <section className="card" style={{ marginBottom: 16 }} role="region" aria-label={t("threat.title")}>
      <div className="section-label">{t("threat.title")}</div>

      {intel.stale.length > 0 && (
        <p role="status" style={{ fontSize: 12, color: "var(--sev-medium-text)", margin: "0 0 10px" }}>
          ⚠ {t("intel.stale")}: {intel.stale.map((s) => t(`intel.source.${s}`)).join(", ")}
        </p>
      )}

      {intel.cwe && (
        <div style={{ marginBottom: intel.cves.length ? 12 : 0 }}>
          <span style={MONO}>
            {cweNum ? (
              <a href={`https://cwe.mitre.org/data/definitions/${cweNum}.html`} target="_blank" rel="noopener noreferrer">
                {intel.cwe.id}
              </a>
            ) : (
              intel.cwe.id
            )}
          </span>
          {intel.cwe.name && <span style={{ marginLeft: 8 }}>{intel.cwe.name}</span>}
          <div style={{ fontSize: 12, ...MUTED, marginTop: 2 }}>
            {t("threat.category")}: {intel.cwe.category ?? t("threat.noCategory")}
          </div>
        </div>
      )}

      {intel.cves.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {intel.cves.map((c) => (
            <li key={c.id} data-cve={c.id} style={{ borderLeft: "2px solid var(--border)", paddingLeft: 10 }}>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <span style={{ ...MONO, fontWeight: 500 }}>{c.id}</span>
                {c.kev && <KevBadge />}
                <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                  {c.epss != null
                    ? t("threat.epss", {
                        value: formatPercent(c.epss),
                        percentile: c.percentile != null ? formatPercent(c.percentile) : "—",
                      })
                    : t("threat.noEpss")}
                </span>
              </div>
              {c.kev && <KevDetails kev={c.kev} />}
              {c.bdu.map((b) => (
                <div key={b.id} style={{ fontSize: 12, marginTop: 4 }}>
                  <span style={MONO}>{b.id}</span>
                  {b.name && <span style={{ marginLeft: 6 }}>{b.name}</span>}
                  {b.severity && <div style={MUTED}>{b.severity}</div>}
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}

      {dates.length > 0 && (
        <p style={{ fontSize: 11, ...MUTED, margin: "10px 0 0" }}>
          {t("threat.sources")}: {dates.join(" · ")}
        </p>
      )}
    </section>
  );
}
