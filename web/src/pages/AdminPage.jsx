import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";

const ROLES = ["free", "paid", "owner"];

export default function AdminPage() {
  const { user } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [updatingId, setUpdatingId] = useState(null);

  const load = useCallback(async () => {
    try {
      setError(null);
      const data = await api.adminListUsers();
      setUsers(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const changeRole = async (userId, role) => {
    setUpdatingId(userId);
    setError(null);
    try {
      await api.adminSetUserRole(userId, role);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setUpdatingId(null);
    }
  };

  if (loading) return <div className="center">Loading…</div>;

  return (
    <div className="page">
      <p className="disclaimer">
        All registered users. Flip a user's role to "paid" once they've paid
        you outside the app — unlocks Signals, AI Search, and "Why it's
        moving" for them on their very next request.
      </p>
      {error && <p className="error-text">{error}</p>}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Joined</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td className="mono">{u.email}</td>
                <td className="mono">{u.role}</td>
                <td className="mono">{u.created_at?.slice(0, 10)}</td>
                <td>
                  {u.id === user.id ? (
                    <span className="sub">(you)</span>
                  ) : (
                    <div style={{ display: "flex", gap: 6 }}>
                      {ROLES.filter((r) => r !== u.role).map((r) => (
                        <button
                          key={r}
                          className="btn-refresh"
                          disabled={updatingId === u.id}
                          onClick={() => changeRole(u.id, r)}
                        >
                          Make {r}
                        </button>
                      ))}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!users.length && <div className="empty">No users yet.</div>}
      </div>
    </div>
  );
}
