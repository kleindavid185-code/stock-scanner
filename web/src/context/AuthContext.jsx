import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, setAuthToken } from "../api/client";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) {
      setLoading(false);
      return;
    }
    setAuthToken(token);
    api
      .me()
      .then((data) => setUser(data.user))
      .catch(() => {
        localStorage.removeItem("token");
        setAuthToken(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email, password) => {
    const data = await api.login(email, password);
    localStorage.setItem("token", data.token);
    setAuthToken(data.token);
    setUser(data.user);
  }, []);

  const signup = useCallback(async (email, password) => {
    const data = await api.signup(email, password);
    localStorage.setItem("token", data.token);
    setAuthToken(data.token);
    setUser(data.user);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("token");
    setAuthToken(null);
    setUser(null);
  }, []);

  const hasFullAccess = user ? user.role === "owner" || user.role === "paid" : false;
  const isOwner = user?.role === "owner";

  return (
    <AuthContext.Provider
      value={{ user, loading, login, signup, logout, hasFullAccess, isOwner }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
