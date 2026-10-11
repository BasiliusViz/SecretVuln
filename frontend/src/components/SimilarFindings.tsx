import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { apiJson } from "../api/json";
import type { SimilarResponse } from "../api/types";
import { SeverityBadge } from "./SeverityBadge";
import { MONO, formatDate } from "./ui";

const MUTED = { color: "var(--text-muted)" } as const;

/**
 * Блок «Похожие находки» в окне SV-N — только при включённых векторах (решает окно).
 * Сервер отдаёт похожие лишь из видимых пользователю проектов. Заголовки и причины —
 * текст из SARIF и от людей, показываем как текст.
 */
export function SimilarFindings({ findingId }: { findingId: string }) {
  const { t } = useTranslation();
  const [data, setData] = useState<SimilarResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let alive = true;
    setData(null);
    setFailed(false);
    void apiJson<SimilarResponse>(`/api/v1/findings/${findingId}/similar?limit=5`).then((r) => {
      if (!alive) return;
      if (r.ok && r.data) setData(r.data);
      else setFailed(true);
    });
    return () => {
      alive = false;
    };
  }, [findingId]);

  // Ошибку (в т.ч. 503 — векторы выключили на ходу) не показываем: блок вспомогательный
  if (failed) return null;

  return (
    <section className="card" style={{ marginBottom: 16 }} aria-label={t("similar.title")}>
      <div className="section-label">{t("similar.title")}</div>
      <p style={{ fontSize: 12, ...MUTED, margin: "0 0 10px" }}>{t("similar.hint")}</p>
      {!data ? (
        <p style={{ ...MUTED, margin: 0 }}>{t("common.loading")}</p>
      ) : data.pending ? (
        <p role="status" style={{ ...MUTED, margin: 0 }}>{t("similar.pending")}</p>
      ) : data.items.length === 0 ? (
        <p style={{ ...MUTED, margin: 0 }}>{t("similar.empty")}</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {data.items.map((s) => (
            <li key={s.id} style={{ borderLeft: "2px solid var(--border)", paddingLeft: 10 }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <Link to={`/f/${s.number}`} style={MONO}>
                  {s.number}
                </Link>
                <SeverityBadge severity={s.severity} />
                <span style={{ fontWeight: 500 }}>{s.title}</span>
              </div>
              <div style={{ fontSize: 12, ...MUTED, marginTop: 4 }}>
                <span style={MONO}>{s.entity_path}</span> · {t(`status.${s.status}`)} ·{" "}
                {t("similar.similarity", { value: Math.round(s.similarity * 100) })}
              </div>
              {s.decision && (
                <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
                  {t("similar.decidedBy", { status: t(`status.${s.decision.status}`) })}
                  {s.decision.reason_tag && ` — ${t(`decision.tags.${s.decision.reason_tag}`, { defaultValue: s.decision.reason_tag })}`}
                  {s.decision.reason && ` — ${s.decision.reason}`}
                  {` · ${formatDate(s.decision.at)}`}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
