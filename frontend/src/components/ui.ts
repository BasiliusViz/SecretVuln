import type { CSSProperties } from "react";

export const PRIMARY_BUTTON: CSSProperties = {
  background: "var(--accent)",
  color: "var(--on-accent)",
  borderColor: "var(--accent)",
};

export const MONO: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 12,
};

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU");
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}
