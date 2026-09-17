// Цвета критичности для графиков Recharts и цветовых акцентов (границы карточек).
// Бейджи используют CSS-переменные --sev-{severity}-{bg,text} из global.css —
// они автоматически переключаются со сменой темы.
// Шкала — отраслевая конвенция (CVSS/DefectDojo); «низкая» — синяя, не зелёная
// (красно-зелёная пара неразличима при дейтеранопии). Severity всегда
// сопровождается текстом/иконкой, не только цветом (см. DESIGN.md).

export type Severity = "critical" | "high" | "medium" | "low" | "info";

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

export const SEVERITY: Record<Severity, { color: string }> = {
  critical: { color: "#A32D2D" },
  high: { color: "#D85A30" },
  medium: { color: "#BA7517" },
  low: { color: "#378ADD" },
  info: { color: "#888780" },
};
