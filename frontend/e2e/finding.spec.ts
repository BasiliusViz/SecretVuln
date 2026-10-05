import { expect, test } from "@playwright/test";

import { Api } from "./api";
import { t } from "./i18n";

test("окно SV-N: взять в работу и комментарий попадают в историю", async ({ page }) => {
  const api = await Api.as();
  const { findings } = await api.projectWithFindings("finding");
  await api.dispose();
  const finding = findings[0];
  expect(finding.status).toBe("new");

  await page.goto(`/f/SV-${finding.number}`);
  await expect(page.getByText(finding.title).first()).toBeVisible();
  const history = page.locator("section").filter({ hasText: t("window.history") }).getByRole("listitem");

  await page.getByRole("button", { name: t("window.take") }).click();
  // Кнопка пропадает, в шапке новый статус, в истории — переход статусов
  await expect(page.getByRole("button", { name: t("window.take") })).toHaveCount(0);
  await expect(page.getByText(t("status.in_progress"), { exact: true })).toBeVisible();
  await expect(
    history.filter({ hasText: `${t("status.new")} → ${t("status.in_progress")}` }),
  ).toHaveCount(1);

  const comment = `Проверено e2e ${Date.now()}`;
  await page.getByLabel(t("window.commentPlaceholder")).fill(comment);
  await page.getByRole("button", { name: t("window.addComment") }).click();
  await expect(history.filter({ hasText: comment })).toHaveCount(1);

  // После перезагрузки всё на месте — это записано на бэкенде, а не только в состоянии страницы
  await page.reload();
  await expect(history.filter({ hasText: comment })).toHaveCount(1);
  await expect(page.getByText(t("status.in_progress"), { exact: true })).toBeVisible();
});
