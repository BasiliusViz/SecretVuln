import { expect, test } from "@playwright/test";

import { Api, createUser, pageAs, sample, uniq } from "./api";
import { t } from "./i18n";

test("привязка к поддереву: виден только он, чужое по прямой ссылке — «не найдено»", async ({ browser }) => {
  const api = await Api.as();
  const mine = await api.createEntity(uniq("mine"));
  const mineChild = await api.createEntity(uniq("sub"), mine.id);
  const foreign = await api.createEntity(uniq("foreign"));
  await api.importSarif(mineChild.id, sample("semgrep.sarif"));
  await api.importSarif(foreign.id, sample("semgrep.sarif"));
  const [mineFinding] = await api.findings(mineChild.id);
  const [foreignFinding] = await api.findings(foreign.id);
  const user = createUser();
  await api.grant(user.email, "Наблюдатель", mine.id);
  await api.dispose();

  const page = await pageAs(browser, user.email, user.password);
  try {
    // Дерево: свой проект и вложенный видны, соседний корень — нет
    await page.goto("/projects");
    await expect(page.getByRole("group", { name: mine.path, exact: true })).toBeVisible();
    await expect(page.getByRole("group", { name: mineChild.path, exact: true })).toBeVisible();
    await expect(page.getByRole("group", { name: foreign.path, exact: true })).toHaveCount(0);
    // Наблюдатель не создаёт корневые проекты
    await expect(page.getByRole("button", { name: `+ ${t("projects.createRoot")}` })).toHaveCount(0);

    // Список уязвимостей — только из своего поддерева
    await page.goto("/vulnerabilities");
    await expect(page.getByRole("link", { name: `SV-${mineFinding.number}`, exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: `SV-${foreignFinding.number}`, exact: true })).toHaveCount(0);

    // Прямые ссылки на чужое: тот же ответ, что и на несуществующее
    await page.goto(`/projects/${foreign.id}/settings`);
    await expect(page.getByText(t("common.notFound"))).toBeVisible();
    await page.goto(`/f/SV-${foreignFinding.number}`);
    await expect(page.getByText(t("common.notFound"))).toBeVisible();

    // А своё по прямой ссылке открывается, без кнопок разбора (только чтение)
    await page.goto(`/f/SV-${mineFinding.number}`);
    await expect(page.getByText(mineFinding.title).first()).toBeVisible();
    await expect(page.getByRole("button", { name: t("window.take") })).toHaveCount(0);
  } finally {
    await page.context().close();
  }
});
