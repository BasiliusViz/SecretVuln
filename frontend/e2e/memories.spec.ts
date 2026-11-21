import { expect, test } from "@playwright/test";

import { Api, createUser, pageAs } from "./api";
import { t } from "./i18n";

test("правило команды: создать → подсказка в окне SV-N → запрос по правилу → одобрение", async ({
  page,
  browser,
}) => {
  const api = await Api.as();
  const { project, findings } = await api.projectWithFindings("memory");
  const [finding] = findings;
  const ref = `SV-${finding.number}`;
  const { rule_id: ruleId } = await api.get<{ rule_id: string }>(`/api/v1/findings/${finding.id}`);
  const reason = "Демо-код: правило из e2e";

  // Админ создаёт правило вручную — оно сразу действует и подсказывает открытым находкам
  await page.goto("/memories");
  await page.getByRole("button", { name: t("memory.create") }).click();
  const form = page.getByRole("dialog", { name: t("memory.create") });
  await form.getByLabel(t("memory.scope")).selectOption({ label: project.path });
  await form.getByLabel(t("memory.ruleId")).fill(ruleId);
  await form.getByLabel(t("memory.reasonTag")).selectOption("test_code");
  await form.getByLabel(t("decision.reasonOptional")).fill(reason);
  await form.getByRole("button", { name: t("common.save") }).click();
  await expect(form).toHaveCount(0);

  const row = page.getByRole("row").filter({ hasText: project.path }).filter({ hasText: ruleId });
  await expect(row).toBeVisible();
  await expect(row).toContainText(t("decision.tags.test_code"));

  // Значок и фильтр в «Уязвимостях»
  await page.goto("/vulnerabilities");
  await page.getByLabel(t("vulns.hasMemory")).check();
  await expect(page.getByRole("row").filter({ hasText: ref }).getByText(t("memory.badge"))).toBeVisible();

  // Разработчик видит подсказку и просит решение по правилу: форма уже заполнена
  const user = createUser();
  await api.grant(user.email, "Разработчик", project.id);
  const devPage = await pageAs(browser, user.email, user.password);
  try {
    await devPage.goto(`/f/${ref}`);
    const block = devPage.getByRole("region", { name: t("memory.block") });
    await expect(block).toContainText(reason);
    await expect(block).toContainText(project.path);
    await block.getByRole("button", { name: t("memory.request") }).click();
    const dialog = devPage.getByRole("dialog", { name: t("decision.fpTitle") });
    await expect(dialog.getByLabel(t("decision.tags.test_code"))).toBeChecked();
    await expect(dialog.getByLabel(t("decision.reasonOptional"))).toHaveValue(reason);
    await dialog.getByRole("button", { name: t("decision.submit") }).click();
    await expect(dialog).toHaveCount(0);
    await expect(devPage.getByText(t("decision.pending"))).toBeVisible();
  } finally {
    await devPage.context().close();
  }

  const [request] = await api.get<{ memory_id: string | null; status: string }[]>(
    `/api/v1/findings/${finding.id}/decisions`,
  );
  expect(request.memory_id).not.toBeNull();

  // Одобряет человек с finding:approve — статус меняется только теперь
  await page.goto(`/f/${ref}`);
  await page.getByRole("button", { name: t("decision.approve") }).click();
  await expect(page.getByText(t("status.false_positive"), { exact: true })).toBeVisible();
  await expect(page.getByText(t("memory.byRule")).first()).toBeVisible();
  const after = await api.get<{ status: string }>(`/api/v1/findings/${finding.id}`);
  expect(after.status).toBe("false_positive");
  await api.dispose();
});
