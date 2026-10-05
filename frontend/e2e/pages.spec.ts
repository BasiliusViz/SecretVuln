import { expect, test, type Page } from "@playwright/test";

import { Api } from "./api";
import { allKeys, t } from "./i18n";

// Маршруты из App.tsx; динамические (/f/:ref, /projects/:id/settings) — на данных из beforeAll
const STATIC_ROUTES = [
  "/",
  "/my",
  "/inbox",
  "/projects",
  "/vulnerabilities",
  "/imports",
  "/groups",
  "/roles",
  "/sla",
  "/audit",
];

const KEYS = allKeys();
let dynamicRoutes: string[] = [];

test.beforeAll(async () => {
  const api = await Api.as();
  const { project, findings } = await api.projectWithFindings("pages");
  await api.dispose();
  dynamicRoutes = [`/projects/${project.id}/settings`, `/f/SV-${findings[0].number}`];
});

/** Собирает ошибки консоли, неудачные ответы (с адресом) и необработанные исключения страницы. */
function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    // «Failed to load resource» без адреса — его ловит обработчик response ниже
    if (msg.type() === "error" && !msg.text().startsWith("Failed to load resource")) {
      errors.push(`console: ${msg.text()}`);
    }
  });
  page.on("response", (res) => {
    if (res.status() >= 400) errors.push(`HTTP ${res.status()}: ${res.request().method()} ${res.url()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  return errors;
}

test("каждая страница открывается без ошибок и без сырых ключей i18n", async ({ page }) => {
  const errors = collectErrors(page);
  for (const route of [...STATIC_ROUTES, ...dynamicRoutes]) {
    await page.goto(route);
    // Дождаться, пока страница догрузит данные: сеть затихла и нет «Загрузка…»
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(t("common.loading"), { exact: true })).toHaveCount(0);
    await expect(page.getByRole("main")).not.toBeEmpty();
    await expect(page.getByText(t("common.error"), { exact: true }), route).toHaveCount(0);

    const text = await page.locator("body").innerText();
    const raw = KEYS.filter((key) => text.includes(key));
    expect(raw, `сырые ключи i18n на ${route}`).toEqual([]);
    expect(errors, `ошибки на ${route}`).toEqual([]);
  }
});

test("переключение темы применяется и переживает перезагрузку", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  const picker = page.getByLabel(t("nav.theme"));
  const html = page.locator("html");
  const values = await picker.locator("option").evaluateAll((opts) =>
    opts.map((o) => (o as HTMLOptionElement).value),
  );
  expect(values.length).toBeGreaterThan(1);

  for (const value of values) {
    await picker.selectOption(value);
    await expect(html).toHaveAttribute("data-theme", value);
  }
  // Последняя выбранная тема сохраняется
  const last = values[values.length - 1];
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", last);
  await expect(picker).toHaveValue(last);
  expect(errors).toEqual([]);
});
