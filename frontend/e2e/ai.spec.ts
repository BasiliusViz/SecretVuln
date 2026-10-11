import { expect, test } from "@playwright/test";

import { Api, uniq } from "./api";
import { t } from "./i18n";

test("агент ИИ: токен в админке → вывод через API → блок в окне → принять → действие по выводу", async ({
  page,
}) => {
  const api = await Api.as();
  const { project, findings } = await api.projectWithFindings("ai");
  const [finding] = findings;
  const ref = `SV-${finding.number}`;
  const name = uniq("agent");

  // Админка: создать сервисный аккаунт и выдать токен (показ один раз)
  await page.goto("/service-accounts");
  await page.getByRole("button", { name: t("sa.create") }).click();
  const create = page.getByRole("dialog", { name: t("sa.create") });
  await create.getByLabel(t("sa.name")).fill(name);
  await create.getByRole("button", { name: t("sa.createSubmit") }).click();
  await expect(create).toHaveCount(0);

  const row = page.getByRole("row").filter({ hasText: `${name}@service.local` });
  await row.getByRole("button", { name: t("sa.issue") }).click();
  const issue = page.getByRole("dialog");
  await issue.getByLabel(t("sa.tokenName")).fill("e2e");
  await issue.getByRole("button", { name: t("sa.issue") }).click();
  const tokenInput = issue.getByLabel(t("sa.tokenValue"));
  await expect(tokenInput).toHaveValue(/^sv_/);
  const token = await tokenInput.inputValue();
  await issue.getByRole("button", { name: t("sa.done") }).click();
  await expect(row.getByText("e2e", { exact: true })).toBeVisible();

  // Доступ агенту — обычной привязкой: группа + роль «ИИ-агент» на проект
  const accounts = await api.get<{ id: string; email: string }[]>("/api/v1/service-accounts");
  const account = accounts.find((a) => a.email === `${name}@service.local`);
  if (!account) throw new Error("Сервисный аккаунт не найден");
  const group = await api.createGroup(uniq("agents"));
  await api.addMember(group.id, account.id);
  await api.bind(group.id, await api.roleId("ИИ-агент"), project.id);

  // Агент пишет вывод своим токеном
  const agent = await Api.as(token);
  await agent.post(`/api/v1/findings/${finding.id}/analyses`, {
    kind: "triage",
    verdict: "false_positive",
    confidence: 0.82,
    title_plain: "Тестовый код, пользовательского ввода нет",
    explanation: "Строка из e2e: данные приходят из константы.",
    agent: "e2e-agent",
    model: "test-model",
  });
  await agent.dispose();

  // Список: колонка и фильтр «Вердикт ИИ»
  await page.goto("/vulnerabilities");
  await page.getByLabel(t("ai.verdict.label")).selectOption("false_positive");
  const listRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: ref, exact: true }) });
  await expect(listRow.getByText(t("ai.verdict.false_positive"))).toBeVisible();

  // Окно находки: блок, принять, предложенное действие с пометкой «по выводу ИИ»
  await page.goto(`/f/${ref}`);
  const block = page.getByRole("region", { name: t("ai.title") });
  await expect(block.getByText("Тестовый код, пользовательского ввода нет")).toBeVisible();
  await expect(block.getByText(t("ai.verdict.false_positive"))).toBeVisible();
  await block.getByRole("button", { name: t("ai.accept") }).click();
  await expect(block.getByText(t("ai.review.accepted"))).toBeVisible();

  const next = page.getByRole("region", { name: t("ai.nextTitle") });
  await next.getByRole("button", { name: t("window.falsePositive") }).click();
  const dialog = page.getByRole("dialog", { name: t("decision.fpTitle") });
  await dialog.getByLabel(t("decision.tags.test_code")).check();
  await dialog.getByRole("button", { name: t("decision.submit") }).click();
  await expect(dialog).toHaveCount(0);
  await expect(next).toHaveCount(0);
  await expect(page.getByText(t("ai.byAnalysis"), { exact: false }).first()).toBeVisible();

  const after = await api.get<{ status: string }>(`/api/v1/findings/${finding.id}`);
  expect(after.status).toBe("false_positive");
  await api.dispose();
});

test("вывод ИИ: «Отклонить» с комментарием; обычная панель после «Принять» без пометки «по выводу ИИ»", async ({
  page,
}) => {
  const api = await Api.as();
  const { project, findings } = await api.projectWithFindings("ai-rej");
  const [finding] = findings;
  const ref = `SV-${finding.number}`;

  // Агент — через API: аккаунт, токен, группа с ролью «ИИ-агент» на проект
  const account = await api.post<{ id: string }>("/api/v1/service-accounts", { name: uniq("agent") });
  const { token } = await api.post<{ token: string }>(`/api/v1/service-accounts/${account.id}/tokens`, {
    name: "e2e",
  });
  const group = await api.createGroup(uniq("agents"));
  await api.addMember(group.id, account.id);
  await api.bind(group.id, await api.roleId("ИИ-агент"), project.id);
  const agent = await Api.as(token);
  const analyse = (title: string) =>
    agent.post(`/api/v1/findings/${finding.id}/analyses`, {
      kind: "triage",
      verdict: "true_positive",
      confidence: 0.7,
      title_plain: title,
      agent: "e2e-agent",
    });

  // «Отклонить»: комментарий из prompt, вердикт пересчитан (других выводов нет)
  await analyse("Первый вывод — неверный");
  await page.goto(`/f/${ref}`);
  const block = page.getByRole("region", { name: t("ai.title") });
  await expect(block.getByText("Первый вывод — неверный")).toBeVisible();
  page.once("dialog", (d) => {
    expect(d.message()).toBe(t("ai.rejectComment"));
    void d.accept("Санитайзер есть выше по стеку");
  });
  await block.getByRole("button", { name: t("ai.reject") }).click();
  await expect(block.getByText(t("ai.review.rejected"))).toBeVisible();
  await expect(block.getByText("Санитайзер есть выше по стеку", { exact: false })).toBeVisible();
  await expect(page.getByRole("region", { name: t("ai.nextTitle") })).toHaveCount(0);
  expect((await api.get<{ ai_verdict: string | null }>(`/api/v1/findings/${finding.id}`)).ai_verdict).toBeNull();

  // «Принять» второй вывод, но действие — из обычной панели: пометки быть не должно
  await analyse("Второй вывод — верный");
  await page.reload();
  await block.locator("li").filter({ hasText: "Второй вывод — верный" }).getByRole("button", { name: t("ai.accept") }).click();
  const next = page.getByRole("region", { name: t("ai.nextTitle") });
  await expect(next).toBeVisible();
  // кнопка «Взять в работу» есть и в блоке действия, и в панели; панель идёт после блока
  await page.getByRole("button", { name: t("window.take") }).last().click();
  await expect(next).toHaveCount(0);

  const events = await api.get<{ to_status: string | null; payload: Record<string, unknown> | null }[]>(
    `/api/v1/findings/${finding.id}/events`,
  );
  const taken = events.find((e) => e.to_status === "in_progress");
  expect(taken).toBeTruthy();
  expect(taken?.payload?.ai_analysis_id).toBeUndefined();
  await expect(page.getByText(t("ai.byAnalysis"), { exact: false })).toHaveCount(0);

  await agent.dispose();
  await api.dispose();
});
