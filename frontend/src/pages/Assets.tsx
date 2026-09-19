import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { apiFetch } from "../api/client";

interface EntityNode {
  id: string;
  name: string;
  parent_id: string | null;
  description: string | null;
}

function useEntities() {
  const [items, setItems] = useState<EntityNode[] | null>(null);
  const [error, setError] = useState(false);
  const reload = useCallback(() => {
    apiFetch("/api/v1/entities")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setItems)
      .catch(() => setError(true));
  }, []);
  useEffect(reload, [reload]);
  return { items, error, reload };
}

function CreateForm({
  parent,
  onDone,
  onCancel,
}: {
  parent: EntityNode | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    const res = await apiFetch("/api/v1/entities", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name.trim(),
        description: description.trim() || null,
        parent_id: parent?.id ?? null,
      }),
    }).catch(() => null);
    setBusy(false);
    if (res?.status === 201) {
      onDone();
    } else if (res?.status === 409) {
      setError(t("projects.duplicate"));
    } else {
      setError(t("projects.saveError"));
    }
  };

  const inputStyle = {
    fontFamily: "inherit",
    fontSize: 13,
    color: "var(--text-primary)",
    background: "var(--bg-page)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius)",
    padding: "6px 10px",
  } as const;

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ fontWeight: 500, marginBottom: 10 }}>
        {parent ? t("projects.createChildIn", { name: parent.name }) : t("projects.createRoot")}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 10 }}>
        <input
          style={{ ...inputStyle, flex: "1 1 200px" }}
          placeholder={t("projects.name")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <input
          style={{ ...inputStyle, flex: "2 1 260px" }}
          placeholder={t("projects.description")}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      {error && <div style={{ color: "#A32D2D", fontSize: 12, marginBottom: 8 }}>{error}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button onClick={submit} disabled={busy || !name.trim()}>
          {t("projects.create")}
        </button>
        <button onClick={onCancel}>{t("projects.cancel")}</button>
      </div>
    </div>
  );
}

function TreeNode({
  node,
  childrenMap,
  depth,
  onAddChild,
  onDelete,
}: {
  node: EntityNode;
  childrenMap: Map<string | null, EntityNode[]>;
  depth: number;
  onAddChild: (node: EntityNode) => void;
  onDelete: (node: EntityNode) => void;
}) {
  const { t } = useTranslation();
  const children = childrenMap.get(node.id) ?? [];
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 12px",
          paddingLeft: 12 + depth * 24,
          borderTop: "1px solid var(--border)",
        }}
      >
        <span aria-hidden="true" style={{ color: "var(--text-muted)", fontSize: 12 }}>
          {children.length > 0 ? "в–ё" : "В·"}
        </span>
        <span style={{ fontWeight: 500 }}>{node.name}</span>
        {node.description && (
          <span
            style={{
              fontSize: 12,
              color: "var(--text-muted)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              flex: 1,
              minWidth: 0,
            }}
          >
            {node.description}
          </span>
        )}
        <span style={{ marginLeft: "auto", display: "flex", gap: 6, flexShrink: 0 }}>
          <button style={{ fontSize: 12, padding: "2px 10px" }} onClick={() => onAddChild(node)}>
            + {t("projects.addChild")}
          </button>
          <button
            style={{ fontSize: 12, padding: "2px 10px", color: "var(--text-muted)" }}
            onClick={() => onDelete(node)}
            aria-label={t("projects.delete")}
          >
            вњ•
          </button>
        </span>
      </div>
      {children.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          childrenMap={childrenMap}
          depth={depth + 1}
          onAddChild={onAddChild}
          onDelete={onDelete}
        />
      ))}
    </>
  );
}

export function Assets() {
  const { t } = useTranslation();
  const { items, error, reload } = useEntities();
  const [formParent, setFormParent] = useState<EntityNode | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const childrenMap = useMemo(() => {
    const map = new Map<string | null, EntityNode[]>();
    for (const item of items ?? []) {
      const list = map.get(item.parent_id) ?? [];
      list.push(item);
      map.set(item.parent_id, list);
    }
    return map;
  }, [items]);

  const handleDelete = async (node: EntityNode) => {
    if (!window.confirm(t("projects.deleteConfirm", { name: node.name }))) return;
    await apiFetch(`/api/v1/entities/${node.id}`, { method: "DELETE" });
    reload();
  };

  const roots = childrenMap.get(null) ?? [];

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1>{t("projects.title")}</h1>
        <button
          onClick={() => {
            setFormParent(null);
            setFormOpen(true);
          }}
        >
          + {t("projects.createRoot")}
        </button>
      </div>
      {formOpen && (
        <CreateForm
          parent={formParent}
          onDone={() => {
            setFormOpen(false);
            reload();
          }}
          onCancel={() => setFormOpen(false)}
        />
      )}
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        {error ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("common.error")}</p>
        ) : items === null ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>
            {t("common.loading")}
          </p>
        ) : roots.length === 0 ? (
          <p style={{ color: "var(--text-muted)", margin: 0, padding: 16 }}>{t("projects.empty")}</p>
        ) : (
          <div style={{ marginTop: -1 }}>
            {roots.map((node) => (
              <TreeNode
                key={node.id}
                node={node}
                childrenMap={childrenMap}
                depth={0}
                onAddChild={(n) => {
                  setFormParent(n);
                  setFormOpen(true);
                }}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
