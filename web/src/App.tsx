import { Link, Outlet } from "react-router-dom";

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>
          <Link to="/">TestPilot</Link>
        </h1>
        <span className="muted">Nouveau job &amp; traçabilité</span>
      </header>
      <Outlet />
    </div>
  );
}
