import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const TABS = [
  { to: "/", label: "Scanner", end: true },
  { to: "/watchlists", label: "Watchlists" },
  { to: "/ai-search", label: "AI Search" },
  { to: "/signals", label: "Signals" },
  { to: "/earnings", label: "Earnings" },
];

export default function Layout() {
  const { user, isOwner, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const tabs = isOwner ? [...TABS, { to: "/admin", label: "Admin" }] : TABS;

  return (
    <div className="app-shell">
      <nav className="sidebar">
        <h1>Market Scanner</h1>
        {tabs.map((tab) => (
          <NavLink
            key={tab.to}
            to={tab.to}
            end={tab.end}
            className={({ isActive }) =>
              "nav-link" + (isActive ? " active" : "")
            }
          >
            {tab.label}
          </NavLink>
        ))}
        {user && (
          <div className="user-footer">
            <div className="email">{user.email}</div>
            <button className="logout-btn" onClick={handleLogout}>
              Log out
            </button>
          </div>
        )}
      </nav>
      <div className="main-panel">
        <Outlet />
      </div>
    </div>
  );
}
