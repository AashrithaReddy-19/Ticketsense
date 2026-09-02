import { IconArrowLeft } from "../components/icons";

const STEPS = ["Approved KB article", "Text preprocessing", "all-MiniLM-L6-v2", "384-dim embedding", "PostgreSQL / pgvector", "Scoped cosine-similarity retrieval"];

export default function KnowledgePipeline() {
  return (
    <div className="content narrow">
      <div className="page-title">
        <div><h1>Knowledge retrieval pipeline</h1><p>How an approved article becomes retrievable evidence for a ticket.</p></div>
      </div>

      <div className="panel" style={{ padding: 24 }}>
        <h2 style={{ margin: "0 0 4px", font: "700 15px var(--font-display)" }}>Embedding pipeline</h2>
        <p className="empty-note" style={{ marginBottom: 8 }}>Every approved knowledge-base article follows this fixed sequence before it can be retrieved.</p>
        <div className="kp-flow">
          {STEPS.map((step, i) => (
            <div key={step} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div className="kp-flow-step">{step}</div>
              {i < STEPS.length - 1 && <span className="kp-flow-arrow" aria-hidden="true">→</span>}
            </div>
          ))}
        </div>

        <h2 style={{ margin: "28px 0 4px", font: "700 15px var(--font-display)" }}>Architecture facts</h2>
        <p className="empty-note" style={{ marginBottom: 8 }}>Reference figures for this deployment's seeded demo knowledge base.</p>
        <div className="kp-fact-grid">
          <div className="kp-fact"><strong>48</strong><span>Total KB articles</span></div>
          <div className="kp-fact"><strong>12</strong><span>Cloud</span></div>
          <div className="kp-fact"><strong>12</strong><span>HR</span></div>
          <div className="kp-fact"><strong>12</strong><span>Networking</span></div>
          <div className="kp-fact"><strong>12</strong><span>SAP</span></div>
          <div className="kp-fact"><strong>384</strong><span>Vector dimensions</span></div>
        </div>

        <h2 style={{ margin: "28px 0 4px", font: "700 15px var(--font-display)" }}>Retrieval-time scoping</h2>
        <ul style={{ fontSize: "var(--text-sm)", lineHeight: 1.8, color: "var(--color-ink-soft)", paddingLeft: 20 }}>
          <li>Cosine similarity via pgvector (<code>embedding &lt;=&gt; query_vector</code>)</li>
          <li>Tenant-scoped — only the ticket's own organization is searched</li>
          <li>Department-scoped — only the ticket's routed department is searched</li>
          <li>Article status must be <b>approved</b></li>
          <li>Article must be marked <b>publishable</b></li>
          <li>Article version must match the requested version (default 1.0)</li>
        </ul>
      </div>

      <p className="empty-note" style={{ marginTop: 16 }}>
        <IconArrowLeft size={12} style={{ verticalAlign: -1 }} /> Open any ticket's <b>Pipeline</b> tab to see these stages applied to that ticket's real, retrieved evidence.
      </p>
    </div>
  );
}
