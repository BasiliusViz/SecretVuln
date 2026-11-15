import { expect, test, type Page } from "@playwright/test";

import { Api, uniq, type Entity, type Finding } from "./api";
import { t } from "./i18n";

const RECENT_LIMIT = 8; // как в Dashboard.tsx

let project: Entity;
let open: Finding[];
let closed: Finding;
let emptyProject: Entity;

test.beforeAll(async () => {
  const api = await Api.as();
  const created = await api.projectWithFindings("dash");
  project = created.project;
  // Одну находку закрываем как ложную — в таблице «последних открытых» её быть не должно
  closed = created.findings[0];
  const decision = await api.post<{ id: string; status: string }>(
    `/api/v1/findings/${closed.id}/decisions`,
    { decision_type: "false_positive", reason_tag: "test_code", reason: "e2e" },
  );
  if (decision.status === "pending") await api.post(`/api/v1/decisions/${decision.id}/approve`, {});
  const after = await api.findings(project.id);
  expect(after.find((f) => f.id === closed.id)?.status).toBe("false_positive");
  open = after.filter((f) => f.id !== closed.id);
  expect(open.length).toBeGreaterThan(0);
  emptyProject = await api.createEntity(uniq("dash-empty"));
  await api.dispose();
});

/** Карточка дашборда по заголовку. */
const card = (page: Page, titleKey: string) =>
  page.locator(".dash-card").filter({ hasText: t(titleKey) });

const selectProject = (page: Page, entity: Entity) =>
  page.getByLabel(t("vulns.project")).selectOption({ label: entity.path });

test("смена проекта меняет цифры и таблицу; строка ведёт в окно SV-N", async ({ page }) => {
  await page.goto("/");
  await selectProject(page, project);

  // Плитка «Открыто» — по выбранному проекту, без закрытой находки
  await expect(card(page, "dashboard.tiles.open").locator(".stat-value")).toHaveText(String(open.length));

  const recent = card(page, "dashboard.recent");
  const rows = recent.locator("tbody tr");
  await expect(rows).toHaveCount(Math.min(RECENT_LIMIT, open.length));
  // Все строки — из выбранного проекта, закрытой находки среди них нет
  await expect(rows.filter({ hasText: project.path })).toHaveCount(Math.min(RECENT_LIMIT, open.length));
  await expect(recent.getByRole("link", { name: `SV-${closed.number}`, exact: true })).toHaveCount(0);

  // Клик по строке (не по ссылке) открывает окно уязвимости
  const number = (await rows.first().getByRole("link").innerText()).trim();
  await rows.first().getByRole("cell").nth(1).click();
  await expect(page).toHaveURL(new RegExp(`/f/${number}$`));
});

test("проект без уязвимостей: пустые состояния вместо таблицы и графиков", async ({ page }) => {
  await page.goto("/");
  await selectProject(page, emptyProject);

  await expect(card(page, "dashboard.tiles.open").locator(".stat-value")).toHaveText("0");
  const recent = card(page, "dashboard.recent");
  await expect(recent.getByText(t("dashboard.recentEmpty"), { exact: true })).toBeVisible();
  await expect(recent.locator("table")).toHaveCount(0);
  await expect(card(page, "dashboard.byStatus").getByText(t("dashboard.noData"), { exact: true })).toBeVisible();
  await expect(
    card(page, "dashboard.overdueByTeam").getByText(t("dashboard.noOverdue"), { exact: true }),
  ).toBeVisible();
});

test("упавшие запросы показывают «ошибку», а не пустоту или вечную загрузку", async ({ page }) => {
  const fail = (route: import("@playwright/test").Route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"e2e"}' });
  // Список находок (но не /findings/stats) и агрегаты метрик
  await page.route(/\/api\/v1\/findings\?/, fail);
  await page.route("**/api/v1/metrics/aggregate", fail);
  await page.goto("/");

  const error = t("common.error");
  for (const title of ["dashboard.recent", "dashboard.weekly", "dashboard.overdueByTeam"]) {
    await expect(card(page, title).getByText(error, { exact: true }), title).toBeVisible();
  }
  await expect(page.getByText(t("common.loading"), { exact: true })).toHaveCount(0);
  // «По статусу» идёт отдельным запросом и не пострадал
  await expect(card(page, "dashboard.byStatus").getByText(error, { exact: true })).toHaveCount(0);
});
