import { fileURLToPath } from "node:url";

// Пути — от каталога e2e, а не от cwd: запуск из корня с -c frontend/playwright.config.ts тоже работает
export const E2E_DIR = fileURLToPath(new URL(".", import.meta.url));
export const ROOT_DIR = fileURLToPath(new URL("../../", import.meta.url));

// Адреса и учётки стенда: scripts/e2e.ps1 кладёт их в env (учётки — из e2e/.env или .env.example)
export const BASE_URL = process.env.SV_E2E_BASE_URL ?? "http://127.0.0.1:5174";
export const API_URL = process.env.SV_E2E_API_URL ?? "http://127.0.0.1:8001";

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Нет ${name}: запускайте через scripts/e2e.ps1 или задайте env`);
  return value;
}

export const admin = () => ({
  email: required("SV_E2E_ADMIN_EMAIL"),
  password: required("SV_E2E_ADMIN_PASSWORD"),
});
/** Пароль обычных тестовых пользователей; сами пользователи — свои у каждого теста (createUser в api.ts). */
export const userPassword = () => required("SV_E2E_USER_PASSWORD");

export const ADMIN_STATE = `${E2E_DIR}.auth/admin.json`;
export const TOKEN_KEY = "sv-token";
