import { useState } from "react";
import { useTranslation } from "react-i18next";

import { REASON_TAGS, type ReasonTag } from "../api/types";
import { Modal } from "./Modal";
import { PRIMARY_BUTTON } from "./ui";

export interface DecisionBody {
  decision_type: "false_positive" | "risk_accepted";
  reason_tag?: ReasonTag;
  reason?: string;
  expires_at?: string;
}

/**
 * «Ложное срабатывание» (причина из списка) или «Принять риск» (срок + пояснение).
 * onSubmit возвращает текст ошибки или null — тогда окно закрывается.
 */
export function DecisionDialog({
  mode,
  onSubmit,
  onClose,
}: {
  mode: DecisionBody["decision_type"];
  onSubmit: (body: DecisionBody) => Promise<string | null>;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [tag, setTag] = useState<ReasonTag>("data_not_user_controlled");
  const [reason, setReason] = useState("");
  const [expires, setExpires] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reasonRequired = mode === "risk_accepted" || tag === "other";

  const submit = async () => {
    setBusy(true);
    setError(null);
    const text = reason.trim() || undefined;
    const body: DecisionBody =
      mode === "false_positive"
        ? { decision_type: mode, reason_tag: tag, reason: text }
        : { decision_type: mode, reason: text, expires_at: expires ? `${expires}T23:59:59Z` : undefined };
    const err = await onSubmit(body);
    setBusy(false);
    if (err) setError(err);
    else onClose();
  };

  return (
    <Modal title={t(mode === "false_positive" ? "decision.fpTitle" : "decision.riskTitle")} onClose={onClose}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {mode === "false_positive" ? (
          <fieldset style={{ border: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 6 }}>
            <legend style={{ fontSize: 13, marginBottom: 6 }}>{t("decision.reasonTag")}</legend>
            {REASON_TAGS.map((value) => (
              <label key={value} style={{ display: "flex", gap: 8, fontSize: 13, alignItems: "center" }}>
                <input type="radio" name="reason_tag" checked={tag === value} onChange={() => setTag(value)} />
                {t(`decision.tags.${value}`)}
              </label>
            ))}
          </fieldset>
        ) : (
          <label style={{ fontSize: 13 }}>
            {t("decision.expiresAt")}
            <input
              type="date"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
              style={{ display: "block", marginTop: 4 }}
            />
          </label>
        )}
        <label style={{ fontSize: 13 }}>
          {t(reasonRequired ? "decision.reasonRequired" : "decision.reasonOptional")}
          <textarea
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ display: "block", width: "100%", marginTop: 4, boxSizing: "border-box" }}
          />
        </label>
        {error && (
          <p role="alert" style={{ color: "var(--sev-critical)", margin: 0, fontSize: 13 }}>
            {error}
          </p>
        )}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button onClick={onClose}>{t("common.cancel")}</button>
          <button onClick={submit} disabled={busy || (reasonRequired && !reason.trim())} style={PRIMARY_BUTTON}>
            {t("decision.submit")}
          </button>
        </div>
      </div>
    </Modal>
  );
}
