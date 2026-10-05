import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { basename, join } from "node:path";

import {
  request,
  type APIRequestContext,
  type APIResponse,
  type Browser,
  type Page,
} from "@playwright/test";

import { ADMIN_STATE, API_URL, BASE_URL, ROOT_DIR, TOKEN_KEY, userPassword } from "./env";

/** Уникальный суффикс для имён: тесты не мешают друг другу в одной БД. */
export function uniq(prefix = "e2e"): string {
  return `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/** Путь к образцу SARIF из scripts/samples. */
export const sample = (name: string) => join(ROOT_DIR, "scripts", "samples", name);

/**
 * Новый локальный пользователь без прав — свой у каждого теста, чтобы выданные роли
 * не копились между тестами. API для этого нет, поэтому — CLI backend на БД e2e-стенда.
 */
export function createUser(): { email: string; password: string } {
  const db = process.env.SV_DATABASE_URL ?? "";
  if (!db.endsWith("/secretvuln_e2e")) {
    throw new Error("createUser только на e2e-стенде (SV_DATABASE_URL → secretvuln_e2e): запускайте через scripts/e2e.ps1");
  }
  const email = `${uniq("user")}@e2e.local`;
  const password = userPassword();
  const backend = join(ROOT_DIR, "backend");
  execFileSync(
    join(backend, ".venv", "Scripts", "python.exe"),
    ["-m", "app.cli", "create-user", "--email", email, "--password", password],
    { cwd: backend, stdio: "pipe" },
  );
  return { email, password };
}

/** Токен админа из storageState, который сохранил global-setup. */
export function adminToken(): string {
  const state = JSON.parse(readFileSync(ADMIN_STATE, "utf-8"));
  const origin = state.origins.find((o: { origin: string }) => o.origin === BASE_URL);
  const item = origin?.localStorage.find((i: { name: string }) => i.name === TOKEN_KEY);
  if (!item) throw new Error("В storageState нет токена — global-setup не отработал");
  return item.value;
}

export async function login(email: string, password: string): Promise<string> {
  const ctx = await request.newContext({ baseURL: API_URL });
  const res = await ctx.post("/api/v1/auth/login", { data: { email, password } });
  if (!res.ok()) throw new Error(`Вход ${email}: HTTP ${res.status()} ${await res.text()}`);
  const { access_token } = await res.json();
  await ctx.dispose();
  return access_token;
}

/** Подложить токен в браузер до загрузки приложения — вход без формы. */
export async function useToken(page: Page, token: string): Promise<void> {
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key, value),
    [TOKEN_KEY, token],
  );
}

/** Отдельная вкладка браузера под другим пользователем (у теста по умолчанию — админ). */
export async function pageAs(browser: Browser, email: string, password: string): Promise<Page> {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  await useToken(page, await login(email, password));
  return page;
}

export interface Entity { id: string; name: string; path: string; parent_id: string | null }
export interface Finding { id: string; number: number; status: string; title: string }

/** Тонкая обёртка над API для подготовки данных: проекты, группы, импорты. */
export class Api {
  private constructor(private ctx: APIRequestContext) {}

  static async as(token = adminToken()): Promise<Api> {
    const ctx = await request.newContext({
      baseURL: API_URL,
      extraHTTPHeaders: { Authorization: `Bearer ${token}` },
    });
    return new Api(ctx);
  }

  async dispose() {
    await this.ctx.dispose();
  }

  private async json<T>(res: APIResponse, what: string): Promise<T> {
    if (!res.ok()) throw new Error(`${what}: HTTP ${res.status()} ${await res.text()}`);
    return res.status() === 204 ? (undefined as T) : res.json();
  }

  get<T>(url: string, params?: Record<string, string | number>) {
    return this.ctx.get(url, { params }).then((r) => this.json<T>(r, `GET ${url}`));
  }

  post<T>(url: string, data?: unknown) {
    return this.ctx.post(url, { data }).then((r) => this.json<T>(r, `POST ${url}`));
  }

  patch<T>(url: string, data: unknown) {
    return this.ctx.patch(url, { data }).then((r) => this.json<T>(r, `PATCH ${url}`));
  }

  createEntity(name: string, parentId: string | null = null) {
    return this.post<Entity>("/api/v1/entities", { name, parent_id: parentId });
  }

  createGroup(name: string) {
    return this.post<{ id: string; name: string }>("/api/v1/groups", { name });
  }

  async userId(email: string): Promise<string> {
    const users = await this.get<{ id: string; email: string }[]>("/api/v1/users");
    const user = users.find((u) => u.email === email);
    if (!user) throw new Error(`Нет пользователя ${email}`);
    return user.id;
  }

  addMember(groupId: string, userId: string) {
    return this.post(`/api/v1/groups/${groupId}/members/${userId}`);
  }

  async roleId(name: string): Promise<string> {
    const roles = await this.get<{ id: string; name: string }[]>("/api/v1/roles");
    const role = roles.find((r) => r.name === name);
    if (!role) throw new Error(`Нет роли ${name}`);
    return role.id;
  }

  bind(groupId: string, roleId: string, entityId: string | null) {
    return this.post(`/api/v1/groups/${groupId}/bindings`, { role_id: roleId, entity_id: entityId });
  }

  /** Выдать пользователю роль на поддерево: новая группа + участник + привязка. */
  async grant(email: string, roleName: string, entityId: string | null): Promise<{ id: string; name: string }> {
    const group = await this.createGroup(uniq("grp"));
    await this.addMember(group.id, await this.userId(email));
    await this.bind(group.id, await this.roleId(roleName), entityId);
    return group;
  }

  /** Загрузить SARIF в проект и дождаться, пока воркер его обработает. */
  async importSarif(entityId: string, file: string): Promise<{ id: string }> {
    const res = await this.ctx.post(`/api/v1/entities/${entityId}/imports`, {
      multipart: {
        file: { name: basename(file), mimeType: "application/json", buffer: readFileSync(file) },
      },
    });
    const created = await this.json<{ id: string }>(res, "Импорт");
    await this.waitImport(created.id);
    return created;
  }

  async waitImport(importId: string, timeoutMs = 20_000): Promise<{ status: string }> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const imp = await this.get<{ status: string; error: string | null }>(`/api/v1/imports/${importId}`);
      if (imp.status === "done") return imp;
      if (imp.status === "failed") throw new Error(`Импорт упал: ${imp.error}`);
      await new Promise((r) => setTimeout(r, 300));
    }
    throw new Error(`Импорт ${importId} не обработан за ${timeoutMs} мс — воркер жив?`);
  }

  findings(entityId: string): Promise<Finding[]> {
    return this.get<Finding[]>("/api/v1/findings", { entity_id: entityId, limit: 500, order: "number" });
  }

  /** Новый проект с уязвимостями из semgrep.sarif — основа для сценариев разбора. */
  async projectWithFindings(prefix: string): Promise<{ project: Entity; findings: Finding[] }> {
    const project = await this.createEntity(uniq(prefix));
    await this.importSarif(project.id, sample("semgrep.sarif"));
    return { project, findings: await this.findings(project.id) };
  }
}
