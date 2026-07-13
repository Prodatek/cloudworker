import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { api, getStoredToken, setStoredToken } from "../api/client";

interface CurrentUser {
  userId: string;
  email: string;
}

interface AuthContextValue {
  user: CurrentUser | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const USER_STORAGE_KEY = "cloudworker.user";

const AuthContext = createContext<AuthContextValue | null>(null);

function loadStoredUser(): CurrentUser | null {
  const raw = localStorage.getItem(USER_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as CurrentUser;
  } catch {
    return null;
  }
}

function storeUser(user: CurrentUser | null): void {
  if (user) {
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
  } else {
    localStorage.removeItem(USER_STORAGE_KEY);
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(() =>
    getStoredToken() ? loadStoredUser() : null,
  );

  const login = useCallback(async (email: string, password: string) => {
    const { data, error } = await api.POST("/api/v1/auth/login", {
      body: { email, password },
    });
    if (error) {
      throw new Error("Invalid email or password");
    }
    setStoredToken(data.access_token);
    const nextUser = { userId: data.user_id, email: data.email };
    storeUser(nextUser);
    setUser(nextUser);
  }, []);

  const register = useCallback(
    async (email: string, password: string) => {
      const { error: registerError } = await api.POST("/api/v1/auth/register", {
        body: { email, password },
      });
      if (registerError) {
        const detail =
          "detail" in registerError && typeof registerError.detail === "string"
            ? registerError.detail
            : "Registration failed";
        throw new Error(detail);
      }
      // Registration only returns an API key, not a session — log in right after so
      // the dashboard flow is a single "create account" step from the user's view.
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(() => {
    setStoredToken(null);
    storeUser(null);
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, isAuthenticated: user !== null, login, register, logout }),
    [user, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
