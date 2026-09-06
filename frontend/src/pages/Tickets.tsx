import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, type Ticket } from "../api/client";
import { Badge, Empty, ErrorState, Loading, SyncIndicator } from "../components/States";
import { useAuth } from "../auth/AuthContext";
import { IconPlus } from "../components/icons";
import { Button } from "../components/ui/Button";
import { FilterBar, Pagination, SearchInput } from "../components/ui/Utility";
import { useAutoRefresh } from "../lib/useAutoRefresh";
import { useLiveEvents } from "../lib/useLiveEvents";

const PAGE_SIZE = 10;

export default function Tickets({ escalated = false }: { escalated?: boolean }) {
  const { hasPermission } = useAuth();
  const internal = hasPermission("ai:view_confidence");
  const location = useLocation();
  const navigate = useNavigate();
  const initial = new URLSearchParams(location.search).get("q") || "";
  const [q, setQ] = useState(initial);
  const [status, setStatus] = useState(escalated ? "escalated" : "");
  const [priority, setPriority] = useState("");
  const [sort, setSort] = useState<"newest" | "oldest">("newest");
  const [page, setPage] = useState(1);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load(opts: { silent?: boolean } = {}) {
    if (!opts.silent) { setLoading(true); setError(""); }
    try { setTickets(await api.tickets(q, status)); }
    catch (e) { if (!opts.silent) setError(e instanceof Error ? e.message : "Request failed"); else throw e; }
    finally { if (!opts.silent) setLoading(false); }
  }
  useEffect(() => { load(); }, [location.search, escalated]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setPage(1); }, [priority, sort, status]);
  const { status: syncStatus, lastSyncedAt, retryNow } = useAutoRefresh(() => load({ silent: true }), undefined, !loading && !error);
  useLiveEvents(!loading && !error, () => retryNow()); // low-latency nudge only; polling above never stops

  function search(e: FormEvent) { e.preventDefault(); navigate(`/tickets${q ? `?q=${encodeURIComponent(q)}` : ""}`); load(); }
  function clearFilters() { setQ(""); setStatus(escalated ? "escalated" : ""); setPriority(""); setSort("newest"); navigate("/tickets"); }
  const filtersActive = Boolean(q || (status && !escalated) || priority || sort !== "newest");

  const filtered = useMemo(() => {
    let rows = priority ? tickets.filter(t => t.priority === priority) : tickets;
    rows = [...rows].sort((a, b) => sort === "newest"
      ? new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      : new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    return rows;
  }, [tickets, priority, sort]);
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="content">
      <div className="page-title">
        <div><h1>{escalated ? "Escalations" : "Tickets"}</h1><p>{escalated ? "Tickets requiring expert intervention." : internal ? "Search the authorized department queue." : "Track the support tickets you created."}</p></div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <SyncIndicator status={syncStatus} lastSyncedAt={lastSyncedAt} onRetry={retryNow} />
          <Button variant="primary" icon={<IconPlus size={15} />} onClick={() => navigate("/tickets/new")}>New ticket</Button>
        </div>
      </div>

      <FilterBar>
        <form onSubmit={search} style={{ display: "flex", flex: 1, gap: 8, minWidth: 220 }}>
          <SearchInput value={q} onChange={setQ} placeholder="Search title or description" ariaLabel="Search tickets" />
          <button className="ui-btn ui-btn-outline ui-btn-md" type="submit">Search</button>
        </form>
        {!escalated && (
          <select value={status} onChange={e => setStatus(e.target.value)} aria-label="Filter by status">
            <option value="">All statuses</option>
            <option value="submitted">Submitted</option>
            <option value="routed">Routed</option>
            <option value="assigned">Assigned</option>
            <option value="in_progress">In progress</option>
            <option value="pending_review">Pending review</option>
            <option value="changes_requested">Changes requested</option>
            <option value="resolved">Resolved</option>
            <option value="escalated">Escalated</option>
          </select>
        )}
        <select value={priority} onChange={e => setPriority(e.target.value)} aria-label="Filter by priority">
          <option value="">All priorities</option>
          <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="urgent">Urgent</option>
        </select>
        <select value={sort} onChange={e => setSort(e.target.value as "newest" | "oldest")} aria-label="Sort order">
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
        </select>
        {filtersActive && <Button variant="ghost" size="sm" onClick={clearFilters}>Clear filters</Button>}
      </FilterBar>

      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : filtered.length ? (
        <>
          <p className="result-count">{filtered.length} ticket{filtered.length === 1 ? "" : "s"}{filtersActive ? " matching your filters" : ""}</p>
          <div className="panel ticket-list">
            <div className="list-head"><span>Ticket</span><span>Priority</span>{internal && <span>Confidence</span>}<span>Status</span></div>
            {paged.map(t => (
              <Link to={`/tickets/${t.id}`} className="list-row" key={t.id}>
                <div><b>{t.subject}</b><small>{t.id.slice(0, 8)} · {new Date(t.created_at).toLocaleString()}</small></div>
                <Badge value={t.priority} />
                {internal && <strong>{Math.round((t.confidence_score || 0) * 100)}%</strong>}
                <Badge value={t.status} />
              </Link>
            ))}
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={filtered.length} onPageChange={setPage} />
        </>
      ) : (
        <Empty label={filtersActive ? "No tickets match these filters." : "You have no matching tickets."} action={filtersActive && <Button variant="outline" size="sm" onClick={clearFilters}>Clear filters</Button>} />
      )}
    </div>
  );
}
