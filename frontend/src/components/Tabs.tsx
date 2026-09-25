/** Вкладки-переключатель (очередь AppSec, «Мои уязвимости»). */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
}: {
  tabs: { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={label}
      style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--border)", marginBottom: 12 }}
    >
      {tabs.map((tab) => {
        const active = tab.id === value;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.id)}
            style={{
              border: "none",
              borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
              borderRadius: 0,
              background: "transparent",
              color: active ? "var(--accent)" : "var(--text-secondary)",
              padding: "8px 12px",
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
