import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { Api, sample, uniq } from "./api";
import { ROOT_DIR } from "./env";
import { t } from "./i18n";

const KEV_FIXTURE = join(ROOT_DIR, "backend", "tests", "fixtures", "intel", "kev.json");
const LOG4J = "CVE-2021-44228";

test("справочник KEV: загрузка → плашка в окне SV-N → фильтр «Только KEV»", async ({ page }) => {
  const api = await Api.as();
  // Сначала импорт: после загрузки справочника воркер пересчитывает уже существующие находки
  const project = await api.createEntity(uniq("intel"));
  await api.importSarif(project.id, sample("trivy.sarif"));

  await page.goto("/intel");
  const card = page.getByRole("region", { name: t("intel.source.kev") });
  await card.getByLabel(`${t("intel.upload")}: ${t("intel.source.kev")}`).setInputFiles(KEV_FIXTURE);
  await card.getByRole("button", { name: t("intel.upload"), exact: true }).click();
  // Страница сама опрашивает статус, пока воркер грузит файл
  await expect(card.getByTestId("intel-status")).toHaveText(t("intel.status.ok"), { timeout: 20_000 });
  await expect(card).toContainText("2");

  const all = await api.get<{ number: number; cves: string[]; kev: boolean }[]>("/api/v1/findings", {
    entity_id: project.id,
    limit: 500,
  });
  const log4j = all.find((f) => f.cves.includes(LOG4J));
  expect(log4j, "в trivy.sarif есть находка с Log4Shell").toBeTruthy();
  expect(log4j!.kev).toBe(true);
  const ref = `SV-${log4j!.number}`;

  // Блок «Угрозы»: CVE, плашка KEV, вымогатели
  await page.goto(`/f/${ref}`);
  const threat = page.getByRole("region", { name: t("threat.title") });
  await expect(threat).toContainText(LOG4J);
  await expect(threat.getByLabel(t("threat.kev"))).toBeVisible();
  await expect(threat).toContainText(t("threat.ransomware"));

  // Фильтр «Только KEV» в «Уязвимостях»: остаются только находки из каталога
  await page.goto("/vulnerabilities");
  await page.getByLabel(t("vulns.project")).selectOption({ label: project.path });
  await page.getByLabel(t("vulns.kevOnly")).check();
  const kevCount = all.filter((f) => f.kev).length;
  await expect(page.getByRole("row").filter({ hasText: /SV-\d+/ })).toHaveCount(kevCount);
  await expect(page.getByRole("row").filter({ hasText: ref }).getByLabel(t("threat.kev"))).toBeVisible();
  await api.dispose();
});
