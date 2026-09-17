import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";

const NAV_ITEMS = [
  { to: "/", key: "nav.dashboard", end: true },
  { to: "/assets", key: "nav.assets" },
  { to: "/findings", key: "nav.findings" },
  { to: "/imports", key: "nav.imports" },
  { to: "/groups", key: "nav.groups" },
  { to: "/roles", key: "nav.rolesNav" },
] as const;

function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = localStorage.getItem("sv-theme");
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("sv-theme", theme);
  }, [theme]);
  return { theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) };
}

export function Layout() {
  const { t } = useTranslation();
  const { theme, toggle } = useTheme();
  const { user, logout } = useAuth();

  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <aside
        style={{
          width: 200,
          flexShrink: 0,
          background: "var(--bg-sidebar)",
          borderRight: "1px solid var(--border)",
          padding: "16px 10px",
          display: "flex",
          flexDirection: "column",
          gap: 2,
        }}
      >
        <div style={{ padding: "6px 10px", marginBottom: 14, fontWeight: 600, fontSize: 15 }}>
          {t("app.name")}
          <div style={{ fontSize: 11, fontWeight: 400, color: "var(--text-muted)" }}>
            {t("app.tagline")}
          </div>
        </div>
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={"end" in item && item.end}
            style={({ isActive }) => ({
              padding: "8px 10px",
              borderRadius: "var(--radius)",
              fontSize: 13,
              fontWeight: isActive ? 500 : 400,
              color: isActive ? "var(--accent)" : "var(--text-secondary)",
              background: isActive ? "var(--accent-bg)" : "transparent",
            })}
          >
            {t(item.key)}
          </NavLink>
        ))}
        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
          <button onClick={toggle}>
            {t("nav.theme")}: {theme === "dark" ? "тёмная" : "светлая"}
          </button>
          {user && (
            <div
              style={{
                borderTop: "1px solid var(--border)",
                paddingTop: 10,
                display: "flex",
                flexDirection: "column",
                gap: 6,
              }}
            >
              <div style={{ fontSize: 12, lineHeight: 1.3, minWidth: 0 }}>
                <div
                  style={{
                    fontWeight: 500,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {user.full_name || user.email}
                </div>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                  {user.auth_source === "ldap" ? "LDAP" : t("auth.local")}
                </div>
              </div>
              <button onClick={logout} style={{ fontSize: 12 }}>
                {t("auth.logout")}
              </button>
            </div>
          )}
        </div>
      </aside>
      <main style={{ flex: 1, minWidth: 0, padding: "24px 32px" }}>
        <Outlet />
      </main>
    </div>
  );
}
