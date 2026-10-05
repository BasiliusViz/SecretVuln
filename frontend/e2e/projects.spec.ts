import { expect, test } from "@playwright/test";

import { uniq } from "./api";
import { t } from "./i18n";

test("проект, дочерний проект и наследование настроек", async ({ page }) => {
  const root = uniq("root");
  const child = uniq("child");

  await page.goto("/projects");
  await page.getByRole("button", { name: `+ ${t("projects.createRoot")}` }).click();
  await page.getByPlaceholder(t("projects.name")).fill(root);
  await page.getByRole("button", { name: t("projects.create"), exact: true }).click();
  const rootRow = page.getByRole("group", { name: root, exact: true });
  await expect(rootRow).toBeVisible();

  await rootRow.getByRole("button", { name: `+ ${t("projects.addChild")}` }).click();
  await expect(page.getByText(t("projects.createChildIn", { name: root }))).toBeVisible();
  await page.getByPlaceholder(t("projects.name")).fill(child);
  await page.getByRole("button", { name: t("projects.create"), exact: true }).click();
  // Путь в дереве: дочерний узел адресуется как root/child
  await expect(page.getByRole("group", { name: `${root}/${child}`, exact: true })).toBeVisible();

  // У родителя задаём основную ветку
  await rootRow.getByRole("link", { name: t("settings.open") }).click();
  await expect(page.getByRole("heading", { name: root })).toBeVisible();
  const branch = page.getByLabel(t("settings.defaultBranch"));
  await branch.fill("develop");
  await page
    .locator("section")
    .filter({ has: branch })
    .getByRole("button", { name: t("common.save"), exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText(t("common.saved"));

  // Дочерний проект наследует её: значение подсказкой и источник «от родителя»
  await page.goto("/projects");
  await page
    .getByRole("group", { name: `${root}/${child}`, exact: true })
    .getByRole("link", { name: t("settings.open") })
    .click();
  await expect(page.getByRole("heading", { name: child })).toBeVisible();
  const childBranch = page.getByLabel(t("settings.defaultBranch"));
  await expect(childBranch).toHaveValue("");
  await expect(childBranch).toHaveAttribute("placeholder", "develop");
  await expect(page.getByText(t("settings.source.inherited", { from: root }))).toBeVisible();
});
