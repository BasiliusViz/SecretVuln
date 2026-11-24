import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "../api/client";
import { apiJson } from "../api/json";
import type { IntelSource, IntelSourceName } from "../api/types";
import { MONO, PRIMARY_BUTTON, formatDate, formatDateTime } from "../components/ui";

const ACCEPT: Record<IntelSourceName, string> = {
  epss: ".csv,.gz",
  kev: ".json",
  bdu: ".xml,.zip",
  cwe: ".xml,.zip",
};

const STATUS_COLORS: Record<IntelSource["status"], string> = {
  ok: "var(--sev-low-text)",
  failed: "var(--sev-critical-text)",
  loading: "var(--sev-medium-text)",
  idle: "var(--text-muted)",
};

export function Intel() {
  const { t } = useTranslation();
  const [sources, setSources] = useState<IntelSource[] | null>(null);
  const [forbidden, setForbidden] = useState(false);

  const load = useCallback(async () => {
    const r = await apiJson<IntelSource[]>("/api/v1/intel");
    if (r.status === 403) setForbidden(true);
    else if (r.ok && r.data) setSources(r.data);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Пока воркер грузит справочник — опрашиваем статус
  useEffect(() => {
    if (sources?.some((s) => s.status === "loading")) {
      const interval = setInterval(() => void load(), 3000);
      return () => clearInterval(interval);
    }
  }, [sources, load]);

  if (forbidden) return <p style={{ color: "var(--text-muted)" }}>{t("intel.forbidden")}</p>;

  return (
    <div>
      <h1>{t("intel.title")}</h1>
      <p style={{ color: "var(--text-secondary)", fontSize: 13, maxWidth: 760 }}>{t("intel.intro")}</p>
      {!sources ? (
        <p style={{ color: "var(--text-muted)" }}>{t("common.loading")}</p>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
            gap: 16,
          }}
        >
          {sources.map((s) => (
            <SourceCard key={s.source} item={s} onChanged={load} />
          ))}
        </div>
      )}
    </div>
  );
}

function SourceCard({ item, onChanged }: { item: IntelSource; onChanged: () => Promise<void> }) {
  const { t } = useTranslation();
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    const res = await apiFetch(`/api/v1/intel/${item.source}`, { method: "POST", body: form }).catch(
      () => null,
    );
    if (res?.ok) {
      if (fileRef.current) fileRef.current.value = "";
    } else {
      const detail = await res
        ?.json()
        .then((d: { detail?: unknown }) => (typeof d.detail === "string" ? d.detail : null))
        .catch(() => null);
      setError(detail || t("intel.uploadError"));
    }
    setUploading(false);
    await onChanged();
  };

  const row = (label: string, value: React.ReactNode) => (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 13 }}>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span style={{ textAlign: "right" }}>{value}</span>
    </div>
  );
  const hasData = item.record_count != null;
  const busy = uploading || item.status === "loading";

  return (
    <section className="card" aria-label={t(`intel.source.${item.source}`)} data-source={item.source}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: 16 }}>{t(`intel.source.${item.source}`)}</h2>
        <span data-testid="intel-status" style={{ fontSize: 12, color: STATUS_COLORS[item.status] }}>
          {t(`intel.status.${item.status}`)}
        </span>
      </div>
      <div style={{ fontSize: 12, color: "var(--text-secondary)", margin: "4px 0 12px" }}>
        {t(`intel.sourceHint.${item.source}`)}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
        {row(t("intel.fileDate"), item.file_date ? formatDate(item.file_date) : "—")}
        {row(t("intel.records"), hasData ? <span style={MONO}>{item.record_count?.toLocaleString("ru-RU")}</span> : "—")}
        {row(t("intel.loadedAt"), item.loaded_at ? formatDateTime(item.loaded_at) : "—")}
        {item.loaded_at &&
          row(t("intel.loadedBy"), item.loaded_by ?? <span style={{ color: "var(--text-muted)" }}>{t("intel.builtin")}</span>)}
      </div>

      {item.stale && item.stale_after_days != null && (
        <div
          role="status"
          title={t("intel.staleHint", { days: item.stale_after_days })}
          style={{ fontSize: 12, color: "var(--sev-medium-text)", marginBottom: 8 }}
        >
          ⚠ {t("intel.stale")} — {t("intel.staleHint", { days: item.stale_after_days })}
        </div>
      )}
      {item.status === "failed" && item.error && (
        <div role="alert" style={{ fontSize: 12, color: "var(--sev-critical-text)", marginBottom: 8 }}>
          {item.error}
          {hasData && <div style={{ color: "var(--text-muted)" }}>{t("intel.previousData")}</div>}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPT[item.source]}
          aria-label={`${t("intel.upload")}: ${t(`intel.source.${item.source}`)}`}
          disabled={busy}
          style={{ flex: "1 1 160px", fontSize: 12, minWidth: 0 }}
        />
        <button onClick={() => void upload()} disabled={busy} style={PRIMARY_BUTTON}>
          {busy ? t("intel.status.loading") : t("intel.upload")}
        </button>
      </div>
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>{t(`intel.accept.${item.source}`)}</div>
      {error && (
        <div role="alert" style={{ color: "var(--sev-critical-text)", fontSize: 12, marginTop: 8 }}>
          {error}
        </div>
      )}
    </section>
  );
}
