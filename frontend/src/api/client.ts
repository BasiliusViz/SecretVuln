import { getToken } from "../auth/AuthContext";

const TOKEN_KEY = "sv-token";

/**
 * fetch с автоматическим Bearer-токеном. При 401 (токен истёк/невалиден) —
 * чистим токен и уводим на логин. 403 (нет прав) пробрасываем как есть,
 * чтобы страница показала «Недостаточно прав».
 */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(input, { ...init, headers });
  if (res.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    if (window.location.pathname !== "/login") window.location.href = "/login";
  }
  return res;
}
