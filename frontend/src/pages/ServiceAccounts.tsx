import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { apiJson } from "../api/json";
import type { ApiToken, ServiceAccount } from "../api/types";
import { Modal } from "../components/Modal";
import { MONO, PRIMARY_BUTTON, formatDate, formatDateTime } from "../components/ui";

const inputStyle = {
  fontFamily: "inherit",
  fontSize: 13,
  color: "var(--text-primary)",
  background: "var(--bg-page)",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  padding: "6px 10px",
  width: "100%",
  boxSizing: "border-box",
} as const;
const cell = { padding: "8px 12px", verticalAlign: "top" } as const;
const MUTED = { color: "var(--text-muted)" } as const;
const ERROR = { color: "var(--sev-critical-text)", fontSize: 12 } as const;
const EXPIRY_OPTIONS = ["30", "90", "365", ""] as const;
const KEEP_OPEN = () => undefined;

function tokenState(token: ApiToken): "revoked" | "expired" | "active" {
  if (token.revoked_at) return "revoked";
  if (token.expires_at && new Date(token.expires_at) <= new Date()) return "expired";
  return "active";
}

/** Админка «Сервисные аккаунты»: агенты ИИ и их API-токены (право `token:manage`). */
export function ServiceAccounts() {
  const { t } = useTranslation();
  const [accounts, setAccounts] = useState<ServiceAccount[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [issuingFor, setIssuingFor] = useState<ServiceAccount | null>(null);

  const load = useCallback(async () => {
    const res = await apiJson<ServiceAccount[]>("/api/v1/service-accounts");
    if (res.ok) setAccounts(res.data);
    else setLoadError(res.status === 403 ? t("common.forbidden") : t("common.error"));
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleActive = async (a: ServiceAccount) => {
    if (a.is_active && !window.confirm(t("sa.disableConfirm", { name: a.email }))) return;
    setActionError(null);
    const res = await apiJson(`/api/v1/service-accounts/${a.id}`, "PATCH", { is_active: !a.is_active });
    if (!res.ok) setActionError(res.error ?? t("common.error"));
    await load();
  };

  const revoke = async (a: ServiceAccount, token: ApiToken) => {
    if (!window.confirm(t("sa.revokeConfirm", { name: token.name }))) return;
    setActionError(null);
    const res = await apiJson(`/api/v1/service-accounts/${a.id}/tokens/${token.id}`, "DELETE");
    if (!res.ok) setActionError(res.error ?? t("common.error"));
    await load();
  };

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1>{t("sa.title")}</h1>
        <button style={PRIMARY_BUTTON} onClick={() => setCreating(true)}>
          {t("sa.create")}
        </button>
      </div>
      <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 0 }}>
        {t("sa.intro")} <Link to="/groups">{t("nav.groups")}</Link>.
      </p>

      {actionError && (
        <p role="alert" style={ERROR}>
          {actionError}
        </p>
      )}

      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        {loadError ? (
          <p style={{ ...MUTED, margin: 0, padding: 16 }}>{loadError}</p>
        ) : !accounts ? (
          <p style={{ ...MUTED, margin: 0, padding: 16 }}>{t("common.loading")}</p>
        ) : accounts.length === 0 ? (
          <p style={{ ...MUTED, margin: 0, padding: 16 }}>{t("sa.empty")}</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                <th style={{ ...cell, fontWeight: 500 }}>{t("sa.account")}</th>
                <th style={{ ...cell, fontWeight: 500 }}>{t("sa.tokens")}</th>
                <th style={cell} />
              </tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.id} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={cell}>
                    <div style={MONO}>{a.email}</div>
                    {a.full_name && <div>{a.full_name}</div>}
                    <div style={{ fontSize: 12, color: a.is_active ? "var(--text-secondary)" : "var(--sev-critical-text)" }}>
                      {t(a.is_active ? "sa.active" : "sa.disabled")} · {t("sa.since", { date: formatDate(a.created_at) })}
                    </div>
                  </td>
                  <td style={cell}>
                    {a.tokens.length === 0 ? (
                      <span style={MUTED}>{t("sa.noTokens")}</span>
                    ) : (
                      <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                        {a.tokens.map((token) => {
                          const state = tokenState(token);
                          return (
                            <li key={token.id} style={{ opacity: state === "active" ? 1 : 0.6 }}>
                              <span style={{ fontWeight: 500 }}>{token.name}</span>{" "}
                              <span style={MONO}>{token.prefix}…</span>{" "}
                              <span style={{ fontSize: 12, ...MUTED }}>
                                {state === "revoked"
                                  ? t("sa.revoked")
                                  : state === "expired"
                                    ? t("sa.expired")
                                    : token.expires_at
                                      ? t("sa.expires", { date: formatDate(token.expires_at) })
                                      : t("sa.noExpiry")}
                                {" · "}
                                {token.last_used_at
                                  ? t("sa.lastUsed", { date: formatDateTime(token.last_used_at) })
                                  : t("sa.neverUsed")}
                              </span>
                              {state !== "revoked" && (
                                <button
                                  onClick={() => void revoke(a, token)}
                                  style={{ marginLeft: 8, fontSize: 12 }}
                                  aria-label={`${t("sa.revoke")} ${token.name}`}
                                >
                                  {t("sa.revoke")}
                                </button>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </td>
                  <td style={{ ...cell, whiteSpace: "nowrap", textAlign: "right" }}>
                    {a.is_active && <button onClick={() => setIssuingFor(a)}>{t("sa.issue")}</button>}{" "}
                    <button onClick={() => void toggleActive(a)}>{t(a.is_active ? "sa.disable" : "sa.enable")}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {creating && (
        <CreateAccount
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            void load();
          }}
        />
      )}
      {issuingFor && (
        <IssueToken
          account={issuingFor}
          onIssued={() => void load()}
          onClose={() => setIssuingFor(null)}
        />
      )}
    </div>
  );
}

function CreateAccount({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const valid = /^[a-z0-9][a-z0-9._-]{1,63}$/.test(name);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const res = await apiJson("/api/v1/service-accounts", "POST", {
      name,
      full_name: fullName.trim() || null,
    });
    setBusy(false);
    if (res.ok) onCreated();
    else setError(res.status === 409 ? t("sa.duplicate") : (res.error ?? t("common.error")));
  };

  return (
    <Modal title={t("sa.create")} onClose={onClose}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label style={{ fontSize: 13 }}>
          {t("sa.name")}
          <input
            value={name}
            onChange={(e) => setName(e.target.value.toLowerCase())}
            style={{ ...inputStyle, marginTop: 4 }}
            autoFocus
          />
          <span style={{ fontSize: 12, ...MUTED }}>{t("sa.nameHint")}</span>
        </label>
        <label style={{ fontSize: 13 }}>
          {t("sa.fullName")}
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} style={{ ...inputStyle, marginTop: 4 }} />
        </label>
        {error && (
          <p role="alert" style={{ ...ERROR, margin: 0 }}>
            {error}
          </p>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}>{t("common.cancel")}</button>
          <button style={PRIMARY_BUTTON} disabled={!valid || busy} onClick={submit}>
            {t("sa.createSubmit")}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function IssueToken({
  account,
  onIssued,
  onClose,
}: {
  account: ServiceAccount;
  onIssued: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [days, setDays] = useState<string>("90");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Сам токен приходит один раз — после закрытия окна его больше не увидеть
  const [issued, setIssued] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const res = await apiJson<ApiToken & { token: string }>(`/api/v1/service-accounts/${account.id}/tokens`, "POST", {
      name: name.trim(),
      expires_in_days: days ? Number(days) : null,
    });
    setBusy(false);
    if (res.ok && res.data) {
      setIssued(res.data.token);
      onIssued();
    } else setError(res.error ?? t("common.error"));
  };

  const copy = async () => {
    if (!issued) return;
    await navigator.clipboard.writeText(issued).then(
      () => setCopied(true),
      () => undefined,
    );
  };

  return (
    // Показанный токен не теряем случайным кликом по фону или Esc — только «Готово»
    <Modal title={t("sa.issueTitle", { name: account.email })} onClose={issued ? KEEP_OPEN : onClose}>
      {issued ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <p role="alert" style={{ margin: 0, fontSize: 13, color: "var(--sev-high-text)" }}>
            {t("sa.onceWarning")}
          </p>
          <input
            readOnly
            value={issued}
            aria-label={t("sa.tokenValue")}
            onFocus={(e) => e.target.select()}
            style={{ ...inputStyle, fontFamily: "var(--font-mono)" }}
          />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button onClick={copy}>{copied ? t("sa.copied") : t("sa.copy")}</button>
            <button style={PRIMARY_BUTTON} onClick={onClose}>
              {t("sa.done")}
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <label style={{ fontSize: 13 }}>
            {t("sa.tokenName")}
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t("sa.tokenNamePlaceholder")}
              style={{ ...inputStyle, marginTop: 4 }}
              autoFocus
            />
          </label>
          <label style={{ fontSize: 13 }}>
            {t("sa.expiry")}
            <select value={days} onChange={(e) => setDays(e.target.value)} style={{ ...inputStyle, marginTop: 4 }}>
              {EXPIRY_OPTIONS.map((d) => (
                <option key={d} value={d}>
                  {d ? t("sa.expiryDays", { count: Number(d) }) : t("sa.noExpiry")}
                </option>
              ))}
            </select>
          </label>
          {error && (
            <p role="alert" style={{ ...ERROR, margin: 0 }}>
              {error}
            </p>
          )}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button onClick={onClose}>{t("common.cancel")}</button>
            <button style={PRIMARY_BUTTON} disabled={!name.trim() || busy} onClick={submit}>
              {t("sa.issue")}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
