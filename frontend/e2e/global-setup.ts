import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { login } from "./api";
import { ADMIN_STATE, BASE_URL, TOKEN_KEY, admin } from "./env";

// Вход админа один раз через API: токен кладём в storageState (localStorage приложения)
export default async function globalSetup() {
  const { email, password } = admin();
  const token = await login(email, password);
  mkdirSync(dirname(ADMIN_STATE), { recursive: true });
  writeFileSync(
    ADMIN_STATE,
    JSON.stringify({
      cookies: [],
      origins: [{ origin: BASE_URL, localStorage: [{ name: TOKEN_KEY, value: token }] }],
    }),
  );
}
