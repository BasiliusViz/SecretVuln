import { expect, test } from "@playwright/test";

import { admin } from "./env";
import { t } from "./i18n";

// Здесь проверяем саму форму входа — без сохранённого токена админа
test.use({ storageState: { cookies: [], origins: [] } });

async function fillLogin(page: import("@playwright/test").Page, email: string, password: string) {
  await page.getByLabel(t("auth.email")).fill(email);
  await page.getByLabel(t("auth.password")).fill(password);
  await page.getByRole("button", { name: t("auth.signIn") }).click();
}

test("без токена приложение уводит на вход", async ({ page }) => {
  await page.goto("/vulnerabilities");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: t("auth.signIn") })).toBeVisible();
});

test("неверный пароль — ошибка, остаёмся на входе", async ({ page }) => {
  await page.goto("/login");
  await fillLogin(page, admin().email, "wrong-password-123");
  await expect(page.getByRole("alert")).toHaveText(t("auth.invalidCredentials"));
  await expect(page).toHaveURL(/\/login$/);
});

test("вход и выход", async ({ page }) => {
  const { email, password } = admin();
  await page.goto("/login");
  await fillLogin(page, email, password);
  await expect(page).toHaveURL(/\/$/);
  const logout = page.getByRole("button", { name: t("auth.logout") });
  await expect(logout).toBeVisible();

  await logout.click();
  await expect(page).toHaveURL(/\/login$/);
  // Токен стёрт: защищённая страница снова уводит на вход
  await page.goto("/projects");
  await expect(page).toHaveURL(/\/login$/);
});
