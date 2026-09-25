import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { ThemeProvider } from "./theme/ThemeContext";
import { Assets } from "./pages/Assets";
import { Dashboard } from "./pages/Dashboard";
import { FindingWindow } from "./pages/FindingWindow";
import { Findings } from "./pages/Findings";
import { Groups } from "./pages/Groups";
import { Imports } from "./pages/Imports";
import { Inbox } from "./pages/Inbox";
import { Login } from "./pages/Login";
import { Roles } from "./pages/Roles";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return <div style={{ padding: 40, color: "var(--text-muted)" }}>Загрузка…</div>;
  }
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function LoginRoute() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/" replace />;
  return <Login />;
}

export function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginRoute />} />
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="projects" element={<Assets />} />
              <Route path="vulnerabilities" element={<Findings />} />
              <Route path="f/:ref" element={<FindingWindow />} />
              <Route path="inbox" element={<Inbox />} />
              <Route path="imports" element={<Imports />} />
              <Route path="groups" element={<Groups />} />
              <Route path="roles" element={<Roles />} />
              {/* старые адреса — чтобы не ломались сохранённые ссылки */}
              <Route path="assets" element={<Navigate to="/projects" replace />} />
              <Route path="findings" element={<Navigate to="/vulnerabilities" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}
