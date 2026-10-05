import { expect, test } from "@playwright/test";

import { Api, sample, uniq } from "./api";
import { t, tc } from "./i18n";

const SEMGREP_RESULTS = 5; // число results в scripts/samples/semgrep.sarif

test("загрузка SARIF через страницу импортов; повторная не плодит дубли", async ({ page }) => {
  const api = await Api.as();
  const project = await api.createEntity(uniq("import"));
  await api.dispose();

  await page.goto("/imports");
  const upload = async () => {
    await page.getByLabel(t("imports.entity")).selectOption({ label: project.name });
    await page.getByLabel(t("imports.filename")).setInputFiles(sample("semgrep.sarif"));
    await page.getByRole("button", { name: t("imports.upload") }).click();
  };
  const rows = page.getByRole("row").filter({ hasText: project.name });
  // Колонка «Создано / обновлено / дубликаты»
  const stats = (i: number) => rows.nth(i).getByRole("cell").nth(4);

  await upload();
  await expect(rows).toHaveCount(1);
  // Воркер обработал: статус «Завершён», созданы все находки (страница сама опрашивает раз в 3 с)
  await expect(rows.first()).toContainText(t("importStatus.done"), { timeout: 20_000 });
  await expect(stats(0)).toHaveText(`${SEMGREP_RESULTS} / 0 / 0`);

  await upload();
  await expect(rows).toHaveCount(2);
  // Новые сверху: повторная загрузка ничего не создала — все находки распознаны как дубликаты
  await expect(rows.first()).toContainText(t("importStatus.done"), { timeout: 20_000 });
  await expect(stats(0)).toHaveText(`0 / 0 / ${SEMGREP_RESULTS}`);

  await page.goto("/vulnerabilities");
  await page.getByLabel(t("vulns.project")).selectOption({ label: project.path });
  await expect(page.getByText(tc("vulns.count", SEMGREP_RESULTS), { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /^SV-\d+$/ })).toHaveCount(SEMGREP_RESULTS);
});
