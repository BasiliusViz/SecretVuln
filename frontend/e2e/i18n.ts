import ru from "../src/i18n/ru.json" with { type: "json" };

/** Строка интерфейса по ключу, как t() в приложении: t("auth.signIn"), t("x", { n: 1 }). */
export function t(key: string, vars: Record<string, string | number> = {}): string {
  let node: unknown = ru;
  for (const part of key.split(".")) {
    node = (node as Record<string, unknown> | undefined)?.[part];
  }
  if (typeof node !== "string") throw new Error(`Нет строки i18n: ${key}`);
  return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, name: string) => String(vars[name] ?? `{{${name}}}`));
}

const plural = new Intl.PluralRules("ru");

/** Плюрализованная строка, как t("vulns.count", { count }) — ключи _one/_few/_many/_other. */
export function tc(key: string, count: number): string {
  return t(`${key}_${plural.select(count)}`, { count });
}

/** Все ключи-листья ru.json — чтобы ловить на странице сырые ключи вместо перевода. */
export function allKeys(): string[] {
  const out: string[] = [];
  const walk = (node: Record<string, unknown>, prefix: string) => {
    for (const [k, v] of Object.entries(node)) {
      const key = prefix ? `${prefix}.${k}` : k;
      if (v && typeof v === "object") walk(v as Record<string, unknown>, key);
      else out.push(key);
    }
  };
  walk(ru as Record<string, unknown>, "");
  return out;
}
