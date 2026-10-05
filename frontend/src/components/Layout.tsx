import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth, useCan } from "../auth/AuthContext";
import { useTheme } from "../theme/ThemeContext";
import { THEMES, isThemeId } from "../theme/themes";

const NAV_ITEMS: { to: string; key: string; end?: boolean; perm?: string }[] = [
  { to: "/", key: "nav.dashboard", end: true },
  { to: "/my", key: "nav.my" },
  { to: "/inbox", key: "nav.inbox", perm: "finding:approve" },
  { to: "/projects", key: "nav.projects" },
  { to: "/vulnerabilities", key: "nav.vulns" },
  { to: "/imports", key: "nav.imports" },
  { to: "/sla", key: "nav.sla", perm: "sla:read" },
  { to: "/groups", key: "nav.groups" },
  { to: "/roles", key: "nav.rolesNav" },
  { to: "/audit", key: "nav.audit", perm: "audit:read" },
];

export function Layout() {
  const { t } = useTranslation();
  const { theme, setTheme } = useTheme();
  const { user, logout } = useAuth();
  const can = useCan();

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
        <div style={{ padding: "6px 10px", marginBottom: 14 }}>
          <div
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 14,
              fontWeight: 500,
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--accent)",
              textShadow: "var(--glow)",
            }}
          >
            {t("app.name")}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{t("app.tagline")}</div>
        </div>
        {NAV_ITEMS.filter((item) => !item.perm || can(item.perm)).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            style={({ isActive }) => ({
              padding: "8px 10px",
              fontFamily: "var(--font-display)",
              fontSize: 12,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              fontWeight: isActive ? 500 : 400,
              color: isActive ? "var(--accent)" : "var(--text-secondary)",
              background: isActive ? "var(--accent-bg)" : "transparent",
              borderLeft: isActive ? "2px solid var(--accent)" : "2px solid transparent",
            })}
          >
            {t(item.key)}
          </NavLink>
        ))}
        <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
          <label style={{ fontSize: 11, color: "var(--text-muted)" }}>
            {t("nav.theme")}
            <select
              value={theme}
              onChange={(e) => isThemeId(e.target.value) && setTheme(e.target.value)}
              style={{ width: "100%", fontSize: 12, padding: "5px 6px", marginTop: 4 }}
            >
              {THEMES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
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
