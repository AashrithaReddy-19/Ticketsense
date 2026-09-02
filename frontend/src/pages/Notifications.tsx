import { useEffect, useState } from "react";
import { api, type Notification } from "../api/client";
import { Empty, ErrorState, Loading } from "../components/States";
import { IconRefresh } from "../components/icons";
import { Button } from "../components/ui/Button";

export default function Notifications() {
  const [items, setItems] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    try { setItems(await api.notifications()); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function read(id: string) {
    try { await api.markNotificationRead(id); setItems(x => x.map(n => n.id === id ? { ...n, is_read: true } : n)); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to update notification"); }
  }

  return (
    <div className="content">
      <div className="page-title">
        <div><h1>Notifications</h1><p>Real account and ticket updates.</p></div>
        <Button variant="outline" icon={<IconRefresh size={14} />} onClick={load}>Refresh</Button>
      </div>
      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : items.length ? (
        <div className="panel notification-list">
          {items.map(n => (
            <button key={n.id} className={n.is_read ? "read" : ""} onClick={() => read(n.id)}>
              <i aria-hidden="true" />
              <div><b>{n.title}</b><p>{n.message}</p><small>{new Date(n.created_at).toLocaleString()}</small></div>
              <span>{n.is_read ? "Read" : "Mark read"}</span>
            </button>
          ))}
        </div>
      ) : <Empty label="No notifications." />}
    </div>
  );
}
