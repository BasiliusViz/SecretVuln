import { useTranslation } from "react-i18next";

import type { Severity } from "../theme/severity";

const ICONS: Record<Severity, string> = {
  critical: "▲",
  high: "▲",
  medium: "●",
  low: "●",
  info: "○",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { t } = useTranslation();
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        background: `var(--sev-${severity}-bg)`,
        color: `var(--sev-${severity}-text)`,
        fontSize: 12,
        fontWeight: 500,
        padding: "2px 10px",
        borderRadius: 99,
      }}
    >
      <span aria-hidden="true" style={{ fontSize: 9 }}>
        {ICONS[severity]}
      </span>
      {t(`severity.${severity}`)}
    </span>
  );
}
