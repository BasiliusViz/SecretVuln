import { createContext, useCallback, useContext, useEffect, useState } from "react";

export interface CurrentUser {
  id: string;
  email: string;
  full_name: string | null;
  auth_source: string;
  is_superuser: boolean;
  roles: string[];
  // Права вида "finding:approve" — считает бэкенд (/auth/me), у суперюзера все
  permissions: string[];
}

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const TOKEN_KEY = "sv-token";
const AuthContext = createContext<AuthState | null>(null);

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchMe = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const res = await fetch("/api/v1/auth/me", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setUser(await res.json());
      } else {
        localStorage.removeItem(TOKEN_KEY);
        setUser(null);
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMe();
  }, [fetchMe]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) {
        let detail = "";
        try {
          detail = (await res.json()).detail;
        } catch {
          /* ignore */
        }
        const err = new Error(detail || `HTTP ${res.status}`);
        (err as Error & { status?: number }).status = res.status;
        throw err;
      }
      const { access_token } = await res.json();
      localStorage.setItem(TOKEN_KEY, access_token);
      await fetchMe();
    },
    [fetchMe],
  );

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

/** Проверка права текущего пользователя, например can("finding:approve"). */
export function useCan(): (permission: string) => boolean {
  const { user } = useAuth();
  return useCallback(
    (permission: string) => !!user && user.permissions.includes(permission),
    [user],
  );
}
