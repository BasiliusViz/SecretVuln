import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "../api/client";
import type { ImportRecord } from "../api/types";

interface EntityNode {
  id: string;
  name: string;
  parent_id: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  done: "var(--sev-low-text)",
  failed: "var(--sev-critical-text)",
  processing: "var(--sev-medium-text)",
  pending: "var(--text-muted)",
};

export function Imports() {
  const { t } = useTranslation();
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [selectedEntity, setSelectedEntity] = useState<string>("");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [onlyMine, setOnlyMine] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadEntities = useCallback(() => {
    apiFetch("/api/v1/entities")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setEntities)
      .catch(() => {});
  }, []);

  // Номер запроса: поздний ответ со старым фильтром не перезаписывает список
  const requestSeq = useRef(0);
  const loadImports = useCallback(() => {
    const seq = ++requestSeq.current;
    apiFetch(onlyMine ? "/api/v1/imports?uploaded_by=me" : "/api/v1/imports")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((data: ImportRecord[]) => {
        if (seq === requestSeq.current) setImports(data);
      })
      .catch(() => {});
  }, [onlyMine]);

  useEffect(() => {
    loadEntities();
    loadImports();
  }, [loadEntities, loadImports]);

  useEffect(() => {
    if (imports.some((i) => i.status === "pending" || i.status === "processing")) {
      const interval = setInterval(loadImports, 3000);
      return () => clearInterval(interval);
    }
  }, [imports, loadImports]);

  const handleUpload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file || !selectedEntity) return;
    setUploading(true);
    setUploadError(null);
    const form = new FormData();
    form.append("file", file);
    const res = await apiFetch(`/api/v1/entities/${selectedEntity}/imports`, {
      method: "POST",
      body: form,
    }).catch(() => null);
    setUploading(false);
    if (res?.ok) {
      if (fileRef.current) fileRef.current.value = "";
      loadImports();
    } else {
      setUploadError(t("imports.uploadError"));
    }
  };

  const entityNames = new Map(entities.map((e) => [e.id, e.name]));
  const inputStyle = {
    fontFamily: "inherit",
    fontSize: 13,
    color: "var(--text-primary)",
    background: "var(--bg-page)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    padding: "6px 10px",
  };

  return (
    <div>
      <h1>{t("imports.title")}</h1>

      <div className="card" style={{ marginBottom: 16 }}>
        <div style={{ fontWeight: 500, marginBottom: 10 }}>{t("imports.upload")}</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <select
            style={{ ...inputStyle, minWidth: 180 }}
            value={selectedEntity}
            onChange={(e) => setSelectedEntity(e.target.value)}
            aria-label={t("imports.entity")}
          >
            <option value="">{t("imports.selectEntity")}</option>
            {entities.map((e) => (
              <option key={e.id} value={e.id}>{e.name}</option>
            ))}
          </select>
          <input
            ref={fileRef}
            type="file"
            accept=".sarif,.json"
            aria-label={t("imports.filename")}
            style={{ ...inputStyle, flex: "1 1 200px" }}
          />
          <button onClick={handleUpload} disabled={uploading || !selectedEntity}>
            {uploading ? t("common.loading") : t("imports.upload")}
          </button>
        </div>
        {uploadError && (
          <div style={{ color: "#A32D2D", fontSize: 12, marginTop: 8 }}>{uploadError}</div>
        )}
      </div>

      <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
        <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
        {t("imports.onlyMine")}
      </label>

      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {imports.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>
            {t("imports.empty")}
          </p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("imports.filename")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("imports.entity")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("imports.scanner")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("status.label")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("imports.stats")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("imports.uploadedBy")}</th>
                <th style={{ padding: "8px 12px", fontWeight: 500 }}>{t("imports.uploadedAt")}</th>
              </tr>
            </thead>
            <tbody>
              {imports.map((imp) => (
                <tr key={imp.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={{ padding: "8px 12px" }}>{imp.filename}</td>
                  <td style={{ padding: "8px 12px", color: "var(--text-secondary)" }}>
                    {entityNames.get(imp.entity_id) || "—"}
                  </td>
                  <td style={{ padding: "8px 12px" }}>{imp.scanner || "—"}</td>
                  <td style={{ padding: "8px 12px", color: STATUS_COLORS[imp.status] || "inherit" }}>
                    {t(`importStatus.${imp.status}`)}
                  </td>
                  <td style={{ padding: "8px 12px", fontFamily: "var(--font-mono)", fontSize: 12 }}>
                    {imp.status === "done"
                      ? `${imp.stats.created ?? 0} / ${imp.stats.updated ?? 0} / ${imp.stats.duplicates ?? 0}`
                      : imp.error
                        ? imp.error.slice(0, 80)
                        : "—"}
                  </td>
                  <td style={{ padding: "8px 12px", color: "var(--text-secondary)" }}>
                    {imp.uploaded_by ? imp.uploaded_by.display_name || imp.uploaded_by.email : "—"}
                  </td>
                  <td style={{ padding: "8px 12px", color: "var(--text-muted)", fontSize: 12 }}>
                    {new Date(imp.created_at).toLocaleString("ru-RU")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
