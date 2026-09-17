import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Assets } from "./pages/Assets";
import { Dashboard } from "./pages/Dashboard";
import { Findings } from "./pages/Findings";
import { Groups } from "./pages/Groups";
import { Imports } from "./pages/Imports";
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
            <Route path="assets" element={<Assets />} />
            <Route path="findings" element={<Findings />} />
            <Route path="imports" element={<Imports />} />
            <Route path="groups" element={<Groups />} />
            <Route path="roles" element={<Roles />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
