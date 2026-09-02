import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { IconEye, IconEyeOff, IconWifi } from "../components/icons";
import { Button } from "../components/ui/Button";

const accounts = ["customer@demo.com", "agent@demo.com", "reviewer@demo.com", "kbmanager@demo.com", "teamlead@demo.com", "sysadmin@demo.com", "auditor@demo.com"];
const landing: Record<string, string> = { customer: "/portal", support_agent: "/agent", reviewer: "/review", knowledge_manager: "/knowledge", team_lead: "/operations", system_admin: "/admin", auditor: "/audit" };

export default function Login() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("agent@demo.com");
  const [password, setPassword] = useState("Demo@123");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [offline, setOffline] = useState(false);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={landing[user.role] || "/dashboard"} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true); setError(""); setOffline(false);
    try {
      const current = await login(email, password);
      nav((location.state as { from?: string })?.from || landing[current.role] || "/dashboard", { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to sign in";
      setOffline(/unable to connect|check that the backend/i.test(message));
      setError(message);
    } finally { setBusy(false); }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit} aria-labelledby="login-heading">
        <div className="login-brand">
          <div className="brandmark">T</div>
          <div><b>Ticket<em>Sense</em></b><small>AI SUPPORT INTELLIGENCE</small></div>
        </div>
        <h1 id="login-heading">Welcome back</h1>
        <p>Sign in to your enterprise support workspace.</p>

        <label htmlFor="login-email">Email
          <select id="login-email" value={email} onChange={e => setEmail(e.target.value)}>
            {accounts.map(a => <option key={a}>{a}</option>)}
          </select>
        </label>

        <label htmlFor="login-password">Password
          <div className="ui-password-field">
            <input
              id="login-password"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
            <button
              type="button"
              className="ui-icon-btn ui-btn-ghost"
              onClick={() => setShowPassword(v => !v)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
            >
              {showPassword ? <IconEyeOff size={16} /> : <IconEye size={16} />}
            </button>
          </div>
        </label>

        {error && (
          <div className="error-box" role="alert">
            {offline && <IconWifi size={16} />}
            <span>{offline ? "Can't reach the TicketSense backend. Confirm the API service is running and try again." : error}</span>
          </div>
        )}

        <Button type="submit" variant="primary" className="login-submit" loading={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
        <small className="demo-note">Development accounts use the password <b>Demo@123</b></small>
      </form>
    </main>
  );
}
