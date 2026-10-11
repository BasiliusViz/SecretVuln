import { useTranslation } from "react-i18next";

import type { AiAnalysis } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AiVerdictBadge } from "./AiVerdictBadge";
import { PRIMARY_BUTTON, formatDateTime } from "./ui";

const MUTED = { color: "var(--text-muted)" } as const;
const TEXT = { whiteSpace: "pre-wrap", margin: "4px 0 0" } as const;

function who(user: AiAnalysis["author"]): string | null {
  return user ? user.full_name || user.email : null;
}

/**
 * Блок «Анализ ИИ» в окне находки. Тексты пишет агент — показываем их только как
 * текст (без разметки). Принятие статус не меняет: окно потом предлагает действие.
 */
export function AiAnalyses({
  analyses,
  canReview,
  onReview,
}: {
  analyses: AiAnalysis[];
  canReview: boolean;
  onReview: (analysis: AiAnalysis, accept: boolean) => void;
}) {
  const { t } = useTranslation();
  const { user } = useAuth();
  if (analyses.length === 0) return null;

  return (
    <section className="card" style={{ marginBottom: 16 }} aria-label={t("ai.title")}>
      <div className="section-label">{t("ai.title")}</div>
      <p style={{ fontSize: 12, ...MUTED, margin: "0 0 10px" }}>{t("ai.hint")}</p>
      <ol style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 14 }}>
        {analyses.map((a) => (
          <li
            key={a.id}
            data-testid="ai-analysis"
            style={{
              borderLeft: "2px solid var(--border)",
              paddingLeft: 10,
            }}
          >
            {/* отклонённый вывод приглушён, но строка «Отклонил … — причина» остаётся читаемой */}
            <div style={{ opacity: a.review_status === "rejected" ? 0.6 : 1 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 12 }}>
              {a.kind === "triage" ? (
                <AiVerdictBadge verdict={a.verdict} />
              ) : (
                <span style={{ fontWeight: 500 }}>{t("ai.kind.summary")}</span>
              )}
              {a.confidence !== null && (
                <span style={MUTED}>{t("ai.confidence", { value: Math.round(a.confidence * 100) })}</span>
              )}
              <span style={{ color: "var(--text-secondary)" }}>{t(`ai.review.${a.review_status}`)}</span>
            </div>
            {a.title_plain && <div style={{ fontWeight: 500, marginTop: 6 }}>{a.title_plain}</div>}
            {a.explanation && (
              <div style={{ marginTop: 6 }}>
                <div style={{ fontSize: 12, ...MUTED }}>{t("ai.explanation")}</div>
                <p style={TEXT}>{a.explanation}</p>
              </div>
            )}
            {a.remediation && (
              <div style={{ marginTop: 6 }}>
                <div style={{ fontSize: 12, ...MUTED }}>{t("ai.remediation")}</div>
                <p style={TEXT}>{a.remediation}</p>
              </div>
            )}
            <div style={{ fontSize: 12, ...MUTED, marginTop: 6 }}>
              {formatDateTime(a.created_at)} · {who(a.author) ?? t("window.system")}
              {a.agent && ` · ${a.agent}`}
              {a.model && ` · ${t("ai.model")}: ${a.model}`}
              {a.prompt_version && ` · ${t("ai.prompt")}: ${a.prompt_version}`}
            </div>
            </div>
            {a.review_status !== "pending" && a.reviewed_at && (
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
                {t(a.review_status === "accepted" ? "ai.acceptedBy" : "ai.rejectedBy", {
                  name: who(a.reviewer) ?? t("window.system"),
                  date: formatDateTime(a.reviewed_at),
                })}
                {a.review_comment && ` — ${a.review_comment}`}
              </div>
            )}
            {canReview && a.review_status === "pending" && a.created_by !== user?.id && (
              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                <button style={PRIMARY_BUTTON} onClick={() => onReview(a, true)}>
                  {t("ai.accept")}
                </button>
                <button onClick={() => onReview(a, false)}>{t("ai.reject")}</button>
              </div>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
