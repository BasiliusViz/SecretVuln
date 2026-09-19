// Цвета критичности берутся из CSS-переменных активной темы (--sev-*),
// поэтому графики Recharts меняют цвет вместе с темой. Бейджи используют
// пары --sev-{severity}-{bg,text}.
// Шкала — отраслевая конвенция (CVSS/DefectDojo); «низкая» — синяя, не зелёная
// (красно-зелёная пара неразличима при дейтеранопии). Severity всегда
// сопровождается текстом/иконкой, не только цветом (см. DESIGN.md).

import { useMemo } from "react";

import { useTheme } from "./ThemeContext";

export type Severity = "critical" | "high" | "medium" | "low" | "info";

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

const FALLBACK: Record<Severity, string> = {
  critical: "#A32D2D",
  high: "#D85A30",
  medium: "#BA7517",
  low: "#378ADD",
  info: "#888780",
};

export function severityColor(severity: Severity): string {
  if (typeof window === "undefined") return FALLBACK[severity];
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(`--sev-${severity}`)
    .trim();
  return value || FALLBACK[severity];
}

/** Цвета критичности текущей темы; пересчитываются при её смене. */
export function useSeverityColors(): Record<Severity, string> {
  const { theme } = useTheme();
  return useMemo(() => {
    void theme;
    return Object.fromEntries(
      SEVERITY_ORDER.map((severity) => [severity, severityColor(severity)]),
    ) as Record<Severity, string>;
  }, [theme]);
}
