import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { apiFetch } from "../lib/apiClient";

export interface User {
  id: string;
  email: string;
  name: string;
  role: "commuter" | "admin" | "depot_manager" | "conductor" | "driver";
  preferred_lang?: string;
  phone?: string;
  reliability?: number;
  gender?: Gender | null;
  /** Null (not false) when the server could not determine it — see /auth/me. */
  shakti_eligible?: boolean | null;
}

export type Gender = "male" | "female" | "transgender" | "prefer_not_to_say";

interface AuthContextType {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (data: RegisterData) => Promise<void>;
  logout: () => void;
  isAdmin: boolean;
  isDepot: boolean;
  isConductor: boolean;
  isAuthenticated: boolean;
}

interface RegisterData {
  email: string;
  name: string;
  password: string;
  phone?: string;
  preferred_lang?: string;
  role?: string;
  gender?: Gender | "";
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  token: null,
  loading: true,
  login: async () => {},
  register: async () => {},
  logout: () => {},
  isAdmin: false,
  isDepot: false,
  isConductor: false,
  isAuthenticated: false,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("bmtc-token"));
  const [loading, setLoading] = useState(true);

  // On mount / token change, fetch user profile
  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    fetchMe(token)
      .then((u) => setUser(u))
      .catch(() => {
        localStorage.removeItem("bmtc-token");
        setToken(null);
      })
      .finally(() => setLoading(false));
  }, [token]);

  const login = async (email: string, password: string) => {
    const res = await apiFetch(`/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Login failed" }));
      throw new Error(err.detail || "Login failed");
    }
    const data = await res.json();
    localStorage.setItem("bmtc-token", data.access_token);
    localStorage.setItem("bmtc-refresh", data.refresh_token);
    setToken(data.access_token);
    setUser(data.user);
  };

  const register = async (regData: RegisterData) => {
    // The select's "not chosen" value is an empty string, which the server's
    // gender enum rejects. Drop the key entirely rather than sending "" —
    // absent means "not answered", which is exactly what happened.
    const { gender, ...rest } = regData;
    const body = gender ? { ...rest, gender } : rest;

    const res = await apiFetch(`/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Registration failed" }));
      throw new Error(err.detail || "Registration failed");
    }
    const data = await res.json();
    localStorage.setItem("bmtc-token", data.access_token);
    localStorage.setItem("bmtc-refresh", data.refresh_token);
    setToken(data.access_token);
    setUser(data.user);
  };

  const logout = () => {
    localStorage.removeItem("bmtc-token");
    localStorage.removeItem("bmtc-refresh");
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        login,
        register,
        logout,
        isAdmin: user?.role === "admin",
        isDepot: user?.role === "depot_manager",
        isConductor: user?.role === "conductor",
        isAuthenticated: !!user,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

async function fetchMe(token: string): Promise<User> {
  const res = await apiFetch(`/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Not authenticated");
  const data = await res.json();
  return data.user || data;
}

export const useAuth = () => useContext(AuthContext);
