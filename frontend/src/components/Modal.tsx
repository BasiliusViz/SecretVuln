import { useEffect } from "react";

/** Модальное окно: закрывается по Esc и клику на фон. */
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0, 0, 0, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 50,
        padding: 16,
      }}
    >
      <div
        className="card"
        onClick={(e) => e.stopPropagation()}
        style={{ width: "100%", maxWidth: 520, maxHeight: "90vh", overflow: "auto" }}
      >
        <h2 style={{ marginTop: 0, fontSize: 16 }}>{title}</h2>
        {children}
      </div>
    </div>
  );
}
