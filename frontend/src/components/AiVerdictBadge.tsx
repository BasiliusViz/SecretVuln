import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";

import { AI_VERDICTS, type AiVerdict } from "../api/types";

// Цвета — пары критичности из темы: «настоящая» — как критичная, «ложная» — синяя
// (не зелёная, см. severity.ts), «не уверен» — нейтральная. Плюс текст и иконка.
const PALETTE: Record<AiVerdict, { sev: string; icon: string }> = {
  true_positive: { sev: "critical", icon: "▲" },
  false_positive: { sev: "low", icon: "✕" },
  uncertain: { sev: "info", icon: "?" },
};

export function AiVerdictBadge({ verdict }: { verdict: AiVerdict | null }) {
  const { t } = useTranslation();
  if (!verdict) return <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{t("ai.verdict.none")}</span>;
  const { sev, icon } = PALETTE[verdict];
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        background: `var(--sev-${sev}-bg)`,
        color: `var(--sev-${sev}-text)`,
        fontSize: 12,
        fontWeight: 500,
        padding: "2px 10px",
        borderRadius: 99,
        whiteSpace: "nowrap",
      }}
    >
      <span aria-hidden="true" style={{ fontSize: 10 }}>
        {icon}
      </span>
      {t(`ai.verdict.${verdict}`)}
    </span>
  );
}

/** Значение фильтра «Вердикт ИИ»: "" — все, "none" — без вердикта, иначе вердикт. */
export function applyAiVerdictFilter(params: URLSearchParams, value: string) {
  if (value === "none") params.set("no_ai_verdict", "true");
  else if (value) params.set("ai_verdict", value);
}

export function AiVerdictFilter({
  value,
  onChange,
  style,
}: {
  value: string;
  onChange: (value: string) => void;
  style?: CSSProperties;
}) {
  const { t } = useTranslation();
  return (
    <select style={style} value={value} onChange={(e) => onChange(e.target.value)} aria-label={t("ai.verdict.label")}>
      <option value="">
        {t("ai.verdict.label")}: {t("vulns.all")}
      </option>
      {AI_VERDICTS.map((v) => (
        <option key={v} value={v}>
          {t(`ai.verdict.${v}`)}
        </option>
      ))}
      <option value="none">{t("ai.verdict.none")}</option>
    </select>
  );
}
