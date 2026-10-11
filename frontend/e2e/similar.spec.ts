import { expect, test, type Page } from "@playwright/test";

import { Api } from "./api";
import { t } from "./i18n";

// На стенде модель эмбеддингов не задана — включённые векторы подставляем через page.route

async function embeddingsOn(page: Page) {
  await page.route("**/api/v1/ai/status", (route) =>
    route.fulfill({ json: { enabled: false, model: null, embeddings_enabled: true } }),
  );
}

test("похожие: при выключенных векторах блока нет и /similar не запрашивается", async ({ page }) => {
  const api = await Api.as();
  const { findings } = await api.projectWithFindings("similar-off");
  await api.dispose();
  const similarCalls: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/similar")) similarCalls.push(r.url());
  });

  const status = page.waitForResponse((r) => r.url().endsWith("/api/v1/ai/status"));
  await page.goto(`/f/SV-${findings[0].number}`);
  await status;
  await expect(page.getByText(findings[0].title).first()).toBeVisible();
  await expect(page.getByRole("region", { name: t("similar.title") })).toHaveCount(0);
  expect(similarCalls).toEqual([]);
});

test("похожие: строки со ссылкой, проектом, статусом, решением и процентом", async ({ page }) => {
  const api = await Api.as();
  const { project, findings } = await api.projectWithFindings("similar-on");
  await api.dispose();
  const [finding, other] = findings;
  await embeddingsOn(page);
  await page.route("**/api/v1/findings/*/similar*", (route) =>
    route.fulfill({
      json: {
        pending: false,
        items: [
          {
            id: other.id,
            number: `SV-${other.number}`,
            title: other.title,
            entity_path: project.path,
            status: "false_positive",
            severity: "high",
            similarity: 0.873,
            decision: {
              status: "false_positive",
              reason: "Константа из конфига",
              reason_tag: "test_code",
              at: "2026-10-01T10:00:00+00:00",
            },
          },
        ],
      },
    }),
  );

  await page.goto(`/f/SV-${finding.number}`);
  const block = page.getByRole("region", { name: t("similar.title") });
  const row = block.getByRole("listitem");
  await expect(row).toHaveCount(1);
  await expect(row.getByRole("link", { name: `SV-${other.number}` })).toHaveAttribute(
    "href",
    `/f/SV-${other.number}`,
  );
  await expect(row).toContainText(other.title);
  await expect(row).toContainText(project.path);
  await expect(row).toContainText(t("similar.similarity", { value: 87 }));
  await expect(row).toContainText(t("similar.decidedBy", { status: t("status.false_positive") }));
  await expect(row).toContainText(t("decision.tags.test_code"));
  await expect(row).toContainText("Константа из конфига");

  // Переход по ссылке открывает окно похожей находки
  await row.getByRole("link", { name: `SV-${other.number}` }).click();
  await expect(page).toHaveURL(new RegExp(`/f/SV-${other.number}$`));
  await expect(page.getByText(other.title).first()).toBeVisible();
});

test("похожие: «ещё вычисляются» и «не найдено»", async ({ page }) => {
  const api = await Api.as();
  const { findings } = await api.projectWithFindings("similar-state");
  await api.dispose();
  await embeddingsOn(page);
  let pending = true;
  await page.route("**/api/v1/findings/*/similar*", (route) =>
    route.fulfill({ json: { pending, items: [] } }),
  );

  await page.goto(`/f/SV-${findings[0].number}`);
  const block = page.getByRole("region", { name: t("similar.title") });
  await expect(block).toContainText(t("similar.pending"));

  pending = false;
  await page.reload();
  await expect(block).toContainText(t("similar.empty"));
  await expect(block).not.toContainText(t("similar.pending"));
});

test("анализ ИИ: «На основе похожих» с номерами находок", async ({ page }) => {
  const api = await Api.as();
  const { findings } = await api.projectWithFindings("similar-ai");
  await api.dispose();
  const [finding, a, b] = findings;
  // similar_ids пишет только встроенный триажёр — подставляем вывод в ответ /analyses
  // (номера похожих сервер отдаёт в similar, отфильтровав по видимости — см. pytest)
  await page.route("**/api/v1/findings/*/analyses", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      json: [
        {
          id: "00000000-0000-0000-0000-000000000001",
          finding_id: finding.id,
          kind: "triage",
          verdict: "false_positive",
          confidence: 0.7,
          title_plain: "Похоже на уже разобранные",
          explanation: null,
          remediation: null,
          agent: "builtin",
          model: "test",
          prompt_version: "triage-v2",
          created_by: null,
          author: null,
          created_at: "2026-10-11T10:00:00+00:00",
          review_status: "pending",
          reviewed_by: null,
          reviewer: null,
          reviewed_at: null,
          review_comment: null,
          similar_ids: [a.id, b.id],
          similar: [
            { id: a.id, number: a.number },
            { id: b.id, number: b.number },
          ],
        },
      ],
    });
  });

  await page.goto(`/f/SV-${finding.number}`);
  const analysis = page.getByTestId("ai-analysis");
  await expect(analysis).toContainText(`${t("ai.basedOn")} SV-${a.number}, SV-${b.number}`);
  await expect(analysis.getByRole("link", { name: `SV-${a.number}` })).toHaveAttribute("href", `/f/SV-${a.number}`);
});
