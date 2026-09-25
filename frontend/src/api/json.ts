import { apiFetch } from "./client";

export interface ApiResult<T> {
  ok: boolean;
  status: number;
  data: T | null;
  /** Текст ошибки из `detail` ответа FastAPI (строка или список ошибок валидации) */
  error: string | null;
}

/** JSON-запрос к API с токеном: разбирает ответ и текст ошибки. Не бросает исключений. */
export async function apiJson<T>(url: string, method = "GET", body?: unknown): Promise<ApiResult<T>> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await apiFetch(url, init).catch(() => null);
  if (!res) return { ok: false, status: 0, data: null, error: null };

  const text = await res.text();
  let parsed: unknown = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = text;
  }
  if (res.ok) return { ok: true, status: res.status, data: parsed as T, error: null };

  const detail = (parsed as { detail?: unknown } | null)?.detail;
  let error: string | null = null;
  if (typeof detail === "string") error = detail;
  else if (Array.isArray(detail)) error = detail.map((d: { msg?: string }) => d.msg ?? "").join("; ");
  return { ok: false, status: res.status, data: null, error };
}
