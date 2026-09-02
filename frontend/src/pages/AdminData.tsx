import { useEffect, useMemo, useState } from "react";
import { Empty, ErrorState, Loading } from "../components/States";
import { api } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { IconRefresh } from "../components/icons";
import { Button } from "../components/ui/Button";
import { ReadOnlyPill } from "../components/ui/Badges";
import { Pagination, SearchInput } from "../components/ui/Utility";

const PAGE_SIZE = 12;

export function Audit() { return <DataPage title="Audit logs" description="Tenant-scoped security and operational events." loader={api.auditLogs} readOnlyForAuditor /> }
export function Integrations() { return <DataPage title="Integrations" description="Configured enterprise connection providers." loader={api.integrations} /> }
export function AIMetrics() { return <DataPage title="AI observability" description="Per-agent calls, latency and confidence from the backend." loader={async () => (await api.aiMetrics()).agents} /> }

function DataPage({ title, description, loader, readOnlyForAuditor }: { title: string; description: string; loader: () => Promise<Array<Record<string, unknown>>>; readOnlyForAuditor?: boolean }) {
  const { user } = useAuth();
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);

  async function load() {
    setLoading(true);
    try { setItems(await loader()); setError(""); }
    catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setPage(1); }, [q]);

  const filtered = useMemo(() => {
    if (!q.trim()) return items;
    const needle = q.trim().toLowerCase();
    return items.filter(item => Object.values(item).some(v => typeof v !== "object" && String(v).toLowerCase().includes(needle)));
  }, [items, q]);
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="content">
      <div className="page-title">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
          {readOnlyForAuditor && user?.role === "auditor" && <ReadOnlyPill />}
        </div>
        <Button variant="outline" icon={<IconRefresh size={14} />} onClick={load}>Refresh</Button>
      </div>
      {items.length > 0 && <div className="ui-filter-bar" style={{ marginBottom: 16 }}><SearchInput value={q} onChange={setQ} placeholder="Search records" /></div>}
      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : filtered.length ? (
        <>
          <div className="panel data-list">
            {paged.map((item, index) => (
              <article key={String(item.id || item.name || index)}>
                {Object.entries(item).filter(([, v]) => typeof v !== "object").map(([k, v]) => <div key={k}><span>{k.replaceAll("_", " ")}</span><b>{String(v)}</b></div>)}
              </article>
            ))}
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={filtered.length} onPageChange={setPage} />
        </>
      ) : <Empty label={q ? "No records match your search." : "No records available."} />}
    </div>
  );
}
