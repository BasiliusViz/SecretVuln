import { defineConfig, devices } from "@playwright/test";

import { ADMIN_STATE } from "./e2e/env";

// Стенд поднимает scripts/e2e.ps1 (БД secretvuln_e2e, API :8001, Vite :5174) и
// передаёт адреса через env. Отдельно: npm run e2e — при уже поднятом e2e-стенде.
const baseURL = process.env.SV_E2E_BASE_URL ?? "http://127.0.0.1:5174";

export default defineConfig({
  testDir: "./e2e",
  // Общая БД и фоновый воркер — по одному тесту за раз; ретраев нет: флак лечим, а не прячем
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL,
    storageState: ADMIN_STATE,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "ru-RU",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Установленный Chrome; пустая SV_E2E_CHANNEL — встроенный Chromium Playwright
        channel: process.env.SV_E2E_CHANNEL ?? "chrome",
      },
    },
  ],
});
