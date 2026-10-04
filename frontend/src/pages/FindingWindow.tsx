import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";

import { apiJson } from "../api/json";
import { OPEN_STATUSES, type Decision, type FindingDetail, type FindingEvent, type Group } from "../api/types";
import { useCan } from "../auth/AuthContext";
import { DecisionDialog, type DecisionBody } from "../components/DecisionDialog";
import { DueBadge } from "../components/DueBadge";
import { Modal } from "../components/Modal";
import { SeverityBadge } from "../components/SeverityBadge";
import { MONO, PRIMARY_BUTTON, formatDate, formatDateTime } from "../components/ui";

const SECTION = { marginBottom: 16 } as const;
const MUTED = { color: "var(--text-muted)" } as const;

export function FindingWindow() {
  const { ref = "" } = useParams();
  const number = Number(ref.replace(/^SV-/i, ""));
  const { t } = useTranslation();
  const can = useCan();
  const [finding, setFinding] = useState<FindingDetail | null>(null);
  const [events, setEvents] = useState<FindingEvent[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"false_positive" | "risk_accepted" | "help" | null>(null);
  const [helpText, setHelpText] = useState("");
  const [comment, setComment] = useState("");
  const [resolveHelp, setResolveHelp] = useState(false);

  const load = useCallback(async () => {
    if (!Number.isInteger(number) || number <= 0) {
      setLoadError(t("common.notFound"));
      return;
    }
    const res = await apiJson<FindingDetail>(`/api/v1/findings/by-number/${number}`);
    if (!res.ok || !res.data) {
      setLoadError(
        res.status === 404 ? t("common.notFound") : res.status === 403 ? t("common.forbidden") : t("common.error"),
      );
      return;
    }
    const found = res.data;
    setFinding(found);
    const [ev, dec] = await Promise.all([
      apiJson<FindingEvent[]>(`/api/v1/findings/${found.id}/events`),
      apiJson<Decision[]>(`/api/v1/findings/${found.id}/decisions`),
    ]);
    setEvents(ev.data ?? []);
    setDecisions(dec.data ?? []);
  }, [number, t]);

  useEffect(() => {
    // Переход между /f/SV-N: сбрасываем состояние предыдущей находки, иначе на миг
    // видно старые данные (или старую ошибку) поверх нового номера.
    setFinding(null);
    setLoadError(null);
    setEvents([]);
    setDecisions([]);
    setMessage(null);
  }, [number]);

  useEffect(() => {
    void load();
  }, [load]);

  const canTriage = can("finding:triage");
  const canApprove = can("finding:approve");
  const canAssign = canTriage && can("group:read");
  useEffect(() => {
    if (canAssign) void apiJson<Group[]>("/api/v1/groups").then((r) => setGroups(r.data ?? []));
  }, [canAssign]);

  if (loadError) return <p style={MUTED}>{loadError}</p>;
  if (!finding) return <p style={MUTED}>{t("common.loading")}</p>;

  const base = `/api/v1/findings/${finding.id}`;
  const isOpen = OPEN_STATUSES.includes(finding.status);
  const pending = decisions.find((d) => d.status === "pending") ?? null;

  const act = async (request: Promise<{ ok: boolean; error: string | null }>) => {
    setMessage(null);
    const res = await request;
    if (!res.ok) setMessage(res.error ?? t("common.error"));
    await load();
  };
  const setStatus = (status: string) => void act(apiJson(base, "PATCH", { status }));
  const submitDecision = async (body: DecisionBody) => {
    const res = await apiJson(`${base}/decisions`, "POST", body);
    if (!res.ok) return res.error ?? t("common.error");
    await load();
    return null;
  };
  const submitHelp = async () => {
    setDialog(null);
    await act(apiJson(`${base}/help`, "POST", { text: helpText.trim() }));
    setHelpText("");
  };
  const addComment = async () => {
    await act(apiJson(`${base}/comments`, "POST", { text: comment.trim(), resolve_help: resolveHelp }));
    setComment("");
    setResolveHelp(false);
  };
  const reassign = (value: string) => {
    if (!value) return;
    void act(apiJson(`${base}/assign`, "POST", value === "__rules" ? { by_rules: true } : { group_id: value }));
  };
  const decide = async (decision: Decision, approve: boolean) => {
    if (approve) {
      await act(apiJson(`/api/v1/decisions/${decision.id}/approve`, "POST", { comment: null }));
      return;
    }
    const reason = window.prompt(t("decision.rejectComment"));
    if (!reason?.trim()) return;
    await act(apiJson(`/api/v1/decisions/${decision.id}/reject`, "POST", { comment: reason.trim() }));
  };
  const copyLink = async () => {
    await navigator.clipboard
      .writeText(`${window.location.origin}/f/SV-${finding.number}`)
      .catch(() => undefined);
    setMessage(t("common.copied"));
  };

  const location = finding.file_path
    ? `${finding.file_path}${finding.line_start ? `:${finding.line_start}` : ""}`
    : t("common.none");

  return (
    <div style={{ maxWidth: 900 }}>
      <Link to="/vulnerabilities" style={{ fontSize: 12 }}>
        ← {t("window.back")}
      </Link>

      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", margin: "12px 0 4px" }}>
        <SeverityBadge severity={finding.severity} />
        <span style={MONO}>SV-{finding.number}</span>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>{t(`status.${finding.status}`)}</span>
        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
          {t("team.label")}: {finding.assignee_group?.name ?? t("team.none")}
          {finding.assigned_manually && ` (${t("team.manual")})`}
        </span>
        <span style={{ fontSize: 12, ...MUTED }}>
          {t("window.project")}: {finding.entity_path}
        </span>
        <span style={{ fontSize: 12 }}>
          {t("due.label")}: <DueBadge dueAt={finding.due_at} status={finding.status} />
          {finding.due_at && isOpen && <span style={MUTED}> ({t("window.dueUntil", { date: formatDate(finding.due_at) })})</span>}
        </span>
        <button onClick={copyLink} style={{ marginLeft: "auto", fontSize: 12 }}>
          {t("common.copyLink")}
        </button>
      </div>

      <h1 style={{ marginTop: 4 }}>{finding.title}</h1>
      {finding.description && finding.description !== finding.title && (
        <p style={{ color: "var(--text-secondary)", whiteSpace: "pre-wrap" }}>{finding.description}</p>
      )}
      {message && (
        <p role="status" style={{ fontSize: 13, color: "var(--accent)" }}>
          {message}
        </p>
      )}

      <section className="card" style={SECTION}>
        <div className="section-label">{t("window.where")}</div>
        <div style={MONO}>{location}</div>
        {(finding.code_url || finding.code_url_head) && (
          <div style={{ display: "flex", gap: 12, marginTop: 8, fontSize: 13 }}>
            {finding.code_url && (
              <a href={finding.code_url} target="_blank" rel="noopener noreferrer">
                {t("window.openInRepo")}
              </a>
            )}
            {finding.code_url_head && (
              <a href={finding.code_url_head} target="_blank" rel="noopener noreferrer">
                {t("window.openHead")}
              </a>
            )}
          </div>
        )}
      </section>

      <section className="card" style={SECTION}>
        <div className="section-label">{t("window.howToFix")}</div>
        <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{finding.help_text ?? t("window.noHelp")}</p>
        {isOpen && <p style={{ fontSize: 12, ...MUTED, marginBottom: 0 }}>{t("window.fixHint")}</p>}
      </section>

      {pending && (
        <section className="card" style={SECTION}>
          <div className="section-label">{t("decision.pending")}</div>
          <p style={{ margin: "0 0 8px" }}>
            {t(`decision.type.${pending.decision_type}`)}
            {pending.reason_tag && ` — ${t(`decision.tags.${pending.reason_tag}`)}`}
            {pending.expires_at && ` — ${t("decision.expiresAt")} ${formatDate(pending.expires_at)}`}
          </p>
          {pending.reason && <p style={{ whiteSpace: "pre-wrap" }}>{pending.reason}</p>}
          {canApprove && (
            <div style={{ display: "flex", gap: 8 }}>
              <button style={PRIMARY_BUTTON} onClick={() => void decide(pending, true)}>
                {t("decision.approve")}
              </button>
              <button onClick={() => void decide(pending, false)}>{t("decision.reject")}</button>
            </div>
          )}
        </section>
      )}

      {canTriage && isOpen && (
        <section style={{ ...SECTION, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {finding.status !== "in_progress" && (
            <button style={PRIMARY_BUTTON} onClick={() => setStatus("in_progress")}>
              {t("window.take")}
            </button>
          )}
          {canApprove && ["new", "triaged"].includes(finding.status) && (
            <button onClick={() => setStatus("confirmed")}>{t("window.confirm")}</button>
          )}
          {!pending && <button onClick={() => setDialog("false_positive")}>{t("window.falsePositive")}</button>}
          {canApprove && !pending && (
            <button onClick={() => setDialog("risk_accepted")}>{t("window.acceptRisk")}</button>
          )}
          {finding.help_requested_at ? (
            <span style={{ fontSize: 12, ...MUTED }}>
              {t("window.helpAsked", { date: formatDateTime(finding.help_requested_at) })}
            </span>
          ) : (
            <button onClick={() => setDialog("help")}>{t("window.needHelp")}</button>
          )}
          {canAssign && groups.length > 0 && (
            <select
              value=""
              onChange={(e) => reassign(e.target.value)}
              aria-label={t("window.reassign")}
              style={{ fontSize: 12 }}
            >
              <option value="">{t("window.reassign")}…</option>
              <option value="__rules">{t("window.byRules")}</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          )}
        </section>
      )}

      <section className="card" style={SECTION}>
        <div className="section-label">{t("window.history")}</div>
        <ol style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 10 }}>
          {events.map((ev) => (
            <li key={ev.id} style={{ fontSize: 13, borderLeft: "2px solid var(--border)", paddingLeft: 10 }}>
              <div style={{ fontSize: 12, ...MUTED }}>
                {formatDateTime(ev.created_at)} · {ev.actor_name ?? t("window.system")} ·{" "}
                {t(`window.events.${ev.event_type}`)}
                {ev.from_status && ev.to_status && ` · ${t(`status.${ev.from_status}`)} → ${t(`status.${ev.to_status}`)}`}
                {!ev.from_status && ev.to_status && ` · ${t(`status.${ev.to_status}`)}`}
              </div>
              {ev.reason && <div style={{ whiteSpace: "pre-wrap" }}>{ev.reason}</div>}
            </li>
          ))}
        </ol>
        {canTriage && (
          <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
            <textarea
              rows={2}
              value={comment}
              placeholder={t("window.commentPlaceholder")}
              aria-label={t("window.commentPlaceholder")}
              onChange={(e) => setComment(e.target.value)}
              style={{ width: "100%", boxSizing: "border-box" }}
            />
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              {canApprove && finding.help_requested_at && (
                <label style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center" }}>
                  <input type="checkbox" checked={resolveHelp} onChange={(e) => setResolveHelp(e.target.checked)} />
                  {t("window.resolveHelp")}
                </label>
              )}
              <button onClick={addComment} disabled={!comment.trim()} style={{ marginLeft: "auto" }}>
                {t("window.addComment")}
              </button>
            </div>
          </div>
        )}
      </section>

      <details className="card" style={SECTION}>
        <summary style={{ cursor: "pointer" }}>{t("window.details")}</summary>
        <dl
          style={{
            display: "grid",
            gridTemplateColumns: "max-content 1fr",
            gap: "4px 16px",
            fontSize: 13,
            margin: "12px 0 0",
          }}
        >
          <dt>{t("window.scanner")}</dt>
          <dd style={{ margin: 0 }}>{finding.scanner}</dd>
          <dt>{t("window.rule")}</dt>
          <dd style={{ margin: 0, ...MONO }}>{finding.rule_id ?? t("common.none")}</dd>
          <dt>{t("window.cwe")}</dt>
          <dd style={{ margin: 0 }}>{finding.cwe ?? t("common.none")}</dd>
          <dt>{t("window.commit")}</dt>
          <dd style={{ margin: 0, ...MONO }}>{finding.commit_sha?.slice(0, 12) ?? t("common.none")}</dd>
          <dt>{t("window.firstSeen")}</dt>
          <dd style={{ margin: 0 }}>{formatDateTime(finding.first_seen)}</dd>
          <dt>{t("window.lastSeen")}</dt>
          <dd style={{ margin: 0 }}>{formatDateTime(finding.last_seen)}</dd>
          {finding.resolved_at && (
            <>
              <dt>{t("window.resolvedAt")}</dt>
              <dd style={{ margin: 0 }}>{formatDateTime(finding.resolved_at)}</dd>
            </>
          )}
        </dl>
      </details>

      {(dialog === "false_positive" || dialog === "risk_accepted") && (
        <DecisionDialog mode={dialog} onSubmit={submitDecision} onClose={() => setDialog(null)} />
      )}
      {dialog === "help" && (
        <Modal title={t("window.needHelp")} onClose={() => setDialog(null)}>
          <textarea
            rows={4}
            value={helpText}
            placeholder={t("window.helpPlaceholder")}
            aria-label={t("window.helpPlaceholder")}
            onChange={(e) => setHelpText(e.target.value)}
            style={{ width: "100%", boxSizing: "border-box" }}
          />
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 10 }}>
            <button onClick={() => setDialog(null)}>{t("common.cancel")}</button>
            <button style={PRIMARY_BUTTON} disabled={!helpText.trim()} onClick={submitHelp}>
              {t("window.send")}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
