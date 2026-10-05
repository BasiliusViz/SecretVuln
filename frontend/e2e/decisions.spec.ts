import { expect, test } from "@playwright/test";

import { Api, createUser, pageAs } from "./api";
import { t } from "./i18n";

test("ложное срабатывание: запрос разработчика → «Запросы на одобрение» → одобрение", async ({
  page,
  browser,
}) => {
  const api = await Api.as();
  const { project, findings } = await api.projectWithFindings("decision");
  const [finding, other] = findings;
  const ref = `SV-${finding.number}`;
  const otherRef = `SV-${other.number}`;
  // У разработчика нет finding:approve — его запрос ждёт одобрения (у админа одобрился бы сразу)
  const user = createUser();
  await api.grant(user.email, "Разработчик", project.id);

  // Два запроса: один одобрим, второй останется в очереди — по нему видно, что список загрузился
  const devPage = await pageAs(browser, user.email, user.password);
  try {
    for (const r of [ref, otherRef]) {
      await devPage.goto(`/f/${r}`);
      await devPage.getByRole("button", { name: t("window.falsePositive") }).click();
      const dialog = devPage.getByRole("dialog", { name: t("decision.fpTitle") });
      await dialog.getByLabel(t("decision.tags.test_code")).check();
      await dialog.getByLabel(t("decision.reasonOptional")).fill("Демо-код из e2e");
      await dialog.getByRole("button", { name: t("decision.submit") }).click();
      await expect(dialog).toHaveCount(0);
      await expect(devPage.getByText(t("decision.pending"))).toBeVisible();
      // Одобрить сам разработчик не может
      await expect(devPage.getByRole("button", { name: t("decision.approve") })).toHaveCount(0);
    }
  } finally {
    await devPage.context().close();
  }

  // Админ находит запрос в очереди AppSec, открывает окно и одобряет
  await page.goto("/inbox");
  await page.getByRole("tab", { name: t("inbox.tabs.requests") }).click();
  await page.getByRole("link", { name: ref, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/f/${ref}$`));
  await page.getByRole("button", { name: t("decision.approve") }).click();

  await expect(page.getByText(t("status.false_positive"), { exact: true })).toBeVisible();
  await expect(page.getByText(t("decision.pending"))).toHaveCount(0);
  const after = await api.get<{ status: string }>(`/api/v1/findings/${finding.id}`);
  expect(after.status).toBe("false_positive");

  // В очереди запросов остался только второй
  await page.goto("/inbox");
  await page.getByRole("tab", { name: t("inbox.tabs.requests") }).click();
  await expect(page.getByRole("link", { name: otherRef, exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: ref, exact: true })).toHaveCount(0);
  await api.dispose();
});
