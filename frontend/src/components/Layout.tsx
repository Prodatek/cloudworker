import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function Layout() {
  const { isAuthenticated, user, logout } = useAuth();

  return (
    <div className="app-shell">
      <nav className="app-nav">
        <span className="brand">CloudWorker</span>
        {isAuthenticated && (
          <>
            <NavLink to="/jobs" className={({ isActive }) => (isActive ? "active" : "")}>
              Jobs
            </NavLink>
            <NavLink to="/jobs/new" className={({ isActive }) => (isActive ? "active" : "")}>
              New Job
            </NavLink>
            <NavLink to="/api-keys" className={({ isActive }) => (isActive ? "active" : "")}>
              API Keys
            </NavLink>
          </>
        )}
        {isAuthenticated ? (
          <span className="muted">
            {user?.email}{" "}
            <button type="button" className="secondary" onClick={logout}>
              Log out
            </button>
          </span>
        ) : (
          <>
            <NavLink to="/login">Log in</NavLink>
            <NavLink to="/register">Register</NavLink>
          </>
        )}
      </nav>
      <Outlet />
    </div>
  );
}
