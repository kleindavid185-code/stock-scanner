import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function OwnerRoute() {
  const { isOwner, loading } = useAuth();

  if (loading) return <div className="center">Loading…</div>;
  if (!isOwner) return <Navigate to="/" replace />;

  return <Outlet />;
}
