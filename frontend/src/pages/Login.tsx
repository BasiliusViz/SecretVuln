import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../auth/AuthContext";

export function Login() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password || busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
    } catch (err) {
      const status = (err as Error & { status?: number }).status;
      setError(status === 401 ? t("auth.invalidCredentials") : (err as Error).message || t("auth.error"));
      setBusy(false);
    }
  };

  const inputStyle = {
    fontFamily: "inherit",
    fontSize: 14,
    color: "var(--text-primary)",
    background: "var(--bg-page)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    padding: "9px 12px",
    width: "100%",
  } as const;

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "var(--bg-page)",
        padding: 20,
      }}
    >
      <form onSubmit={submit} className="card" style={{ width: 360, maxWidth: "100%" }}>
        <div
          style={{
            marginBottom: 4,
            fontFamily: "var(--font-display)",
            fontSize: 18,
            fontWeight: 500,
            letterSpacing: "0.14em",
            textTransform: "uppercase",
            color: "var(--accent)",
            textShadow: "var(--glow)",
          }}
        >
          {t("app.name")}
        </div>
        <div style={{ marginBottom: 20, fontSize: 13, color: "var(--text-muted)" }}>
          {t("auth.subtitle")}
        </div>

        <label style={{ display: "block", marginBottom: 6, fontSize: 13 }}>{t("auth.email")}</label>
        <input
          style={{ ...inputStyle, marginBottom: 14 }}
          type="text"
          autoComplete="username"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoFocus
        />

        <label style={{ display: "block", marginBottom: 6, fontSize: 13 }}>
          {t("auth.password")}
        </label>
        <input
          style={{ ...inputStyle, marginBottom: 18 }}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        {error && (
          <div style={{ color: "var(--sev-critical-text)", fontSize: 13, marginBottom: 14 }}>
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={busy || !email.trim() || !password}
          style={{
            width: "100%",
            padding: "10px",
            fontSize: 14,
            fontWeight: 500,
            color: "var(--on-accent)",
            background: "var(--accent)",
            borderColor: "var(--accent)",
          }}
        >
          {busy ? t("auth.signingIn") : t("auth.signIn")}
        </button>
      </form>
    </div>
  );
}
