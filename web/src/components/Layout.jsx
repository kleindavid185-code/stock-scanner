import { NavLink, Outlet } from "react-router-dom";

const TABS = [
  { to: "/", label: "Scanner", end: true },
  { to: "/watchlists", label: "Watchlists" },
  { to: "/ai-search", label: "AI Search" },
  { to: "/signals", label: "Signals" },
];

export default function Layout() {
  return (
    <div className="app-shell">
      <nav className="sidebar">
        <h1>Market Scanner</h1>
        {TABS.map((tab) => (
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
      </nav>
      <div className="main-panel">
        <Outlet />
      </div>
    </div>
  );
}
