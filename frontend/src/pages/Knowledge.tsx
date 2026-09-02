import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import { Empty, ErrorState, Loading } from "../components/States";
import { IconKnowledge } from "../components/icons";
import { FilterBar, SearchInput } from "../components/ui/Utility";
import { Button } from "../components/ui/Button";

export default function Knowledge() {
  const [q, setQ] = useState("");
  const [docs, setDocs] = useState<Array<{ id: string; title: string; excerpt: string; source?: string; updated_at: string }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true); setError("");
    try { setDocs(await api.knowledge(q)); }
    catch (e) { setError(e instanceof Error ? e.message : "Request failed"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  function search(e: FormEvent) { e.preventDefault(); load(); }

  return (
    <div className="content">
      <div className="page-title"><div><h1>Knowledge</h1><p>Tenant-scoped articles retrieved from the backend.</p></div></div>
      <FilterBar>
        <form onSubmit={search} style={{ display: "flex", flex: 1, gap: 8 }}>
          <SearchInput value={q} onChange={setQ} placeholder="Search knowledge titles and content" ariaLabel="Search knowledge base" />
          <Button variant="outline" type="submit">Search</Button>
        </form>
      </FilterBar>
      {loading ? <Loading skeleton /> : error ? <ErrorState message={error} onRetry={load} /> : docs.length ? (
        <div className="knowledge-grid">
          {docs.map(d => (
            <article className="panel knowledge-card" key={d.id}>
              <span><IconKnowledge size={20} /></span>
              <h3>{d.title}</h3>
              <p>{d.excerpt}</p>
              <small>{d.source || "Internal knowledge base"} · Updated {new Date(d.updated_at).toLocaleDateString()}</small>
            </article>
          ))}
        </div>
      ) : <Empty label="No knowledge articles found." />}
    </div>
  );
}
