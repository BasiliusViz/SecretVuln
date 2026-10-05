import { expect, test } from "@playwright/test";

import { Api, uniq } from "./api";
import { t } from "./i18n";

test("действия попадают в журнал, изменения раскрываются", async ({ page }) => {
  const api = await Api.as();
  const project = await api.createEntity(uniq("audit"));
  await api.patch(`/api/v1/entities/${project.id}/settings`, { default_branch: "release" });
  await api.dispose();

  await page.goto("/audit");
  await expect(page.getByRole("heading", { name: t("audit.title") })).toBeVisible();
  await page.getByLabel(t("audit.project")).selectOption({ label: project.path });

  const rows = page.getByRole("row").filter({ hasText: project.name });
  const created = rows.filter({ hasText: t("audit.action.entity.create") });
  const changed = rows.filter({ hasText: t("audit.action.entity.settings_update") });
  await expect(created).toHaveCount(1);
  await expect(changed).toHaveCount(1);

  // Раскрытие: строка-деталь с полем «Основная ветка» и новым значением
  await expect(changed).toHaveAttribute("aria-expanded", "false");
  await changed.click();
  await expect(changed).toHaveAttribute("aria-expanded", "true");
  // Имя строки: «поле · было · стало»; внешняя строка-обёртка начинается с заголовка таблицы
  const field = t("audit.fieldName.default_branch");
  await expect(page.getByRole("row", { name: new RegExp(`^${field} .*release$`) })).toBeVisible();

  // Та же запись видна во вкладке «Журнал» проекта
  await page.goto(`/projects/${project.id}/settings`);
  await page.getByRole("tab", { name: t("audit.tab") }).click();
  await expect(
    page.getByRole("row").filter({ hasText: t("audit.action.entity.settings_update") }),
  ).toHaveCount(1);
});
