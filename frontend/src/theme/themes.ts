// Пять тем интерфейса. Значения цветов живут в global.css ([data-theme="..."]),
// здесь — только список для переключателя. Палитры и правила — в DESIGN.md.

export type ThemeId = "amber" | "cyber" | "indigo" | "matrix" | "light";

export const THEMES: { id: ThemeId; label: string }[] = [
  { id: "amber", label: "Янтарный терминал" },
  { id: "cyber", label: "Кибер-бирюза" },
  { id: "indigo", label: "Индиго" },
  { id: "matrix", label: "Матрица" },
  { id: "light", label: "Светлая" },
];

export const DEFAULT_THEME: ThemeId = "amber";

export function isThemeId(value: unknown): value is ThemeId {
  return THEMES.some((theme) => theme.id === value);
}
