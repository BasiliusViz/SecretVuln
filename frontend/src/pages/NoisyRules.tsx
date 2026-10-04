import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiJson } from "../api/json";
import type { NoisyRule } from "../api/types";
import { MONO } from "../components/ui";

const CELL = { padding: "8px 12px" } as const;
const HEAD = { padding: "8px 12px", fontWeight: 500 } as const;
const MIN_DECIDED = 10;
const MIN_FP_RATIO = 0.7;

/** Вкладка очереди AppSec: правила сканеров, которые чаще всего признают ложными. */
export function NoisyRules() {
  const { t } = useTranslation();
  const [rules, setRules] = useState<NoisyRule[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void apiJson<NoisyRule[]>(
      `/api/v1/findings/noisy-rules?min_decided=${MIN_DECIDED}&min_fp_ratio=${MIN_FP_RATIO}`,
    ).then((r) => {
      if (r.ok) setRules(r.data ?? []);
      else setError(r.status === 403 ? t("common.forbidden") : t("common.error"));
    });
  }, [t]);

  return (
    <>
      <p style={{ fontSize: 12, color: "var(--text-muted)", margin: "0 0 8px" }}>
        {t("noisy.hint", { decided: MIN_DECIDED, ratio: Math.round(MIN_FP_RATIO * 100) })}
      </p>
      <div className="card" style={{ padding: 0, overflow: "auto" }}>
        {error ? (
          <p style={{ padding: 16, margin: 0, color: "var(--text-muted)" }}>{error}</p>
        ) : rules === null ? (
          <p style={{ padding: 16, margin: 0, color: "var(--text-muted)" }}>{t("common.loading")}</p>
        ) : rules.length === 0 ? (
          <p style={{ padding: 16, margin: 0, color: "var(--text-muted)" }}>{t("noisy.empty")}</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                <th style={HEAD}>{t("vulns.scanner")}</th>
                <th style={HEAD}>{t("vulns.rule")}</th>
                <th style={HEAD}>{t("noisy.falsePositive")}</th>
                <th style={HEAD}>{t("noisy.reasons")}</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={`${r.scanner}/${r.rule_id}`} style={{ borderBottom: "1px solid var(--border)" }}>
                  <td style={CELL}>{r.scanner}</td>
                  <td style={{ ...CELL, ...MONO }}>{r.rule_id}</td>
                  <td style={{ ...CELL, whiteSpace: "nowrap" }}>
                    <span style={{ fontWeight: 500 }}>{Math.round(r.fp_ratio * 100)}%</span>
                    <span style={{ fontSize: 12, color: "var(--text-muted)" }}>
                      {" "}
                      {t("noisy.ofDecided", { fp: r.false_positive, count: r.decided })}
                    </span>
                  </td>
                  <td style={{ ...CELL, fontSize: 12, color: "var(--text-secondary)" }}>
                    {r.top_reasons.length === 0
                      ? t("common.none")
                      : r.top_reasons.map((x) => `${t(`decision.tags.${x.reason_tag}`)} (${x.count})`).join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  );
}
