import { useTranslation } from "react-i18next";

import { OPEN_STATUSES } from "../api/types";
import { formatDate } from "./ui";

const DAY_MS = 24 * 60 * 60 * 1000;
// Сколько дней до срока считается «скоро»
const SOON_DAYS = 3;

/** Срок исправления: «осталось N дн.» / «просрочено на N дн.» — цвет + текст + значок. */
export function DueBadge({ dueAt, status }: { dueAt: string | null; status: string }) {
  const { t } = useTranslation();
  if (!dueAt) return <span style={{ color: "var(--text-muted)" }}>{t("due.none")}</span>;

  const date = formatDate(dueAt);
  if (!OPEN_STATUSES.includes(status)) {
    return (
      <span style={{ color: "var(--text-muted)", fontSize: 12 }} title={t("due.closedHint")}>
        {date}
      </span>
    );
  }

  const diff = new Date(dueAt).getTime() - Date.now();
  if (diff < 0) {
    // меньше суток просрочки — всё равно «на 1 день», иначе срок выглядел бы как «сегодня»
    return (
      <span title={date} style={{ color: "var(--sev-critical-text)", fontWeight: 500, whiteSpace: "nowrap" }}>
        ⚠ {t("due.overdue", { count: Math.ceil(-diff / DAY_MS) })}
      </span>
    );
  }
  const days = Math.floor(diff / DAY_MS);
  const soon = days <= SOON_DAYS;
  return (
    <span
      title={date}
      style={{ color: soon ? "var(--sev-medium-text)" : "var(--text-secondary)", whiteSpace: "nowrap" }}
    >
      {soon ? "⏱ " : ""}
      {days === 0 ? t("due.today") : t("due.left", { count: days })}
    </span>
  );
}
